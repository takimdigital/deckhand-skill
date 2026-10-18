"""WORKFLOW AUTOPSY: any moment of a run → what happened, what the owner was asked and answered, what could have been
asked up front, where the run left its workflow, what each failure cost — and proposals to improve the workflow,
each with its reason and evidence. Deterministic (same inputs → same bytes), read-only: it writes only its own report
under .deckhand/autopsy/ and never edits the skill. The owner decides where an accepted proposal goes: their own
workflow pool, the community pool (a PR), or nowhere.

Inputs: the project's own files (history, notes, run log, the pinned workflow and its progress) + the session when
one is found (Claude Code transcript, Hermes state.db or export, any chat JSONL). `--part` returns one section as
JSON, so a sub-agent with a fresh context can take one part of a long session.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .util import DhError, read_json, read_jsonl, redact_obj, today, write_json
from . import state as STATE
from . import workflow as WF

PARTS = ("timeline", "questions", "deviations", "errors", "delegation", "guidance", "proposals")
PAUSE_S = 20 * 60
QUESTION_RX = re.compile(r"(DECISION NEEDED|ACTION NEEDED|\?\s*$|\?\s*\n|reply (with )?[\"'“]?\w|(^|\n)\s*(\d+[\).]|[a-e]\))\s+\S.*\n\s*(\d+[\).]|[a-e]\))\s)", re.I | re.M)
GATE_Q_RX = re.compile(r"\b(G[1-4]|go live|say go|your go|approve|looks right|ready to (build|ship|deploy))\b", re.I)
JARGON = ("tsc", "hydration", "SSR", "middleware", "HOSTNAME", "standalone", "PGlite", "drizzle", "prisma", "server action", "env var",
          "webhook", "CORS", "SIGTERM", "EBUSY", "EADDRINUSE", "lockfile", "monorepo", "turbopack", "stdout", "regex")
LOST_RX = re.compile(r"(request was not processed|could not process your (request|message)|message was not delivered)", re.I)


def _ts(v) -> float | None:
    from .autopsy import _epoch
    return _epoch(v)


def _short(t: str, n: int = 160) -> str:
    from .util import mask_tokens
    t = mask_tokens(re.sub(r"\s+", " ", str(t or "")).strip())          # a key pasted in chat never reaches a report
    return t if len(t) <= n else t[: n - 1] + "…"


def _phase_at(ts: float | None, marks: list) -> str:
    """The phase a moment belongs to: marks = [(ts, phase that STARTS then)]."""
    cur = "define"
    for t, ph in marks:
        if ts is not None and t is not None and ts >= t:
            cur = ph
    return cur


def _source(root: Path, source: str | None, latest: bool, session: str | None):
    from . import autopsy as AU
    path = None
    if source:
        path = Path(source).expanduser()
    else:
        try:
            path = AU.latest_source(root)
        except DhError:
            path = None
        if path and path.name == "runs.jsonl" and not latest:
            path = None                                   # the run log is read anyway: no chat to add
    if not path or not path.exists():
        return [], {"messages": [], "delegations": []}, None, None
    kind = AU.detect(path)
    events, meta = AU.load(path, kind, session, root)
    return events, meta, path, kind


# ------------------------------------------------------------------ sections

def timeline(root: Path, hist: list, runs: list) -> dict:
    marks, out, gates, reopens = [], [], [], []
    for h in hist:
        t = _ts(h.get("at"))
        e = h.get("event")
        if e == "phase_done" or e == "phase_skip":
            nxt = STATE.PHASE_IDS[min(STATE.PHASE_IDS.index(h["phase"]) + 1, len(STATE.PHASE_IDS) - 1)] if h.get("phase") in STATE.PHASE_IDS else None
            marks.append((t, nxt))
            out.append({"at": h.get("at"), "event": f"{h.get('phase')} {'done' if e == 'phase_done' else 'skipped'}" + (" (FORCED)" if h.get("forced") else "")})
        elif e == "gate":
            q = h.get("quote")
            gates.append({"gate": h.get("gate"), "at": h.get("at"), "quote": q, "note": h.get("note"), "verdict": h.get("verdict"),
                          "flag": None if q else "PARAPHRASED: passed without the owner's own words"})
            out.append({"at": h.get("at"), "event": f"gate {h.get('gate')} passed" + (f" — owner: \"{_short(q, 80)}\"" if q else f" — agent note: \"{_short(h.get('note'), 80)}\"")})
        elif e == "reopen":
            marks.append((t, h.get("phase")))
            out.append({"at": h.get("at"), "event": f"REOPENED {h.get('phase')}: {_short(h.get('reason'), 100)}"})
            reopens.append({"at": h.get("at"), "phase": h.get("phase"), "reason": _short(h.get("reason"), 200)})
        elif e in ("init", "workflow", "base"):
            out.append({"at": h.get("at"), "event": {"init": "project started", "workflow": f"workflow pinned: {h.get('id')}@{h.get('version')}",
                                                     "base": f"base recorded ({h.get('kind')})"}[e]})
    # active time vs pauses, from every command's timestamp
    ts = sorted(t for t in (_ts(r.get("at")) for r in runs) if t)
    active, pauses = 0.0, []
    for a, b in zip(ts, ts[1:]):
        if b - a > PAUSE_S:
            pauses.append({"from": _iso(a), "minutes": round((b - a) / 60)})
        else:
            active += b - a
    per_phase = {}
    for a, b in zip(ts, ts[1:]):
        if b - a <= PAUSE_S:
            ph = _phase_at(a, marks)
            per_phase[ph] = per_phase.get(ph, 0) + (b - a)
    return {"events": out, "gates": gates, "reopens": reopens, "active_minutes": round(active / 60), "pauses": pauses,
            "active_by_phase": {k: round(v / 60) for k, v in per_phase.items()}, "_marks": marks}


def _iso(t: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def questions(root: Path, msgs: list, marks: list, hist: list, notes: list, runs: list) -> dict:
    """Every question put to the owner → the answer → what it changed. LATE: asked after define and not a gate
    question. DIRECTION-CHANGE: a reopen, a brief change or a decision followed within 30 minutes, or the answer asks
    for a change. LOST: the harness dropped the owner's message."""
    reopen_t = [_ts(h.get("at")) for h in hist if h.get("event") == "reopen"]
    change_t = [_ts(n.get("at")) for n in notes if n.get("kind") == "decision"] + \
               [_ts(r.get("at")) for r in runs if re.match(r"^dh (brief set|reopen)", str(r.get("cmd", ""))) and not r.get("exit")]
    define_end = next((_ts(h.get("at")) for h in hist if h.get("event") in ("phase_done", "phase_skip") and h.get("phase") == "define"), None)
    ledger, lost = [], []
    owner = [m for m in msgs if not m.get("injected")]
    for k, m in enumerate(owner):
        if m["role"] == "assistant" and LOST_RX.search(m["text"]) and k and owner[k - 1]["role"] == "user":
            lost.append({"at": _iso(owner[k - 1]["ts"]) if owner[k - 1].get("ts") else None, "message": _short(owner[k - 1]["text"], 200)})
        if m["role"] != "assistant" or not QUESTION_RX.search(m["text"][-1500:]):
            continue
        ans = next((x for x in owner[k + 1:k + 4] if x["role"] == "user"), None)
        if not ans:
            continue
        q_line = next((ln for ln in m["text"].splitlines()[::-1] if "?" in ln or "DECISION NEEDED" in ln or "ACTION NEEDED" in ln), m["text"].splitlines()[-1])
        ph = _phase_at(m.get("ts"), marks)
        is_gate = bool(GATE_Q_RX.search(q_line) or GATE_Q_RX.search(m["text"][-600:])) and ph != "define"
        kind = "gate" if is_gate else ("define" if ph == "define" or define_end is None else "late")
        t_ans = ans.get("ts")
        flags = []
        if kind == "late":
            flags.append("LATE")
        near = lambda xs: any(x and t_ans and 0 <= x - t_ans <= 1800 for x in xs)  # noqa: E731
        if STATE.classify_quote(ans["text"]) == "change_request" and kind == "gate":
            flags.append("DIRECTION-CHANGE")
        elif t_ans and (near(reopen_t) or (kind != "define" and near(change_t))):
            flags.append("DIRECTION-CHANGE")
        ledger.append({"n": len(ledger) + 1, "at": _iso(m["ts"]) if m.get("ts") else None, "phase": ph, "kind": kind,
                       "asked": _short(q_line, 200), "questions_in_message": len(re.findall(r"\?", m["text"])),
                       "answer": _short(ans["text"], 240), "flags": flags, "msg": m.get("id") or m["i"]})
    # without a transcript the notes are the only record of what was decided when
    if not msgs:
        for n in notes:
            if n.get("kind") == "decision":
                ph = _phase_at(_ts(n.get("at")), marks)
                ledger.append({"n": len(ledger) + 1, "at": n.get("at"), "phase": ph, "kind": "define" if ph == "define" else "late",
                               "asked": "(no transcript) decision recorded", "answer": _short(n.get("text"), 240),
                               "flags": ["LATE"] if ph != "define" else [], "msg": None})
    return {"ledger": ledger, "lost": lost, "late": len([q for q in ledger if "LATE" in q["flags"]]),
            "direction_changes": len([q for q in ledger if "DIRECTION-CHANGE" in q["flags"]])}


