"""The owner, once: ~/.deckhand/profile.json (facts) + ~/.deckhand/vault.env (secrets, chmod 600) — plus a
per-project layer: <project>/.deckhand/profile.json + vault.env + profile.md (gitignored, never pushed), or a folder
the owner chose outside the project.

The profile answers the questions every project would otherwise ask again (providers, domain habits,
defaults, languages). A project's own layer overrides the machine's for that project only.
WHERE a project's settings and secrets are written is chosen once per project and remembered in
<project>/.deckhand/layout.json (`dh profile where --set here|machine|<folder>`): `here` (the default the first
write records, then asks the owner once), `machine` (shared by every project, as before 2.3), or a folder outside
the project. The owner's own facts (owner.*, defaults.*) stay on the machine in a personal project, so no project
asks them again. A project made for a CLIENT (`dh init --for client`) keeps everything in its own layer and cannot
be bound to the machine, so client A's keys can never be used in client B's project.
Reads always merge: machine, then the project's layer (it wins). Lookup: environment → project vault → machine
vault → v1's ops keyring.
Secrets never enter the profile, the chat, or a repo: scripts read the vault directly, `dh vault list` shows
names only, and `dh profile doctor` proves which capabilities are reachable WITHOUT printing a value.
"""
from __future__ import annotations

import os
import re
import shlex
import stat
import sys
import urllib.request
from pathlib import Path

from .util import DhError, ensure_gitignore, home, now, read_json, write_json, which, run

FIELDS = {
    "owner.name": "how the owner wants to be addressed",
    "owner.languages": "languages the owner reads (comma list)",
    "owner.timezone": "IANA zone, e.g. Africa/Casablanca",
    "defaults.mode": "phased | auto",
    "defaults.hosting": "vps | free-preview",
    "defaults.projects_root": "where new projects are created",
    "defaults.package_manager": "npm | pnpm | bun",
    "vps.provider": "hostinger | hetzner | contabo | oracle-free | other",
    "vps.ip": "server IPv4 (not secret)",
    "vps.ssh_user": "usually root",
    "coolify.url": "https://coolify.example.com (or the SSH-tunnel URL)",
    "dns.provider": "cloudflare | registrar",
    "domain.default": "a domain the owner owns (optional)",
    "github.user": "GitHub handle for new repos",
    "email.provider": "resend | mailgun | brevo | smtp",
    "notify.channel": "telegram | discord | email | webhook (where bots report)",
}
SECRET_NAMES = ("COOLIFY_TOKEN", "CLOUDFLARE_API_TOKEN", "HOSTINGER_API_TOKEN", "GITHUB_TOKEN", "RESEND_API_KEY",
                "MAILGUN_API_KEY", "BREVO_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
                "NOTIFY_WEBHOOK_URL", "B2_KEY_ID", "B2_APP_KEY", "TIGRIS_ACCESS_KEY_ID", "TIGRIS_SECRET_ACCESS_KEY",
                "STRIPE_SECRET_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SMTP_URL")


_PROJECT: Path | None = None      # the project whose layer applies (set by the CLI for every command)
# the owner's own facts and infrastructure (their server, DNS, GitHub, where bots report, backups): in a personal
# project they stay on the machine, so no new project asks them again; a business's own keys (email, payments) and a
# client's everything stay in the project
PERSON = ("owner.", "defaults.", "vps.", "coolify.", "dns.", "github.", "notify.")
PERSON_SECRETS = ("COOLIFY_TOKEN", "CLOUDFLARE_API_TOKEN", "HOSTINGER_API_TOKEN", "GITHUB_TOKEN", "TELEGRAM_BOT_TOKEN",
                  "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "NOTIFY_WEBHOOK_URL", "B2_KEY_ID", "B2_APP_KEY",
                  "TIGRIS_ACCESS_KEY_ID", "TIGRIS_SECRET_ACCESS_KEY")
LOCATIONS = ("here", "machine")   # … or a folder outside the project
ASK_ONCE = ("Tell the owner once: this project's settings and keys are kept in {where} (this project only, on this "
            "machine only, never pushed). To keep them somewhere else: `dh profile where --set machine` (shared by "
            "every project) or `dh profile where --set <folder>` (a folder outside the project). Not asked again here.")


