"""LEARN: a failure is paid for once.

  dh run -- <cmd>        run anything; on failure the output is matched against known lessons and the
                          proven fix is printed at once (no re-debugging), and the failure is recorded
  dh learn add           a fixed failure -> a lesson {signature regex, cause, fix, command, rung}
  dh learn from-failure  the same, with the signature derived from the last recorded failure
  dh learn preflight --phase P   the lessons for phase P (+ this stack), max 8 lines — `dh next` includes them
  dh learn promote       lessons seen twice -> a patch proposal for the skill itself (fix ladder:
                          eliminate > preflight > reorder > gate > pitfall). Pitfalls are debt.
Global lessons live in ~/.deckhand/lessons.jsonl (every project benefits); project ones in .deckhand/.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .util import DATA, DhError, append_jsonl, home, now, read_jsonl, redact, run
from . import state as STATE

RUNGS = ("eliminate", "preflight", "reorder", "gate", "pitfall")


def _paths(root: Path | None):
    out = [DATA / "lessons.seed.jsonl", home() / "lessons.jsonl"]
    if root:
        out.append(Path(root) / ".deckhand" / "lessons.jsonl")
    return out


def all_lessons(root: Path | None = None) -> list:
    merged = {}
    for p in _paths(root):
        for l in read_jsonl(p):
            key = l.get("id") or l.get("signature")
            if key in merged:
                merged[key]["seen"] = max(merged[key].get("seen", 1), l.get("seen", 1))
                merged[key].update({k: v for k, v in l.items() if k not in ("seen",)})
            else:
                merged[key] = dict(l)
    return list(merged.values())


def _stack(root: Path | None) -> set:
    tags = set()
    import platform
    tags.add(platform.system().lower())            # windows | linux | darwin
    if root:
        s = STATE.load(root, required=False) or {}
        st = ((s.get("base") or {}).get("stack") or {})
        tags |= {str(v).lower() for v in st.values() if isinstance(v, str)}
        pj = Path(root) / "package.json"
        if pj.exists():
            t = pj.read_text(encoding="utf-8")
            for k in ("next", "vite", "prisma", "drizzle", "better-auth", "tailwindcss", "pnpm"):
                if f'"{k}' in t:
                    tags.add(k)
    return tags


def add(root: Path | None, phase: str, symptom: str, cause: str, fix: str, signature: str | None = None,
        command: str | None = None, rung: str = "pitfall", scope: str = "global", stack: list | None = None,
        extra: dict | None = None) -> dict:
    if rung not in RUNGS:
        raise DhError("BAD_RUNG", f"rung: {RUNGS}")
    sig = signature or re.escape(symptom.strip()[:120])
    try:
        re.compile(sig)
    except re.error as e:
        raise DhError("BAD_SIGNATURE", f"signature is not a valid regex: {e}")
    target = (home() / "lessons.jsonl") if scope == "global" or not root else Path(root) / ".deckhand" / "lessons.jsonl"
    existing = read_jsonl(target)
    for l in existing:
        if l.get("signature") == sig:
            l["seen"] = l.get("seen", 1) + 1
            l["last_seen"] = now()
            l.update({"fix": fix, "cause": cause, **({"command": command} if command else {}), **(extra or {})})
            if RUNGS.index(rung) < RUNGS.index(l.get("rung", "pitfall")):
                l["rung"] = rung                                   # evidence can only move a lesson UP the ladder
            target.write_text("".join(__import__("json").dumps(x, ensure_ascii=False) + "\n" for x in existing), encoding="utf-8")
            return {"updated": l["id"], "seen": l["seen"]}
    n = len(all_lessons(root)) + 1
    lesson = {"id": f"L-{n:04d}", "at": now(), "phase": phase, "signature": sig, "symptom": symptom, "cause": cause, "fix": fix,
              **({"command": command} if command else {}), "rung": rung, "stack": stack or [], "seen": 1, "last_seen": now(), **(extra or {})}
    append_jsonl(target, lesson)
    return {"added": lesson["id"], "to": str(target)}


def match(root: Path | None, text: str) -> list:
    hits = []
    for l in all_lessons(root):
        try:
            if re.search(l["signature"], text, re.I | re.M):
                hits.append({k: l.get(k) for k in ("id", "symptom", "cause", "fix", "command", "seen", "recipe", "auto") if l.get(k) is not None})
        except re.error:
            continue
    return sorted(hits, key=lambda h: -(h.get("seen") or 1))


def preflight(root: Path | None, phase: str, limit: int = 8) -> list:
    tags = _stack(root)
    out = []
    for l in all_lessons(root):
        if l.get("phase") != phase:
            continue
        st = set(x.lower() for x in l.get("stack") or [])
        if st and not (st & tags):
            continue
        out.append(l)
    out.sort(key=lambda l: (-(l.get("seen") or 1), l.get("id", "")))
    return [f"[{l['id']} ×{l.get('seen', 1)}] {l['symptom']} → {l['fix']}" + (f"  ⟶ `{l['command']}`" if l.get("command") else "")
            + ("  (auto: dh run --fix replays it)" if l.get("auto") else "") for l in out[:limit]]


def secret_values() -> list:
    """Every secret value the owner stored (vault + legacy ops keyring): exact strings to redact."""
    from . import profile as PROFILE
    return list(PROFILE.vault_read().values()) + list(PROFILE.legacy_read().values())


def scrub(text: str) -> str:
    return redact(text or "", secret_values())


def log_run(root: Path | None, cmd: str, code: int, out: str = "", phase: str | None = None) -> None:
    """Every command, success or not, in .deckhand/runs.jsonl — the harness-neutral source `dh autopsy` reads.
    Credentials are redacted before anything touches the disk (the file is also gitignored by `dh init`)."""
    if not root or not (Path(root) / ".deckhand").is_dir():
        return
    append_jsonl(Path(root) / ".deckhand" / "runs.jsonl", {"at": now(), "cmd": scrub(cmd), "exit": code,
                                                           "out": scrub(out[-1500:] if code else out[-200:]),
                                                           **({"phase": phase} if phase else {})})


def resolve_dh(argv: list, root: Path | None) -> list:
    """`dh run -- dh …` or `dh run -- py dh.py …` runs in the project folder, where a bare `dh` / relative `dh.py`
    does not exist (D18): point it at this skill's own dh.py, with this interpreter."""
    import sys
    from .util import SKILL
    me = str(SKILL / "dh.py")
    if argv and argv[0] in ("dh", "dh.py"):
        return [sys.executable, me, *argv[1:]]
    if len(argv) > 1 and Path(argv[0]).name.lower() in ("py", "py.exe", "python", "python.exe", "python3", "python3.exe") \
            and Path(argv[1]).name == "dh.py":
        a1 = Path(argv[1])
        local = a1 if a1.is_absolute() else Path(root or ".") / a1       # relative to the PROJECT, never the process cwd
        if not local.is_file():
            return [argv[0], me, *argv[2:]]
    return argv