def deviations(root: Path) -> dict:
    pin = WF.pinned(root)
    if not pin:
        return {"workflow": None, "items": [], "note": "no workflow pinned — this run is the material for a new one (`dh workflow new --from-run`)"}
    wf = read_json(root / ".deckhand" / "workflow.json", {}) or {}
    steps = {st["id"]: (ph["id"], st) for ph in wf.get("phases", []) for st in ph.get("steps", [])}
    return {"workflow": f"{pin['source']}:{pin['id']}@{pin['version']}", "done": len(pin.get("done", [])), "skipped": len(pin.get("skipped", [])),
            "steps": len(steps), "items": pin.get("deviations", [])}


def errors(root: Path, events: list, meta: dict, runs_events: list) -> dict:
    """The failure engine on the richest source (the session when found, else the run log), each episode mapped to
    the workflow step whose command it ran."""
    from . import autopsy as AU
    from . import learn as LE
    ev = events if any(e.get("kind") == "cmd" for e in events) else runs_events
    rep = AU.analyze(ev, meta or {}, LE.all_lessons(root))
    wf = read_json(root / ".deckhand" / "workflow.json", {}) or {}
    by_norm = {}
    for ph in wf.get("phases", []):
        for st in ph.get("steps", []):
            for c in WF._commands(st.get("do") or st.get("check") or st.get("gate") or ""):
                by_norm.setdefault(WF._norm(c), st["id"])
    eps = []
    for e in rep["episodes"]:
        step = by_norm.get(WF._norm(re.sub(r"^.*?\bdh\.py\b", "dh", e.get("first_cmd") or "")))
        eps.append({**{k: e.get(k) for k in ("id", "owner", "rung", "signature", "first_cmd", "attempts", "occurrences", "resolved", "resolved_by", "minutes", "recipe", "known")},
                    "step": step})
    return {"commands": rep["commands"], "failures": rep["failures"], "blind_retries": rep["blind_retries"],
            "minutes_lost": round(sum(e.get("minutes") or 0 for e in eps), 1), "episodes": eps[:20], "tool_errors": rep["tool_errors"][:8]}


