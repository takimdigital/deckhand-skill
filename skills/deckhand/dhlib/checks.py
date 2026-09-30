"""Phase checks — each returns {"ok": bool, "why": [...], "hint": str}. A gate that cannot fail is not a gate."""
from __future__ import annotations

import json
import re
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
    r = read_json(root / ".deckhand" / "research.json", None, expect=dict)
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


def _fetch(url: str) -> tuple:
    """(status or None, the first 400 kB of HTML). An HTTP error still has a status: that is the evidence."""
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — any failure to answer is the evidence
        return getattr(e, "code", None), ""


def _planned(root: Path) -> tuple:
    """The plan's public static routes, and each planned form with the route of its page (F9)."""
    sm = read_json(root / ".deckhand" / "sitemap.json", {}) or {}
    pages = [p for p in sm.get("pages", []) or [] if p.get("route") and "[" not in p["route"]]
    public = {p.get("id"): p["route"] for p in pages if (p.get("auth") or "public") == "public"}
    forms = [(f.get("id"), public[f.get("page")]) for f in sm.get("forms", []) or [] if f.get("page") in public]
    return list(dict.fromkeys(public.values())), forms


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
        base = url.rstrip("/")
        routes, forms = _planned(root)
        worst = 400 if routes else 500                # with a plan, a planned page that 404s is not built (F9); without, only the root is judged
        html_of = {}
        for r_ in (["/"] + [x for x in routes if x != "/"])[:40]:
            code, html = _fetch(base + r_)
            html_of[r_] = html
            if not code:
                why.append(f"{base + r_} does not answer")
            elif code >= worst:
                why.append(f"{r_} -> {code}" if r_ != "/" else f"{url} answered {code}")
        for fid, r_ in forms:
            html = html_of[r_] if r_ in html_of else _fetch(base + r_)[1]
            if html and re.search(r'<div id="(root|app|__next)"></div>', html) and "<form" not in html.lower():
                continue                              # drawn by JavaScript: `dh verify` checks it in a browser
            if "<form" not in html.lower():
                why.append(f"form {fid}: {r_} has no <form>")
    return _res(not why, why, "build the pages and forms listed in why (dh plan render shows each one), keep dh dev start running, then dh phase done build — the owner tests it (gate G2)", url=url)


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


def verify_stale(root: Path, r: dict) -> str:
    """A green verify proves one commit; code committed after it (a reopened phase, a quick fix) is unproven.
    Committing deckhand's own files (.deckhand/: run.json, verify.json, VERIFY.md) changes no code."""
    from .util import run
    vc = (r or {}).get("commit")
    head = run(["git", "rev-parse", "HEAD"], cwd=root)["out"].strip() if vc else ""
    if not vc or not head or vc == head:
        return ""
    d = run(["git", "diff", "--name-only", vc, "HEAD", "--", ".", ":(exclude).deckhand"], cwd=root)
    if d["code"] != 0:
        return f"verify proved {vc[:7]}, which this repository no longer has"
    files = d["out"].split()
    return f"{len(files)} file(s) changed since the verify of {vc[:7]} ({', '.join(files[:4])})" if files else ""


def review(root: Path, s: dict) -> dict:
    r = read_json(root / ".deckhand" / "verify.json", None, expect=dict)
    if not r:
        return _res(False, ["no verify report"], "dh verify")
    stale = verify_stale(root, r)
    if stale:
        return _res(False, [stale], "dh verify (again: the code changed since)")
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