def run_cmd(root: Path | None, argv: list, phase: str | None = None, fix: bool = False) -> dict:
    if not argv:
        raise DhError("USAGE", "dh run -- <command …>")
    argv = resolve_dh(argv, root)
    r = run(argv, cwd=root, timeout=3600)
    log_run(root, r["cmd"], r["code"], (r["err"] + "\n" + r["out"]) if r["code"] else r["out"], phase)
    if r["code"] == 0:
        return {"ok": True, "cmd": scrub(r["cmd"]), "ms": r["ms"], "tail": scrub(r["out"][-600:])}
    tail = (r["err"] + "\n" + r["out"])[-4000:]
    known = match(root, tail)
    tail = scrub(tail)
    if root:
        s = STATE.load(root, required=False) or {}
        append_jsonl(Path(root) / ".deckhand" / "failures.jsonl", {"at": now(), "cmd": scrub(r["cmd"]), "code": r["code"],
                                                                     "phase": phase or (STATE.current(s)["id"] if s else None), "tail": tail[-2000:]})
    auto = next((k for k in known if k.get("auto") and k.get("recipe")), None)
    if fix and auto:
        # a recipe proven by a past session and made only of safe, repeatable commands: replay it, retry once
        steps = []
        for kind, step in auto["recipe"]:
            if kind != "run":
                continue
            rr = run(["bash", "-lc", step] if os.name != "nt" else ["cmd", "/c", step], cwd=root, timeout=1800)
            log_run(root, step, rr["code"], rr["err"] + rr["out"], phase)
            steps.append({"run": step, "exit": rr["code"]})
            if rr["code"] != 0:
                break
        again = run(argv, cwd=root, timeout=3600)
        log_run(root, again["cmd"], again["code"], (again["err"] + "\n" + again["out"]) if again["code"] else again["out"], phase)
        return {"ok": again["code"] == 0, "cmd": scrub(again["cmd"]), "code": again["code"], "fixed_by": auto["id"], "replayed": steps,
                "tail": scrub((again["err"] + "\n" + again["out"])[-1500:] if again["code"] else again["out"][-600:])}
    return {"ok": False, "cmd": scrub(r["cmd"]), "code": r["code"], "tail": tail[-1500:], "known_fixes": known,
            "next": (f"`dh run --fix -- …` replays the proven recipe of {auto['id']}" if auto else "apply the known fix") if known
            else "fix it, then `dh learn from-failure --fix \"…\" --cause \"…\"` (or `dh autopsy --apply` after the session) so it never costs tokens again"}


