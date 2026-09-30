"""RESUME: continue any project from any AI, in any fresh session, with no memory — without fear of losing anything.

  .deckhand/RESUME.md      regenerated after EVERY dh command from the project's own files (run state, brief, plan,
                           verify, deploy, SEO, PENDING, try-on sessions, run log, git) + the one-line notes below.
                           Deterministic, ≤ ~1,500 tokens, local only (gitignored). Nothing in it is a model's recap.
  dh note decision "…"     an owner decision, the moment it is made (the one thing that otherwise lives only in chat)
  dh note doing "…"        what is in progress right now (clears with `dh note doing done`)
  dh note next "…"         the intended next step when stopping mid-way
  dh resume                prints it + "SAFE TO START A FRESH SESSION: YES/NO (why)" — the verdict is computed:
                           edits made after the last note, or an unexplained failed command, would be lost with the chat
  dh resume --check        re-proves every claim against reality (checks re-run, verify/deploy vs HEAD, brief edited
                           after the plan was approved, dev server, open sessions) — no model recap, no build
  dh resume --hook         SessionStart hook for Claude Code (startup, resume, clear, AND after compaction): prints
                           the resume as context — or nothing outside a deckhand project
Any harness: `dh init` writes a marked block in the project's AGENTS.md (and CLAUDE.md) telling a cold agent to run
`dh resume` first.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time
from pathlib import Path

from .util import is_guard, DhError, SKILL, append_jsonl, ensure_gitignore, now, read_json, read_jsonl, redact, run, write_json
from . import state as STATE

KINDS = ("decision", "doing", "next")
MANAGED = ("PENDING.md", "HANDOFF.md", ".gitignore", "AGENTS.md", "CLAUDE.md")   # written by dh: not the agent's unexplained work
BUDGET = 6000                       # characters (~1,500 tokens): a cold start must stay cheap
BEGIN = "<!-- deckhand:begin — written by `dh init`; it lets any AI resume this project cold. Keep it. -->"
END = "<!-- deckhand:end -->"


def _dk(root) -> Path:
    return Path(root) / ".deckhand"


def _ts(s) -> float:
    try:
        return _dt.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _short(s: str, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ------------------------------------------------------------------ notes

def note(root: Path, kind: str, text: str) -> dict:
    if kind not in KINDS:
        raise DhError("USAGE", f"dh note {'|'.join(KINDS)} \"…\"")
    text = (text or "").strip()
    if not text:
        raise DhError("USAGE", f"dh note {kind} \"what\" — one line")
    if not STATE.load(root, required=False):
        raise DhError("NO_RUN", "no project here — `dh init` first (or --project)")
    from .redact import scrub_text
    s = STATE.load(root)
    row = {"at": now(), "ts": round(time.time(), 3), "kind": kind, "text": scrub_text(text)[:400],
           "phase": STATE.current(s)["id"]}
    append_jsonl(_dk(root) / "notes.jsonl", row)
    write(root)
    return {"noted": kind, "text": row["text"]}


def notes(root: Path) -> list:
    return read_jsonl(_dk(root) / "notes.jsonl")


# ------------------------------------------------------------------ facts

def _git(root: Path, *args) -> str:
    r = run(["git", *args], cwd=root, timeout=20)
    return r["out"].strip() if r["code"] == 0 else ""


def _dirty(root: Path) -> list:
    r = run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, timeout=20)
    out = r["out"] if r["code"] == 0 else ""          # not stripped: the first line's leading status column matters
    files = []
    for line in out.splitlines():
        p = line[3:].strip().strip('"')
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        if p and not p.startswith(".deckhand/") and p not in MANAGED:
            files.append(p)
    return files


def _last_failure(root: Path) -> dict | None:
    runs = read_jsonl(_dk(root) / "runs.jsonl")
    for i in range(len(runs) - 1, -1, -1):
        r = runs[i]
        if r.get("exit", 0) and not is_guard(r):
            cmd = r.get("cmd", "")
            if any(x.get("cmd") == cmd and not x.get("exit") for x in runs[i + 1:]):
                return None                             # the same command succeeded later: resolved
            out = r.get("out", "")
            line = next((l for l in out.splitlines() if re.search(r"(error|Error|ERR!|failed|FAIL|Cannot|not found|refused|[A-Z_]{4,}:)", l)),
                        out.strip().splitlines()[-1] if out.strip() else "")
            from . import learn as LE
            known = [k.get("id") for k in LE.match(root, out)] if out else []
            return {"at": r.get("at"), "cmd": _short(cmd, 90), "error": _short(line, 120), "known_fix": known[:2]}
    return None


def _sessions(root: Path) -> dict:
    t = _dk(root) / "tryon"
    tryon = [j for j in (read_json(p, {}) for p in sorted((t / "sessions").glob("*.json"))) if j and j.get("state") == "open"] if (t / "sessions").is_dir() else []
    tune = [j for j in (read_json(p, {}) for p in sorted((t / "tune").glob("*.json"))) if j and j.get("state") == "open"] if (t / "tune").is_dir() else []
    drafts = [j for j in (read_json(p, {}) for p in sorted((t / "drafts").glob("*.json"))) if j and j.get("state") in ("pending", "rejected")] if (t / "drafts").is_dir() else []
    return {"tryon": [f"try-on {j['id']} on {j.get('slot')} in {j.get('file')} ({len(j.get('variants', []))} variants, showing {j.get('shown')})" for j in tryon],
            "tune": [f"tune {j['id']} on {j.get('file')}" for j in tune],
            "drafts": [f"AI draft {j['id']} for {j.get('slot') or (j.get('request') or {}).get('slot', '?')} ({j.get('state')})" for j in drafts]}


def _services(root: Path) -> list:
    """What the app needs running (a database…): a restarted machine or a long pause kills them silently (D5)."""
    try:
        from . import build as B
        info = read_json(_dk(root) / "dev.json", {}) or {}
        return [{"name": x["name"], "up": B.service_up(root, x, info), "port": x.get("port")} for x in B.services(root)]
    except Exception:  # noqa: BLE001
        return []


def _proof(root: Path, phase: str, s: dict) -> str:
    dk = _dk(root)
    b = read_json(dk / "brief.json", {}) or {}
    if phase == "define":
        return _short(f"{b.get('shape') or '?'} · {b.get('business') or ''}", 60)
    if phase == "research":
        return f"{len((read_json(dk / 'research.json', {}) or {}).get('competitors', []))} competitors"
    if phase == "plan":
        return f"{len((read_json(dk / 'sitemap.json', {}) or {}).get('pages', []))} pages, lint 0 errors"
    if phase == "build":
        base = s.get("base") or {}
        return _short(f"{base.get('kind', '?')}{(' ' + base['name']) if base.get('name') else ''} · {(read_json(dk / 'dev.json', {}) or {}).get('url') or 'dev not started'}", 70)
    if phase == "brand":
        return "0 blocking leaks"
    if phase == "tryon":
        return "no open session"
    if phase == "review":
        v = read_json(dk / "verify.json", {}) or {}
        return f"verify {'green' if v.get('ok') else 'red'} {str(v.get('at', ''))[:10]}"
    if phase == "deploy":
        d = read_json(dk / "deploy.json", {}) or {}
        return _short(f"{d.get('url', '?')} · {str((d.get('last') or {}).get('commit', ''))[:7]}", 70)
    return ""


def safety_facts(root: Path) -> dict:
    """What the switch verdict needs, cheap enough for `dh next` to ask too."""
    ns = notes(root)
    return {"root": str(root), "dirty": _dirty(root), "failure": _last_failure(root),
            "last_note_at": max((n.get("ts") or _ts(n.get("at")) for n in ns), default=0.0)}


def gather(root: Path) -> dict | None:
    root = Path(root)
    try:
        s = STATE.load(root, required=False)
    except DhError:                                     # RUN_CORRUPT: the commands say so; the hook stays quiet
        return None
    if not s:
        return None
    from . import guide
    dk = _dk(root)
    cur = STATE.current(s)
    gate = STATE.blocking_gate(s)
    try:
        nxt = guide.next_step(root)
    except Exception as e:  # noqa: BLE001 — the resume must render even when a step cannot be computed
        nxt = {"do": [f"(dh next failed: {e})"]}
    short = lambda x: x.replace(guide.DH, "dh").replace(guide.TRYON, "tryon")  # noqa: E731
    ns = notes(root)
    last = {k: next((n for n in reversed(ns) if n["kind"] == k), None) for k in KINDS}
    if last["doing"] and last["doing"]["text"].lower() in ("done", "none", "-"):
        last["doing"] = None
    hist = read_jsonl(dk / "history.jsonl")
    events = [(h.get("at", ""), _event(h)) for h in hist] + [(n["at"], f"note {n['kind']}: {_short(n['text'], 70)}") for n in ns]
    events.sort(key=lambda e: e[0])
    seo = read_json(dk / "seo.json", None)
    from . import pending as PEND
    pend = PEND.summary(root)
    return {
        "name": s.get("name"), "mode": s.get("mode"), "path": s.get("path"),
        "client": (read_json(dk / "profile.json", {}) or {}).get("scope") == "client", "store": _store(root),
        "n": f"{STATE.PHASE_IDS.index(cur['id']) + 1}/{len(STATE.PHASES)}", "phase": cur["id"], "title": cur["title"], "gate": gate,
        "gate_what": STATE.GATES.get(gate) if gate else None,
        "next": [short(x) for x in (nxt.get("do") or [])[:3]], "read": nxt.get("read"),
        "done": [(p["id"], s["phases"][p["id"]].get("at", "")[:10], _proof(root, p["id"], s)) for p in STATE.PHASES if s["phases"][p["id"]]["status"] == "done"],
        "skipped": [p for p in STATE.PHASE_IDS if s["phases"][p]["status"] == "skipped"],
        "gates": [(g, v.get("at", "")[:10], v.get("by"), (f"owner: {v['quote']}" if v.get("quote") else v.get("note", "")))
                  for g, v in s.get("gates", {}).items() if v.get("status") == "passed"],
        "services": _services(root),
        "workflow": (nxt.get("workflow") or {}).get("line"),
        "suggest": nxt.get("suggest") or {"items": [], "more": 0},
        **safety_facts(root), "head": _git(root, "log", "-1", "--format=%h %s (%cr)"),
        "sessions": _sessions(root),
        "doing": last["doing"], "note_next": last["next"],
        "decisions": [n for n in reversed(ns) if n["kind"] == "decision"][:8],
        "pending": pend, "seo": seo and {"score": seo.get("score"), "blockers": len(seo.get("blockers", []))},
        "timeline": events[-8:],
        "files": [f for f in ("brief.json", "research.json", "sitemap.json", "PLAN.md", "copy.json", "SEO.md", "VERIFY.md") if (dk / f).exists()]
                 + [f for f in ("PENDING.md", "HANDOFF.md") if (root / f).exists()],
    }


def _event(h: dict) -> str:
    e = h.get("event")
    if e == "phase_done":
        return f"{h.get('phase')} done" + (" (FORCED: " + str(h.get("forced")) + ")" if h.get("forced") else "")
    if e == "gate":
        return f"gate {h.get('gate')} passed" + (f" — \"{_short(h.get('note'), 60)}\"" if h.get("note") else "")
    if e == "reopen":
        return f"reopened {h.get('phase')}: {_short(h.get('reason'), 60)}"
    if e == "phase_skip":
        return f"{h.get('phase')} skipped: {_short(h.get('reason'), 60)}"
    if e == "init":
        return f"project started ({h.get('mode')}, {h.get('path')})"
    return str(e)


def safe(st: dict, root: Path | None = None) -> tuple:
    """Nothing that exists only in the chat would be lost by starting over: computed, not felt."""
    why = []
    root = Path(root or st["root"])
    newest = 0.0
    for f in st["dirty"]:
        try:
            newest = max(newest, (root / f).stat().st_mtime)
        except OSError:
            pass
    if st["dirty"] and newest > st["last_note_at"]:
        why.append(f"{len(st['dirty'])} changed file(s) not described since the last note — `dh note doing \"what you were changing and why\"` (or commit)")
    f = st["failure"]
    if f and not f["known_fix"] and _ts(f["at"]) > st["last_note_at"]:
        why.append(f"the last failure ({f['cmd']}) is explained nowhere — `dh note doing \"…\"` with what you found, or fix it")
    return (not why, why)


# ------------------------------------------------------------------ render / write

def render(st: dict) -> str:
    ok, why = safe(st)
    L = [f"# RESUME — {st['name']}",
         f"_Generated by deckhand after every `dh` command from the project's files (not a recap). Local only. {now()}_", "",
         f"**SAFE TO START A FRESH SESSION: {'YES' if ok else 'NO'}**" + ("" if ok else " — " + " · ".join(why)), "",
         f"- dh = `{_dh()}` · project: `{st['root']}` · skill: `{SKILL}`",
         f"- Stage: {st['n']} **{st['phase']}** — {st['title']} · mode {st['mode']} · path {st['path']}"
         + (" · **for a client**: `dh profile set`/`dh vault set` write to this project's own layer (never another client's)" if st["client"] else "")
         + (f" · **waiting for the owner: {st['gate']}** ({st['gate_what']})" if st["gate"] else ""),
         f"- Settings and keys: {st['store']}",
         "- Next (exact, from `dh next`):"] + [f"  - `{x}`" for x in st["next"]]
    if st["read"]:
        rd = Path(st["read"])
        L.append(f"- Read only: `{rd.relative_to(SKILL).as_posix() if str(rd).startswith(str(SKILL)) else rd.as_posix()}` (inside the skill)")
    L += ["", "## Done (with proof)"]
    L += [f"- {p} {at} — {proof}" for p, at, proof in st["done"]] or ["- nothing yet"]
    if st["skipped"]:
        L.append(f"- skipped: {', '.join(st['skipped'])}")
    for g, at, by, n in st["gates"]:
        L.append(f"- gate {g} passed {at} by {by}" + (f": \"{_short(n, 80)}\"" if n else ""))
    if st["seo"]:
        L.append(f"- SEO {st['seo']['score'] if st['seo']['score'] is not None else '—'}/100, {st['seo']['blockers']} launch-breakers (.deckhand/SEO.md)")
    L += ["", "## In progress"]
    prog = []
    if st["doing"]:
        prog.append(f"- doing ({st['doing']['at'][:16].replace('T', ' ')}): {_short(st['doing']['text'], 160)}")
    if st["note_next"]:
        prog.append(f"- intended next ({st['note_next']['at'][:16].replace('T', ' ')}): {_short(st['note_next']['text'], 160)}")
    if st["dirty"]:
        prog.append(f"- uncommitted: {', '.join(st['dirty'][:8])}" + (f" (+{len(st['dirty']) - 8})" if len(st["dirty"]) > 8 else ""))
    for k in ("tryon", "tune", "drafts"):
        prog += [f"- open: {x} — the helper (`tryon serve`) does not survive a new session: restart it" if k == "tryon" else f"- open: {x}" for x in st["sessions"][k][:4]]
    down = [x for x in st.get("services") or [] if not x["up"]]
    if down:
        prog.append("- services DOWN: " + ", ".join(x["name"] + (f" (port {x['port']})" if x.get("port") else "") for x in down)
                    + " — `dh dev start` restarts them (it reuses what is up)")
    f = st["failure"]
    if f:
        prog.append(f"- last failure {f['at'][:16].replace('T', ' ')}: `{f['cmd']}` → {f['error']}" + (f" (known fix {', '.join(f['known_fix'])}: `dh learn match`)" if f["known_fix"] else ""))
    if st["head"]:
        prog.append(f"- last commit: {st['head']}")
    L += prog or ["- nothing"]
    L += ["", "## Owner decisions (latest first — honour them)"]
    L += [f"- {d['at'][:10]}: {_short(d['text'], 150)}" for d in st["decisions"]] or ["- none recorded (`dh note decision \"…\"` the moment one is made)"]
    L += ["", f"## Waiting on the owner — {st['pending']['open']} open (end every report with these)"]
    L += [f"- {i.get('id', '')} {_short(i['item'], 120)}".replace("-  ", "- ") + (f" · {i['age_days']} d" if i.get("age_days") is not None else "")
          + (" · yours, all projects" if i.get("from") == "machine" else "") for i in st["pending"]["items"][:8]] or ["- nothing"]
    if st["pending"].get("deferred"):
        L.append(f"- (+{st['pending']['deferred']} deferred until their trigger — `dh pending list --all`)")
    from . import suggest as SUG
    sug = st.get("suggest") or {}
    if sug.get("items"):
        L += ["", "## Next (optional — by importance; say these after the pending list)"]
        L += [f"- {x}" for x in SUG.lines(sug)]
        if sug.get("more"):
            L.append(f"- (+{sug['more']} more: `dh suggest`)")
    if st.get("workflow"):
        L += ["", f"`{st['workflow']}` — the last line of every report (`dh workflow todo` for the checklist)"]
    L += ["", "## Recent"]
    L += [f"- {at[:16].replace('T', ' ')} {e}" for at, e in st["timeline"]] or ["- —"]
    L += ["", "## Where to look (only if the step needs it)",
          "- " + " · ".join(f".deckhand/{f}" if not f.endswith(".md") or f in ("PLAN.md", "SEO.md", "VERIFY.md") else f for f in st["files"]),
          "- how the skill works: SKILL.md in the skill folder · full history: .deckhand/history.jsonl · commands run: .deckhand/runs.jsonl"]
    from .redact import scrub_text
    text = scrub_text("\n".join(L) + "\n")            # defence in depth: stored notes / pending text from before the scrubber existed
    if len(text) > BUDGET:                      # stay cheap: trim the oldest detail first, never the verdict or the next step
        text = text[: BUDGET - 80].rsplit("\n", 1)[0] + "\n- … (trimmed to stay under the cold-start budget; `dh resume` for the rest)\n"
    return text


def _dh() -> str:
    from . import guide
    return guide.DH


def _store(root: Path) -> str:
    """Where this project's settings and keys are written (`dh profile where`), in one line."""
    from . import profile as PROFILE
    b = PROFILE.binding(root)
    if b is None:
        return "not chosen yet (the first `dh profile set`/`dh vault set` keeps them in `.deckhand/`, then asks the owner once)"
    if not b["ok"]:
        return f"**BROKEN** — `.deckhand/layout.json` {b['problem']}: ask the owner, then `dh profile where --set here|machine|<folder>`"
    where = {"here": "`.deckhand/` (this project only)", "machine": "`~/.deckhand/` (shared by every project)"}.get(
        b["location"], f"`{b.get('dir')}` (this project only, outside it)")
    return where + ("" if b.get("chosen_by") == "owner" else " — default, the owner has not chosen") + " · `dh profile where`"


