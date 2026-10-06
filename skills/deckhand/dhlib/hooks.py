"""HOOKS: deckhand guards its own records and feeds its learning loop from inside any agent harness.

  dh hook pre|post|start|stop --harness H      stdin = the harness's own hook JSON; raw output; exit 2 = block

Every harness Deckhand knows (Claude Code, Codex, Gemini CLI, Cursor, Hermes, OpenCode) can run a command around a tool
call. One policy serves them all; what differs — tool names, field names, how to say "block" or "here is context" —
is DATA (data/harness.json → `hooks`), so no harness tool name lives in this file.

  pre    a hand edit of deckhand's own records (run, history, verify, deploy) · a push that deploys before G4 ·
         a vault value written in clear                                                       → blocked, with the dh way
  post   every shell command and its result → .deckhand/runs.jsonl (scrubbed): `dh autopsy` and `dh learn` see the
         whole session, not only what went through `dh run`
  start  the project's RESUME as context (once per session)
  stop   unexplained edits or an unexplained failure → one reminder to `dh note` before the session ends

Outside a deckhand project, or on any error, a hook does nothing (fail open); only a guard decision blocks.
`dh harness install` writes these hooks into the harness's own configuration (dhlib/harness.py).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

RECORDS = r"\.deckhand[\\/](?P<rec>run\.json|history\.jsonl|verify\.json|deploy\.json)"
RECORD_PATH = re.compile(r"(^|[\\/])" + RECORDS + r"$")
SHELL_ONTO_RECORD = re.compile(r"(>>?\s*|\btee\s+(-a\s+)?|\bsed\s+-i\S*\s+.*?|\b(cp|mv)\s+\S+\s+|\brm\s+(-\S+\s+)*)\S*" + RECORDS)
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
GIT_PUSH = re.compile(r"(^|[;&|]\s*)git\s+(-\S+\s+)*push\b")
DH_CMD = re.compile(r"^\s*((py|python3?)(\.exe)?\s+\S*dh\.py|dh)(\s|$)")
NAG_EVERY = 600
RECORD_WHY = ("Deckhand: {f} is deckhand's own record — change it only through dh (dh phase done|skip, dh gate pass, "
              "dh reopen, dh verify, dh deploy). A hand edit would bypass the checks the owner relies on.")


def adapter(harness: str) -> dict:
    from .util import SKILL, read_json
    data = read_json(SKILL / "data" / "harness.json", {}) or {}
    return {**((data.get("unknown") or {}).get("hooks") or {}), **((data.get(harness) or {}).get("hooks") or {})}


def project_of(cwd) -> Path | None:
    cwd = Path(cwd)
    return next((d for d in [cwd, *cwd.parents] if (d / ".deckhand" / "run.json").is_file()), None)


def _first(d, keys: list):
    if not isinstance(d, dict):
        return ""
    return next((d[k] for k in keys if d.get(k) not in (None, "", [])), "")


def normalize(payload: dict, harness: str) -> dict:
    """Any harness's tool event → {tool, kind (shell|edit|other), command, paths, content, cwd}."""
    a = adapter(harness)
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input")
    if inp is None:
        inp = (payload.get("extra") or {}).get("args") or {}
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except ValueError:
            inp = {"command": inp}
    if not tool and payload.get("command"):              # shell-only events carry the command at the top level
        inp, tool = {"command": payload["command"]}, "\0shell"
    kinds = a.get("tools") or {}
    kind = "shell" if tool == "\0shell" else next((k for k, names in kinds.items() if tool in names), "other")
    f = a.get("fields") or {}
    command = str(_first(inp, f.get("command", ["command"])) or "")
    paths = [str(_first(inp, f.get("path", ["file_path", "path"])) or "")]
    content = [_first(inp, [k]) for k in f.get("content", ["content"])]
    if a.get("patch_paths") and kind == "edit":          # a patch tool names its files inside the patch text
        paths += PATCH_FILE.findall(command)
        content.append(command)
        command = ""
    return {"tool": tool, "kind": kind, "cwd": str(payload.get("cwd") or os.getcwd()), "command": command,
            "paths": [p.strip() for p in paths if p and p.strip()],
            "content": "\n".join(c if isinstance(c, str) else json.dumps(c) for c in content if c)}


def _g4_owed(root: Path) -> bool:
    from . import state as STATE
    from .util import read_json
    s = STATE.load(root, required=False) or {}
    d = read_json(root / ".deckhand" / "deploy.json", {}) or {}
    return bool(d.get("app")) and (s.get("gates") or {}).get("G4", {}).get("status") != "passed"


