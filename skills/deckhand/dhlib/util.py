"""Shared plumbing for the dh control plane (stdlib only, Python 3.9+)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent          # .../skills/deckhand
DATA = SKILL / "data"
REFS = SKILL / "references"
TEMPLATES = SKILL / "templates"
TRYON = SKILL / "tryon"

# one secret policy for every scanner and for log redaction (data/secrets.json, shared with try-on)
SECRETS = json.loads((DATA / "secrets.json").read_text(encoding="utf-8"))
SECRET_RX = re.compile("|".join(f"(?:{v['rx']})" for v in SECRETS["values"]))
SECRET_STRICT_RX = re.compile("|".join(f"(?:{v['rx']})" for v in SECRETS["values"] + SECRETS["strict_extra"]))
SECRET_FILE_RX = re.compile(SECRETS["files"])
_REDACT_CTX = [re.compile(r"(?i)(\bauthorization:\s*(?:bearer|basic|token)\s+)[^\s'\"]+"),
               re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|key|secret|password)=)[^&\s'\"]+"),
               re.compile(r"(\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)=)[^\s'\"]+"),
               re.compile(r"(://[^/\s:@]+:)[^@\s/]+(@)")]


def home() -> Path:
    """~/.deckhand (DECKHAND_HOME overrides) — the owner's portable state."""
    return Path(os.environ.get("DECKHAND_HOME") or (Path.home() / ".deckhand"))


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def today() -> str:
    return time.strftime("%Y-%m-%d")


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def append_jsonl(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(p: Path) -> list:
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def emit(obj, code: int = 0):
    """Machine-first output: exactly one JSON object on stdout."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return code


class DhError(Exception):
    def __init__(self, code: str, message: str, /, **extra):       # positional-only: extra may carry its own "code"
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def redact(text: str, values=()) -> str:
    """Credentials out of anything we write to disk (run logs, failures, autopsy reports): the shared patterns,
    secret-looking assignments/headers/URL parts, and every exact value the caller knows is secret (the vault)."""
    if not text:
        return text
    for v in sorted({v for v in values if v and len(v) >= 8}, key=len, reverse=True):
        text = text.replace(v, "***")
    text = SECRET_STRICT_RX.sub("***", text)
    for rx in _REDACT_CTX:
        text = rx.sub(lambda m: m.group(1) + "***" + (m.group(2) if rx.groups > 1 else ""), text)
    return text


# Deckhand refusing on purpose (a guardrail doing its job) — never a failure to explain, learn from or retry
# (a red check, a busy folder, a step out of order or past a gate is the agent's work to fix: those stay failures)
GUARD_CODES = ("CHANGE_REQUEST", "HOLD", "NEED_QUOTE", "NEEDS_ACCEPT", "NEED_REASON", "NEED_HOW_WHERE", "SECRET_IN_TEXT", "SEO_ITEM",
               "NOTE_TOO_THIN")
GUARD_RX = re.compile(r"^(" + "|".join(GUARD_CODES) + r"):")


def is_guard(run_row: dict) -> bool:
    """A logged dh call that ended on a guard code (runs.jsonl `out` starts with it)."""
    return bool(GUARD_RX.match(str(run_row.get("out") or "").strip()))


TOKENISH = re.compile(r"(?<![\w/.-])[A-Za-z0-9_-]{24,}(?![\w/.-])")


def _keylike(m) -> str:
    """A key has a long unbroken run mixing digits and letters (sk-or-v1-9f3c…); a slug has words between dashes."""
    w = m.group(0)
    run_ = max(re.findall(r"[A-Za-z0-9]{20,}", w), key=len, default="")
    return "***" if len(re.findall(r"\d", run_)) >= 3 and len(re.findall(r"[A-Za-z]", run_)) >= 3 else w


def mask_tokens(text: str) -> str:
    """What people paste in chat that no pattern knows (a provider's API key) becomes ***.
    Used on free text from conversations (autopsy ledgers, pending items); commands and paths keep their own redaction."""
    return TOKENISH.sub(_keylike, text) if text else text


def redact_obj(obj, values=()):
    """redact() over every string of a JSON-like structure (a report before it is written anywhere)."""
    if isinstance(obj, str):
        return redact(obj, values)
    if isinstance(obj, list):
        return [redact_obj(x, values) for x in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(x, values) for x in obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v, values) for k, v in obj.items()}
    return obj


GITIGNORE_MARK = "# deckhand: run logs and local state"
# run logs hold command output; RESUME/notes/project profile/vault/notes/layout are this machine's own (never pushed)
GITIGNORE_LINES = (".deckhand/runs.jsonl", ".deckhand/failures.jsonl", ".deckhand/*.log", ".deckhand/dev.json",
                   ".deckhand/autopsy/", ".deckhand/tryon/", ".deckhand/RESUME.md", ".deckhand/notes.jsonl",
                   ".deckhand/profile.json", ".deckhand/vault.env", ".deckhand/profile.md", ".deckhand/layout.json",
                   ".deckhand/research/cache/", ".deckhand/suggest.json")
GITIGNORE_BLOCK = GITIGNORE_MARK + " (they can hold command output — never commit them)\n" + "\n".join(GITIGNORE_LINES) + "\n"
# probe path -> what to show (a directory is probed through a file inside it)
RUNTIME_STATE = {".deckhand/runs.jsonl": ".deckhand/runs.jsonl", ".deckhand/failures.jsonl": ".deckhand/failures.jsonl",
                 ".deckhand/dev.log": ".deckhand/*.log", ".deckhand/dev.json": ".deckhand/dev.json",
                 ".deckhand/autopsy/r.md": ".deckhand/autopsy/", ".deckhand/tryon/s.json": ".deckhand/tryon/",
                 ".deckhand/RESUME.md": ".deckhand/RESUME.md", ".deckhand/notes.jsonl": ".deckhand/notes.jsonl",
                 ".deckhand/profile.json": ".deckhand/profile.json", ".deckhand/vault.env": ".deckhand/vault.env",
                 ".deckhand/profile.md": ".deckhand/profile.md", ".deckhand/layout.json": ".deckhand/layout.json",
                 ".deckhand/research/cache/p.txt": ".deckhand/research/cache/", ".deckhand/suggest.json": ".deckhand/suggest.json"}


def ensure_gitignore(root: Path) -> bool:
    """Keep deckhand's run logs and local state out of the owner's git history. Idempotent; an older block is
    upgraded in place (missing lines added under it). Returns True when it wrote."""
    gi = Path(root) / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if GITIGNORE_MARK in text:
        lines = text.splitlines()
        have = {x.strip() for x in lines}
        missing = [x for x in GITIGNORE_LINES if x not in have]
        if not missing:
            return False
        i = next(n for n, x in enumerate(lines) if x.startswith(GITIGNORE_MARK)) + 1
        while i < len(lines) and lines[i].strip().startswith(".deckhand/"):
            i += 1
        lines[i:i] = missing
        gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    gi.parent.mkdir(parents=True, exist_ok=True)
    gi.write_text((text.rstrip("\n") + "\n\n" if text.strip() else "") + GITIGNORE_BLOCK, encoding="utf-8")
    return True


_RESERVED = None


def reserved_ports() -> list:
    """Windows keeps TCP port ranges for Hyper-V/WSL/Docker (`netsh … show excludedportrange`); a server cannot
    listen there even though nothing answers. The owner's machine had 4097–4196 reserved: verify's old fixed
    4100 fell inside it. Empty on other systems. Cached per process."""
    global _RESERVED
    if _RESERVED is None:
        _RESERVED = []
        if os.name == "nt":
            try:
                r = subprocess.run(["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                                   capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
                _RESERVED = [(int(a), int(b)) for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", r.stdout, re.M)]
            except Exception:  # noqa: BLE001
                pass
    return _RESERVED


def port_free(port: int) -> bool:
    """Free = not reserved, nothing answers, and we can really bind it (a connect test alone misses reserved ranges)."""
    import socket
    if any(a <= port <= b for a, b in reserved_ports()):
        return False
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return False
    for host in ("0.0.0.0", "127.0.0.1"):
        with socket.socket() as s:
            try:
                s.bind((host, port))
            except OSError:
                return False
    return True


def free_port(start: int = 3000, span: int = 200) -> int:
    for p in range(start, start + span):
        if port_free(p):
            return p
    raise DhError("NO_PORT", f"no free port in {start}-{start + span - 1} (reserved ranges: {reserved_ports() or 'none'})")


def which(cmd: str):
    """Resolve a launcher to a real executable (Windows PATH carries npm.cmd, not npm)."""
    return shutil.which(cmd)


def rmtree(path) -> None:
    """Delete a tree even where files are read-only (git objects on Windows); a no-op when missing."""
    import stat

    def fix(func, p, _):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except FileNotFoundError:
            pass
    if not Path(path).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def run(argv: list, cwd=None, timeout: int = 900, env=None, check=False) -> dict:
    exe = which(argv[0]) or argv[0]
    t0 = time.time()
    try:
        p = subprocess.run([exe, *argv[1:]], cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, **(env or {})}, encoding="utf-8", errors="replace")
        res = {"cmd": " ".join(argv), "code": p.returncode, "out": p.stdout[-6000:], "err": p.stderr[-6000:],
               "ms": int((time.time() - t0) * 1000)}
    except FileNotFoundError:
        res = {"cmd": " ".join(argv), "code": 127, "out": "", "err": f"{argv[0]}: not found on PATH", "ms": 0}
    except subprocess.TimeoutExpired as e:
        res = {"cmd": " ".join(argv), "code": 124, "out": str(e.stdout or "")[-3000:], "err": "timeout", "ms": timeout * 1000}
    if check and res["code"] != 0:
        raise DhError("COMMAND_FAILED", f"{res['cmd']} -> exit {res['code']}", result=res)
    return res


def project_root(p=None) -> Path:
    """The project: --project, else the nearest parent with .deckhand/run.json or package.json, else cwd.
    Never the owner's home folder or anything above it (F23: a stray ~/package.json once received a run.json), and a
    git repository's root bounds the package.json search."""
    if p:
        return Path(p).resolve()
    cur = Path.cwd().resolve()
    home = Path.home().resolve()
    below = [d for d in [cur, *cur.parents] if d != home and d not in home.parents]
    for d in below:
        if (d / ".deckhand" / "run.json").exists():
            return d
    for d in below:
        if (d / "package.json").exists() or (d / "pyproject.toml").exists():
            return d
        if (d / ".git").exists():
            break
    return cur


def slugify(s: str, n: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(s)).strip("-").lower()
    return s[:n] or "project"


def package_json(root: Path) -> dict:
    return read_json(Path(root) / "package.json", {}) or {}


def package_manager(root: Path) -> str:
    root = Path(root)
    for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("bun.lockb", "bun"), ("bun.lock", "bun"), ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
        if (root / lock).exists():
            return pm
    return "npm"


def pm_run(root: Path, script: str) -> list:
    pm = package_manager(root)
    return {"npm": ["npm", "run", script], "pnpm": ["pnpm", "run", script], "yarn": ["yarn", script], "bun": ["bun", "run", script]}[pm]


def git_files(root: Path) -> list:
    """Tracked + untracked-not-ignored files (falls back to a walk without node_modules/.git)."""
    root = Path(root)
    r = run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root, timeout=60)
    if r["code"] == 0 and r["out"].strip():
        return [root / l for l in r["out"].splitlines() if l.strip()]
    out = []
    skip = {"node_modules", ".git", ".next", "dist", "build", ".deckhand", ".turbo", ".vercel", "__pycache__"}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip]
        out += [Path(dp) / f for f in fns]
    return out


TEXT_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".md", ".mdx", ".css", ".scss", ".html", ".txt",
            ".yml", ".yaml", ".toml", ".env", ".example", ".py", ".sql", ".prisma", ".svg", ".xml", ".vue", ".svelte", ".astro"}


def is_text(p: Path) -> bool:
    return p.suffix.lower() in TEXT_EXT or p.name in (".env.example", "Dockerfile", "README", "LICENSE")
