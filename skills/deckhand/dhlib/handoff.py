"""HANDOFF.md — everything the owner (or the next agent) needs, with secret LOCATIONS, never values."""
from __future__ import annotations

import re
from pathlib import Path

from .util import now, package_json, read_json
from . import profile as PROFILE


def write(root: Path) -> dict:
    root = Path(root)
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    s = read_json(root / ".deckhand" / "run.json", {}) or {}
    dep = read_json(root / ".deckhand" / "deploy.json", {}) or {}
    ver = read_json(root / ".deckhand" / "verify.json", {}) or {}
    sm = read_json(root / ".deckhand" / "sitemap.json", {}) or {}
    pkg = package_json(root)
    name = (brief.get("brand") or {}).get("name") or brief.get("name") or s.get("name") or root.name
    admin = [p["route"] for p in sm.get("pages", []) if p.get("auth") in ("admin", "user")]
    bots = sorted(p.name for p in (root / "ops" / "bots").glob("*.py") if p.name != "notify.py") if (root / "ops" / "bots").exists() else []
    env_names = []
    for ex in (".env.example", ".env.local.example"):
        if (root / ex).exists():
            env_names = [l.split("=")[0] for l in (root / ex).read_text(encoding="utf-8").splitlines() if re.match(r"^[A-Z0-9_]+=", l)]
            break
    pending = []
    if (root / "PENDING.md").exists():
        pending = [l for l in (root / "PENDING.md").read_text(encoding="utf-8").splitlines() if l.startswith("- [ ]")]
    prof = PROFILE.load()
    url = dep.get("url") or ""
    preview = url.startswith("http://") or bool(re.search(r"\.(sslip|nip)\.io(/|$)", url)) or (prof.get("hosting") or "").startswith("free")
    L = [f"# {name} — handoff" + (" (PREVIEW)" if preview else ""), "", f"_Written {now()} by deckhand. Secrets are never in this file — only where they live._", ""]
    if preview:
        L += ["> **Preview deployment.** " + ("No HTTPS: do not take logins, payments or personal data here. " if url.startswith("http://") else "")
              + "Going to production = a domain + HTTPS (references/ops/20-domain-dns-ssl.md) and, from the free tier, "
              "references/ops/60-migrate-to-paid.md.", ""]
    L += ["## Live", "", f"- **Site:** {url or '(not deployed yet)'}" + (" — preview" if preview else ""),
          f"- **Last release:** {(dep.get('last') or {}).get('commit', '—')[:12]} · smoke {'OK' if (dep.get('smoke') or {}).get('ok') else 'not proven'}",
          f"- **Signed-in areas:** {', '.join(admin) or 'none'}",
          f"- **Server dashboard (Coolify):** {((prof.get('coolify') or {}).get('url')) or 'see references/ops/10-bootstrap-vps.md'} — reachable through the SSH tunnel only", ""]
    here = "COOLIFY_TOKEN" in PROFILE.vault_names()["project"]
    lay = PROFILE.layer_dir(root)
    # HANDOFF.md can travel (a client, a repo): a folder outside the project is named by the command, not its path
    own = ("`.deckhand/vault.env` in this project (this project's own; never committed)" if lay == root / ".deckhand"
           else "this project's own vault, in a folder outside the project on the owner's machine (`dh profile where`)")
    L += ["## Access (where, not what)", "",
          "- Coolify API token: " + (own if here else "`~/.deckhand/vault.env`") + " → `COOLIFY_TOKEN`",
          "- App environment variables: Coolify → this application → Environment Variables" + (f" ({', '.join(env_names[:12])})" if env_names else ""),
          "- Admin/owner account: created at first deploy (references/ops/30-deploy-app.md §6b); its password is in YOUR password manager",
          "- Source code: this repository" + (f" ({s.get('base', {}).get('repo')})" if (s.get('base') or {}).get('repo') else ""), ""]
    pm = "npm run" if not (root / "pnpm-lock.yaml").exists() else "pnpm"
    L += ["## Everyday commands", "", "```bash",
          f"{pm} dev                  # run locally",
          "dh resume                    # where the project stands — start every new session (any AI) here",
          "dh next                      # what the agent should do next",
          "dh deploy ship               # push → deploy → wait → smoke (proof, not hope)",
          "dh verify                    # build, routes, secrets, honesty — before every release",
          "dh ops suggest               # bots that could run parts of the business",
          "node <skill>/tryon/cli.mjs serve   # try other designs for any section (dev only)",
          "```", "",
          "Rollback: references/ops/40-change-pipeline.md §rollback (redeploy the previous tag).", ""]
    L += ["## Running on its own", ""] + ([f"- `ops/bots/{b}`" for b in bots] or ["- no bots yet (`dh ops suggest`)"]) + [""]
    L += ["## Quality at handoff", ""] + ([f"- {'✅' if r['ok'] else ('❌' if r['blocking'] else '⚠️')} {r['check']}: {r['detail']}" for r in ver.get("rows", [])] or ["- `dh verify` not run"]) + [""]
    L += ["## Still needed from you", ""] + (pending or ["- nothing open"]) + [""]
    L += ["## Stack & licences", "", f"- {', '.join(f'{k}: {v}' for k, v in ((s.get('base') or {}).get('stack') or {}).items() if v) or pkg.get('name', '')}",
          "- `NOTICE` (base template) and `THIRD_PARTY_NOTICES.md` (components) must stay in the repository.", ""]
    from .redact import scrub_text
    (root / "HANDOFF.md").write_text(scrub_text("\n".join(L)), encoding="utf-8")       # stored text is scrubbed again on the way out
    return {"written": str(root / "HANDOFF.md"), "pending": len(pending)}
