"""HARVEST: a finished business becomes the owner's next head start — in THEIR GitHub library.

  dh harvest --name bakery-base [--push] [--repo owner/name] [--public]

The project's tracked files are copied (no .env, no .deckhand state, no logs), the owner's brand is
neutralised to the base's own name (so the NEXT project's rebrand replaces it and its leak check catches
leftovers), a manifest records what the base contains and what proved it (last verify, live URL), and the
base is registered in the personal pool — ranked first whenever it fits.
--push: a secret scan must be clean, then the base goes to a PRIVATE repo on the owner's GitHub
(owner/deckhand-base-<name>) and its row goes into their library index repo (owner/deckhand-library:
library.json + a readable README). Any machine, any harness: `dh pool sync` pulls the index, `dh pool query`
ranks it, `dh clone <name> --to dir` starts from it in one command.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .util import DhError, git_files, home, now, read_json, rmtree, run, slugify, write_json
from . import pool as POOL
from . import profile as PROFILE

DROP = re.compile(r"(^|/)(\.env($|\.(?!example$))|\.deckhand/|PENDING\.md$|HANDOFF\.md$|VERIFY\.md$|ops/bots/.*\.env$|\.bot-state/|node_modules/|\.next/)")
# the business's own data (catalogue, customers, photos): kept so the base builds, fingerprinted so the next
# project's rebrand check blocks until each file is replaced
OWNER_DATA = re.compile(r"((^|/)(seeds?|fixtures?|data)/.*\.(ts|js|json|sql|csv|md)$|^public/.*\.(jpe?g|png|webp|avif)$)")
# placeholders the rebrand check already blocks on (brand.py DEMO_NAMES)
PH_EMAIL, PH_PHONE, PH_ADDRESS, PH_DOMAIN, PH_SOCIAL, PH_PERSON, PH_TAGLINE = (
    "hello@example.com", "+1 555 0100", "123 Main St", "your-domain.example", "https://example.com/your-profile",
    "Jane Doe", "Your tagline")


def _flat(v) -> list:
    if isinstance(v, dict):
        return [x for y in v.values() for x in _flat(y)]
    if isinstance(v, (list, tuple)):
        return [x for y in v for x in _flat(y)]
    return [str(v)] if v not in (None, "") else []


def _facts(brief: dict, brand: str | None, display: str, name: str) -> list:
    """(regex, replacement) for everything that says who the previous business was: its name in every spelling,
    phone, email, address, domain, social profiles, owner, tagline — and any email or tel: link in the copy."""
    subs = []
    if brand:
        words = re.findall(r"[A-Za-z0-9]+", brand)
        if words:
            camel, dname = "".join(w[:1].upper() + w[1:] for w in words), "".join(w[:1].upper() + w[1:] for w in display.split())
            for spelled, repl in (("-".join(words), name), ("_".join(words), name.replace("-", "_")), (camel, dname),
                                  ("".join(words), name.replace("-", ""))):
                if len(spelled) >= 4:
                    subs.append((re.compile(r"(?<![A-Za-z0-9])" + re.escape(spelled) + r"(?![A-Za-z0-9])", re.I), repl))
    seo = brief.get("seo") or {}
    loc = seo.get("local") or {}
    if loc.get("phone"):
        digits = re.sub(r"\D", "", str(loc["phone"]))
        if len(digits) >= 6:
            # the same number however it is written: +33 6 12 34 56 78 · 06.12.34.56.78 · 0612345678
            core = digits[-9:]
            subs.append((re.compile(r"(\+?\d{1,3}[\s.-]?)?\(?0?\)?[\s.-]?" + r"[\s.-]?".join(core)), PH_PHONE))
    for email in _flat([loc.get("email"), brief.get("email"), (brief.get("contact") or {}).get("email") if isinstance(brief.get("contact"), dict) else None]):
        subs.append((re.compile(re.escape(email), re.I), PH_EMAIL))
    addr = loc.get("address")
    for part in sorted((a for a in _flat(addr) if a != "service-area" and len(a) >= 4), key=len, reverse=True):
        subs.append((re.compile(re.escape(part), re.I), PH_ADDRESS))
    dom = re.sub(r"^https?://(www\.)?", "", str(brief.get("domain") or "")).strip("/")
    if "." in dom:
        subs.append((re.compile(r"(?<![\w-])(www\.)?" + re.escape(dom), re.I), PH_DOMAIN))
    for url in _flat([(brief.get("brand") or {}).get("social"), seo.get("profiles")]):
        if url.startswith("http"):
            subs.append((re.compile(re.escape(url.rstrip("/")) + r"/?"), PH_SOCIAL))
    for who in _flat([(brief.get("owner") or {}).get("name") if isinstance(brief.get("owner"), dict) else brief.get("owner"),
                      PROFILE._get(PROFILE.load(), "owner.name")]):
        if len(who) >= 3:
            subs.append((re.compile(r"(?<![\w])" + re.escape(who) + r"(?![\w])"), PH_PERSON))
    tagline = (brief.get("brand") or {}).get("tagline")
    if tagline and len(tagline) >= 8:
        subs.append((re.compile(re.escape(tagline), re.I), PH_TAGLINE))
    # anything contact-shaped the brief does not know: an email, a tel: link
    subs.append((re.compile(r"(?<![\w.+-])[\w.+-]+@(?!example\.)[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+"), PH_EMAIL))
    subs.append((re.compile(r"tel:\+?[\d\s().-]{6,}"), "tel:" + PH_PHONE.replace(" ", "")))
    return subs


def harvest(root: Path, name: str, to: Path | None = None, repo: str | None = None, private: bool = True, push: bool = False) -> dict:
    root = Path(root)
    name = slugify(name)
    dest = Path(to) if to else home() / "bases" / name
    if dest.exists() and any(dest.iterdir()):
        prev = read_json(dest / "deckhand.template.json", {}) or {}
        if prev.get("from_project") != root.name:
            raise DhError("DEST_NOT_EMPTY", f"{dest} holds something else — pick another --name or --to")
        rmtree(dest)                                   # a new harvest of the same project replaces the previous one
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    brand = (brief.get("brand") or {}).get("name") or brief.get("name")
    display = name.replace("-", " ").title()
    facts = _facts(brief, brand, display, name)
    copied = 0
    owner_data = []
    neutralised = {}
    for p in git_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if DROP.search(rel) or not p.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = p.read_text(encoding="utf-8")
            if not re.search(r"(LICENSE|NOTICE|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?)$", rel):
                if brand:
                    text = re.sub(re.escape(brand), display, text, flags=re.I)
                n0 = text
                for rx, repl in facts:
                    text = rx.sub(repl, text)
                if text != n0:
                    neutralised[rel] = True
            out.write_text(text, encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(p, out)
        if OWNER_DATA.search(rel):
            owner_data.append({"path": rel, "sha": _sha(out)})
        copied += 1
    sm = read_json(root / ".deckhand" / "sitemap.json", {}) or {}
    if sm:
        write_json(dest / "deckhand.sitemap.json", sm)
    sections = sorted({p.parent.name for p in (dest / "components" / "sections").glob("*/*.tsx")}) if (dest / "components" / "sections").exists() else []
    pkg = read_json(dest / "package.json", {}) or {}
    stack = POOL.detect_stack(pkg, [str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if p.is_file()][:20000])
    ver = read_json(root / ".deckhand" / "verify.json", {}) or {}
    dep = read_json(root / ".deckhand" / "deploy.json", {}) or {}
    proven = {"verify": ver.get("ok"), "verified_at": ver.get("at"), "live": bool((dep.get("smoke") or {}).get("ok")),
              "rows": [r["check"] for r in ver.get("rows", []) if r.get("ok")]}
    manifest = {
        "name": name, "display_name": display, "created": now(), "from_project": root.name,
        "description": f"{display}: a {brief.get('shape') or 'web'} base" + (f" with {', '.join(brief.get('features') or [])}" if brief.get("features") else ""),
        "shape": brief.get("shape"), "features": brief.get("features") or [], "languages": brief.get("languages") or [],
        "stack": stack, "pages": [p.get("route") for p in sm.get("pages", [])], "sections": sections, "proven": proven,
        "template_names": [display, name], "owner_data_to_review": [d["path"] for d in owner_data[:100]],
        # the previous business's data files as harvested: the next project's rebrand check blocks while one is unchanged
        "owner_data": owner_data[:500], "neutralised": sorted(neutralised)[:200],
        "licences": {"notice": (dest / "NOTICE").read_text(encoding="utf-8") if (dest / "NOTICE").exists() else None,
                     "third_party": (dest / "THIRD_PARTY_NOTICES.md").exists()},
    }
    write_json(dest / "deckhand.template.json", manifest)
    run(["git", "init", "-q"], cwd=dest)
    run(["git", "add", "-A"], cwd=dest)
    run(["git", "-c", "user.name=deckhand", "-c", "user.email=deckhand@localhost", "commit", "-qm", f"base: {name} (harvested from {root.name})"], cwd=dest)
    row = {"name": name, "display_name": display, "path": str(dest), "license": "owner", "lane": "web", "shape": brief.get("shape"),
           "stack": stack, "canonical": stack.get("framework") == "next", "features": brief.get("features") or [], "vendors": [],
           "pages": manifest["pages"], "sections": sections, "proven": proven, "description": manifest["description"],
           "stars": None, "pushed_at": now()[:10], "measured": "harvest", "measured_at": now()}
    pushed = None
    if push or repo:
        leaks = secret_scan(dest)
        if leaks:
            raise DhError("SECRETS_IN_BASE", "not pushed: credential-shaped values are in the base — remove them, then harvest again "
                          f"(the local copy is at {dest} for review)", files=leaks[:20])
        from . import github as GH
        login = GH.me()
        full = repo or f"{login}/deckhand-base-{name}"
        made = GH.ensure_repo(full, description=f"Deckhand base: {manifest['description']}", private=private)
        if private and made.get("private") is False:
            raise DhError("REPO_PUBLIC", f"{full} is public — a base carries the business's own data: make it private, or pick another --repo")
        if not made["created"] and not made["empty"]:
            raise DhError("REPO_NOT_EMPTY", f"{full} already has commits — pick another --repo, or delete it first")
        GH.push(dest, full, branch="main")
        row["repo"], row["branch"] = full, "main"
        lib = library_repo(login)
        library_upsert(lib, {k: v for k, v in row.items() if k != "path"}, private=True)
        pushed = {"repo": full, "private": made.get("private", private), "library": lib}
    POOL.add_local(dest, row)
    return {"base": name, "path": str(dest), "files": copied, "manifest": "deckhand.template.json", "proven": proven, "pushed": pushed,
            "registered": "personal pool (ranked first when it fits)", "review": [d["path"] for d in owner_data[:12]],
            "neutralised": len(neutralised),
            "next": "dh pool query ranks it; dh clone " + name + " --to <dir> starts from it" + ("" if pushed else " · `--push` puts it in your private GitHub library")}


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def secret_scan(dest: Path) -> list:
    """Every credential-shaped file or value in a base about to be pushed (policy: data/secrets.json)."""
    from .util import SECRET_RX, SECRET_FILE_RX as SECRET_FILE
    hits = []
    for p in sorted(dest.rglob("*")):
        rel = str(p.relative_to(dest)).replace("\\", "/")
        if not p.is_file() or rel.startswith(".git/"):
            continue
        if SECRET_FILE.search(rel):
            hits.append(rel)
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if SECRET_RX.search(line):
                    hits.append(f"{rel}:{i}")
        except (UnicodeDecodeError, OSError):
            continue
    return hits


def library_repo(login: str) -> str:
    return ((PROFILE.load().get("library") or {}).get("repo")) or f"{login}/deckhand-library"


def _readme(rows: list) -> str:
    L = ["# My Deckhand library", "", "Private bases harvested from sites I built and shipped. Start a new project from one:", "",
         "```bash", "dh pool sync        # on any machine: pull this index", "dh clone <name> --to ./new-site", "```", "",
         "| base | shape | features | pages | proven |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["name"]):
        pv = r.get("proven") or {}
        badge = "verified + live" if pv.get("verify") and pv.get("live") else "verified" if pv.get("verify") else "—"
        L.append(f"| [{r['name']}](https://github.com/{r.get('repo', '')}) | {r.get('shape') or ''} | {', '.join(r.get('features') or [])} | "
                 f"{len(r.get('pages') or [])} | {badge} |")
    return "\n".join(L) + "\n"


def library_upsert(lib: str, row: dict, private: bool = True) -> dict:
    from . import github as GH
    made = GH.ensure_repo(lib, description="My Deckhand library: private bases to start new sites from", private=private)
    if private and made.get("private") is False:
        raise DhError("REPO_PUBLIC", f"{lib} is public — the library lists private bases: make it private (or set library.repo)")
    text, sha = GH.get_file(lib, "library.json")
    doc = json.loads(text) if text else {"version": 1, "bases": []}
    doc["bases"] = [b for b in doc.get("bases", []) if b.get("name") != row["name"]] + [row]
    doc["updated"] = now()
    GH.put_file(lib, "library.json", json.dumps(doc, indent=1, ensure_ascii=False) + "\n", f"base: {row['name']}", sha)
    _, rsha = GH.get_file(lib, "README.md")
    GH.put_file(lib, "README.md", _readme(doc["bases"]), f"index: {row['name']}", rsha)
    return {"library": lib, "bases": len(doc["bases"])}


def library_sync() -> dict:
    """Pull the owner's GitHub library index into the personal pool (any machine, any harness)."""
    from . import github as GH
    lib = library_repo(GH.me())
    text, _ = GH.get_file(lib, "library.json")
    if not text:
        return {"library": lib, "synced": 0, "next": "nothing yet — `dh harvest --name <base> --push` fills it"}
    doc = json.loads(text)
    have = {r["name"]: r for r in (read_json(POOL.personal_path(), {}) or {}).get("templates", [])}
    for b in doc.get("bases", []):
        keep = have.get(b["name"]) or {}
        POOL.add_local(Path(keep.get("path") or "."), {**b, **({"path": keep["path"]} if keep.get("path") and Path(keep["path"]).exists() else {})})
    return {"library": lib, "synced": len(doc.get("bases", [])), "bases": [b["name"] for b in doc.get("bases", [])]}
