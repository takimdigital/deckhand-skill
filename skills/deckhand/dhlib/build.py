"""BUILD: four ways in, one result — a project folder that runs locally, with its own git history.

  clone <template>   a pool row (public or yours): shallow clone at the measured commit, fresh
                     history, NOTICE (upstream + commit + licence), .env seeded with LOCAL secrets only
  adopt <path|url>   the owner's existing project, history kept
  scaffold           from scratch: create-next-app + the canonical UI base (tokens, cn, Button)
  compose            a landing page assembled from licensed blocks with the plan's copy (no LLM)
  dev start|stop     run it and prove it answers
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from .util import ensure_gitignore, DhError, TEMPLATES, TRYON, free_port, git_files, now, package_json, package_manager, read_json, rmtree, run, slugify, write_json
from . import pool as POOL
from . import state as STATE

LOCAL_SECRET_KEYS = re.compile(r"^(BETTER_AUTH_SECRET|AUTH_SECRET|NEXTAUTH_SECRET|JWT_SECRET|SESSION_SECRET|COOKIE_SECRET|ENCRYPTION_KEY|SECRET_KEY_BASE|PAYLOAD_SECRET)=", re.M)


def _fresh_git(dest: Path, message: str) -> None:
    rmtree(dest / ".git")                                  # read-only git objects on Windows: really gone, or history leaks
    run(["git", "init", "-q"], cwd=dest)
    run(["git", "add", "-A"], cwd=dest)
    run(["git", "-c", "user.name=deckhand", "-c", "user.email=deckhand@localhost", "commit", "-qm", message], cwd=dest)


def seed_env(dest: Path) -> list:
    """.env from .env.example; generate values ONLY for local secrets (never vendor keys)."""
    ex = next((dest / n for n in (".env.example", ".env.local.example", ".env.sample", ".env.template") if (dest / n).exists()), None)
    target = dest / ".env"
    if not ex or target.exists():
        return []
    text = ex.read_text(encoding="utf-8")
    made = []

    def fill(m):
        made.append(m.group(1))
        return f"{m.group(1)}={secrets.token_urlsafe(32)}"
    text = re.sub(r"^(BETTER_AUTH_SECRET|AUTH_SECRET|NEXTAUTH_SECRET|JWT_SECRET|SESSION_SECRET|COOKIE_SECRET|ENCRYPTION_KEY|SECRET_KEY_BASE|PAYLOAD_SECRET)=.*$", fill, text, flags=re.M)
    target.write_text(text, encoding="utf-8")
    gi = dest / ".gitignore"
    g = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if not re.search(r"^\.env$|^\.env\*|^\.env\.local", g, re.M):
        gi.write_text(g.rstrip("\n") + "\n.env\n.env*.local\n", encoding="utf-8")
    return made


def install(dest: Path) -> dict:
    pm = package_manager(dest)
    cmd = {"npm": ["npm", "install", "--no-audit", "--no-fund"], "pnpm": ["pnpm", "install"], "yarn": ["yarn", "install"], "bun": ["bun", "install"]}[pm]
    r = run(cmd, cwd=dest, timeout=1800)
    return {"pm": pm, "ok": r["code"] == 0, "cmd": r["cmd"], "tail": (r["err"] or r["out"])[-600:]}


def _record_base(dest: Path, base: dict, name: str, path: str) -> None:
    ensure_gitignore(dest)                                # every way in keeps deckhand's run logs out of git
    s = STATE.load(dest, required=False)
    if not s:
        STATE.init(dest, name=name, path=path)            # also writes the AGENTS.md cold-start entry
        s = STATE.load(dest)
    else:
        from . import resume as RESUME
        RESUME.agent_entry(dest)
    s["base"] = base
    STATE.save(dest, s)


# what stays with the folder it describes when a run moves: logs, the dev server, try-on sessions, and the settings
# layer (profile.carry moves that, by the owner's choice)
STAYS = {"run.json", "runs.jsonl", "failures.jsonl", "history.jsonl", "dev.json", "RESUME.md", "suggest.json", "autopsy",
         "tryon", "profile.json", "vault.env", "profile.md", "layout.json"}


def planning_folder(root) -> bool:
    """A folder whose run is waiting for its base: the one a clone/adopt/scaffold `--to` elsewhere continues. A
    project that already has its base is another business: nothing of it goes to the new folder."""
    s = STATE.load(Path(root), required=False) if root else None
    return bool(s) and not s.get("base") and not s.get("moved_to")


def carry_run(src, dst) -> dict | None:
    """`dh clone … --to OTHERDIR` from the planning folder: the app folder continues that run (brief, sitemap, plan,
    gates, notes), never a fresh one at define; the planning folder then points at it."""
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst or not planning_folder(src):
        return None
    s, d = STATE.load(src), STATE.load(dst, required=False) or {}
    if any(ph.get("status") in ("done", "skipped") for ph in (d.get("phases") or {}).values()):
        return None                                      # the destination has a run of its own: never overwrite it
    copied = []
    for p in sorted((src / ".deckhand").iterdir()):
        if p.name in STAYS or p.suffix == ".log":
            continue
        out = dst / ".deckhand" / p.name
        if p.is_dir():
            shutil.copytree(p, out, dirs_exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
        copied.append(p.name)
    moved = {**s, "base": d.get("base")}
    STATE.save(dst, moved)
    from . import resume as RESUME
    RESUME.agent_entry(dst)
    s["moved_to"], s["base"] = str(dst), d.get("base")
    STATE.save(src, s)
    STATE.log(src, {"event": "moved", "to": str(dst)})
    return {"from": str(src), "to": str(dst), "copied": copied}


OWN_FILES = {".deckhand", "AGENTS.md", "CLAUDE.md", "PENDING.md", ".gitignore", ".gitattributes", "HANDOFF.md"}


def _hold(to: Path) -> Path | None:
    """`dh init` fills the folder first (.deckhand, AGENTS.md, PENDING.md…); a base still goes in there.
    Deckhand's own files step aside while the base lands, then come back (the plan, notes and gates survive).
    Anything else in the folder = not empty: refuse, never merge into someone's files."""
    to = Path(to)
    if not to.exists() or not any(to.iterdir()):
        return None
    other = sorted(p.name for p in to.iterdir() if p.name not in OWN_FILES)
    if other:
        raise DhError("DEST_NOT_EMPTY", f"{to} holds files that are not Deckhand's: {', '.join(other[:8])} — pick a new folder, "
                      "or `dh adopt` it if it is the owner's project")
    held = to.parent / f".{to.name}.deckhand-hold"
    if held.exists() and any(held.iterdir()):
        raise DhError("HOLD_EXISTS", f"{held} holds Deckhand files from an interrupted clone/scaffold — move them back into {to}, "
                      "delete the hold folder, then run the command again")
    rmtree(held)
    held.mkdir(parents=True)
    moved = []
    try:
        for p in list(to.iterdir()):
            shutil.move(str(p), str(held / p.name))
            moved.append(p.name)
    except OSError as e:                                   # a locked file (Windows: a shell or server inside): put everything back
        for name in moved:
            try:
                shutil.move(str(held / name), str(to / name))
            except OSError:
                pass
        if not any(held.iterdir()):
            rmtree(held)
        raise DhError("DEST_BUSY", f"{to}: could not move Deckhand's own files aside ({e}) — close shells and servers using that folder, then retry")
    return held