def write(root: Path) -> Path | None:
    st = gather(root)
    if not st:
        return None
    ensure_gitignore(root)                      # RESUME, notes, the project vault: this machine's only, never committed
    p = _dk(root) / "RESUME.md"
    text = render(st)
    body = lambda t: t.split("\n", 2)[2] if t.count("\n") > 2 else t  # noqa: E731 — the timestamp line alone is not a change
    if not p.exists() or body(p.read_text(encoding="utf-8")) != body(text):
        p.write_text(text, encoding="utf-8")
    return p


def resume(root: Path) -> dict:
    root = Path(root)
    st = gather(root)
    if not st:
        return {"state": "no project here", "do": [f"{_dh()} init --name <business> … (or --project <dir> for an existing one)"]}
    p = write(root)
    ok, why = safe(st, root)
    out = {"safe_to_switch": ok, "why": why, "file": str(p), "resume": p.read_text(encoding="utf-8")}
    hint = session_hint(root)
    if hint:
        out["session"] = hint
    return out


def session_hint(root: Path) -> dict | None:
    """Claude Code keeps the session log on disk: a long one means a diluted context — a fresh session is sharper."""
    from . import autopsy as AU
    d = AU.claude_dir_for(root)
    logs = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not logs:
        return None
    mb = logs[-1].stat().st_size / 1_000_000
    return {"log_mb": round(mb, 1),
            "advice": ("this session has been long: a fresh one will be sharper — everything needed is in .deckhand/RESUME.md"
                       if mb > 2 else "fine")}