def use_project(root) -> None:
    global _PROJECT
    _PROJECT = Path(root) if root and (Path(root) / ".deckhand").is_dir() else None


def _proj(root=None) -> Path | None:
    if root is None:
        return _PROJECT
    return Path(root) if (Path(root) / ".deckhand").is_dir() else None


def profile_path() -> Path:
    return home() / "profile.json"


def vault_path() -> Path:
    return home() / "vault.env"


def layout_path(root=None) -> Path | None:
    r = _proj(root)
    return r / ".deckhand" / "layout.json" if r else None


def _same(a, b) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except (OSError, TypeError, ValueError):
        return False


def binding(root=None) -> dict | None:
    """This project's remembered choice (.deckhand/layout.json), checked; None = never chosen. A broken one
    (corrupt, its folder gone, or copied from another project) is reported, never silently replaced."""
    r, p = _proj(root), layout_path(root)
    if not p or not p.exists():
        return None
    b = read_json(p, None)
    if not isinstance(b, dict) or b.get("location") not in ("here", "machine", "folder"):
        return {"ok": False, "problem": "is not a valid layout file", "file": str(p)}
    problem = None
    if b["location"] == "folder":
        d = Path(str(b.get("dir") or ""))
        if not b.get("dir") or not d.is_absolute():
            problem = "has no valid folder"
        elif not d.is_dir():
            problem = f"points to {d}, which is not there (a drive not mounted, a folder moved?)"
        elif not os.access(d, os.R_OK | os.W_OK):
            problem = f"points to {d}, which this user cannot read and write"
        elif not _same(b.get("root"), r):
            problem = (f"was made for the project at {b.get('root')} and this one is at {r} — a copy never shares "
                       "the other copy's keys")
    return {**b, "file": str(p), "ok": problem is None, **({"problem": problem} if problem else {})}


def layer_dir(root=None) -> Path | None:
    """The folder holding this project's own profile.json / vault.env / profile.md: the bound folder, else .deckhand/."""
    r = _proj(root)
    if not r:
        return None
    b = binding(root)
    if b and b["ok"] and b["location"] == "folder":
        return Path(b["dir"])
    return r / ".deckhand"


def project_profile_path(root=None) -> Path | None:
    d = layer_dir(root)
    return d / "profile.json" if d else None


def project_vault_path(root=None) -> Path | None:
    d = layer_dir(root)
    return d / "vault.env" if d else None


def project_notes_path(root=None) -> Path | None:
    d = layer_dir(root)
    return d / "profile.md" if d else None


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def project_profile() -> dict:
    p = project_profile_path()
    return (read_json(p, {}) or {}) if p else {}


def scope(root=None) -> str:
    """"client" when this project was started for a client: its settings and secrets stay in the project.
    Read from .deckhand/profile.json wherever the project's layer lives (the scope belongs to the project itself)."""
    r = _proj(root)
    return "client" if r and (read_json(r / ".deckhand" / "profile.json", {}) or {}).get("scope") == "client" else "me"


def set_scope(root, who: str) -> str:
    """`dh init --for me|client`: a client project keeps its own settings and secrets (.deckhand/, gitignored)."""
    if who not in ("me", "client"):
        raise DhError("BAD_SCOPE", "--for me | client")
    p = Path(root) / ".deckhand" / "profile.json"
    prof = read_json(p, {}) or {}
    if prof.get("scope", "me") != who:
        prof["scope"] = who
        prof["updated"] = now()
        write_json(p, prof)
    return who


def load() -> dict:
    return _merge(read_json(profile_path(), {}) or {}, project_profile())


def _route(where: str | None, kind: str, key: str | None = None):
    """(file, notice) for one write. --machine / --here are per-call overrides; otherwise the project's remembered
    choice. The first write that needs it records `here` and returns the one-time ask; a broken choice refuses."""
    name = "profile.json" if kind == "profile" else "vault.env"
    personal = bool(key) and (key.startswith(PERSON) or key in PERSON_SECRETS)
    if where == "machine" or (where is None and (not _PROJECT or (personal and scope() != "client"))):
        return home() / name, {}
    if not _PROJECT:
        raise DhError("NO_PROJECT", "no project here (.deckhand/) — run inside the project, or pass --project")
    b = binding()
    if b is not None and not b["ok"]:
        raise DhError("BINDING_BROKEN", f"where this project keeps its settings ({b['file']}) {b['problem']} — nothing was "
                      "written. Ask the owner, then `dh profile where --set here|machine|<folder>`", binding=b)
    notice = {}
    if b is None and where is None:
        b = _write_binding("here", None, "default")
        notice = {"bound": where_view(), "ask_once": ASK_ONCE.format(where="`.deckhand/`")}
    if where is None and b["location"] == "machine":
        return home() / name, notice
    return layer_dir() / name, notice


