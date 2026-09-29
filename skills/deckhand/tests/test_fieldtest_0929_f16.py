"""Field test 2026-09-29, findings that were left open: F16."""
import re
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))

from dhlib.cli import build_parser  # noqa: E402


class F16Navbar(unittest.TestCase):
    def test_F16_the_default_compose_starts_with_a_navbar(self):
        ap = build_parser()
        ns = ap.parse_args(["compose"])
        secs = [s.strip() for s in ns.sections.split(",")]
        self.assertEqual(secs[0], "navbar", secs)

    def test_F16_compose_mjs_default_matches_the_cli(self):
        src = (SKILL / "tryon" / "compose.mjs").read_text(encoding="utf-8")
        m = re.search(r"opt\('sections',\s*'([^']*)'\)", src)
        self.assertTrue(m)
        self.assertEqual(m.group(1).split(",")[0], "navbar")

    def test_F16_docs_and_next_hints_name_the_same_default(self):
        for rel in ("dhlib/build.py", "dhlib/guide.py", "references/30-build.md"):
            txt = (SKILL / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"--sections (\S+)", txt):
                if "hero" in m.group(1):
                    self.assertTrue(m.group(1).startswith("navbar,"), f"{rel}: {m.group(1)}")


if __name__ == "__main__":
    unittest.main()
