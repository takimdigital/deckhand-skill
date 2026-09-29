"""`dh next` — ONE instruction for the current state: what to run, which single reference to load,
the lessons that apply, and what makes the phase done. The agent never re-reads the whole skill."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .util import SKILL, read_json
from . import state as STATE
from . import learn as LEARN

DH = f'{"py" if os.name == "nt" else "python3"} "{SKILL / "dh.py"}"'
TRYON = f'node "{SKILL / "tryon" / "cli.mjs"}"'

STEPS = {
    "define": ["{dh} profile doctor            # what access exists (never ask for what a token already covers)",
               "{dh} workflow query            # the 3 proven paths that fit: show them, the owner picks one (dh workflow use REF) or none",
               "{dh} brief set business=\"…\" shape=saas|booking|catalogue|marketplace|leadgen|internal languages=en,… audience=\"…\" brand.name=\"…\"",
               "ask ONLY what the brief + profile cannot answer — one batched message, defaults proposed",
               "{dh} phase done define"],
    "research": ["{dh} research brief --focus competitors --agent A1   # one brief per focus (competitors, pricing, audience, conversion, discovery, local-rules, vocabulary); read the card it names",
                 "search per the card; every page opened: {dh} research add URL --by A1 --kind K --note \"…\" ({dh} research seen URL first — never reread)",
                 "claims (label + url + verbatim quote) and vocabulary (harvested terms) → .deckhand/research/agents/A1.json; summary fields → .deckhand/research.json (template: {skill}/templates/research.json)",
                 "{dh} research verify                # merges the agents' files, fetches every cited page, checks each quote",
                 "{dh} phase done research            # or: {dh} phase skip research --reason \"owner declined\""],
    "plan": ["path=pool|mine: {dh} pool query     # top 3 bases for this brief (reasons + gaps)",
             "write .deckhand/sitemap.json: every page, section, action and its target, every form's success+error (template in .deckhand/ after `{dh} plan init`)",
             "path=scratch: write .deckhand/copy.json now — the words compose places at build, per section slot (schema: references/20-plan.md § Copy); owner facts only, the rest → PENDING.md",
             "{dh} plan lint                      # until 0 errors — no dead ends, no orphan pages, no un-owned API",
             "{dh} plan render && {dh} plan split --agents N   # PLAN.md for the owner; N = the sub-agents you will really run (AGENT-n.md + CONVENTIONS.md)",
             "{dh} phase done plan  → show .deckhand/PLAN.md + the chosen base; wait for the owner's go (G1)"],
    "build": ["path=pool|mine: {dh} clone <template> --to <dir>   (the planning folder itself is fine: Deckhand's files step aside and come back)",
              "path=existing: {dh} adopt <folder|git-url>",
              "path=scratch: {dh} scaffold --to <dir> && {dh} compose --sections hero,features,pricing,faq,cta,footer --copy .deckhand/copy.json",
              "built another way (by hand, another generator)? {dh} base record --kind scratch|existing --note \"how\"   (never a private function)",
              "the app needs a database/queue running? {dh} dev add db --cmd \"…\" --port N [--env-file .env]   # once; dev start/stop/status then handle it",
              "build the shell (WP-00: layout, nav, shared UI, schema, seed) yourself; then one sub-agent per .deckhand/work/AGENT-n.md (references/team.md)",
              "{dh} dev start                      # services first, then the app; prints the local URL for the owner",
              "{dh} phase done build  → give the owner the URL, logins, what you tested; wait for their go (G2)"],
    "brand": ["{dh} rebrand scan && {dh} rebrand apply     # brand from the brief: name, tagline, primary colour, icon",
              "{dh} rebrand check                  # template names, demo copy, fake logos, placeholders",
              "{dh} phase done brand"],
    "tryon": ["{tryon} setup --project . && restart the dev server",
              "{tryon} serve --project .           # the owner opens that URL, clicks Try-on, compares, keeps",
              "no browser? {tryon} try --file <f> --line <n> --col <c> --slot hero   then show / keep / discard",
              "AI draft asked (overlay, serve's draft_request line, or the owner says so): {tryon} drafts → write the brief's component into write_to → run its `then` (gated; labelled AI-generated)",
              "{dh} phase done tryon  (or skip it) → wait for the owner's go on the design (G3)"],
    "review": ["{tryon} clean --project .          # unwire try-on (kept sections stay)",
               "{dh} seo audit                     # SEO readiness; its owner items land in PENDING.md",
               "{dh} verify                         # builds, serves the build, checks every row; red rows are fixed, not argued with",
               "{dh} phase done review  → owner says go live (G4)"],
    "deploy": ["first time: references/ops/00-user-checklist.md → 10/11 (server) → 20/21 (domain) → 30 (app); then {dh} deploy target --app <uuid> --url https://…",
               "domain set? {dh} brief set domain=<domain> && {dh} seo apply   # canonicals, sitemap and structured data on the real domain",
               "{dh} deploy ship                    # push → deploy → wait for YOUR commit → smoke → IndexNow ping",
               "then: {dh} seo audit --url https://<domain>   # live: HTTPS, one host, indexing; owner: Search Console + Bing + Business Profile (PENDING.md)",
               "{dh} handoff                        # HANDOFF.md: access locations, commands, pending",
               "{dh} phase done deploy"],
    "operate": ["change requests: edit → {dh} verify → commit → {dh} deploy ship (references/80-operate.md)",
                "{dh} ops suggest → {dh} ops add <bot> --runner github|cron   (verify each schedule by its own trigger)",
                "monthly: {dh} seo audit --url https://<domain>   · new page or content → words in copy.json seo.pages → {dh} seo apply → ship",
                "a failure fixed? {dh} learn from-failure --fix \"…\" --cause \"…\"    ·   liked the result? {dh} harvest --name <base>"],
}


def _playbook(phase: str) -> list:
    """The steps that finished this phase in at least two past sessions (from `dh autopsy --apply`)."""
    from .util import home, read_jsonl
    rows = [r for r in read_jsonl(home() / "playbooks.jsonl") if r.get("phase") == phase and r.get("seen", 1) >= 2]
    if not rows:
        return []
    best = max(rows, key=lambda r: (r.get("seen", 1), r.get("last_seen", "")))
    return best["steps"][:10]


def _seo_steps(path: str) -> list:
    """Found on Google: included by default for new and owner-folder sites; detected + strongly recommended for bases."""
    from . import seo as SEO
    policy = SEO.POLICY["policy_by_path"].get(path, "apply")
    words = "write per-page titles (≤60) + descriptions (70–160) into .deckhand/copy.json → seo.pages — service + city first, facts only (references/45-seo.md)"
    if policy == "apply":
        return [words, f"{DH} seo apply                    # SEO by default: robots, sitemap, metadata, canonicals, Open Graph, JSON-LD, 404, llms.txt, IndexNow",
                f"{DH} seo audit                    # what is still missing; owner facts/actions go to PENDING.md"]
    return [f"{DH} seo audit                    # detect what this base lacks (owner items go to PENDING.md)",
            "DECISION NEEDED — show .deckhand/SEO.md and recommend `dh seo apply` (strongly, before launch): it adds or improves, never overwrites",
            words + " — then " + f"{DH} seo apply on the owner's yes"]


def _pending(root: Path) -> dict:
    from . import pending as PEND
    return PEND.summary(root)


HARNESS_KEYS = {"build": ("background", "delegate", "limits", "browser"), "research": ("delegate", "limits"), "plan": ("delegate",),
                "review": ("background", "browser"), "tryon": ("background",), "define": ("todo",)}


def harness_notes(phase: str) -> dict | None:
    """D12: one generic harness line was wrong for Hermes. The detected harness's own syntax, only what this phase needs."""
    from . import workflow as WF
    name = WF.harness()
    data = read_json(SKILL / "data" / "harness.json", {}) or {}
    row = data.get(name) or data.get("unknown") or {}
    keys = HARNESS_KEYS.get(phase, ())
    notes = {k: row[k] for k in keys if row.get(k)}
    return {"name": name, **notes} if notes else None