def _unhold(held: Path | None, to: Path) -> list:
    """Deckhand's files back in: .deckhand and PENDING.md win; the base's own AGENTS.md/CLAUDE.md win (the cold-start
    block is re-added to them); .gitignore/.gitattributes lines are merged."""
    if not held:
        return []
    back = []
    for p in sorted(held.iterdir()):
        dst = Path(to) / p.name
        if p.name in (".gitignore", ".gitattributes") and dst.exists():
            have = dst.read_text(encoding="utf-8").splitlines()
            add = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and l not in have]
            if add:
                dst.write_text("\n".join(have + [""] + add) + "\n", encoding="utf-8")
        elif p.name in ("AGENTS.md", "CLAUDE.md") and dst.exists():
            pass
        else:
            if dst.exists():
                rmtree(dst) if dst.is_dir() else dst.unlink()
            shutil.move(str(p), str(dst))
        back.append(p.name)
    rmtree(held)
    return back


def record_base(root: Path, kind: str, note: str = "", source: str | None = None) -> dict:
    """`dh base record`: a project built another way (by hand, by another tool) states its base in the open
    instead of reaching into private functions (D4)."""
    root = Path(root)
    if kind not in ("scratch", "existing", "template"):
        raise DhError("BAD_KIND", "kind must be scratch | existing | template")
    if not (root / "package.json").exists() and not (root / "pyproject.toml").exists():
        raise DhError("NO_APP", f"no package.json in {root}: record the base once the app exists")
    s = STATE.load(root)
    pkg = package_json(root)
    base = {"kind": kind, "at": now(), "recorded_by": "dh base record", **({"note": note} if note else {}), **({"source": source} if source else {}),
            "stack": POOL.detect_stack(pkg, [])}
    s["base"] = base
    STATE.save(root, s)
    STATE.log(root, {"event": "base", "kind": kind, "note": note})
    return {"base": base, "next": "dh dev start"}


