"""DEPLOY: ship to Coolify and PROVE it — terminal deployment for YOUR commit + a live smoke check.

First-time server/domain/app setup is a runbook (references/ops/00→30); from then on:
  dh deploy target --app <uuid> --url https://…   (once)
  dh deploy ship                                   (every release: push → deploy → wait → smoke)
Credentials come from the vault (COOLIFY_TOKEN) + profile (coolify.url); never from chat.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

from .util import SKILL, DhError, now, read_json, run, write_json
from . import profile as PROFILE

sys.path.insert(0, str(SKILL / "ops" / "scripts"))
import coolify_api as CA  # noqa: E402


def _creds():
    prof = PROFILE.load()
    url = os.environ.get("COOLIFY_URL") or (prof.get("coolify") or {}).get("url")
    tok = PROFILE.secret("COOLIFY_TOKEN")
    try:
        return CA.resolve(url_override=url, token_override=tok)
    except SystemExit as e:
        raise DhError("NO_COOLIFY", str(e) + " — `dh profile set coolify.url=…` + `dh vault set COOLIFY_TOKEN`")


def deploy_path(root: Path) -> Path:
    return Path(root) / ".deckhand" / "deploy.json"


def target(root: Path, app: str | None, url: str | None) -> dict:
    d = read_json(deploy_path(root), {}) or {}
    if app:
        d["app_uuid"] = app
    if url:
        d["url"] = url.rstrip("/")
    write_json(deploy_path(root), d)
    from . import seo as SEO
    if d.get("url") and SEO.PREVIEW_RX.search(d["url"]):
        return {**d, "preview": "set the BUILD variable DH_NOINDEX=1 on this app so the preview is never indexed: "
                "`dh deploy raw envset <app-uuid> DH_NOINDEX=1` (the real domain never sets it)"}
    return d


def smoke(root: Path, url: str | None = None, contains: str | None = None) -> dict:
    d = read_json(deploy_path(root), {}) or {}
    url = (url or d.get("url") or "").rstrip("/")
    if not url:
        raise DhError("NO_URL", "no live URL (dh deploy target --url https://…)")
    brief = read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}
    contains = contains or (brief.get("brand") or {}).get("name") or None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CA.smoke(url + "/", expect=200, contains=contains)
    d["url"] = url
    d["smoke"] = {"ok": rc == 0, "at": now(), "evidence": buf.getvalue().strip(), "contains": contains}
    if url.startswith("http://"):
        # the no-domain preview (Coolify's generated sslip.io URL) is fine to show — not to take logins or money
        d["smoke"]["warning"] = "NO_TLS: plain http — preview only; no logins, payments or personal data until a domain + HTTPS (references/70-deploy.md)"
    elif ".sslip.io" in url or ".nip.io" in url:
        d["smoke"]["warning"] = "PREVIEW_URL: a generated address — fine to share for feedback; add a domain before launch"
    write_json(deploy_path(root), d)
    return d["smoke"]


def ship(root: Path, force: bool = False, timeout: int = 900) -> dict:
    root = Path(root)
    d = read_json(deploy_path(root), {}) or {}
    if not d.get("app_uuid"):
        raise DhError("NO_TARGET", "first deploy is the runbook (references/ops/30-deploy-app.md), then `dh deploy target --app <uuid> --url <url>`")
    # deckhand's own records (.deckhand/deploy.json, verify.json…) are not what Coolify builds: they never block a ship
    dirty = run(["git", "status", "--porcelain", "--", ".", ":(exclude).deckhand"], cwd=root)["out"].strip()
    if dirty:
        raise DhError("DIRTY_TREE", "commit first — Coolify builds what is pushed, not what is on disk", files=dirty.splitlines()[:10])
    head = run(["git", "rev-parse", "HEAD"], cwd=root)["out"].strip()
    from .checks import verify_stale
    stale = verify_stale(root, read_json(root / ".deckhand" / "verify.json", {}) or {})
    if stale:
        raise DhError("VERIFY_STALE", f"{stale} — run `dh verify` again, then ship")
    push = run(["git", "push"], cwd=root, timeout=300)
    if push["code"] != 0 and "Everything up-to-date" not in push["err"]:
        raise DhError("PUSH_FAILED", push["err"][-400:])
    url, tok = _creds()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        st, body = CA.api(url, tok, "POST", "/deploy", params={"uuid": d["app_uuid"], **({"force": "true"} if force else {})})
    if st not in (200, 201):
        raise DhError("DEPLOY_REJECTED", f"HTTP {st} {str(body)[:300]}")
    log = []
    rc = CA.wait_for_deploy(url, tok, d["app_uuid"], timeout=timeout, log=log.append, expect_commit=head[:7])
    d["last"] = {"commit": head, "at": now(), "result": {0: "finished", 3: "failed", 5: "timeout"}.get(rc, str(rc)), "log": log[-12:]}
    write_json(deploy_path(root), d)
    if rc != 0:
        raise DhError("DEPLOY_FAILED", f"deployment {d['last']['result']} — `dh deploy raw dlogs <app-uuid>` / references/ops/40-change-pipeline.md (rollback)", log=log[-12:])
    sm = smoke(root)
    if not sm["ok"]:
        raise DhError("SMOKE_FAILED", "deployed, but the live check failed — roll back per references/ops/40-change-pipeline.md §rollback", smoke=sm)
    out = {"ok": True, "commit": head, "url": d.get("url"), "smoke": sm}
    from . import seo as SEO
    if d.get("url") and not SEO.PREVIEW_RX.search(d["url"]):
        out["indexnow"] = SEO.ping(root)              # Bing (ChatGPT search, Copilot), Yandex, Seznam, Naver learn about the release now
        out["next"] = "dh seo audit --url " + d["url"] + "   # live checks: HTTPS, one host, canonicals, indexing"
    return out


def passthrough(args: list) -> int:
    """`dh deploy raw <coolify_api args>` — the full client (logs, envs, envset, status, tunnel …)."""
    url, tok = _creds()
    os.environ["COOLIFY_URL"], os.environ["COOLIFY_TOKEN"] = url, tok
    return CA.main(args)