def _set(d: dict, dotted: str, value):
    cur = d
    parts = dotted.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _get(d: dict, dotted: str):
    cur = d
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


SECRETISH = re.compile(r"(token|secret|password|passwd|api[_-]?key|private)", re.I)


def set_fields(pairs: list, where: str | None = None) -> dict:
    """Where this project keeps its settings (`dh profile where`); the owner's own facts (owner.*, defaults.*) stay on
    the machine in a personal project; --here / --machine override for one call."""
    parsed = []
    for pair in pairs:
        if "=" not in pair:
            raise DhError("BAD_PAIR", f"expected key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        if SECRETISH.search(k):
            raise DhError("SECRET_IN_PROFILE", f"{k} looks like a secret — use `dh vault set {k.upper()}` instead")
        parsed.append((k.strip(), [x.strip() for x in v.split(",")] if k.endswith(("languages", "features")) else v))
    groups, notice = {}, {}
    for k, val in parsed:
        target, n = _route(where, "profile", k)
        notice = notice or n
        groups.setdefault(target, []).append((k, val))
    for target, kv in groups.items():
        prof = read_json(target, {}) or {}
        for k, val in kv:
            _set(prof, k, val)
        prof["updated"] = now()
        write_json(target, prof)
    main = next((t for t in groups if t != profile_path()), profile_path())
    split = {("machine" if t == profile_path() else "project"): [k for k, _ in kv] for t, kv in groups.items()}
    return {"changed": dict(parsed), "path": str(main), "scope": "project" if main != profile_path() else "machine",
            **({"split": split} if len(split) > 1 else {}), **notice}


# ------------------------------------------------------------------ vault
def vault_read() -> dict:
    """Every stored secret this project can use (machine vault, then the project's own, which wins)."""
    out = _vault_file(vault_path())
    pv = project_vault_path()
    if pv:
        out.update(_vault_file(pv))
    return out


def vault_names() -> dict:
    pv = project_vault_path()
    return {"machine": sorted(_vault_file(vault_path())), "project": sorted(_vault_file(pv)) if pv else []}


def _vault_file(p) -> dict:
    out = {}
    if not p or not Path(p).exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.replace("export ", "").strip()] = _unquote(v.strip())
    return out


def _unquote(v: str) -> str:
    try:
        parts = shlex.split(v, posix=True)
        return parts[0] if len(parts) == 1 else v
    except ValueError:
        return v.strip('"').strip("'")


def _quote(v: str) -> str:
    """Single-quoted, so sourcing the vault in a shell never executes or splits a value (`1|abc`, `$x`, spaces)."""
    return "'" + v.replace("'", "'\\''") + "'"


def legacy_home() -> Path:
    return Path(os.environ.get("VPS_OPS_HOME") or (Path.home() / ".vps-ops"))


def legacy_read() -> dict:
    """v1's ops keyring (~/.vps-ops/secrets/*.env.sh) — read-only compatibility, so existing servers keep working."""
    out = {}
    d = legacy_home() / "secrets"
    for f in sorted(d.glob("*.sh")) if d.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", line)
            if m and m.group(1) not in out:
                out[m.group(1)] = _unquote(m.group(2).strip())
    return out


def vault_set(name: str, value: str | None = None, where: str | None = None) -> dict:
    if not re.match(r"^[A-Z][A-Z0-9_]{1,63}$", name):
        raise DhError("BAD_NAME", "vault names are UPPER_SNAKE_CASE")
    if value is None:
        value = sys.stdin.readline().rstrip("\n") if not sys.stdin.isatty() else __import__("getpass").getpass(f"{name}: ")
    if not value:
        raise DhError("EMPTY", "no value given")
    p, notice = _route(where, "vault", name)
    data = _vault_file(p)                      # only this layer is rewritten: a client's secret never lands elsewhere
    data[name] = value
    _write_vault(p, data)
    return {"stored": name, "names": sorted(data), "scope": "project" if p != vault_path() else "machine", **notice}