def delegation(root: Path, meta: dict) -> dict:
    bb = read_jsonl(root / ".deckhand" / "blackboard.jsonl")
    agents = {}
    for r in bb:
        a = r.get("wp")
        if a and a != "all":
            agents.setdefault(a, {"progress": 0, "done": 0, "blocker": 0, "question": 0})
            if r.get("kind") in agents[a]:
                agents[a][r["kind"]] += 1
    planned = sorted(p.stem for p in (root / ".deckhand" / "work").glob("AGENT-*.md"))
    return {"planned_packages": planned, "board": agents, "harness_batches": (meta or {}).get("delegations", []),
            "silent": [a for a, v in agents.items() if not v["done"] and not v["blocker"]]}


def guidance(msgs: list) -> dict:
    """How the AI talked to the owner — counts only, no judgement: labelled asks, questions per message, PENDING at the
    end of reports, jargon per 1000 words."""
    out = [m for m in msgs if m["role"] == "assistant" and not m.get("injected")]
    if not out:
        return {"messages": 0}
    words = sum(len(m["text"].split()) for m in out)
    jargon = sum(len(re.findall(r"\b" + re.escape(j) + r"\b", m["text"], re.I)) for m in out for j in JARGON)
    asks = [m for m in out if QUESTION_RX.search(m["text"][-1500:])]
    return {"messages": len(out), "asks": len(asks),
            "labelled_asks": len([m for m in asks if re.search(r"(DECISION NEEDED|ACTION NEEDED|FYI)", m["text"])]),
            "max_questions_in_one_message": max((len(re.findall(r"\?", m["text"])) for m in asks), default=0),
            "reports_ending_with_pending": len([m for m in out if re.search(r"(PENDING|waiting on you|still needed from you|open items)", m["text"][-800:], re.I)]),
            "jargon_per_1000_words": round(1000 * jargon / max(words, 1), 1), "words": words}