# ------------------------------------------------------------------ check (re-prove, don't trust)

def check(root: Path, online: bool = False) -> dict:
    root = Path(root)
    st = gather(root)
    if not st:
        raise DhError("NO_RUN", "no project here")
    s = STATE.load(root)
    dk = _dk(root)
    from . import checks
    claims = []

    def claim(what, ok, detail="", level="drift"):
        claims.append({"claim": what, "ok": ok, "detail": detail, "level": level if not ok else "ok"})

    for p in ("define", "research", "plan", "brand", "tryon"):
        if s["phases"][p]["status"] == "done" and s["phases"][p].get("forced"):
            claim(f"{p} done", True, f"forced: {s['phases'][p]['forced']}")   # passed on purpose; its check stays red
        elif s["phases"][p]["status"] == "done":
            try:
                r = checks.run(p, root, s)
                claim(f"{p} done", r["ok"], "; ".join(r.get("why", [])[:3]))
            except Exception as e:  # noqa: BLE001
                claim(f"{p} done", False, f"check failed to run: {e}")
    g1 = s["gates"].get("G1", {})
    if g1.get("status") == "passed":
        edited = STATE.plan_drift(root, s)
        claim("the approved plan is the current plan", not edited, f"edited after G1 was passed: {', '.join(edited)} — show the owner" if edited else "")
    if s["phases"]["build"]["status"] == "done":
        url = (read_json(dk / "dev.json", {}) or {}).get("url")
        up = False
        if url:
            from .build import _answers
            up = _answers(url)
        claim("the app runs locally", up, f"{url or 'no dev URL'} does not answer — `dh dev start`", level="info")
    head = _git(root, "rev-parse", "HEAD")
    v = read_json(dk / "verify.json", None)
    if v and s["phases"]["review"]["status"] == "done":
        vc = v.get("commit")
        from .checks import verify_stale
        stale = verify_stale(root, v) if vc and head and vc != head else ""
        if stale:
            claim("verify still describes the code", False, f"{stale} — run `dh verify` again before shipping")
        else:
            later = [f for f in st["dirty"] if (root / f).exists() and (root / f).stat().st_mtime > _ts(v.get("at")) + 1]
            claim("verify still describes the code", bool(v.get("ok")) and not later,
                  f"{len(later)} file(s) edited since the last `dh verify` ({', '.join(later[:4])}) — run it again before shipping" if later
                  else "" if v.get("ok") else "the last verify was red")
    d = read_json(dk / "deploy.json", None)
    if d and (d.get("last") or {}).get("commit"):
        dc = d["last"]["commit"]
        claim("what is live is the current code", not head or dc == head,
              f"live {dc[:7]} ≠ HEAD {head[:7]} — `dh deploy ship` to publish (or it is intentional)" if head and dc != head else "", level="info")
        if online and d.get("url"):
            from .deploy import smoke
            sm = smoke(root, d["url"])
            claim("the live site answers", sm["ok"], sm.get("evidence", ""))
    ses = st["sessions"]
    if s["phases"]["tryon"]["status"] == "done" and (ses["tryon"] or ses["tune"]):
        claim("try-on is closed", False, "; ".join(ses["tryon"] + ses["tune"]))
    ok_switch, why = safe(st, root)
    claim("safe to start a fresh session", ok_switch, " · ".join(why), level="info")
    drift = [c for c in claims if not c["ok"] and c["level"] == "drift"]
    return {"ok": not drift, "claims": claims, "drift": len(drift), "safe_to_switch": ok_switch,
            "pending_open": st["pending"]["open"], "file": str(write(root))}