def clone(name: str, to: Path, do_install: bool = True) -> dict:
    row = next((r for r in POOL.rows() if r["name"] == name), None)
    if not row:
        raise DhError("NO_SUCH_TEMPLATE", f"{name} is not in the pool (dh pool query …)")
    if row.get("license") not in POOL.OK_LICENSES and not (row.get("source") == "mine" and row.get("license") in POOL.OWNER_LICENSES):
        raise DhError("LICENCE_REFUSED", f"{name}: licence {row.get('license')}")
    if POOL.SECURITY_RISKS & set(row.get("risks") or []):
        raise DhError("BASE_UNSAFE", f"{name} is flagged {', '.join(sorted(POOL.SECURITY_RISKS & set(row['risks'])))} — pick another base (dh pool query …)")
    to = Path(to).resolve()
    held = _hold(to)
    to.parent.mkdir(parents=True, exist_ok=True)
    try:
        commit = _fetch_base(row, to)
    except Exception:
        _unhold(held, to)
        raise
    lic = next((p.name for p in to.iterdir() if p.name.upper().startswith(("LICENSE", "LICENCE"))), None)
    warn = None if lic else (f"no licence file came with the base (the pool says {row.get('license')}): "
                             "add that licence's text as LICENSE before shipping")
    if not (to / "NOTICE").exists():                    # a base's own NOTICE is a licence condition: never rewritten (invariant 4)
        (to / "NOTICE").write_text(
            f"This project started from {row.get('repo') or row['name']} ({row.get('license')}), commit {commit}.\n"
            + (f"The upstream licence is kept in {lic} — keep this file and that licence in the project.\n" if lic else
               f"The upstream licence ({row.get('license')}) must be added as LICENSE — keep this file and that licence in the project.\n"),
            encoding="utf-8")
    made = seed_env(to)
    _fresh_git(to, f"base: {row['name']} @ {commit[:12]} ({row.get('license')})")
    kept = _unhold(held, to)
    _record_base(to, {"kind": "template", "name": row["name"], "repo": row.get("repo"), "commit": commit, "at": now()}, name=to.name, path="mine" if row.get("source") == "mine" else "pool")
    inst = install(to) if do_install and (to / "package.json").exists() else None
    return {"project": str(to), "template": row["name"], "commit": commit, "local_secrets_generated": made, "install": inst,
            **({"kept": kept} if kept else {}), **({"licence_warning": warn} if warn else {}), "next": "dh dev start --project " + str(to)}


COPY_SKIP = {"node_modules", ".git", ".next", ".deckhand"}


def _gitignored(rel: str, patterns: list) -> bool:
    """A small .gitignore match for a base that is not inside a git repository (no negations)."""
    import fnmatch
    parts = rel.split("/")
    for p in patterns:
        p = p.strip()
        if not p or p.startswith(("#", "!")):
            continue
        anchored, p = p.startswith("/"), p.strip("/")
        if "/" in p or anchored:
            if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*"):
                return True
        elif any(fnmatch.fnmatch(x, p) for x in parts):
            return True
    return False