def proposals(tl: dict, qs: dict, dv: dict, er: dict, dl: dict) -> tuple[list, list]:
    """Workflow proposals (for the owner to accept) and maintainer items (Deckhand itself). Each carries why + evidence."""
    props, maint = [], []

    def add(target, change, why, evidence, rung, **extra):
        props.append({"id": f"P{len(props) + 1}", "target": target, "change": change, "why": why, "evidence": evidence, "rung": rung, **extra})
    for q in qs["ledger"]:
        if "LATE" in q["flags"] and "DIRECTION-CHANGE" in q["flags"]:
            add("ask_upfront", f"ask at define: \"{_short(q['asked'], 140)}\"",
                f"asked during {q['phase']} and the answer changed the direction — asked up front it costs one line, asked late it re-opens work",
                f"question {q['n']} ({q['at']}), answer: \"{_short(q['answer'], 100)}\"", "reorder", question=q["asked"], answer_example=q["answer"])
        elif "LATE" in q["flags"]:
            add("ask_upfront", f"consider asking at define: \"{_short(q['asked'], 140)}\"", f"asked during {q['phase']}; nothing re-opened, so it may belong there",
                f"question {q['n']} ({q['at']})", "pitfall", question=q["asked"], weak=True)
    asked = {_short(q["answer"], 80) for q in qs["ledger"] if "DIRECTION-CHANGE" in q["flags"]}
    for r in tl.get("reopens", []):                      # work re-opened = a question that belonged up front (even without a transcript)
        if _short(r["reason"], 80) in asked:
            continue
        add("ask_upfront", f"ask at define what re-opened {r['phase']}: \"{r['reason']}\"",
            f"{r['phase']} was re-opened after it was done — asked up front, it costs one line", f"reopen {r['at']}", "reorder",
            question=f"Settle up front: {r['reason']}", answer_example=r["reason"])
    for g in tl["gates"]:
        if g["flag"]:
            maint.append({"what": f"gate {g['gate']} passed without the owner's words", "why": "phased gates need `--quote` since 2.2.0 — an older dh, or an auto run",
                          "evidence": f"history {g['at']}: note \"{_short(g.get('note'), 80)}\""})
    for d in dv["items"]:
        if d.get("kind") == "unplanned":
            add("step", f"add to {d.get('phase')}: `{d.get('cmd')}`", "the run needed it and the workflow did not say so", f"deviation {d.get('at')}", "reorder",
                phase=d.get("phase"), cmd=d.get("cmd"))
        elif d.get("kind") == "not-run":
            add("step", f"mark {d.get('step')} optional (or remove it)", f"{d.get('phase')} finished green without it", f"deviation {d.get('at')}", "eliminate",
                step=d.get("step"))
        elif d.get("kind") == "phase-skipped":
            add("phase", f"{d.get('phase')} was skipped (\"{_short(d.get('why'), 80)}\") — mark it optional for this kind of project?",
                "the owner chose to skip it; if that is usual here, the workflow should say so", f"deviation {d.get('at')}", "eliminate",
                phase=d.get("phase"), weak=True)
        elif d.get("kind") == "skipped":
            add("step", f"review {d.get('step')}: skipped — \"{_short(d.get('why'), 100)}\"", "a step the run chose to skip", f"deviation {d.get('at')}", "pitfall",
                step=d.get("step"), weak=True)
    for e in er["episodes"]:
        if e["owner"] == "skill":
            maint.append({"what": f"Deckhand failed: {_short(e['signature'], 120)}", "why": f"{e['attempts']} attempts" + (f", {e['minutes']} min" if e.get("minutes") else ""),
                          "evidence": _short(e.get("first_cmd"), 160), "fixed_by": e.get("resolved_by")})
            continue
        if e.get("known"):
            continue                                        # a seeded lesson already prints its fix at the moment it happens
        fix = " → ".join(f"{k} {v}" for k, v in (e.get("recipe") or [])[:4]) or \
            ("resolved, but no fixing step was recorded — note what fixed it (`dh learn from-failure`)" if e["resolved"]
             else "not resolved in this run — add a preflight once the cause is known")
        add("pitfall", f"at {e['step'] or 'the step that runs `' + _short(e['first_cmd'], 60) + '`'}: when `{_short(e['signature'], 80)}` → {fix}",
            f"cost {e['attempts']} attempts" + (f" and {e['minutes']} min" if e.get("minutes") else "") + (", resolved" if e["resolved"] else ", NOT resolved"),
            f"episode {e['id']}", e["rung"], step=e["step"], sig=e["signature"], fix=fix)
    for a in dl["silent"]:
        add("delegate", f"{a}: no done/blocker on the board", "a builder that stops silently leaves the orchestrator guessing (the run lost its builders once)",
            f"board: {dl['board'][a]}", "gate", weak=True)
    for b in dl["harness_batches"]:
        if b.get("state") in ("error", "failed", "interrupted") or any(r in ("interrupted", "error", "failed") for r in b.get("results", [])):
            add("delegate", f"batch {b.get('id')}: {b.get('state')} ({', '.join(b.get('results') or [])}) — size each package to finish in one child",
                "children killed together lose the phase (re-cut at the artifact seam, not re-dispatch the same brief)", f"async_delegations {b.get('id')}", "reorder", weak=True)
    return props, maint


