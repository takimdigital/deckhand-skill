"""HARNESS: write deckhand's hooks into the agent harness's own configuration — and prove they work.

  dh harness detect                       which harness this is + which hook configs exist
  dh harness install [--harness H] [--dry]   merge `dh hook …` entries (idempotent; other hooks kept; old resume hook replaced)
  dh harness doctor  [--harness H]        each event installed? and a synthetic hand-edit of run.json → blocked (exit 2)?
  dh harness uninstall [--harness H]      remove only deckhand's entries

Where and how each harness is configured is DATA (data/harness.json → hooks.config): `json-hooks` (Claude Code, Codex,
Gemini CLI: {"hooks": {Event: [{"matcher", "hooks": [{"type": "command", "command"}]}]}}), `cursor-hooks`
({"version": 1, "hooks": {event: [{"command", "matcher"}]}}), `opencode-plugin` (a JS file that calls `dh hook`) and
`hermes-config` — config.yaml is never edited by a script: the block is printed for the owner to paste.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import DhError, SKILL, read_json, write_json

MARK = "dh.py"                                           # our entries call the skill's dh.py; nothing else does
OLD = "resume --hook"                                    # the SessionStart hook `dh resume --install-hook` used to write


def _dh() -> str:
    from .guide import DH
    return DH


def _hooks(h: str) -> dict:
    from .hooks import adapter
    a = adapter(h)
    if not a.get("config"):
        raise DhError("NO_HOOKS", f"no hook support recorded for harness '{h}' — known: claude-code, codex, gemini-cli, cursor, "
                      "hermes, opencode (dh harness install --harness NAME)")
    return a


def _home() -> Path:
    return Path(os.environ.get("DH_HARNESS_HOME") or Path.home())


def config_path(h: str) -> Path | None:
    c = _hooks(h)["config"]
    if c.get("env") and os.environ.get(c["env"]) and not os.environ.get("DH_HARNESS_HOME"):
        return Path(os.environ[c["env"]]) / c["file"]
    return _home() / c["path"][2:] if c.get("path", "").startswith("~/") else (Path(c["path"]) if c.get("path") else None)


def _command(h: str, ev: str) -> str:
    return f"{_dh()} hook {ev} --harness {h}"


def _ours(cmd: str) -> bool:
    return MARK in cmd and (" hook " in cmd or OLD in cmd)


def _strip(data: dict, kind: str) -> dict:
    """Remove deckhand's entries, keep everything else (and drop event lists that end up empty)."""
    hooks = data.get("hooks") or {}
    for ev in list(hooks):
        kept = []
        for e in hooks[ev]:
            if kind == "cursor-hooks":
                if not _ours(e.get("command", "")):
                    kept.append(e)
                continue
            inner = [x for x in e.get("hooks", []) if not _ours(x.get("command", ""))]
            if inner:
                kept.append({**e, "hooks": inner})
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    data["hooks"] = hooks
    return data


def _merged(h: str, data: dict) -> dict:
    c = _hooks(h)["config"]
    kind = c["kind"]
    data = _strip(data, kind)
    if kind == "cursor-hooks":
        data.setdefault("version", 1)
    for ev, name in c["events"].items():
        m = (c.get("matchers") or {}).get(ev)
        if kind == "cursor-hooks":
            data["hooks"].setdefault(name, []).append({"command": _command(h, ev), **({"matcher": m} if m else {}), "timeout": 30})
        else:
            data["hooks"].setdefault(name, []).append({**({"matcher": m} if m else {}),
                                                       "hooks": [{"type": "command", "command": _command(h, ev), "timeout": 30}]})
    return data


def _read(p: Path) -> dict:
    if not p.exists():
        return {}
    data = read_json(p, None, expect=dict)
    if data is None or not isinstance(data.get("hooks", {}), dict):
        raise DhError("BAD_SETTINGS", f"{p} is not valid JSON settings — fix it first; nothing was changed")
    return data


def _hermes_block(h: str) -> str:
    c = _hooks(h)["config"]
    L = ["hooks:"]
    for ev, name in c["events"].items():
        m = (c.get("matchers") or {}).get(ev)
        L += [f"  {name}:", f"    - command: '{_command(h, ev)}'"] + ([f"      matcher: \"{m}\""] if m else []) + ["      timeout: 30"]
    return "\n".join(L)


def _opencode_js(h: str) -> str:
    tpl = (SKILL / "templates" / "harness" / "opencode-deckhand.js").read_text(encoding="utf-8")
    return tpl.replace("__DH__", json.dumps(_dh())).replace("__HARNESS__", h)