def _write_vault(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# deckhand vault — secrets only; never commit, never paste into chat\n" +
                 "\n".join(f"{k}={_quote(v)}" for k, v in sorted(data.items())) + "\n", encoding="utf-8")
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def secret(name: str):
    """Env first (CI / harness secrets), then this project's vault, the machine vault, v1's ops keyring. Never logged."""
    if os.environ.get(name):
        return os.environ[name]
    b = binding() if _PROJECT else None
    if b is not None and not b["ok"] and scope() == "client":
        return None                                   # a client's keys are unreadable: never the owner's instead
    pv = project_vault_path()
    return (_vault_file(pv).get(name) if pv else None) or _vault_file(vault_path()).get(name) or legacy_read().get(name)


def shell_line() -> str:
    """The vault(s) loaded into a shell for curl lines — paths only, never a value (machine first, the project's wins)."""
    files = [f for f in (vault_path(), project_vault_path()) if f and f.exists()]
    return "set -a; " + " ".join(". " + shlex.quote(f.as_posix()) + ";" for f in files) + " set +a" if files else ""


# ------------------------------------------------------------------ where (the per-project choice)
def _write_binding(location: str, folder: Path | None, by: str, root=None) -> dict:
    r = Path(root) if root is not None else _PROJECT
    ensure_gitignore(r)                        # the layout (absolute paths of this machine) and the layer: never in git
    d = folder if location == "folder" else r / ".deckhand"
    rec = {"version": 1, "root": str(r.resolve()), "location": location, **({"dir": str(folder)} if folder else {}),
           "profile_path": str(d / "profile.json"), "vault_path": str(d / "vault.env"), "profile_md_path": str(d / "profile.md"),
           "writes": "machine" if location == "machine" else "project", "chosen_by": by, "bound_at": now()}
    write_json(r / ".deckhand" / "layout.json", rec)
    return binding(r)


def carry(src, dst) -> dict:
    """clone / adopt / scaffold into another folder: the app is the same project as the folder it was planned in, so
    it gets the same choice and a copy of that folder's own layer (profile fields, vault, notes; what the app folder
    already holds wins). A folder binding is shared, never copied. Nothing happens in place or from a broken choice."""
    src, dst = Path(src), Path(dst)
    if _same(src, dst) or not (src / ".deckhand").is_dir() or not dst.is_dir():
        return {}
    b = binding(src)
    if b is not None and not b["ok"]:
        return {}
    (dst / ".deckhand").mkdir(parents=True, exist_ok=True)
    ensure_gitignore(dst)
    out = {}
    if b and b["location"] == "folder":
        _write_binding("folder", Path(b["dir"]), b.get("chosen_by") or "owner", dst)
        return {"shared_folder": b["dir"]}
    old, new = src / ".deckhand", dst / ".deckhand"
    fields = {k: v for k, v in _flat(read_json(old / "profile.json", {}) or {}).items() if k not in KEEP}
    if fields:
        prof = read_json(new / "profile.json", {}) or {}
        have = _flat(prof)
        for k, v in fields.items():
            if k not in have:
                _set(prof, k, v)
        write_json(new / "profile.json", prof)
        out["profile"] = sorted(fields)
    ov = _vault_file(old / "vault.env")
    if ov:
        _write_vault(new / "vault.env", {**ov, **_vault_file(new / "vault.env")})
        out["vault"] = sorted(ov)
    if (old / "profile.md").exists() and not (new / "profile.md").exists():
        (new / "profile.md").write_bytes((old / "profile.md").read_bytes())
        out["notes_md"] = True
    if b:
        _write_binding(b["location"], None, b.get("chosen_by") or "owner", dst)
        out["location"] = b["location"]
    return out


