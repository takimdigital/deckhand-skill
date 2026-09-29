"""Phase checks — each returns {"ok": bool, "why": [...], "hint": str}. A gate that cannot fail is not a gate."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .util import read_json

REQUIRED_BRIEF = ("business", "shape", "languages", "audience")


def _res(ok: bool, why=None, hint: str = "", **extra) -> dict:
    return {"ok": ok, "why": why or [], "hint": hint, **extra}


def define(root: Path, s: dict) -> dict:
    b = read_json(root / ".deckhand" / "brief.json", {}) or {}
    miss = [k for k in REQUIRED_BRIEF if not b.get(k)]
    return _res(not miss, [f"brief.{k} missing" for k in miss], "dh brief set business=\"…\" shape=saas languages=en,fr audience=\"…\"")


def research(root: Path, s: dict) -> dict:
    r = read_json(root / ".deckhand" / "research.json")
    if not r:
        return _res(False, ["no .deckhand/research.json"], "fill templates/research.json (web research, URLs only) then re-run")
    why = []
    comps = [c for c in r.get("competitors", []) if str(c.get("url", "")).startswith("http")]
    if len(comps) < 3:
        why.append(f"{len(comps)} competitors with a URL (need 3)")
    for c in comps:
        if not c.get("strengths") or not c.get("gaps"):
            why.append(f"competitor {c.get('name') or c.get('url')}: strengths + gaps required")
    if not (r.get("audience") or {}).get("primary"):
        why.append("audience.primary missing")
    if not (r.get("conversion") or {}).get("plays"):
        why.append("conversion.plays missing (what makes the best in this niche convert)")
    if not (r.get("features") or {}).get("now"):
        why.append("features.now missing (what must exist on day one)")
    from . import research as RS
    if not r.get("claims") and not list((root / ".deckhand" / "research" / "agents").glob("*.json")):
        why.append("claims[] missing — each fact with label, url and verbatim quote (references/research-card.md)")
    if len(RS._all_vocab(root)) < RS.POLICY["min_vocabulary"]:
        why.append(f"vocabulary: {RS.POLICY['min_vocabulary']}+ terms harvested from real pages (term, kind, url, quote)")
    v = RS.verified_now(root)
    if v is None:
        why.append("run `dh research verify` (after the last change to research.json): every quote is fetched and checked")
    elif not v.get("ok"):
        s = v["summary"]
        why.append(f"dh research verify: {s['mismatch']} quotes not on their page, {s['invalid']} invalid claims, {s['terms_bad']} bad terms")
    elif v["summary"].get("found", 0) + v["summary"].get("terms_found", 0) < RS.POLICY.get("min_found", 3):
        need = RS.POLICY.get("min_found", 3)             # every fetch blocked = nothing proven (review 2026-09-27, finding 14)
        why.append(f"dh research verify found {v['summary'].get('found', 0) + v['summary'].get('terms_found', 0)} quotes on their pages (need {need}): add claims from pages that "
                   f"can be fetched, or, with the owner's word, `dh phase skip research --reason \"…\"`")
    return _res(not why, why, "research is evidence: every claim carries its label, URL and a quote that is really on the page")


def plan(root: Path, s: dict) -> dict:
    from . import plan as P
    from .util import SKILL
    r = P.lint(root)
    why = [e["msg"] for e in r["errors"]]
    if read_json(root / ".deckhand" / "sitemap.json") == read_json(SKILL / "templates" / "sitemap.json"):
        why.insert(0, "sitemap.json is still the `dh plan init` example: write this business's pages from the brief and research")
    return _res(not why, why, "fix the sitemap (dh plan lint shows each dead end)", warnings=len(r["warnings"]))


def build(root: Path, s: dict) -> dict:
    why = []
    if not s.get("base"):
        why.append("no base recorded (dh clone | dh adopt | dh scaffold)")
    if not (root / "package.json").exists() and not (root / "pyproject.toml").exists():
        why.append("no package.json in the project")
    dev = read_json(root / ".deckhand" / "dev.json", {}) or {}
    url = dev.get("url")
    if not url:
        why.append("the app has not been started (dh dev start)")
    else:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                if r.status >= 500:
                    why.append(f"{url} answered {r.status}")
        except Exception as e:  # noqa: BLE001 — any failure to answer is the evidence
            code = getattr(e, "code", None)
            if not code or code >= 500:
                why.append(f"{url} does not answer ({e})")
    return _res(not why, why, "dh dev start — then open the URL; the owner tests it (gate G2)", url=url)


def brand(root: Path, s: dict) -> dict:
    from . import brand as B
    r = B.check(root)
    return _res(r["ok"], [f"{x['file']}:{x['line']} {x['kind']}: {x['text']}" for x in r["findings"][:12]], "dh rebrand apply, then fix what check lists")


def tryon(root: Path, s: dict) -> dict:
    d = root / ".deckhand" / "tryon" / "sessions"
    open_ = []
    if d.exists():
        for f in d.glob("*.json"):
            j = json.loads(f.read_text(encoding="utf-8"))
            if j.get("state") == "open":
                open_.append(j["id"])
    return _res(not open_, [f"try-on session {i} still open (keep or discard it)" for i in open_], "tryon keep|discard --id <id>")


def review(root: Path, s: dict) -> dict:
    r = read_json(root / ".deckhand" / "verify.json")
    if not r:
        return _res(False, ["no verify report"], "dh verify")
    return _res(bool(r.get("ok")), [f"{x['check']}: {x['detail']}" for x in r.get("rows", []) if not x.get("ok") and x.get("blocking", True)], "dh verify (fix every red row)")


def deploy(root: Path, s: dict) -> dict:
    d = read_json(root / ".deckhand" / "deploy.json", {}) or {}
    why = []
    if not d.get("url"):
        why.append("no live URL recorded")
    if not (d.get("smoke") or {}).get("ok"):
        why.append("no passing smoke check against the live URL")
    if not (root / "HANDOFF.md").exists():
        why.append("HANDOFF.md not written (dh handoff)")
    return _res(not why, why, "dh deploy … then dh handoff")


def operate(root: Path, s: dict) -> dict:
    return _res(True)


def run(phase: str, root: Path, s: dict) -> dict:
    return globals()[phase](Path(root), s)