def install(h: str, dry: bool = False) -> dict:
    a = _hooks(h)
    c = a["config"]
    if c["kind"] == "hermes-config":
        return {"harness": h, "written": False, "paste": _hermes_block(h),
                "how": "Hermes settings are never edited by a script: open them with `hermes config edit` and paste this block "
                       "(merge it into an existing `hooks:` key), then restart Hermes",
                "verify": "hermes hooks doctor   # then: dh harness doctor --harness hermes", "note": c.get("note")}
    p = config_path(h)
    if c["kind"] == "opencode-plugin":
        js = _opencode_js(h)
        if dry:
            return {"harness": h, "would_write": {str(p): js}}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(js, encoding="utf-8")
        return {"harness": h, "written": str(p), "events": list(c["events"].values())}
    data = _merged(h, _read(p))
    if dry:
        return {"harness": h, "would_write": {str(p): data}}
    write_json(p, data)
    return {"harness": h, "written": str(p), "events": list(c["events"].values()), **({"note": c["note"]} if c.get("note") else {}),
            "next": f"restart {h}, then dh harness doctor --harness {h}"}


def uninstall(h: str) -> dict:
    c = _hooks(h)["config"]
    if c["kind"] == "hermes-config":
        return {"harness": h, "how": "remove the deckhand lines (`dh.py\" hook`) from the hooks: block with `hermes config edit`"}
    p = config_path(h)
    if c["kind"] == "opencode-plugin":
        if p.exists() and MARK in p.read_text(encoding="utf-8"):
            p.unlink()
        return {"harness": h, "removed": str(p)}
    if not p.exists():
        return {"harness": h, "removed": None}
    data = _strip(_read(p), c["kind"])
    if not data["hooks"]:
        del data["hooks"]
    write_json(p, data)
    return {"harness": h, "removed": str(p)}


def _installed(h: str) -> dict:
    c = _hooks(h)["config"]
    if c["kind"] == "hermes-config":
        return {}
    p = config_path(h)
    if c["kind"] == "opencode-plugin":
        on = bool(p and p.exists() and MARK in p.read_text(encoding="utf-8"))
        return {name: {"installed": on} for name in c["events"].values()}
    data = _read(p) if p and p.exists() else {"hooks": {}}
    out = {}
    for ev, name in c["events"].items():
        entries = data.get("hooks", {}).get(name, [])
        cmds = [e.get("command", "") for e in entries] if c["kind"] == "cursor-hooks" else \
            [x.get("command", "") for e in entries for x in e.get("hooks", [])]
        out[name] = {"installed": any(f"hook {ev} --harness {h}" in x and MARK in x for x in cmds)}
    return out


def _guard_probe(h: str) -> dict:
    """A throwaway project + a hand edit of its run.json, sent through the real `dh hook pre` command."""
    from .hooks import adapter
    tool = ((adapter(h).get("tools") or {}).get("edit") or ["Write"])[0]
    field = ((adapter(h).get("fields") or {}).get("path") or ["file_path"])[0]
    with tempfile.TemporaryDirectory(prefix="dh-doctor-") as d:
        root = Path(d)
        (root / ".deckhand").mkdir()
        write_json(root / ".deckhand" / "run.json", {"phases": {}, "gates": {}})
        inp = {"command": f"*** Begin Patch\n*** Update File: .deckhand/run.json\n*** End Patch"} if adapter(h).get("patch_paths") \
            else {field: str(root / ".deckhand" / "run.json"), "content": "{}"}
        r = subprocess.run([sys.executable, str(SKILL / "dh.py"), "hook", "pre", "--harness", h],
                           input=json.dumps({"cwd": str(root), "tool_name": tool, "tool_input": inp}),
                           capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "PYTHONUTF8": "1"})
    return {"exit": r.returncode, "blocked": r.returncode == 2, "message": (r.stderr or r.stdout)[:200]}


def doctor(h: str) -> dict:
    c = _hooks(h)["config"]
    events = _installed(h)
    guard = _guard_probe(h)
    on = bool(events) and all(e["installed"] for e in events.values())
    ok = guard["blocked"] and (on or c["kind"] == "hermes-config")
    out = {"harness": h, "ok": ok, "config": str(config_path(h)) if config_path(h) else "config.yaml (hermes config edit)",
           "events": events, "guard": guard}
    if not on and c["kind"] != "hermes-config":
        out["fix"] = f"dh harness install --harness {h}   (then restart {h})"
    if c["kind"] == "hermes-config":
        out["verify"] = "hermes hooks doctor   # lists the hooks Hermes really loaded and their consent"
    return out


def detect() -> dict:
    from .workflow import harness
    h = harness()
    found = {}
    for name in ("claude-code", "codex", "gemini-cli", "cursor", "opencode"):
        p = config_path(name)
        found[name] = {"config": str(p), "exists": p.exists(), "deckhand_hooks": p.exists() and MARK in p.read_text(encoding="utf-8", errors="replace")}
    return {"harness": h, "configs": found, "next": f"dh harness install --harness {h if h != 'unknown' else '[name]'}"}