def _copy_base(src: Path, to: Path) -> None:
    """A local base copied the way git sees it: tracked + untracked-not-ignored (its .gitignore and its parents'), never
    node_modules/.git/.next/.deckhand or .env files (F10: a clone committed what the base's git had ignored)."""
    src = Path(src).resolve()
    inside = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=src, timeout=30)
    if inside["code"] == 0 and inside["out"].strip() == "true":
        r = run(["git", "ls-files", "-co", "--exclude-standard"], cwd=src, timeout=60)
        files = [src / l for l in r["out"].splitlines() if l.strip()]
    else:
        pats = (src / ".gitignore").read_text(encoding="utf-8", errors="replace").splitlines() if (src / ".gitignore").exists() else []
        files = [Path(dp) / f for dp, dns, fns in os.walk(src) for f in fns
                 if not _gitignored(os.path.relpath(Path(dp) / f, src).replace(os.sep, "/"), pats)]
    for f in files:
        rel = f.relative_to(src)
        if not f.is_file() or set(rel.parts) & COPY_SKIP or rel.name == ".env" or rel.name.startswith(".env."):
            continue
        (to / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, to / rel)


def _fetch_base(row: dict, to: Path) -> str:
    if row.get("path") and Path(row["path"]).exists():   # a harvested base on this machine
        to.mkdir(parents=True, exist_ok=True)
        _copy_base(Path(row["path"]), to)
        commit = "local"
    elif row.get("source") == "mine" and row.get("repo"):  # the owner's private library base, from their GitHub
        from . import github as GH
        GH.clone(row["repo"], to, branch=row.get("branch") or "main")
        commit = run(["git", "rev-parse", "HEAD"], cwd=to)["out"].strip() or "library"
    else:
        url = f"https://github.com/{row['repo']}.git"
        r = run(["git", "clone", "--depth", "1", "--branch", row.get("branch") or "main", url, str(to)], timeout=900)
        if r["code"] != 0:
            raise DhError("CLONE_FAILED", r["err"][-400:])
        commit = run(["git", "rev-parse", "HEAD"], cwd=to)["out"].strip()
        if row.get("commit") and row["commit"] != commit:
            f = run(["git", "fetch", "--depth", "1", "origin", row["commit"]], cwd=to, timeout=300)
            if f["code"] == 0:
                run(["git", "checkout", "-q", row["commit"]], cwd=to)
                commit = row["commit"]
    return commit


def adopt(src: str, to: Path | None = None, do_install: bool = False) -> dict:
    if re.match(r"^(https?://|git@)", src):
        dest = Path(to or slugify(src.rstrip("/").split("/")[-1].removesuffix(".git"))).resolve()
        r = run(["git", "clone", src, str(dest)], timeout=1800)
        if r["code"] != 0:
            raise DhError("CLONE_FAILED", r["err"][-400:])
    else:
        dest = Path(src).resolve()
        if not dest.exists():
            raise DhError("NO_SUCH_PATH", str(dest))
        if to:
            shutil.copytree(dest, Path(to), ignore=shutil.ignore_patterns("node_modules", ".next"))
            dest = Path(to).resolve()
    pkg = package_json(dest)
    stack = POOL.detect_stack(pkg, [str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if "node_modules" not in p.parts and p.is_file()][:20000])
    _record_base(dest, {"kind": "existing", "source": src, "stack": stack, "at": now()}, name=dest.name, path="existing")
    inst = install(dest) if do_install and (dest / "package.json").exists() else None
    return {"project": str(dest), "stack": stack, "install": inst, "next": "dh dev start"}


