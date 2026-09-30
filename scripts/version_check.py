#!/usr/bin/env python3
"""version_check.py — every human-readable version claim must match: README badge ==
skills/deckhand/SKILL.md `version:` == the top CHANGELOG.md entry == the architecture atlas header == the first line of docs/releases/v<version>.md
(== --tag vX.Y.Z when given).
Exit 0 = consistent · 1 = mismatch · 2 = usage/IO error. Stdlib only."""
import argparse
import re
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--tag")
    a = ap.parse_args(argv)
    root = Path(a.repo)
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        skill = (root / "skills" / "deckhand" / "SKILL.md").read_text(encoding="utf-8")
        log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        atlas = (root / "docs" / "architecture-atlas.html").read_text(encoding="utf-8")
    except OSError as e:
        print(f"version_check: {e}", file=sys.stderr)
        return 2
    found = {
        "README badge": (re.search(r"badge/version-([0-9][^-]*)-", readme) or [None, None])[1],
        "SKILL.md": (re.search(r"^version:\s*([^\s]+)", skill, re.M) or [None, None])[1],
        "CHANGELOG top": (re.search(r"^## \[?v?([0-9][^\]\s]*)", log, re.M) or [None, None])[1],
    }
    v = found["SKILL.md"]
    try:
        first = (root / "docs" / "releases" / f"v{v}.md").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError, TypeError):
        first = ""
    found["atlas header"] = (re.search(r"system map · v([0-9][^\s<]*)", atlas) or [None, None])[1]
    found["release notes"] = v if re.search(rf"(?<![\d.])v?{re.escape(v or '?')}(?![\d.])", first) else None
    if a.tag:
        found["tag"] = a.tag.lstrip("v")
    vals = set(found.values())
    for k, v in found.items():
        print(f"{k:14} {v}")
    if None in vals or len(vals) != 1:
        print("VERSION MISMATCH")
        return 1
    print("VERSIONS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