def where_view() -> dict:
    """Where this project's settings and keys are read from and written to — every path, no value."""
    b = binding()
    lay = layer_dir()
    if not _PROJECT:
        return {"project": None, "location": None, "writes": {"profile": str(profile_path()), "vault": str(vault_path())},
                "say": "not inside a Deckhand project (.deckhand/): the machine layer is used — `dh init` gives a project its own"}
    machine_writes = bool(b and b.get("ok") and b.get("location") == "machine")
    out = {"project": str(_PROJECT), "location": b.get("location") if b else None,
           "chosen_by": (b or {}).get("chosen_by"), "ok": b["ok"] if b else True,
           "layer": {"profile": str(lay / "profile.json"), "vault": str(lay / "vault.env"), "notes_md": str(lay / "profile.md")},
           "machine": {"profile": str(profile_path()), "vault": str(vault_path()), "notes_md": str(home() / "profile.md")},
           "writes": {"profile": str(profile_path() if machine_writes else lay / "profile.json"),
                      "vault": str(vault_path() if machine_writes else lay / "vault.env"),
                      "owner_facts": str(profile_path() if scope() != "client" else lay / "profile.json")},
           "scope": scope()}
    if b and not b["ok"]:
        out["problem"] = b["problem"]
    if not b:
        out["say"] = ("not chosen yet: the first `dh profile set` / `dh vault set` for this project keeps them in .deckhand/ "
                      "and asks the owner once")
    return out


def _flat(d: dict, pre: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, pre + k + "."))
        else:
            out[pre + k] = v
    return out


KEEP = ("scope", "updated")                    # the project's own record in .deckhand/profile.json, never moved


def bind(to: str) -> dict:
    """`dh profile where --set here|machine|<folder>`: record where this project's settings and keys live. Moving to
    another folder carries this project's own layer along (profile fields, vault, notes); a value that differs on
    both sides stops everything (names only, nothing changed). Nothing is ever copied into the machine layer."""
    if not _PROJECT:
        raise DhError("NO_PROJECT", "no Deckhand project here (.deckhand/) — `dh init` first, or pass --project")
    to = (to or "").strip()
    if not to:
        raise DhError("USAGE", "dh profile where --set here | machine | <folder outside the project>")
    folder = None
    if to in LOCATIONS:
        location = to
    else:
        location = "folder"
        folder = Path(os.path.expanduser(to))
        folder = (folder if folder.is_absolute() else Path.cwd() / folder).resolve()
        root = _PROJECT.resolve()
        if folder == root or root in folder.parents:
            raise DhError("IN_PROJECT", f"{folder} is inside the project, where a file can end up committed — use `here` "
                          "(.deckhand/, always gitignored) or a folder outside the project")
        if _same(folder, home()):
            raise DhError("IS_MACHINE", f"{folder} is the machine layer — use `dh profile where --set machine`")
        if folder.exists() and not folder.is_dir():
            raise DhError("NOT_A_FOLDER", f"{folder} is a file")
    if location == "machine" and scope() == "client":
        raise DhError("CLIENT_PROJECT", "a client project keeps its settings and keys in its own layer (never shared "
                      "with other projects) — choose `here` or a folder")
    old, new = layer_dir(), (folder if location == "folder" else _PROJECT / ".deckhand")
    moved = _move_layer(old, new) if not _same(old, new) else {}
    b = _write_binding(location, folder, "owner")
    return {**where_view(), **({"moved": moved} if moved else {}), "bound_at": b["bound_at"]}


def _move_layer(old: Path, new: Path) -> dict:
    """Carry this project's own layer from one folder to another. Checks everything first, then writes."""
    op, np_ = old / "profile.json", new / "profile.json"
    oprof, nprof = read_json(op, {}) or {}, read_json(np_, {}) or {}
    ofields = {k: v for k, v in _flat(oprof).items() if k not in KEEP}
    nfields = _flat(nprof)
    ov, nv = _vault_file(old / "vault.env"), _vault_file(new / "vault.env")
    om, nm = old / "profile.md", new / "profile.md"
    clash = sorted([k for k, v in ofields.items() if k in nfields and nfields[k] != v] +
                   [k for k, v in ov.items() if k in nv and nv[k] != v] +
                   (["profile.md"] if om.exists() and nm.exists() and om.read_bytes() != nm.read_bytes() else []))
    if clash:
        raise DhError("CONFLICT", f"both {old} and {new} hold a different value for: {', '.join(clash)} — nothing was "
                      "changed. Keep one (edit or remove the other), then run this again", names=clash)
    if not new.exists():
        new.mkdir(parents=True)
        try:
            os.chmod(new, stat.S_IRWXU)
        except OSError:
            pass
    moved = {}
    if ofields:
        for k, v in ofields.items():
            _set(nprof, k, v)
        nprof["updated"] = now()
        write_json(np_, nprof)
        rest = {k: oprof[k] for k in KEEP if k in oprof}
        if rest.get("scope"):
            write_json(op, rest)
        else:
            op.unlink()
        moved["profile"] = sorted(ofields)
    if ov:
        _write_vault(new / "vault.env", {**nv, **ov})
        (old / "vault.env").unlink()
        moved["vault"] = sorted(ov)
    if om.exists():
        if not nm.exists():
            new.joinpath("profile.md").write_bytes(om.read_bytes())
        om.unlink()
        moved["notes_md"] = True
    return moved


