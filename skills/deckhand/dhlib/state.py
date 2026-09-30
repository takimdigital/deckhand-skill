"""The run state machine: one file (.deckhand/run.json) says where a build is and what comes next.

Phases run in order. A phase is DONE only when its check (a script, never an opinion) passes.
In `phased` mode a gate after a phase blocks the next one until the owner says go
(`dh gate pass G1`); in `auto` mode gates pass themselves and are logged.
`dh next` prints ONE instruction + the ONE reference to load + the lessons for that phase:
the agent never needs to re-read the whole skill to know what to do.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .util import DhError, now, read_json, write_json, append_jsonl, ensure_gitignore, locked, SKILL

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
    if state_path(root).exists() and not _shaped(s):   # unreadable is not "no run": gates would stop being enforced
        raise DhError("RUN_CORRUPT", f"{state_path(root)} is not a valid run (bad JSON, a merge conflict or a half edit?) — "
                      "restore it (`git checkout .deckhand/run.json`, or rebuild from .deckhand/history.jsonl), "
                      "or `dh init --name …` starts a fresh run and keeps the broken file as run.json.corrupt-<time>")
    if s is None and required:
        raise DhError("NO_RUN", f"no .deckhand/run.json in {root} — start with `dh init`")
    return s


def _shaped(s) -> bool:
    """A run is an object with `phases` and `gates` objects (missing ids are filled in: an older or hand-trimmed file still works)."""
    if not isinstance(s, dict) or not isinstance(s.get("phases"), dict) or not isinstance(s.get("gates"), dict):
        return False
    for k in ("phases", "gates"):
        if not all(isinstance(v, dict) for v in s[k].values()):
            return False
    for p in PHASE_IDS:
        s["phases"].setdefault(p, {"status": "pending"})
    for g in GATES:
        s["gates"].setdefault(g, {"status": "pending"})
    s.setdefault("name", "?")
    s.setdefault("mode", "phased")
    s.setdefault("path", "pool")
    return True


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
    try:
        existing = load(root, required=False)
    except DhError as e:
        if e.code != "RUN_CORRUPT":
            raise
        existing = None                                 # init is the repair: a fresh run, the broken file kept beside it
        keep = state_path(root).with_name(f"run.json.corrupt-{time.strftime('%Y%m%dT%H%M%S')}")
        os.replace(state_path(root), keep)             # kept whole beside the new run
    root.mkdir(parents=True, exist_ok=True)
    ensure_gitignore(root)                              # run logs, RESUME, notes, project vault: never in git
    from . import profile as PROFILE, resume as RESUME
    was = (read_json(root / ".deckhand" / "profile.json", {}) or {}).get("scope", "me")
    if for_:
        (root / ".deckhand").mkdir(parents=True, exist_ok=True)
        PROFILE.set_scope(root, for_)
    entry = RESUME.agent_entry(root)                    # AGENTS.md block (+ CLAUDE.md import): any AI resumes cold
    if existing:                                        # never silent: what was kept, what the call changed
        asked = {"name": name, "mode": mode, "path": path}
        kept = {k: existing.get(k) for k, v in asked.items() if existing.get(k) != v}
        out = {"created": False, **summary(root, existing), "agents": entry["written"]}
        if kept:
            out["kept"] = kept
            out["note"] = (f"this folder already has a run: its {', '.join(f'{k}={v}' for k, v in kept.items())} stay "
                           "(a new run = a new folder)")
        if for_ and for_ != was:
            out["scope_changed"] = {"from": was, "to": for_}
        return out
    s = {"version": 2, "name": name, "mode": mode, "path": path, "created": now(),
         "phases": {p["id"]: {"status": "pending"} for p in PHASES},
         "gates": {g: {"status": "pending"} for g in GATES}}
    with locked(root):
        if load(root, required=False):                  # a parallel init won the race: keep its run
            return {"created": False, **summary(root, load(root)), "agents": entry["written"]}
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
        raise DhError("GATE_BLOCKED", f"gate {g} ({GATES[g]}) needs the owner's go: `dh gate pass {g} --quote \"<their words, verbatim>\"`", gate=g)


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
    if force_reason is not None and not str(force_reason).strip():
        raise DhError("NEED_REASON", "--force records a phase done despite a red check: say why with --reason \"…\" (it is shown to the owner)")
    if force_reason and phase in NOT_SKIPPABLE:
        raise DhError("NOT_FORCEABLE", f"phase {phase} cannot be forced: {NOT_SKIPPABLE[phase]}")
    idx = PHASE_IDS.index(phase)
    reached(s, phase)
    result = checks.run(phase, Path(root), s)
    if not result["ok"] and not force_reason:
        return {"ok": False, "phase": phase, "check": result}
    with locked(root):                                  # the check ran unlocked (it can build); the write re-reads the newest run
        s = load(root)
        s["phases"][phase] = {"status": "done", "at": now(), "check": result, **({"forced": force_reason} if not result["ok"] else {}),
                              **({"evidence": evidence} if evidence else {})}
        p = PHASES[idx]
        if p.get("gate") and s["mode"] == "auto":
            s["gates"][p["gate"]] = {"status": "passed", "at": now(), "by": "auto"}
        save(root, s)
        log(root, {"event": "phase_done", "phase": phase, "ok": result["ok"], "forced": force_reason})
    summ = summary(root, s)                             # "phase" = the one just done; "now" = where the run stands
    return {"ok": True, **summ, "phase": phase, "now": summ["phase"], "check": result}


NOT_SKIPPABLE = {"review": "nothing reaches production without `dh verify` green (fix the red rows instead)"}


def phase_skip(root: Path, phase: str, reason: str) -> dict:
    s = load(root)
    if not reason:
        raise DhError("NEED_REASON", "a skipped phase needs --reason (it is shown to the owner)")
    if phase not in PHASE_IDS:
        raise DhError("BAD_PHASE", f"phase must be one of {PHASE_IDS}")
    if phase in NOT_SKIPPABLE:
        raise DhError("NOT_SKIPPABLE", f"phase {phase} cannot be skipped: {NOT_SKIPPABLE[phase]}")
    if s["phases"][phase]["status"] == "done":
        raise DhError("ALREADY_DONE", f"phase {phase} is already done (its gate and evidence stay): to redo it use `dh reopen {phase} --reason \"…\"`", phase=phase)
    reached(s, phase)                                   # only the phase the run is at: no skipping ahead
    with locked(root):
        s = load(root)
        s["phases"][phase] = {"status": "skipped", "at": now(), "reason": reason}
        p = PHASES[PHASE_IDS.index(phase)]
        if p.get("gate") and s["mode"] == "auto":       # phased: the owner still gives the go (G3 = the brand, try-on or not)
            s["gates"][p["gate"]] = {"status": "passed", "at": now(), "by": "skip"}
        save(root, s)
        log(root, {"event": "phase_skip", "phase": phase, "reason": reason})
    return summary(root, s)


# the owner's own words decide a gate: a go passes it, a change request re-opens the work instead.
# A quote passes only when, after the polite filler is removed, NOTHING but approval phrases is left: a request after
# "ok" ("ok, make the hero bigger") is a change request, and anything the classifier does not recognise is one too.
_APPROVALS = (
    r"go ahead|go live|go|let'?s go|lets go|ok(?:ay)?|oki|okey|k|kk|yes+|yep|yeah|yup|ya|sure|approved?|approve it|lgtm|ship it|ship|proceed|continue|"
    r"looks? (?:good|great|right|fine|perfect|nice)|sounds? (?:good|great|perfect|fine)|works? for me|good to go|all good|all set|"
    r"fine|good|great|perfect|nice|awesome|excellent|amazing|agreed?|validated?|confirm(?:ed)?|do it|love it|loved it|like it|i like it|well done|great job|"
    r"g[1-4] ok|g[1-4]|"
    r"oui|ouais|d'accord|dac|vas y|allez|allons y|on y va|valid[ée]e?|parfait|c'est bon|bon|bien|tr[èe]s bien|super|nickel|top|g[ée]nial|impeccable|j'adore|[çc]a marche|"
    r"s[ií]|vale|adelante|genehmigt|passt|"
    r"نعم|موافق|تمام|ممتاز|اوكي|أوكي|حسنا|حسناً|ماشي|جميل|رائع|"
    r"naam|na3am|aywa|ayoua|aiwa|iwa|wakha|mwafiq|mouafik|muwafiq|tamam|tmam|yalla|yallah|mashi|machi|mzyan|mzian|zwin|bahi|behi|mumtaz|momtaz|mashallah|sah|sahit|"
    r"👍|✅|👌|🙌|🚀|❤|🔥|💯")
_FILLER = frozenset(("please pls plz thanks thank you thx merci beaucoup shukran choukran for me to the plan design site "
                     "i i'm im we really very so then now just pour moi c'est je mon ma my our "
                     "also too bro sir team everyone guys hey hi hello salut bonjour").split())
_PURE_RX = re.compile(r"(?:%s)(?: (?:%s))*" % (_APPROVALS, _APPROVALS))
APPROVE_RX = re.compile(r"(?i)(^|\b)(%s)(\b|$)" % _APPROVALS)                     # kept for callers: "an approval word is in there"
CHANGE_RX = re.compile(r"(?i)\b(change|make it|instead|but|however|add|remove|replace|rename|move|fix|not (yet|good|ok|right)|no\b|"
                       r"should|must|needs? to|wrong|redo|rather|prefer|modif|chang|ajout|enl[eè]v|pas encore|plut[oô]t|mais)\b")


# a go the owner holds back is no go: "don't ship it", "wait, do not proceed", "this is not good"
HOLD_RX = re.compile(r"(?i)(\b(don'?t|do not|does not|doesn'?t|not|never|no|nope|wait|hold|stop|non|pas|attends?|arr[êe]te)\b|n't\b)")
# …and a go put off is no go yet: "ok, I'll look later", "fine, let me think about it", "yes got it, checking tonight"
DELAY_RX = re.compile(r"(?i)\b(later|tonight|tomorrow|this (evening|weekend)|next week|(let me|i'?ll|i will|need to) (think|check|look|see|review|read)|"
                      r"think(ing)? (about|it over)|checking|get back to you|haven'?t (looked|read|seen|checked)|(will|to) (look|check)|"
                      r"plus tard|ce soir|demain|je (vais )?regarde|je v[ée]rifie|m[áa]s tarde|ma[ñn]ana|luego|sp[äa]ter|morgen)\b")
# …except the negations that are themselves a go: "no changes", "no problem", "pas de souci"
NO_PROBLEM_RX = re.compile(r"(?i)\b(no (problem|worries|changes?|issues?|notes?)|nothing (to (change|add)|else)|pas de (souci|probl[eè]me|changement))\b")
# a go explicit enough to carry a named change ("G1 ok, but add a pricing page"); a bare "ok but add…" is a change
STRONG_RX = re.compile(r"(?i)(\b(g[1-4] ok|approved?|approve it|go ahead|ship it|lgtm|validated?|go live|let'?s go|genehmigt)\b|valid[ée])")
_BUT_RX = re.compile(r"(?i)\b(but|mais|except|sauf|however|although)\b")


def _tokens(q: str) -> str:
    q = (q or "").lower().replace("’", "'").replace("\ufe0f", "")
    q = re.sub(r"[👍✅👌🙌🚀❤🔥💯]", lambda m: f" {m.group(0)} ", q)
    q = re.sub(r"[-_/]", " ", q)
    q = re.sub(r"[^\w' 👍✅👌🙌🚀❤🔥💯]", " ", q)
    return " ".join(w for w in q.split() if w not in _FILLER)


def _pure_approval(q: str) -> bool:
    t = _tokens(q)
    return bool(t) and bool(_PURE_RX.fullmatch(t))


def classify_quote(quote: str) -> str:
    """approve | approve_with_changes | change_request — deterministic, from the owner's own words. Only a bare approval
    is a go; a request after the approval word is a change request; when in doubt it is one (a gate asks again rather
    than passing on a "no" or a "make it bigger")."""
    q = NO_PROBLEM_RX.sub(" ", (quote or "").strip())
    if not q.strip() or HOLD_RX.search(q) or DELAY_RX.search(q):
        return "change_request"
    if _pure_approval(q):
        return "approve"
    m = _BUT_RX.search(q)
    if m and q[m.end():].strip(" .,;:!?") and _pure_approval(q[:m.start()]) and STRONG_RX.search(q[:m.start()]):
        return "approve_with_changes"
    return "change_request"


def is_hold(quote: str) -> bool:
    """The owner holds it back ("wait", "don't ship it yet", "hold on, give me a day") without asking for a change:
    the answer is to wait, never to reopen and redo a phase they did not question (SKILL invariant 7)."""
    q = NO_PROBLEM_RX.sub(" ", (quote or "").strip())
    return bool(HOLD_RX.search(q) or DELAY_RX.search(q)) and not CHANGE_RX.search(re.sub(r"(?i)\b(not|pas) (yet|encore)\b", " ", q))


PLAN_FILES = ("brief.json", "sitemap.json")


def _plan_hashes(root: Path) -> dict:
    import hashlib
    out = {}
    for f in PLAN_FILES:
        p = Path(root) / ".deckhand" / f
        if p.exists():
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def plan_drift(root: Path, s: dict) -> list:
    """Plan files that changed after G1 passed. The gate records their content hashes, so a touched file or a fresh clone
    (new mtimes) is no drift; a gate without hashes (older runs, hand-set) falls back to mtimes."""
    g1 = (s.get("gates") or {}).get("G1", {})
    if g1.get("status") != "passed":
        return []
    root = Path(root)
    now_h = _plan_hashes(root)
    if isinstance(g1.get("plan_hashes"), dict):
        was = g1["plan_hashes"]
        return [f for f in PLAN_FILES if was.get(f) != now_h.get(f)]
    import datetime as _dt
    try:
        t = _dt.datetime.strptime(str(g1.get("at"))[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:
        return []
    return [f for f in PLAN_FILES if (root / ".deckhand" / f).exists() and _changed_since(root, f, t)]


def _changed_since(root: Path, name: str, t: float) -> bool:
    """No recorded hash: a file the repository holds unmodified changed when its last commit was made (a clone gives every
    file a new mtime, which is no edit); an edited or untracked file falls back to its mtime."""
    rel = f".deckhand/{name}"
    from .util import run
    if (root / ".git").exists():
        dirty = run(["git", "status", "--porcelain", "--", rel], cwd=root)
        log = run(["git", "log", "-1", "--format=%ct", "--", rel], cwd=root)
        if dirty["code"] == 0 and log["code"] == 0 and not dirty["out"].strip() and log["out"].strip().isdigit():
            return int(log["out"].strip()) > t + 1
    return (root / ".deckhand" / name).stat().st_mtime > t + 1


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
    if verdict == "change_request" and is_hold(quote):
        raise DhError("HOLD", f"the owner is holding it back, not asking for a change: {quote!r}",
                      gate=gate, do=["wait: change nothing, reopen nothing", "ask what they need before they give the go",
                                     f"a change asked? `dh reopen {due} --reason \"[their words]\"`; the go given? quote it"])
    if verdict == "change_request":
        phase = due
        raise DhError("CHANGE_REQUEST", f"the owner's words read as a change request, not a go: {quote!r}",
                      gate=gate, do=[f"dh reopen {phase} --reason \"{(quote or '')[:80]}\"", "make the change, show it again, ask for the go",
                                     "the owner did say go? quote the words that say it (\"ok go\", \"approved\", \"G1 ok\")"])
    with locked(root):
        s = load(root)
        s["gates"][gate] = {"status": "passed", "at": now(), "by": "owner", "note": note, **({"plan_hashes": _plan_hashes(root)} if gate == "G1" else {}),
                            **({"quote": quote, "verdict": verdict} if quote is not None else {})}
        save(root, s)
        log(root, {"event": "gate", "gate": gate, "note": note, **({"quote": quote, "verdict": verdict} if quote is not None else {})})
    out = summary(root, s)
    if verdict == "approve_with_changes":
        out["changes_asked"] = f"the go came with a change: record it now — dh note decision \"{quote[:100]}\" — and do it in the next phase"
    return out


def reopen(root: Path, phase: str, reason: str) -> dict:
    """Owner wants changes: reopen a phase (and everything after it)."""
    idx = PHASE_IDS.index(phase)
    with locked(root):
        s = load(root)
        if idx > PHASE_IDS.index(current(s)["id"]):
            raise DhError("NOT_REACHED", f"phase {phase} was never reached (the run is at '{current(s)['id']}'): nothing to reopen", phase=phase, at=current(s)["id"])
        for pid in PHASE_IDS[idx:]:
            s["phases"][pid] = {"status": "pending", "reopened": reason}
        for p in PHASES[idx:]:
            if p.get("gate"):
                s["gates"][p["gate"]] = {"status": "pending"}
        save(root, s)
        log(root, {"event": "reopen", "phase": phase, "reason": reason})
    return summary(root, s)