# ------------------------------------------------------------------ report

def run(root: Path, source: str | None = None, latest: bool = False, part: str | None = None, session: str | None = None) -> dict:
    root = Path(root)
    if not (root / ".deckhand").is_dir():
        raise DhError("NO_RUN", f"no .deckhand/ in {root}")
    if part and part not in PARTS:
        raise DhError("BAD_PART", f"--part must be one of {', '.join(PARTS)}")
    hist = read_jsonl(root / ".deckhand" / "history.jsonl")
    from . import resume as RESUME
    notes = RESUME.notes(root)
    runs = read_jsonl(root / ".deckhand" / "runs.jsonl")
    events, meta, path, kind = _source(root, source, latest, session)
    from . import autopsy as AU
    runs_events = AU.load_runs(root / ".deckhand" / "runs.jsonl")[0] if (root / ".deckhand" / "runs.jsonl").exists() else []
    tl = timeline(root, hist, runs)
    qs = questions(root, meta.get("messages", []), tl["_marks"], hist, notes, runs)
    dv = deviations(root)
    er = errors(root, events, meta, runs_events)
    dl = delegation(root, meta)
    gd = guidance(meta.get("messages", []))
    props, maint = proposals(tl, qs, dv, er, dl)
    s = STATE.load(root, required=False) or {}
    tl.pop("_marks", None)
    from . import learn as LE
    rep = redact_obj({"project": s.get("name"), "at_phase": STATE.current(s)["id"] if s else None, "source": {"kind": kind or "project files only", "session": meta.get("session")},
                      "timeline": tl, "questions": qs, "deviations": dv, "errors": er, "delegation": dl, "guidance": gd,
                      "proposals": props, "maintainer": maint}, LE.secret_values())
    body = json.dumps({k: v for k, v in rep.items() if k != "at"}, sort_keys=True, ensure_ascii=False)
    wid = "W-" + hashlib.sha1(body.encode()).hexdigest()[:10]
    rep["id"] = wid
    out = root / ".deckhand" / "autopsy"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / f"{wid}.json", rep)
    write_json(out / "workflow-latest.json", {"id": wid, "proposals": [p["id"] for p in props if not p.get("weak")]})
    (out / f"{wid}.md").write_text(render_owner(rep), encoding="utf-8")
    (out / f"{wid}.maintainer.md").write_text(render_maintainer(rep), encoding="utf-8")
    if part:
        return {"id": wid, "part": part, part: rep[part]}
    strong = [p for p in props if not p.get("weak")]
    return {"id": wid, "report": str(out / f"{wid}.md"), "maintainer_report": str(out / f"{wid}.maintainer.md"),
            "summary": {"phase": rep["at_phase"], "active_minutes": tl["active_minutes"], "questions": len(qs["ledger"]), "late": qs["late"],
                        "direction_changes": qs["direction_changes"], "deviations": len(dv["items"]), "failures": er["failures"],
                        "minutes_lost": er["minutes_lost"], "proposals": len(props), "maintainer_items": len(maint)},
            "proposals": [{k: p[k] for k in ("id", "target", "change", "why")} for p in props][:12],
            "ask_owner": save_prompt(wid, strong, bool(maint)),
            "parts": "a sub-agent can take one section: dh autopsy --workflow --part " + "|".join(PARTS)}


