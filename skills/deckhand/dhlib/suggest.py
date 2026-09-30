"""SUGGEST: after the PENDING list, what the owner could do next — computed from the project's files, never guessed.

Every rule reads facts (run state, history, the run log, notes, pending, reports and their dates) and, when its
condition holds, proposes ONE thing: what, why (the evidence), the exact command, and how important it is:
  now    (score ≥ 80)  something is at risk or waiting on the owner — say it first
  soon   (50–79)       worth doing at the next natural pause
  later  (< 50)        optional: a reminder, a good habit, a nice-to-have
Suggestions are optional by design: the owner decides. `dh suggest dismiss ID [--days N]` hides one (default 7 days);
a suggestion whose condition stops holding disappears by itself. Same files → same suggestions, same order.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .util import DhError, is_guard, read_json, read_jsonl, today, write_json
from . import state as STATE

SHOW = 3


def _mtime(p: Path) -> float:
    try:
        return Path(p).stat().st_mtime
    except OSError:
        return 0.0


def _ts(v) -> float:
    from .autopsy import _epoch
    return _epoch(v) or 0.0


def _tail_jsonl(p: Path, n: int = 3000) -> list:
    if not p.exists():
        return []
    import json
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _dismissed(root: Path) -> dict:
    return (read_json(Path(root) / ".deckhand" / "suggest.json", {}) or {}).get("dismissed", {})


def dismiss(root: Path, sid: str, days: int = 7) -> dict:
    if not re.match(r"^[a-z0-9][a-z0-9:._-]{1,80}$", sid or ""):
        raise DhError("BAD_ID", "dh suggest dismiss <id from `dh suggest`>")
    p = Path(root) / ".deckhand" / "suggest.json"
    doc = read_json(p, {}) or {}
    until = time.strftime("%Y-%m-%d", time.gmtime(time.time() + max(1, days) * 86400))
    doc.setdefault("dismissed", {})[sid] = until
    write_json(p, doc)
    return {"dismissed": sid, "until": until}


def autopsy_cmd(workflow: bool = True) -> str:
    """The exact autopsy command for the harness in use (inside Hermes and Claude Code, --latest is this session)."""
    from . import workflow as WF
    h = WF.harness()
    from .util import DH
    base = f"{DH} autopsy --workflow" if workflow else f"{DH} autopsy"
    return base + (" --latest" if h in ("hermes", "claude-code") else "")


def _item(sid, score, what, why, cmd=None, kind="action"):
    return {"id": sid, "level": "now" if score >= 80 else "soon" if score >= 50 else "later", "score": score,
            "what": what, "why": why, **({"cmd": cmd} if cmd else {}), "kind": kind}


# ------------------------------------------------------------------ facts (cheap reads only; no network)

def facts(root: Path) -> dict | None:
    root = Path(root)
    s = STATE.load(root, required=False)
    if not s:
        return None
    dk = root / ".deckhand"
    from . import resume as RESUME, pending as PEND
    cur = STATE.current(s)["id"]
    hist = read_jsonl(dk / "history.jsonl")
    runs = _tail_jsonl(dk / "runs.jsonl")
    aut = dk / "autopsy"
    a_reports = sorted(aut.glob("A-*.json"), key=_mtime) if aut.is_dir() else []
    w_reports = sorted([p for p in aut.glob("W-*.json")], key=_mtime) if aut.is_dir() else []
    return {
        "root": root, "s": s, "phase": cur, "gate": STATE.blocking_gate(s), "hist": hist, "runs": runs,
        "safety": RESUME.safety_facts(root), "pending": PEND.summary(root, include_deferred=True),
        "last_autopsy": _mtime(a_reports[-1]) if a_reports else 0.0,
        "last_a_report": a_reports[-1] if a_reports else None,
        "applied": read_json(aut / "applied.json", {}) or {},
        "last_wautopsy": _mtime(w_reports[-1]) if w_reports else 0.0,
        "w_latest": read_json(aut / "workflow-latest.json", {}) or {},
        "w_maintainer": (aut / f"{(read_json(aut / 'workflow-latest.json', {}) or {}).get('id', '')}.maintainer.md"),
        "workflow": s.get("workflow"), "brief": read_json(dk / "brief.json", {}) or {},
        "verify": read_json(dk / "verify.json", None, expect=dict), "seo": read_json(dk / "seo.json", None, expect=dict), "deploy": read_json(dk / "deploy.json", {}) or {},
        "head": RESUME._git(root, "rev-parse", "HEAD"),
    }


def _since(f: dict, t: float) -> list:
    return [r for r in f["runs"] if _ts(r.get("at")) > t]


# ------------------------------------------------------------------ rules (each returns 0..n items)

def r_gate(f):
    g = f["gate"]
    if not g:
        return []
    return [_item("gate", 88, f"Your turn ({g}): {GATE_ASK.get(g, 'say go, or what to change')}",
                  "the run is stopped at this checkpoint until you answer, in your own words", None, "owner")]


GATE_ASK = {"G1": "approve the plan, or say what to change", "G2": "try the app on your computer, then say go or what to change",
            "G3": "approve the design, or say what to change", "G4": "say go live, or what to fix first"}


def r_unsaved(f):
    from . import resume as RESUME
    ok, why = RESUME.safe(f["safety"], f["root"])
    if ok:
        return []
    return [_item("unsaved", 95, "Write down what is being changed, so no session can lose it", why[0][:160],
                  'dh note doing "what is being changed and why"')]


def r_services(f):
    from . import resume as RESUME
    down = [x["name"] for x in RESUME._services(f["root"]) if not x["up"]]
    if not down:
        return []
    return [_item("services", 85, f"Restart what the app needs: {', '.join(down)} is down", "the app cannot work without it", "dh dev start")]


def r_deferred_due(f):
    out = []
    reached = set(f["s"]["phases"])
    for it in f["pending"]["items"]:
        w = (it.get("when") or "").lower()
        if not w:
            continue
        hit = next((ph for ph in STATE.PHASE_IDS if re.search(r"\b" + ph + r"\b", w)), None) or \
            next((g for g in STATE.GATES if g.lower() in w), None)
        if not hit:
            continue
        due = (hit in STATE.GATES and f["gate"] == hit) or (hit in STATE.PHASE_IDS and STATE.PHASE_IDS.index(f["phase"]) >= STATE.PHASE_IDS.index(hit))
        if due and hit in reached | set(STATE.GATES):
            out.append(_item(f"due:{it['id']}", 86, f"{it['id']} is due now: {it['item'][:90]}", f"deferred until \"{it['when']}\" — that moment has come",
                             "dh pending list --all", "reminder"))
    return out


def r_repeated_failure(f):
    fails = [r for r in f["runs"][-60:] if r.get("exit") and not is_guard(r)]
    counts = {}
    for r in fails:
        counts[r.get("cmd", "")] = counts.get(r.get("cmd", ""), 0) + 1
    worst = max(counts.items(), key=lambda x: (x[1], x[0]), default=("", 0))
    ok_after = any(r.get("cmd") == worst[0] and not r.get("exit") for r in f["runs"][-60:][::-1][:20])
    if worst[1] < 2 or ok_after:
        return []
    return [_item("stuck", 82, "Stop retrying: the same command failed " + str(worst[1]) + " times — read what fixed it before",
                  f"`{worst[0][:80]}`", f"dh learn match --text \"{_sig(worst[0])}\"")]


def _sig(cmd: str) -> str:
    return re.sub(r"[\"'`$]", "", cmd)[:60]


def r_autopsy_due(f):
    fails = [r for r in _since(f, f["last_autopsy"]) if r.get("exit") and not is_guard(r)]
    if len(fails) < 3:
        return []
    return [_item("autopsy", 70, f"Turn the last {len(fails)} failures into lessons, so each is paid once",
                  "failures since the last autopsy; the fixes that worked become recipes the next run gets up front",
                  autopsy_cmd(workflow=False) + " --apply")]


def r_lessons_unapplied(f):
    rep = f["last_a_report"]
    if not rep or f["applied"].get("id") == rep.stem:
        return []
    return [_item("apply", 45, "Keep what the last autopsy learned (lessons + recipes for every future project)", f"report {rep.stem} was not applied",
                  autopsy_cmd(workflow=False) + " --apply")]


def r_workflow_query(f):
    if f["workflow"] or f["phase"] not in ("define", "research", "plan"):
        return []
    if any("workflow query" in str(r.get("cmd", "")) for r in f["runs"]):
        return []                                        # already looked: the owner picked one or none
    score = 75 if f["phase"] == "define" else 45
    return [_item("workflow-query", score, "Follow a proven path instead of improvising: see the 3 that fit this project",
                  "a workflow is the exact steps that worked before, with its questions asked up front", "dh workflow query", "optional")]


def r_workflow_checkpoint(f):
    marks = [h for h in f["hist"] if h.get("event") in ("gate", "phase_done") and _ts(h.get("at")) > f["last_wautopsy"]]
    if not marks:
        return []
    devs = len((f["workflow"] or {}).get("deviations", []))
    score = 60 if devs >= 3 else 40
    last = marks[-1]
    label = f"gate {last.get('gate')}" if last.get("event") == "gate" else f"{last.get('phase')} done"
    return [_item("checkpoint", score, "Checkpoint review: what you were asked late, where the run left its path, what failures cost",
                  f"{label} since the last review" + (f"; {devs} deviations from the workflow" if devs else "") + " — it only proposes, it changes nothing",
                  autopsy_cmd(), "optional")]


def r_proposals(f):
    w = f["w_latest"]
    if not w.get("proposals"):
        return []
    saved = any(h.get("event") == "workflow_saved" and h.get("autopsy") == w.get("id") for h in f["hist"])
    if saved:
        return []
    return [_item(f"proposals:{w['id']}", 62, f"Decide on {len(w['proposals'])} workflow improvement(s): keep them for next time, share them, or skip",
                  f"from review {w['id']} (.deckhand/autopsy/{w['id']}.md)",
                  f"dh workflow save --from-autopsy {w['id']} --proposals {','.join(w['proposals'])}", "optional")]


def r_complete(f):
    done = f["s"]["phases"].get("deploy", {}).get("status") in ("done", "skipped")
    if not done:
        return []
    out = []
    after = max((_ts(h.get("at")) for h in f["hist"] if h.get("phase") == "deploy"), default=0.0)
    if f["workflow"] and f["last_wautopsy"] < after:
        out.append(_item("proof", 60, "Record this finished run as proof for its workflow (draft → proven)",
                         "a complete run that followed it; the review adds it with its errors and time", autopsy_cmd(), "optional"))
    if not f["workflow"] and not any("workflow new" in str(r.get("cmd", "")) for r in f["runs"]):
        out.append(_item("extract", 55, "Save this run as a workflow, so the next similar project starts from it",
                         "no workflow was followed; this run is the path", "dh workflow new --from-run", "optional"))
    if not (f["root"] / "HANDOFF.md").exists() or _mtime(f["root"] / "HANDOFF.md") < _mtime(f["root"] / ".deckhand" / "deploy.json"):
        out.append(_item("handoff", 65, "Refresh HANDOFF.md (where every access lives, the everyday commands)", "the last deploy is newer than it", "dh handoff"))
    if not any("dh harvest" in str(r.get("cmd", "")) for r in f["runs"]):
        out.append(_item("harvest", 30, "Keep this project as a private base for the next client", "one command next time instead of a new build",
                         "dh harvest --name " + re.sub(r"[^a-z0-9-]+", "-", str(f["s"].get("name", "base")).lower()).strip("-") + " --push", "optional"))
    return out


def r_research_stale(f):
    dk = f["root"] / ".deckhand"
    if not (dk / "research.json").exists() or STATE.PHASE_IDS.index(f["phase"]) < STATE.PHASE_IDS.index("research"):
        return []
    if f["s"]["phases"].get("research", {}).get("status") == "skipped":
        return []
    r = read_json(dk / "research.json", {}) or {}
    if not r.get("claims") and not any(str(c.get("url", "")).startswith("http") for c in r.get("competitors", [])):
        return []                                        # still the template: nothing to verify yet
    v = dk / "research" / "verify.json"
    if v.exists() and _mtime(v) >= _mtime(dk / "research.json"):
        return []
    return [_item("research-verify", 80 if f["phase"] == "research" else 55, "Re-check the research quotes on their pages",
                  "research.json changed after the last verify" if v.exists() else "no verify yet", "dh research verify")]


def r_plan_drift(f):
    g1 = (f["s"].get("gates") or {}).get("G1", {})
    if g1.get("status") != "passed":
        return []
    t = _ts(g1.get("at"))
    dk = f["root"] / ".deckhand"
    changed = [n for n in ("sitemap.json", "brief.json") if _mtime(dk / n) > t + 5]
    if not changed:
        return []
    return [_item("plan-drift", 68, "The approved plan changed afterwards: re-check what still holds",
                  f"{', '.join(changed)} edited after G1", "dh resume --check")]


def r_verify_stale(f):
    if STATE.PHASE_IDS.index(f["phase"]) < STATE.PHASE_IDS.index("review"):
        return []
    v = f["verify"]
    if v and v.get("commit") and f["head"] and v["commit"] == f["head"] and v.get("ok"):
        return []
    why = "no verify yet" if not v else ("red rows" if not v.get("ok") else "the code changed since it was proved")
    return [_item("verify", 72 if f["phase"] in ("review", "deploy") else 50, "Prove the current code again before shipping", why, "dh verify")]


def r_seo(f):
    ph = f["phase"]
    seo = f["seo"]
    if ph in ("brand", "review") and not seo:
        return [_item("seo", 58, "Check what stands between the site and Google", "no SEO audit yet", "dh seo audit")]
    if ph == "operate" and seo and time.time() - _ts(seo.get("at")) > 30 * 86400:
        dom = f["brief"].get("domain")
        return [_item("seo-monthly", 40, "Monthly SEO check on the live site", "the last audit is over 30 days old",
                      f"dh seo audit --url https://{dom}" if dom else "dh seo audit", "reminder")]
    return []


def r_pending_age(f):
    old = [it for it in f["pending"]["items"] if not it.get("when") and (it.get("age_days") or 0) >= 7]
    if not old:
        return []
    it = max(old, key=lambda x: (x["age_days"], x["id"]))
    score = 66 if it["age_days"] >= 14 else 52
    return [_item(f"pending-age:{it['id']}", score, f"{it['id']} has waited {it['age_days']} days: {it['item'][:90]}",
                  f"{len(old)} item(s) open a week or more", f"dh pending done {it['id']}   # or: dh pending wait {it['id']} (you did it, to confirm)", "reminder")]


def r_fresh(f):
    from . import resume as RESUME
    hint = RESUME.session_hint(f["root"]) or {}
    big = (hint.get("log_mb") or 0) > 2
    gate_just = f["hist"] and f["hist"][-1].get("event") == "gate"
    if not (big or gate_just):
        return []
    ok, _ = RESUME.safe(f["safety"], f["root"])
    if not ok:
        return []
    return [_item("fresh", 55 if big else 42, "A fresh session is safe now (and sharper)",
                  f"this session log is {hint['log_mb']} MB" if big else "a checkpoint just passed; nothing lives only in the chat",
                  "dh resume   # first command of the new session", "optional")]


def r_ops(f):
    if f["phase"] != "operate":
        return []
    bots = list((f["root"] / "ops" / "bots").glob("*")) if (f["root"] / "ops" / "bots").is_dir() else []
    if bots:
        return []
    return [_item("bots", 38, "Let bots watch the site and the business (uptime, broken links, leads…)", "no bot installed yet", "dh ops suggest", "optional")]


def r_maintainer(f):
    p = f["w_maintainer"]
    if not p.exists() or "- nothing:" in p.read_text(encoding="utf-8", errors="replace"):
        return []
    return [_item("maintainer", 25, "Send the Deckhand issues found in this run to its maintainer (optional)",
                  f"{p.relative_to(f['root']).as_posix()} lists them — no secret values inside", None, "optional")]


def r_profile(f):
    if f["phase"] != "define" or any("profile doctor" in str(r.get("cmd", "")) for r in f["runs"]):
        return []
    return [_item("profile", 70, "Check what access already exists before asking the owner anything", "never ask for what a token covers", "dh profile doctor")]


RULES = (r_unsaved, r_gate, r_deferred_due, r_services, r_repeated_failure, r_research_stale, r_verify_stale, r_workflow_query,
         r_profile, r_autopsy_due, r_plan_drift, r_complete, r_pending_age, r_proposals, r_workflow_checkpoint, r_seo, r_fresh,
         r_lessons_unapplied, r_ops, r_maintainer)


def compute(root: Path, limit: int = SHOW, include_dismissed: bool = False, exclude_cmds=()) -> dict:
    """exclude_cmds: what `dh next` already tells the agent to do — a suggestion never repeats it."""
    f = facts(root)
    if not f:
        return {"items": [], "more": 0}
    from . import workflow as WF
    said = {WF._norm(re.sub(r"^\S+ ", "", str(c)) if not str(c).startswith("dh ") else str(c)) for c in exclude_cmds}
    said |= {WF._norm("dh " + m.group(1)) for c in exclude_cmds for m in [re.search(r"dh\.py\"?\s+(.+)$", str(c))] if m}
    items, seen = [], set()
    for rule in RULES:
        try:
            for it in rule(f):
                if it["id"] in seen or (it.get("cmd") and WF._norm(it["cmd"].split("   #")[0]) in said):
                    continue
                seen.add(it["id"])
                items.append(it)
        except Exception:  # noqa: BLE001 — one broken rule never hides the others
            continue
    gone = {k: v for k, v in _dismissed(root).items() if v >= today()}
    hidden = [it for it in items if it["id"] in gone]
    if not include_dismissed:
        items = [it for it in items if it["id"] not in gone]
    items.sort(key=lambda it: (-it["score"], it["id"]))
    return {"items": items[:limit] if limit else items, "more": max(0, len(items) - limit) if limit else 0,
            **({"dismissed": len(hidden)} if hidden else {}),
            "say": "after the PENDING list: 'Next (optional)' — each line: importance, what, the command; the owner decides"}


def lines(sug: dict) -> list:
    """The report form: one line per suggestion, importance first."""
    tag = {"now": "NOW", "soon": "SOON", "later": "LATER"}
    return [f"{tag[it['level']]} · {it['what']}" + (f" — {it['why'][:90]}" if it.get("why") else "") + (f" → `{it['cmd']}`" if it.get("cmd") else "")
            for it in sug.get("items", [])]