def scaffold(to: Path, pm: str = "npm") -> dict:
    """create-next-app wants a folder it creates itself. It builds in a sibling and moves in: `to` is never removed,
    because it may be the shell's cwd (`--to .`: Windows refuses to rmdir it, POSIX leaves the shell in a deleted
    folder, and the held Deckhand files were stranded either way)."""
    to = Path(to).resolve()
    held = _hold(to)
    to.mkdir(parents=True, exist_ok=True)
    fresh = to.parent / f".{to.name}.deckhand-scaffold"
    rmtree(fresh)
    try:
        r = run(["npx", "--yes", "create-next-app@latest", str(fresh), "--ts", "--tailwind", "--app", "--no-eslint", "--no-src-dir",
                 "--import-alias", "@/*", f"--use-{pm}", "--yes", "--disable-git"], timeout=1800)
        if r["code"] != 0 or not fresh.is_dir():
            raise DhError("SCAFFOLD_FAILED", (r["err"] or r["out"] or "create-next-app wrote nothing")[-600:])
        for p in list(fresh.iterdir()):
            shutil.move(str(p), str(to / p.name))
    except Exception:
        for p in list(to.iterdir()):                       # back to how it was: the held files only
            rmtree(p) if p.is_dir() else p.unlink()
        _unhold(held, to)
        raise
    finally:
        rmtree(fresh)
    base = TEMPLATES / "scaffold"
    for rel in ("components/ui/button.tsx", "lib/utils.ts"):
        (to / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(base / rel, to / rel)
    css = to / "app" / "globals.css"
    css.write_text((base / "app" / "globals.css").read_text(encoding="utf-8"), encoding="utf-8")
    deps = ["clsx", "tailwind-merge", "class-variance-authority", "radix-ui", "lucide-react", "tw-animate-css"]
    ir = run({"npm": ["npm", "install", "--no-audit", "--no-fund"], "pnpm": ["pnpm", "add"], "bun": ["bun", "add"], "yarn": ["yarn", "add"]}[pm] + deps, cwd=to, timeout=1800)
    _fresh_git(to, "base: create-next-app + deckhand UI base (tokens, cn, Button)")
    kept = _unhold(held, to)
    _record_base(to, {"kind": "scratch", "at": now()}, name=to.name, path="scratch")
    return {"project": str(to), "deps_ok": ir["code"] == 0, **({"kept": kept} if kept else {}), "next": "dh compose --sections navbar,hero,features,pricing,faq,cta,footer (or build pages from the plan)"}


def compose(root: Path, page: str, sections: list, copy: str | None) -> dict:
    if copy:
        cp = Path(copy) if Path(copy).is_absolute() else root / copy
        if not cp.is_file():
            raise DhError("NO_COPY", f"{copy} does not exist: write the words first (per section slot; schema in references/20-plan.md § Copy)",
                          path=str(cp), do=["write .deckhand/copy.json from the plan and the brief, then compose again"])
    node = shutil.which("node")
    if not node:
        raise DhError("NO_NODE", "node is required for compose")
    argv = [node, str(TRYON / "compose.mjs"), "--project", str(root), "--page", page, "--sections", ",".join(sections)]
    if copy:
        argv += ["--copy", copy]
    r = run(argv, cwd=root, timeout=900)
    try:
        out = __import__("json").loads(r["out"].strip().splitlines()[-1])
    except Exception:
        raise DhError("COMPOSE_FAILED", (r["err"] or r["out"])[-800:])
    if copy and isinstance(out, dict):
        from . import slop as SLOP                       # the words the model wrote, read before the owner sees them
        rep = SLOP.summarize(SLOP.copy_units(root, (root / copy) if not Path(copy).is_absolute() else Path(copy)), top=3)
        out["copy_check"] = {**rep, **({"next": "rewrite what copy_check lists in copy.json, then compose again (dh slop brief first)"}
                                       if rep["verdict"] != "clean" else {})}
    return out


# ------------------------------------------------------------------ dev server (+ the services it needs)
def _free_port(start: int = 3000) -> int:
    return free_port(start)


def _answers(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", None)


PIN_RX = re.compile(r"(?:(?:^|\s)(?:-p|--port)[ =](\d{2,5})\b|\bPORT=(\d{2,5})\b)")


def pinned_port(root: Path, script: str) -> int | None:
    """A port the owner's own script already pins (`next dev -p 3010`, `PORT=3010 …`): keep it, never append another."""
    cmd = ((package_json(root).get("scripts") or {}).get(script) or "")
    m = PIN_RX.search(cmd)
    return int(m.group(1) or m.group(2)) if m else None


def _spawn(argv: list, cwd: Path, log: Path, env: dict):
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "w", encoding="utf-8")
    kw = {"cwd": str(cwd), "stdout": out, "stderr": subprocess.STDOUT, "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        argv = [shutil.which(argv[0]) or argv[0], *argv[1:]]
    else:
        kw["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kw)
    finally:
        out.close()                                            # the child keeps its own handle


def serve(root: Path, script: str, port: int, log: Path, wait: int = 180, keep_pinned: bool = True):
    """Start `<pm> run <script> --port N` detached (own process group); wait until it answers < 500.
    Returns (proc, url, status). The caller stops it with kill_tree(proc.pid).
    HOSTNAME is pinned to 127.0.0.1: git-bash exports the machine name and Next's standalone server binds to it."""
    root = Path(root)
    pm = package_manager(root)
    pinned = pinned_port(root, script) if keep_pinned else None
    cmd = {"npm": ["npm", "run", script, "--"], "pnpm": ["pnpm", "run", script], "yarn": ["yarn", script], "bun": ["bun", "run", script]}[pm]
    if pinned:
        port = pinned
        cmd = cmd[:-1] if cmd[-1] == "--" else cmd
    else:
        cmd = cmd + ["--port", str(port)]
    proc = _spawn(cmd, root, log, {**os.environ, "PORT": str(port), "HOSTNAME": "127.0.0.1"})
    url = f"http://localhost:{port}"
    t0 = time.time()
    status = None
    while time.time() - t0 < wait:
        status = _answers(url)
        if status and status < 500:
            break
        if proc.poll() is not None:
            break
        time.sleep(1.5)
    proc.cmd = " ".join(cmd)
    return proc, url, status


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        os.killpg(os.getpgid(pid), signal.SIGTERM)


def services_path(root: Path) -> Path:
    return Path(root) / ".deckhand" / "services.json"


def services(root: Path) -> list:
    return (read_json(services_path(root), {}) or {}).get("services", [])


def service_add(root: Path, name: str, cmd: str, port: int | None = None, ready: str | None = None, env_file: str | None = None) -> dict:
    """What the app needs running before it can answer (a database, a queue, a mail catcher). Committed config:
    every session, every AI, starts the same things the same way (`dh dev start` starts them first)."""
    if not re.match(r"^[a-z][a-z0-9-]{0,30}$", name or "") or name == "app":
        raise DhError("BAD_NAME", "service name: lowercase letters, digits, dashes (not 'app')")
    if not cmd:
        raise DhError("USAGE", "dh dev add NAME --cmd \"…\" [--port N] [--ready REGEX] [--env-file .env]")
    if not port and not ready:
        raise DhError("NO_READY_SIGNAL", "give --port N (it answers) or --ready REGEX (a log line) so Deckhand knows it is up")
    if ready:
        re.compile(ready)
    rows = [r for r in services(root) if r["name"] != name]
    rows.append({"name": name, "cmd": cmd, **({"port": port} if port else {}), **({"ready": ready} if ready else {}),
                 **({"env_file": env_file} if env_file else {})})
    write_json(services_path(root), {"services": rows})
    return {"services": rows, "next": "dh dev start   # starts these first, then the app"}


def service_remove(root: Path, name: str) -> dict:
    rows = [r for r in services(root) if r["name"] != name]
    write_json(services_path(root), {"services": rows})
    return {"services": rows}


def _env_file(root: Path, rel: str | None) -> dict:
    if not rel:
        return {}
    p = Path(root) / rel
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


def _bash_exe() -> str | None:
    """git-bash on Windows: HERMES_GIT_BASH_PATH may name bash.exe or the git tree that holds it."""
    for cand in (os.environ.get("HERMES_GIT_BASH_PATH"), shutil.which("bash")):
        if not cand:
            continue
        c = Path(cand)
        if c.is_file():
            return str(c)
        for rel in ("usr/bin/bash.exe", "bin/bash.exe", "bash.exe"):
            if (c / rel).is_file():
                return str(c / rel)
    return None


def _shell(cmd: str) -> list:
    if os.name == "nt":
        bash = _bash_exe()
        return [bash, "-lc", cmd] if bash else ["cmd", "/c", cmd]
    return [shutil.which("bash") or "/bin/sh", "-c", cmd]


def _port_open(port: int) -> bool:
    with socket.socket() as sk:
        sk.settimeout(1)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def _alive(pid) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def service_up(root: Path, svc: dict, info: dict | None = None) -> bool:
    if svc.get("port"):
        return _port_open(svc["port"])
    return _alive(((info or {}).get("services") or {}).get(svc["name"], {}).get("pid"))


def _start_service(root: Path, svc: dict, wait: int = 90) -> dict:
    log = Path(root) / ".deckhand" / f"svc-{svc['name']}.log"
    proc = _spawn(_shell(svc["cmd"]), Path(root), log, {**os.environ, **_env_file(root, svc.get("env_file"))})
    rx = re.compile(svc["ready"]) if svc.get("ready") else None
    t0, up = time.time(), False
    while time.time() - t0 < wait:
        if svc.get("port") and _port_open(svc["port"]):
            up = True
        elif rx and rx.search(log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""):
            up = True
        if up or proc.poll() is not None:
            break
        time.sleep(1)
    return {"pid": proc.pid, "up": up, "log": str(log.relative_to(root)).replace("\\", "/"), "started": now(),
            **({} if up else {"log_tail": log.read_text(encoding="utf-8", errors="replace")[-1200:] if log.exists() else ""})}


def dev_start(root: Path, port: int | None = None, wait: int = 180) -> dict:
    """Services first (each once: a live one is reused), then the app. A dead database under a live app is
    restarted too — the app alone answering is not 'running'."""
    root = Path(root)
    info = read_json(root / ".deckhand" / "dev.json", {}) or {}
    svc_state = dict(info.get("services") or {})
    started = []
    for svc in services(root):
        if service_up(root, svc, info):
            svc_state.setdefault(svc["name"], {})["up"] = True
            continue
        r = _start_service(root, svc)
        svc_state[svc["name"]] = r
        started.append(svc["name"])
        if not r["up"]:
            info["services"] = svc_state
            write_json(root / ".deckhand" / "dev.json", info)
            return {"running": False, "service": svc["name"], **r,
                    "hint": f"service {svc['name']} did not come up — read {r['log']}; `dh learn match --log {r['log']}` knows past fixes"}
    if info.get("url") and _answers(info["url"]):
        info["services"] = svc_state
        write_json(root / ".deckhand" / "dev.json", info)
        return {"running": True, **info, "reused": True, **({"restarted_services": started} if started else {})}
    pkg = package_json(root)
    script = "dev" if "dev" in (pkg.get("scripts") or {}) else "start"
    log = root / ".deckhand" / "dev.log"
    proc, url, status = serve(root, script, port or pinned_port(root, script) or _free_port(), log, wait)
    info = {"url": url, "pid": proc.pid, "cmd": proc.cmd, "started": now(), "status": status, **({"services": svc_state} if svc_state else {})}
    write_json(root / ".deckhand" / "dev.json", info)
    tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
    if not status or status >= 500:
        return {"running": False, **info, "log_tail": tail, "hint": "read the log tail; `dh learn match --log .deckhand/dev.log` knows past fixes"}
    return {"running": True, **info, **({"started_services": started} if started else {})}


def dev_stop(root: Path) -> dict:
    info = read_json(Path(root) / ".deckhand" / "dev.json", {}) or {}
    stopped, errors = [], []
    for name, pid in [("app", info.get("pid"))] + [(n, (v or {}).get("pid")) for n, v in reversed(list((info.get("services") or {}).items()))]:
        if not pid:
            continue
        try:
            kill_tree(pid)
            stopped.append(name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    if not stopped and not errors:
        return {"stopped": False, "reason": "not started by dh"}
    return {"stopped": bool(stopped), "what": stopped, **({"errors": errors} if errors else {}), "pid": info.get("pid")}


def dev_status(root: Path) -> dict:
    info = read_json(Path(root) / ".deckhand" / "dev.json", {}) or {}
    svc = [{"name": s["name"], "up": service_up(root, s, info), **({"port": s["port"]} if s.get("port") else {})} for s in services(root)]
    down = [x["name"] for x in svc if not x["up"]]
    return {**info, "answers": _answers(info["url"]) if info.get("url") else None, **({"services": svc} if svc else {}),
            **({"down": down, "restore": "dh dev start   # restarts what is down, reuses what is up"} if down else {})}