def _signature_from(tail: str) -> str:
    lines = [l.strip() for l in tail.splitlines() if l.strip()]
    pick = next((l for l in lines if re.search(r"(error|Error|ERR!|failed|Failed|EACCES|ENOENT|Cannot|not found|refused)", l)), lines[-1] if lines else "")
    pick = re.sub(r"(/[^\s:'\"]+)+", "PATH", pick)[:160]
    sig = re.escape(pick)
    sig = sig.replace("PATH", r"\S+")
    sig = re.sub(r"\d+", r"\\d+", sig)
    return sig


def from_failure(root: Path, fix: str, cause: str, rung: str = "pitfall", scope: str = "global", command: str | None = None) -> dict:
    fails = read_jsonl(Path(root) / ".deckhand" / "failures.jsonl")
    if not fails:
        raise DhError("NO_FAILURE", "no recorded failure (run commands through `dh run -- …`)")
    last = fails[-1]
    sig = _signature_from(last["tail"])
    symptom = re.sub(r"\\(.)", r"\1", sig)[:120]
    return add(root, last.get("phase") or "build", symptom, cause, fix, signature=sig, command=command, rung=rung, scope=scope)


def promote(root: Path | None) -> dict:
    """Lessons seen >= 2 become a patch proposal for the reference that owns their phase."""
    props = []
    out_dir = home() / "autopsy"
    for l in all_lessons(root):
        if (l.get("seen") or 1) < 2 or l.get("promoted") or str(l.get("id", "")).startswith("S-"):   # seeds are already built in
            continue
        ref = next((p["ref"] for p in STATE.PHASES if p["id"] == l.get("phase")), "references/30-build.md")
        rung = l.get("rung", "pitfall")
        suggestion = {
            "eliminate": "change the script/template/default so this path cannot happen (then delete the lesson)",
            "preflight": f"add a check to the phase's preflight in {ref}: detect `{l['symptom']}` before the point of no return",
            "reorder": f"move the correct step earlier in {ref} so it IS the path",
            "gate": f"make `dh phase done {l.get('phase')}` fail loudly on this condition",
            "pitfall": f"one line in {ref} §Traps, verbatim error + fix (counts as debt: aim higher next time)",
        }[rung]
        body = (f"# Promote {l['id']} (seen {l.get('seen')}×)\n\n- phase: {l.get('phase')}\n- symptom: `{l['symptom']}`\n- cause: {l['cause']}\n"
                f"- fix: {l['fix']}\n" + (f"- command: `{l['command']}`\n" if l.get("command") else "") +
                f"- rung: **{rung}** → {suggestion}\n- target: `{ref}`\n\nVerify: replay the failure against the new text/script — it must fail on the old state and pass on the new.\n")
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"PROMOTE-{l['id']}.md"
        p.write_text(body, encoding="utf-8")
        props.append({"lesson": l["id"], "proposal": str(p), "rung": rung, "target": ref})
    return {"proposals": props, "next": "apply each proposal to the skill (owner approves), bump CHANGELOG, then mark it promoted" if props else "nothing recurring yet"}
