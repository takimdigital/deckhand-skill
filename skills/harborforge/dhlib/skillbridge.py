"""SKILL BRIDGE: the agent skills already installed that make the current phase better — named by `dh next`.

Agent Skills (a folder with a SKILL.md) are loaded by every major harness. Which skill helps which phase is DATA
(data/skills.json). Only skills found on this machine are named (at most four, with why), plus how the current harness
loads one (data/harness.json → skill_load). Reading only: a missing or unreadable folder is skipped, never an error.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .util import DATA, read_json

MAX = 4
NAME_RX = re.compile(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.M)


def _home() -> Path:
    return Path(os.environ.get("DH_HARNESS_HOME") or Path.home())


def roots(project: Path | None = None) -> list:
    """Where harnesses keep skills: the user's folders, the active Hermes profile, and the project's own."""
    h = _home()
    out = [h / ".claude" / "skills", h / ".codex" / "skills", h / ".agents" / "skills", h / ".cursor" / "skills",
           h / ".gemini" / "skills", h / ".config" / "opencode" / "skills", h / ".hermes" / "skills"]
    if os.environ.get("HERMES_HOME"):
        out.insert(0, Path(os.environ["HERMES_HOME"]) / "skills")
    if project:
        out += [Path(project) / ".claude" / "skills", Path(project) / ".agents" / "skills", Path(project) / ".opencode" / "skills"]
    return out


def installed(project: Path | None = None) -> dict:
    """{skill name: path to its SKILL.md} — up to three folder levels deep (Hermes groups skills by category)."""
    found = {}
    for base in roots(project):
        if not base.is_dir():
            continue
        for pattern in ("*/SKILL.md", "*/*/SKILL.md", "*/*/*/SKILL.md"):
            for f in base.glob(pattern):
                try:
                    m = NAME_RX.search(f.read_text(encoding="utf-8", errors="replace")[:2000])
                except OSError:
                    continue
                found.setdefault((m.group(1).strip() if m else f.parent.name), str(f))
    return found


def for_phase(project: Path | None, phase: str) -> list:
    rows = ((read_json(DATA / "skills.json", {}) or {}).get("phases") or {}).get(phase) or []
    have = installed(project)
    return [{"name": r["name"], "why": r["why"], "path": have[r["name"]]} for r in rows if r.get("name") in have][:MAX]