def _suggest(root: Path, do=()) -> dict:
    """After PENDING: what the owner could do next, by importance — computed, optional (dhlib/suggest.py)."""
    from . import suggest as SUG
    try:
        cmds = [re.sub(r"^[A-Z]+\d*(-\d+)? (do|check|gate): ", "", x.split("  →")[0]).split("  #")[0].strip() for x in do]
        return SUG.compute(root, exclude_cmds=cmds)
    except Exception:  # noqa: BLE001 — guidance never breaks on a suggestion
        return {"items": [], "more": 0}


def _workflow(root: Path) -> dict | None:
    from . import workflow as WF
    try:
        return WF.progress(root)
    except Exception:  # noqa: BLE001 — guidance never breaks on a workflow problem
        return None


def _fresh_session(root: Path) -> str | None:
    """Right after the owner passed a gate the chat holds nothing the files do not: the best moment to start fresh."""
    from .util import read_jsonl
    hist = read_jsonl(root / ".deckhand" / "history.jsonl")
    if not hist or hist[-1].get("event") != "gate":
        return None
    from . import resume as RESUME
    ok, _ = RESUME.safe(RESUME.safety_facts(root))
    return ("a gate just passed and nothing lives only in this chat: a fresh session is safe and sharper here — "
            "it starts with `dh resume` (tell the owner; never required)") if ok else None


PATH_RX = re.compile(r"^path=([a-z|]+): ")
WAIT_RX = re.compile(r"\s*→ (show|give|wait|owner says).*$")