def decide(ev: dict, root: Path) -> str | None:
    """The reason to block this tool call, or None. Deterministic; reads files only."""
    if ev["kind"] == "edit":
        for p in ev["paths"]:
            m = RECORD_PATH.search(p.replace("\\", "/"))
            if m:
                return RECORD_WHY.format(f=".deckhand/" + m.group("rec"))
    if ev["kind"] == "shell":
        m = SHELL_ONTO_RECORD.search(ev["command"])
        if m:
            return RECORD_WHY.format(f=".deckhand/" + m.group("rec"))
        if GIT_PUSH.search(ev["command"]) and _g4_owed(root):
            return ("Deckhand: this push deploys (auto-deploy is wired in .deckhand/deploy.json) but gate G4 — going live — "
                    "is not passed. Show the owner, then: dh gate pass G4 --quote \"[their words]\"; ship with dh deploy ship.")
    if ev["kind"] in ("edit", "shell"):
        from .redact import secret_values
        text = ev["content"] + "\n" + ev["command"]
        if any(len(v) >= 8 and v in text for v in secret_values()):
            return ("Deckhand: this writes a vault secret in clear. Reference it by name (an environment variable, "
                    "dh vault set NAME), never its value.")
    return None


def _block(why: str, harness: str) -> tuple:
    out = adapter(harness).get("out") or {}
    if out.get("block") == "cursor":
        return 2, json.dumps({"permission": "deny", "user_message": why, "agent_message": why}), why
    return 2, json.dumps({"decision": "block", "reason": why}), why


def _pass(harness: str, event: str) -> tuple:
    p = (adapter(harness).get("out") or {}).get("pass")
    return (0, json.dumps(p), "") if p and event == "pre" else (0, "", "")


def _start(payload: dict, root: Path, harness: str) -> tuple:
    shape = (adapter(harness).get("out") or {}).get("start", "text")
    if shape == "none" or (payload.get("extra") or {}).get("is_first_turn") is False:
        return 0, "", ""                                   # Hermes fires this every turn: the resume goes in once
    from . import resume as RESUME
    text = RESUME.hook(start=root)
    if not text:
        return 0, "", ""
    if shape == "context":
        return 0, json.dumps({"context": text}), ""
    if shape == "hso":
        return 0, json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}), ""
    if shape == "cursor":
        return 0, json.dumps({"additional_context": text}), ""
    return 0, text, ""


def _exit_of(payload: dict) -> int:
    resp = payload.get("tool_response")
    if resp is None and "tool_output" in payload:
        resp = payload["tool_output"]
    if resp is None:
        resp = (payload.get("extra") or {})
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except ValueError:
            return 0
    if not isinstance(resp, dict):
        return 0
    for k in ("exit_code", "exitCode", "returncode", "code"):
        if isinstance(resp.get(k), int):
            return resp[k]
    return 1 if resp.get("status") == "error" or resp.get("error") else 0


def _output_of(payload: dict) -> str:
    for v in (payload.get("tool_response"), payload.get("tool_output"), (payload.get("extra") or {}).get("result")):
        if v:
            return v if isinstance(v, str) else json.dumps(v)
    return ""


def _post(ev: dict, payload: dict, root: Path) -> tuple:
    cmd = ev["command"].strip()
    if ev["kind"] != "shell" or not cmd or DH_CMD.match(cmd):
        return 0, "", ""                                   # dh logs its own calls
    from . import learn as LEARN
    LEARN.log_run(root, cmd, _exit_of(payload), _output_of(payload)[-4000:])      # scrubbed by log_run
    return 0, "", ""


def _stop(payload: dict, root: Path, harness: str) -> tuple:
    if payload.get("stop_hook_active") or (payload.get("loop_count") or 0) > 0:
        return 0, "", ""                                   # never a loop: one reminder per stop
    from . import resume as RESUME
    ok, why = RESUME.safe(RESUME.safety_facts(root))
    mark = root / ".deckhand" / "stop-nag"
    if ok or (mark.exists() and time.time() - mark.stat().st_mtime < NAG_EVERY):
        return 0, "", ""
    mark.write_text(str(time.time()), encoding="utf-8")
    msg = "Deckhand: before this session ends, " + "; ".join(why) + " — so nothing lives only in this chat."
    shape = (adapter(harness).get("out") or {}).get("stop", "exit2")
    if shape == "none":
        return 0, "", ""
    if shape == "cursor":
        return 0, json.dumps({"followup_message": msg}), ""
    return _block(msg, harness)


def handle(event: str, stdin_text: str, harness: str | None = None) -> tuple:
    """(exit code, stdout, stderr) for one hook call. Never raises."""
    try:
        if not harness:
            from .workflow import harness as detect
            harness = detect()
        payload = json.loads(stdin_text) if (stdin_text or "").strip() else {}
        if not isinstance(payload, dict):
            return 0, "", ""
        root = project_of(payload.get("cwd") or os.getcwd())
        if not root:
            return _pass(harness, event)
        from . import profile as PROFILE
        PROFILE.use_project(root)
        if event == "start":
            return _start(payload, root, harness)
        ev = normalize(payload, harness)
        if event == "pre":
            why = decide(ev, root)
            return _block(why, harness) if why else _pass(harness, event)
        if event == "post":
            return _post(ev, payload, root)
        if event == "stop":
            return _stop(payload, root, harness)
    except Exception:  # noqa: BLE001 — a hook must never break the harness
        pass
    return _pass(harness or "unknown", event)
