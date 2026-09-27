"""The run state machine: one file (.deckhand/run.json) says where a build is and what comes next.

Phases run in order. A phase is DONE only when its check (a script, never an opinion) passes.
In `phased` mode a gate after a phase blocks the next one until the owner says go
(`dh gate pass G1`); in `auto` mode gates pass themselves and are logged.
`dh next` prints ONE instruction + the ONE reference to load + the lessons for that phase:
the agent never needs to re-read the whole skill to know what to do.
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import DhError, now, read_json, write_json, append_jsonl, ensure_gitignore, SKILL

PHASES = [
    {"id": "define", "title": "Define the business and the path", "ref": "references/00-define.md"},
    {"id": "research", "title": "Research: market, top competitors, audience, conversion", "ref": "references/10-research.md"},
    {"id": "plan", "title": "Plan: page map + feature wiring (no dead ends)", "ref": "references/20-plan.md", "gate": "G1"},
    {"id": "build", "title": "Build: clone / adopt / scaffold, run it locally", "ref": "references/30-build.md", "gate": "G2"},
    {"id": "brand", "title": "Rebrand to the plan", "ref": "references/40-brand.md"},
    {"id": "tryon", "title": "Try-on: swap sections for licensed variants", "ref": "references/50-tryon.md", "gate": "G3", "optional": True},
    {"id": "review", "title": "Review: build, routes, security, honesty", "ref": "references/60-review.md", "gate": "G4"},
    {"id": "deploy", "title": "Deploy + handoff", "ref": "references/70-deploy.md"},
    {"id": "operate", "title": "Operate: changes, bots, monitoring", "ref": "references/80-operate.md", "continuous": True},
]
PHASE_IDS = [p["id"] for p in PHASES]
GATES = {"G1": "the plan (page map + features) is approved",
         "G2": "the owner opened the local app and says go",
         "G3": "the design (brand + try-on) is approved",
         "G4": "go live: deploy to the server"}
MODES = ("phased", "auto")
PATHS = ("pool", "mine", "existing", "scratch")


def state_path(root: Path) -> Path:
    return Path(root) / ".deckhand" / "run.json"


def load(root: Path, required: bool = True) -> dict:
    s = read_json(state_path(root))
    if s is None and required:
        raise DhError("NO_RUN", f"no .deckhand/run.json in {root} — start with `dh init`")
    return s


def save(root: Path, s: dict) -> None:
    s["updated"] = now()
    write_json(state_path(root), s)


def log(root: Path, event: dict) -> None:
    append_jsonl(Path(root) / ".deckhand" / "history.jsonl", {"at": now(), **event})


def init(root: Path, name: str, mode: str = "phased", path: str = "pool", for_: str | None = None) -> dict:
    """Idempotent: an existing run is kept (its gitignore block, scope and cold-start entry are brought up to date)."""
    if mode not in MODES:
        raise DhError("BAD_MODE", f"mode must be one of {MODES}")
    if path not in PATHS:
        raise DhError("BAD_PATH", f"path must be one of {PATHS}")
    root = Path(root)
    existing = load(root, required=False)
    root.mkdir(parents=True, exist_ok=True)
    ensure_gitignore(root)                              # run logs, RESUME, notes, project vault: never in git
    from . import profile as PROFILE, resume as RESUME
    if for_:
        (root / ".deckhand").mkdir(parents=True, exist_ok=True)
        PROFILE.set_scope(root, for_)
    entry = RESUME.agent_entry(root)                    # AGENTS.md block (+ CLAUDE.md import): any AI resumes cold
    if existing:
        return {"created": False, **summary(root, existing), "agents": entry["written"]}
    s = {"version": 2, "name": name, "mode": mode, "path": path, "created": now(),
         "phases": {p["id"]: {"status": "pending"} for p in PHASES},
         "gates": {g: {"status": "pending"} for g in GATES}}
    save(root, s)
    pending = root / "PENDING.md"
    if not pending.exists():
        pending.write_text((SKILL / "templates" / "PENDING.md").read_text(encoding="utf-8").replace("{{NAME}}", name), encoding="utf-8")
    log(root, {"event": "init", "mode": mode, "path": path, **({"for": for_} if for_ else {})})
    return {"created": True, **summary(root, s), "agents": entry["written"]}


def current(s: dict):
    """First phase that is neither done nor skipped (operate is the steady state)."""
    for p in PHASES:
        st = s["phases"][p["id"]]["status"]
        if st not in ("done", "skipped"):
            return p
    return PHASES[-1]


def blocking_gate(s: dict):
    """A gate owed by a finished phase that still blocks progress (phased mode only)."""
    if s.get("mode") != "phased":
        return None
    for p in PHASES:
        g = p.get("gate")
        if g and s["phases"][p["id"]]["status"] in ("done", "skipped") and s["gates"][g]["status"] != "passed":
            return g
    return None


def summary(root: Path, s: dict) -> dict:
    cur = current(s)
    return {"project": str(root), "name": s["name"], "mode": s["mode"], "path": s["path"], "phase": cur["id"],
            "done": [k for k, v in s["phases"].items() if v["status"] == "done"],
            "gate": blocking_gate(s)}


def gate_phase(gate: str) -> str:
    return next(p["id"] for p in PHASES if p.get("gate") == gate)


def reached(s: dict, phase: str) -> None:
    """Refuse the work of `phase` before the run gets there: every earlier phase done or skipped, no owner's go owed
    before it. `phase done|skip`, clone/scaffold, `rebrand apply` and `deploy ship` all go through here."""
    idx = PHASE_IDS.index(phase)
    for prev in PHASE_IDS[:idx]:
        if s["phases"][prev]["status"] not in ("done", "skipped") and prev != "operate":
            raise DhError("OUT_OF_ORDER", f"phase '{prev}' is not done yet (`dh next` says what is)", phase=phase, first=prev)
    g = blocking_gate(s)
    if g and PHASE_IDS.index(gate_phase(g)) < idx:
        raise DhError("GATE_BLOCKED", f"gate {g} ({GATES[g]}) needs the owner's go: `dh gate pass {g}`", gate=g)


def require(root: Path, phase: str) -> None:
    """`reached` for a command that belongs to a phase; no run (a bare folder) = nothing to enforce."""
    s = load(root, required=False)
    if s and not s.get("moved_to"):
        reached(s, phase)


def phase_done(root: Path, phase: str, evidence: dict | None = None, force_reason: str | None = None) -> dict:
    """Mark a phase done — only after its check passes (checks live in dhlib.checks)."""
    from . import checks
    s = load(root)
    if s.get("moved_to"):
        raise DhError("MOVED", f"this project continues in {s['moved_to']} (its app folder): run `dh next` there", to=s["moved_to"])
    if phase not in PHASE_IDS:
        raise DhError("BAD_PHASE", f"phase must be one of {PHASE_IDS}")
    idx = PHASE_IDS.index(phase)
    reached(s, phase)
    result = checks.run(phase, Path(root), s)
    if not result["ok"] and not force_reason:
        return {"ok": False, "phase": phase, "check": result}
    s["phases"][phase] = {"status": "done", "at": now(), "check": result, **({"forced": force_reason} if not result["ok"] else {}),
                          **({"evidence": evidence} if evidence else {})}
    p = PHASES[idx]
    if p.get("gate") and s["mode"] == "auto":
        s["gates"][p["gate"]] = {"status": "passed", "at": now(), "by": "auto"}
    save(root, s)
    log(root, {"event": "phase_done", "phase": phase, "ok": result["ok"], "forced": force_reason})
    return {"ok": True, "phase": phase, "check": result, **summary(root, s)}


NOT_SKIPPABLE = {"review": "nothing reaches production without `dh verify` green (fix the red rows instead)"}


def phase_skip(root: Path, phase: str, reason: str) -> dict:
    s = load(root)
    if not reason:
        raise DhError("NEED_REASON", "a skipped phase needs --reason (it is shown to the owner)")
    if phase not in PHASE_IDS:
        raise DhError("BAD_PHASE", f"phase must be one of {PHASE_IDS}")
    if phase in NOT_SKIPPABLE:
        raise DhError("NOT_SKIPPABLE", f"phase {phase} cannot be skipped: {NOT_SKIPPABLE[phase]}")
    reached(s, phase)                                   # only the phase the run is at: no skipping ahead
    s["phases"][phase] = {"status": "skipped", "at": now(), "reason": reason}
    p = PHASES[PHASE_IDS.index(phase)]
    if p.get("gate") and s["mode"] == "auto":           # phased: the owner still gives the go (G3 = the brand, try-on or not)
        s["gates"][p["gate"]] = {"status": "passed", "at": now(), "by": "skip"}
    save(root, s)
    log(root, {"event": "phase_skip", "phase": phase, "reason": reason})
    return summary(root, s)


# the owner's own words decide a gate: a go passes it, a change request re-opens the work instead
APPROVE_RX = re.compile(r"(?i)(^|\b)(go|go ahead|ok|okay|oki|yes|yep|yeah|yup|approved?|approve it|looks (good|great|right|fine)|lgtm|ship( it)?|proceed|continue|"
                        r"fine|good|great|perfect|agreed|validated?|confirm(ed)?|do it|let'?s go|g[1-4] ok|go live|"
                        r"oui|d'accord|vas-?y|valid[ée]|parfait|c'est bon|نعم|موافق|s[ií]|vale|adelante|genehmigt|passt)(\b|$)|👍|✅")
CHANGE_RX = re.compile(r"(?i)\b(change|make it|instead|but|however|add|remove|replace|rename|move|fix|not (yet|good|ok|right)|no\b|"
                       r"should|must|needs? to|wrong|redo|rather|prefer|modif|chang|ajout|enl[eè]v|pas encore|plut[oô]t|mais)\b")


# a go the owner holds back is no go: "don't ship it", "wait, do not proceed", "this is not good"
HOLD_RX = re.compile(r"(?i)(\b(don'?t|do not|does not|doesn'?t|not|never|no|nope|wait|hold|stop|non|pas|attends?|arr[êe]te)\b|n't\b)")
# …except the negations that are themselves a go: "no changes", "no problem", "pas de souci"
NO_PROBLEM_RX = re.compile(r"(?i)\b(no (problem|worries|changes?|issues?|notes?)|nothing (to (change|add)|else)|pas de (souci|probl[eè]me|changement))\b")
# a go explicit enough to carry a change with it ("G1 ok, but add a pricing page"); a bare "ok but add…" is a change
STRONG_RX = re.compile(r"(?i)(\b(g[1-4] ok|approved?|approve it|go ahead|ship it|lgtm|validated?|go live|let'?s go|genehmigt)\b|valid[ée])")


def classify_quote(quote: str) -> str:
    """approve | approve_with_changes | change_request — deterministic, from the owner's own words. When in doubt it
    is a change request: a gate asks again rather than passing on a "no"."""
    q = NO_PROBLEM_RX.sub(" ", (quote or "").strip())
    ok, change = bool(APPROVE_RX.search(q)), bool(CHANGE_RX.search(q))
    if not ok or HOLD_RX.search(q):
        return "change_request"
    if not change:
        return "approve"
    return "approve_with_changes" if STRONG_RX.search(q) else "change_request"


def gate_pass(root: Path, gate: str, note: str = "", quote: str | None = None) -> dict:
    """`quote` = the owner's message, verbatim. A change request does not pass the gate (D2: an agent once passed
    G1 on its own paraphrase of "make it like a real business")."""
    s = load(root)
    if gate not in GATES:
        raise DhError("BAD_GATE", f"gate must be one of {list(GATES)}")
    due = gate_phase(gate)
    if s["phases"][due]["status"] not in ("done", "skipped"):
        raise DhError("GATE_NOT_DUE", f"gate {gate} follows phase {due}, which is not done yet: finish it and show the owner first",
                      gate=gate, phase=due, do=[f"dh phase done {due}"])
    verdict = classify_quote(quote) if quote is not None else None
    if verdict == "change_request":
        phase = due
        raise DhError("CHANGE_REQUEST", f"the owner's words read as a change request, not a go: {quote!r}",
                      gate=gate, do=[f"dh reopen {phase} --reason \"{(quote or '')[:80]}\"", "make the change, show it again, ask for the go",
                                     "the owner did say go? quote the words that say it (\"ok go\", \"approved\", \"G1 ok\")"])
    s["gates"][gate] = {"status": "passed", "at": now(), "by": "owner", "note": note,
                        **({"quote": quote, "verdict": verdict} if quote is not None else {})}
    save(root, s)
    log(root, {"event": "gate", "gate": gate, "note": note, **({"quote": quote, "verdict": verdict} if quote is not None else {})})
    out = summary(root, s)
    if verdict == "approve_with_changes":
        out["changes_asked"] = f"the go came with a change: record it now — dh note decision \"{quote[:100]}\" — and do it in the next phase"
    return out


def reopen(root: Path, phase: str, reason: str) -> dict:
    """Owner wants changes: reopen a phase (and everything after it)."""
    s = load(root)
    idx = PHASE_IDS.index(phase)
    for pid in PHASE_IDS[idx:]:
        s["phases"][pid] = {"status": "pending", "reopened": reason}
    for p in PHASES[idx:]:
        if p.get("gate"):
            s["gates"][p["gate"]] = {"status": "pending"}
    save(root, s)
    log(root, {"event": "reopen", "phase": phase, "reason": reason})
    return summary(root, s)