def save_prompt(wid: str, props: list, maint: bool) -> str:
    ids = ",".join(p["id"] for p in props)
    lines = [f"WORKFLOW PROPOSALS ({len(props)})"] + [f"{p['id']} {p['change']} — {p['why']}" for p in props[:8]]
    if props:
        lines += [f"Save the ones you accept to: [1] my workflows (stays on this machine) → dh workflow save --from-autopsy {wid} --proposals {ids}",
                  f"[2] the community pool (a reviewed PR) → dh workflow save --from-autopsy {wid} --proposals {ids} --public",
                  "[3] skip"]
    else:
        lines.append("nothing to change in the workflow from this run" + (" (weak signals are listed in the report)" if wid else ""))
    if maint:
        lines.append(f"Deckhand issues for its maintainer: .deckhand/autopsy/{wid}.maintainer.md (send it if you want them fixed)")
    return "\n".join(lines)


def render_owner(rep: dict) -> str:
    tl, qs, dv, er, dl, gd = (rep[k] for k in ("timeline", "questions", "deviations", "errors", "delegation", "guidance"))
    L = [f"# Workflow autopsy {rep['id']} — {rep.get('project')}", "",
         f"At phase **{rep.get('at_phase')}** · source: {rep['source']['kind']} · active {tl['active_minutes']} min"
         + (f" · {len(tl['pauses'])} pauses" if tl["pauses"] else ""), "", "## How it went", ""]
    L += [f"- {e['at'][:16].replace('T', ' ') if e.get('at') else ''} {e['event']}" for e in tl["events"]] or ["- (no phase finished yet)"]
    if tl["active_by_phase"]:
        L.append("- active minutes by phase: " + ", ".join(f"{k} {v}" for k, v in tl["active_by_phase"].items()))
    L += ["", f"## What you were asked — {len(qs['ledger'])} questions, {qs['late']} late, {qs['direction_changes']} changed the direction", ""]
    L += [f"- {q['n']}. [{q['phase']}] {q['asked']} → \"{q['answer']}\"" + (f" **{' '.join(q['flags'])}**" if q["flags"] else "") for q in qs["ledger"][:30]] or ["- none found"]
    L += [f"- LOST (the harness dropped it): \"{x['message']}\"" for x in qs["lost"]]
    L += ["", "## Against the workflow", ""]
    L += [f"- {dv['workflow']}: {dv.get('done', 0)} done, {dv.get('skipped', 0)} skipped of {dv.get('steps', 0)} steps"] if dv["workflow"] else [f"- {dv['note']}"]
    L += [f"- {d.get('kind')}: {d.get('cmd') or d.get('step')}" + (f" — {d['why']}" if d.get("why") else "") for d in dv["items"][:20]]
    L += ["", f"## What failures cost — {er['failures']} failed commands, {er['blind_retries']} blind retries, ~{er['minutes_lost']} min", ""]
    L += [f"- {e['id']} ({e['owner']}, {e['attempts']}×" + (f", {e['minutes']} min" if e.get("minutes") else "") + f"){' at ' + e['step'] if e.get('step') else ''}: "
          f"{_short(e['signature'], 100)}" + (" — resolved" if e["resolved"] else " — NOT resolved") for e in er["episodes"][:12]] or ["- none"]
    if dl["planned_packages"] or dl["harness_batches"] or dl["board"]:
        L += ["", "## Builders", ""]
        L += [f"- planned: {', '.join(dl['planned_packages']) or '—'}"] + [f"- {a}: {v}" for a, v in dl["board"].items()]
        L += [f"- batch {b.get('id')}: {b.get('state')} · {', '.join(b.get('results') or [])}" for b in dl["harness_batches"]]
    if gd.get("messages"):
        L += ["", "## How the AI talked to you (counts)", "",
              f"- {gd['messages']} messages, {gd['asks']} with questions ({gd['labelled_asks']} labelled DECISION/ACTION NEEDED), "
              f"at most {gd['max_questions_in_one_message']} questions in one message, {gd['reports_ending_with_pending']} ended with what waits on you, "
              f"jargon {gd['jargon_per_1000_words']} per 1000 words"]
    L += ["", "## Proposals for the workflow", ""]
    L += [f"- **{p['id']}** ({p['target']}, {p['rung']}{', weak' if p.get('weak') else ''}) {p['change']}  \n  why: {p['why']} · evidence: {p['evidence']}" for p in rep["proposals"]] or ["- none"]
    L += ["", "```", save_prompt(rep["id"], [p for p in rep["proposals"] if not p.get("weak")], bool(rep["maintainer"])), "```", ""]
    return "\n".join(L)