# ------------------------------------------------------------------ cold-start entry for any harness

def agent_entry(root: Path) -> dict:
    """A marked block in the project's AGENTS.md (read by Codex, Cursor, Hermes, Gemini…). A new CLAUDE.md imports
    AGENTS.md; an owner's existing CLAUDE.md gets the same block instead. Idempotent; an older block is replaced."""
    root = Path(root)
    block = "\n".join([BEGIN, "## This project is built with Deckhand",
                       "New session, any AI, no memory of this project? Before anything else:",
                       "1. Run `dh resume`. It prints where the project stands, what is done (with proof), what is in",
                       "   progress, the owner's decisions, what waits on the owner, and the exact next command.",
                       "   (`dh` = `~/.deckhand/bin/dh`, or `python3 <deckhand skill folder>/dh.py`; Windows: `py`.)",
                       "2. Do what `dh next` says; read only the reference it names.",
                       "3. Record every owner decision the moment it is made: `dh note decision \"…\"`. Before stopping,",
                       "   `dh resume` must say SAFE TO START A FRESH SESSION (else `dh note doing \"…\"`).",
                       "Local only, never committed: .deckhand/RESUME.md, notes, the project profile and vault.", END])
    changed = []
    mark = BEGIN.split(" —")[0]

    def upsert(f: Path) -> None:
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        if mark in text:
            new = re.sub(re.escape(mark) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
        else:
            new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n"
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(f.name)
    upsert(root / "AGENTS.md")
    for own in (".hermes.md", "HERMES.md"):          # Hermes loads ONE project file and these win over AGENTS.md
        if (root / own).exists():
            upsert(root / own)
    cl = root / "CLAUDE.md"
    ct = cl.read_text(encoding="utf-8") if cl.exists() else ""
    if not ct.strip():
        if "@AGENTS.md" not in ct:
            cl.write_text("@AGENTS.md\n", encoding="utf-8")
            changed.append("CLAUDE.md")
    elif "@AGENTS.md" not in ct:
        upsert(cl)               # the owner's own CLAUDE.md: add only our block, never import their whole AGENTS.md
    return {"written": changed}


def hook(stdin_text: str = "", start: Path | None = None) -> str:
    """Claude Code SessionStart hook: the resume as context, or nothing outside a deckhand project. Never fails."""
    try:
        cwd = Path(start or (json.loads(stdin_text) if stdin_text.strip() else {}).get("cwd") or os.getcwd())
        root = next((d for d in [cwd, *cwd.parents] if (d / ".deckhand" / "run.json").exists()), None)
        if not root:
            return ""
        from . import profile as PROFILE
        PROFILE.use_project(root)
        p = write(root)
        return ("Deckhand project detected. Where it stands — generated from its files, not from memory. "
                "Follow `dh next`; record owner decisions with `dh note decision`.\n\n" + p.read_text(encoding="utf-8")) if p else ""
    except Exception:  # noqa: BLE001 — a hook must never break the harness
        return ""


def install_hook(settings: Path | None = None) -> dict:
    """Add the SessionStart hook to Claude Code's user settings (merged, idempotent, other hooks kept)."""
    settings = Path(settings) if settings else Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    data = read_json(settings, None) if settings.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict) or not isinstance(data.get("hooks", {}).get("SessionStart", []), list):
        raise DhError("BAD_SETTINGS", f"{settings} is not valid Claude Code settings JSON — fix it first, nothing was changed")
    cmd = f"{_dh()} resume --hook"
    ss = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    for entry in ss:
        for h in entry.get("hooks", []):
            if "resume --hook" in h.get("command", "") and "dh" in h.get("command", ""):
                if h["command"] == cmd:
                    return {"installed": False, "already": True, "settings": str(settings), "command": cmd}
                h["command"] = cmd
                write_json(settings, data)
                return {"installed": True, "updated": True, "settings": str(settings), "command": cmd}
    ss.append({"matcher": "startup|resume|clear|compact", "hooks": [{"type": "command", "command": cmd}]})
    write_json(settings, data)
    return {"installed": True, "settings": str(settings), "command": cmd,
            "effect": "every Claude Code session (new, resumed, cleared, or compacted) in a deckhand project starts with its RESUME"}


def stdin_if_piped(wait: float = 2.0) -> str:
    """The hook's JSON on stdin — without ever hanging when a caller leaves stdin open and silent."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
    except (OSError, ValueError):
        return ""
    import threading
    got = []
    t = threading.Thread(target=lambda: got.append(sys.stdin.read()), daemon=True)
    t.start()
    t.join(wait)
    return got[0] if got else ""