def _fit(steps: list, mode: str, path: str) -> list:
    """Only the lines for this run: `path=X|Y:` lines of other paths drop out, and in auto mode a gate passes itself,
    so nothing says to wait for the owner (review 2026-09-27: an auto run was told to stop at G1 and G2)."""
    out = []
    for x in steps:
        m = PATH_RX.match(x)
        if m:
            if path not in m.group(1).split("|"):
                continue
            x = x[m.end():]
        if mode == "auto" and "phase done" in x and WAIT_RX.search(x):
            x = WAIT_RX.sub("   # auto mode: the gate passes by itself — run `dh next`", x)
        out.append(x)
    return out


ANGLE_RX = re.compile(r"<([^<>\n]{1,40})>")


def next_step(root: Path) -> dict:
    """`dh next`. Placeholders are written `[x]`, never `<x>`: some harnesses refuse a task that carries `<x>` or `{x}`
    (Hermes `delegate_task`), and these lines are pasted into tasks and RESUME as they are (findings 18, 22)."""
    out = _next_step(root)
    if isinstance(out.get("do"), list):
        out["do"] = [ANGLE_RX.sub(r"[\1]", x) for x in out["do"]]
    return out


def _next_step(root: Path) -> dict:
    root = Path(root)
    s = STATE.load(root, required=False)
    if not s:
        return {"state": "no run", "do": [f"{DH} init --name <business> --mode phased|auto --path pool|mine|existing|scratch --project <dir>"],
                "read": str(SKILL / "references" / "00-define.md"), "dh": DH}
    if s.get("moved_to"):
        return {"state": "moved", "to": s["moved_to"], "do": [f"cd {s['moved_to']}", f"{DH} next"],
                "why": "the app was built in another folder; the run (brief, plan, gates, notes) continues there", "dh": DH}
    gate = STATE.blocking_gate(s)
    cur = STATE.current(s)
    if gate:
        out = {"state": "waiting for the owner", "gate": gate, "what": STATE.GATES[gate],
               "do": [f"show the owner what {gate} is about; ask ONE question; on their go: {DH} gate pass {gate} --quote \"<their words, verbatim>\"",
                      f"their words ask for changes (\"make it…\", \"add…\", \"but…\"): {DH} reopen <phase> --reason \"<their words>\" — not a go"],
               "dh": DH, "pending": _pending(root)}
        wfp = _workflow(root)
        if wfp:
            out["workflow"] = wfp
        out["suggest"] = _suggest(root, out["do"])
        seo = read_json(root / ".deckhand" / "seo.json", None)
        if gate == "G4" and seo:
            out["seo"] = {"score": seo.get("score"), "launch_breakers": len(seo.get("blockers", [])), "agent_fixable": seo.get("auto_fixable", [])}
            if seo.get("auto_fixable") and seo.get("policy") == "suggest":
                out["do"].insert(0, "DECISION NEEDED — SEO is not applied to this base yet: recommend `dh seo apply` before going live (.deckhand/SEO.md)")
        return out
    steps = _fit([x.format(dh=DH, tryon=TRYON, skill=SKILL) for x in STEPS[cur["id"]]], s["mode"], s["path"])
    if cur["id"] == "brand":
        steps[-1:-1] = _seo_steps(s["path"])
    out = {"phase": cur["id"], "n": f"{STATE.PHASE_IDS.index(cur['id']) + 1}/{len(STATE.PHASES)}", "title": cur["title"],
           "mode": s["mode"], "path": s["path"], "read": str(SKILL / cur["ref"]), "do": steps,
           "lessons": LEARN.preflight(root, cur["id"]), "dh": DH, "pending": _pending(root)}
    wfp = _workflow(root)
    if wfp and wfp.get("remaining_here") is not None:
        out["do"] = wfp["remaining_here"] or [f"{DH} phase done {cur['id']}   # every step of this phase in the workflow is done"]
        out["workflow"] = {k: wfp[k] for k in ("ref", "line", "next_step", "pitfalls") if wfp.get(k)}
        out["say"] = "follow the workflow's steps in order (each has the command and what it must print); end every report with PENDING and the WORKFLOW line"
    elif wfp:
        out["workflow"] = wfp
    elif cur["id"] in ("research", "plan"):
        out["workflow_hint"] = f"{DH} workflow query   # a proven path for this kind of project: top 3, the owner picks (or none)"
    fresh = _fresh_session(root)
    if fresh:
        out["fresh_session"] = fresh
    h = harness_notes(cur["id"])
    if h:
        out["harness"] = h
    out["suggest"] = _suggest(root, out["do"])
    books = _playbook(cur["id"])
    if books:
        out["worked_before"] = books
    if cur["id"] == "plan":
        brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
        if s["path"] in ("pool", "mine") and brief:
            from . import pool as POOL
            q = POOL.query({**brief, "lane": brief.get("lane", "web")})
            out["pool_top"] = [{"name": t["name"], "score": t["score"], "reasons": t["reasons"][:4]} for t in q["top"]]
            if q["gap"]:
                out["pool_gap"] = "nothing in the pool fits — offer path=scratch (scaffold + compose) or measure more repos (dh pool add owner/repo)"
    return out