# ------------------------------------------------------------------ doctor
def _probe(url: str, headers=None, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deckhand-doctor/2", **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", None) or str(e)[:80]


def doctor(online: bool = True) -> dict:
    prof = load()
    have = {n: bool(secret(n)) for n in SECRET_NAMES}
    tools = {t: bool(which(t)) for t in ("git", "node", "npm", "pnpm", "bun", "gh", "ssh", "docker", "python3")}
    caps = {}
    cu, ct = _get(prof, "coolify.url") or os.environ.get("COOLIFY_URL"), secret("COOLIFY_TOKEN")
    if cu and ct and online:
        st = _probe(cu.rstrip("/") + "/api/v1/version", {"Authorization": f"Bearer {ct}"})
        caps["coolify"] = {"ok": st == 200, "evidence": f"GET /api/v1/version -> {st}"}
    else:
        caps["coolify"] = {"ok": False, "evidence": "coolify.url + COOLIFY_TOKEN not both set"}
    cf = secret("CLOUDFLARE_API_TOKEN") or secret("CF_API_TOKEN")          # CF_API_TOKEN = v1's name
    if cf and online:
        st = _probe("https://api.cloudflare.com/client/v4/user/tokens/verify", {"Authorization": f"Bearer {cf}"})
        caps["cloudflare"] = {"ok": st == 200, "evidence": f"tokens/verify -> {st}"}
    else:
        caps["cloudflare"] = {"ok": False, "evidence": "CLOUDFLARE_API_TOKEN not set"}
    if tools["gh"]:
        r = run(["gh", "auth", "status"], timeout=20)
        caps["github"] = {"ok": r["code"] == 0, "evidence": "gh auth status -> " + str(r["code"])}
    else:
        caps["github"] = {"ok": bool(secret("GITHUB_TOKEN")), "evidence": "gh not installed; GITHUB_TOKEN " + ("set" if secret("GITHUB_TOKEN") else "missing")}
    ip = _get(prof, "vps.ip")
    caps["vps"] = {"ok": bool(ip), "evidence": f"vps.ip={ip}" if ip else "no vps.ip in profile"}
    caps["notify"] = {"ok": bool(secret("TELEGRAM_BOT_TOKEN") or secret("DISCORD_WEBHOOK_URL") or secret("NOTIFY_WEBHOOK_URL") or secret("SMTP_URL")),
                      "evidence": "a bot can report somewhere" if any(have[n] for n in ("TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL", "NOTIFY_WEBHOOK_URL", "SMTP_URL")) else "no notification channel secret"}
    missing_fields = [k for k in ("owner.name", "defaults.mode", "defaults.hosting") if _get(prof, k) is None]
    asks = []
    if not caps["coolify"]["ok"]:
        asks.append("Coolify: dashboard → Keys & Tokens → API tokens → create (root) → `dh vault set COOLIFY_TOKEN`")
    if not caps["cloudflare"]["ok"]:
        asks.append("Cloudflare: My Profile → API Tokens → Create (Zone.DNS:Edit + Email Routing) → `dh vault set CLOUDFLARE_API_TOKEN`")
    pp = project_profile_path()
    return {"profile": str(profile_path()), "exists": profile_path().exists(),
            "project_layer": str(pp) if pp and pp.exists() else None, "where": where_brief(), "missing_fields": missing_fields,
            "tools": tools, "secrets_present": [k for k, v in have.items() if v], "capabilities": caps,
            "one_batched_ask": asks}


def where_brief() -> dict:
    v = where_view()
    return {k: v[k] for k in ("location", "chosen_by", "ok", "problem", "say", "writes") if k in v}