def render_maintainer(rep: dict) -> str:
    L = [f"# For the Deckhand maintainer — {rep['id']} ({rep.get('project')})", "",
         "Deckhand issues only (the owner's workflow proposals are in the other report). Evidence, no values: secrets are redacted.", ""]
    L += [f"- {m['what']} — {m['why']} · evidence: {m['evidence']}" + (f" · fixed in the run by: {m['fixed_by']}" if m.get("fixed_by") else "") for m in rep["maintainer"]] or ["- nothing: no Deckhand failure, no gate without quote"]
    gd = rep["guidance"]
    if gd.get("messages"):
        L += ["", f"Guidance counts: {json.dumps(gd, ensure_ascii=False)}"]
    L += ["", f"Source: {rep['source']['kind']} · session {rep['source'].get('session')} · generated {today()}", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ save accepted proposals

def workflow_save(root: Path, aid: str, accepted: list, public: bool = False, wid: str | None = None) -> dict:
    """Apply the proposals the owner accepted to the pinned workflow (or this run's extraction), add this run as
    proof, bump the version, record why — then save to the owner's pool or as a community bundle."""
    root = Path(root)
    rep = read_json(root / ".deckhand" / "autopsy" / f"{aid}.json", None, expect=dict)
    if not rep:
        raise DhError("NO_REPORT", f"no workflow autopsy {aid} in .deckhand/autopsy/ (dh autopsy --workflow)")
    props = {p["id"]: p for p in rep["proposals"]}
    bad = [x for x in accepted if x not in props]
    if bad:
        raise DhError("NO_SUCH_PROPOSAL", f"{', '.join(bad)} not in {aid} ({', '.join(props) or 'no proposals'})")
    wf = read_json(root / ".deckhand" / "workflow.json", None, expect=dict)
    pin = WF.pinned(root)
    if not wf:
        made = WF.new_from_run(root, wid)
        wf = read_json(Path(made["saved"]), {})
    wf = json.loads(json.dumps(wf))
    if wid:
        wf["id"] = wid
    src = (pin or {}).get("source")
    if src in ("base", "community") and not public:
        wf["forked_from"] = f"{src}:{pin['id']}@{pin['version']}"
    applied = []
    for pid in accepted:
        p = props[pid]
        if p["target"] == "ask_upfront":
            n = len(wf.setdefault("ask_upfront", [])) + 1
            wf["ask_upfront"].append({"id": f"Q-learned-{n}", "q": _short(p.get("question") or p["change"], 200), "ask_at": "define",
                                      "learned_from": f"{rep.get('project')} {today()} — {p['why']}"})
            for ph in wf.get("phases", []):
                for st in ph.get("steps", []):
                    if isinstance(st.get("ask"), list):
                        st["ask"].append(f"Q-learned-{n}")
                        break
                else:
                    continue
                break
        elif p["target"] == "step" and p.get("cmd"):
            ph = next((x for x in wf.get("phases", []) if x["id"] == p.get("phase")), None)
            if not ph:
                ph = {"id": p.get("phase") or "build", "steps": []}
                wf.setdefault("phases", []).append(ph)
            base = ph["steps"][-1]["id"] if ph["steps"] else WF.ABBR.get(ph["id"], "S")
            ids = {st["id"] for x in wf["phases"] for st in x.get("steps", [])}
            k = 1
            while f"{base}-{k}" in ids:
                k += 1
            ph["steps"].append({"id": f"{base}-{k}", "do": p["cmd"], "expect": "ok: true", "added_by": aid})
        elif p["target"] == "step" and p.get("step"):
            for ph in wf.get("phases", []):
                for st in ph.get("steps", []):
                    if st["id"] == p["step"]:
                        st["optional"] = True
        elif p["target"] == "pitfall":
            wf.setdefault("pitfalls", []).append({"id": f"PF{len(wf['pitfalls']) + 1}", "at": p.get("step") or "", "sig": re.escape(_short(p.get("sig"), 80))[:120],
                                                  "fix": p.get("fix") or p["change"], "learned_from": f"{rep.get('project')} {today()}"})
        applied.append({"id": pid, "change": p["change"], "why": p["why"], "evidence": p["evidence"]})
    s = STATE.load(root, required=False) or {}
    complete = s.get("phases", {}).get("deploy", {}).get("status") in ("done", "skipped")
    unresolved = len([e for e in rep["errors"]["episodes"] if not e["resolved"]])
    wf = WF.add_run(wf, {"date": today(), "project": rep.get("project"), "harness": WF.harness(), "os": WF.os_name(), "complete": complete,
                         "errors": unresolved, "minutes": rep["timeline"]["active_minutes"], "autopsy": aid,
                         "reached": rep.get("at_phase"), "deviations": len(rep["deviations"]["items"])})
    wf["version"] = int(wf.get("version", 1)) + 1
    wf.setdefault("changelog", []).append({"version": wf["version"], "date": today(), "change": "; ".join(a["change"] for a in applied) or "a run added as proof",
                                           "why": "; ".join(a["why"] for a in applied) or "evidence", "evidence": f"workflow autopsy {aid}"})
    res = WF.save(wf, "public" if public else "mine")
    STATE.log(root, {"event": "workflow_saved", "autopsy": aid, "id": wf["id"], "version": wf["version"], "where": "public" if public else "mine",
                     "accepted": accepted})
    return {**res, "applied": applied, "version": wf["version"], "run_added": {"complete": complete, "errors": unresolved}}
