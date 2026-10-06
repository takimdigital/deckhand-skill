"""F4 (foundation audit 2026-10-06): research asks what fits the shape of the business.

An internal tool has no competitors to beat and no visitors to convert: its research is who uses it, the jobs they do
and the tools they use today. Every other shape keeps the full evidence bar (3 competitors, conversion plays, verified
quotes). The rule lives in data/research.json (`by_shape`), not in code.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import checks, state  # noqa: E402
from dhlib.util import read_json, write_json  # noqa: E402


class ResearchByShape(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "p"
        state.init(self.root, "Ops", "phased", "scratch")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def check(self, shape, research):
        write_json(self.root / ".deckhand" / "brief.json", {"shape": shape})
        write_json(self.root / ".deckhand" / "research.json", research)
        return checks.research(self.root, state.load(self.root))

    INTERNAL = {"audience": {"primary": "dispatchers", "jobs_to_be_done": ["assign a job in under a minute"]},
                "current": {"tools": ["a shared spreadsheet", "WhatsApp group"]},
                "features": {"now": ["job board", "assign"]}}

    def test_internal_tool_passes_on_users_jobs_and_current_tools(self):
        r = self.check("internal", self.INTERNAL)
        self.assertTrue(r["ok"], r["why"])

    def test_internal_tool_still_needs_its_own_facts(self):
        r = self.check("internal", {"features": {"now": ["x"]}})
        self.assertFalse(r["ok"])
        txt = " ".join(r["why"])
        self.assertIn("audience.primary", txt)
        self.assertIn("current.tools", txt)
        self.assertNotIn("competitors", txt)

    def test_a_public_shape_keeps_the_full_bar(self):
        r = self.check("leadgen", self.INTERNAL)
        self.assertFalse(r["ok"])
        self.assertIn("competitors", " ".join(r["why"]))

    def test_the_rule_is_data(self):
        pol = read_json(SKILL / "data" / "research.json")
        self.assertEqual(pol["by_shape"]["internal"]["competitors"], 0)


if __name__ == "__main__":
    unittest.main()
