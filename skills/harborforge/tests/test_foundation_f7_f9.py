"""F7–F9 (foundation audit 2026-10-06): the small ones.

F7  path=mine means the owner's own bases: `dh next` and `dh pool query --mine` rank only those.
F8  the owner approves the plan with the reason for it: PLAN.md opens with what the research found.
F9  a missing brand name is flagged at define (rebrand runs at the end of build and needs it) — a warning, not a block:
    it is an owner fact, and a workflow extracted from a run carries none.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import checks, guide, plan, pool, state  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import write_json  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)


class MineMeansMine(Base):
    def setUp(self):
        super().setUp()
        write_json(pool.personal_path(), {"templates": [{"name": "bakery-base", "path": str(self.tmp / "b"), "license": "owner",
                                                         "shape": ["leadgen"], "features": [], "stack": {"framework": "next"}}]})

    def test_query_can_rank_only_the_owners_bases(self):
        q = pool.query({"shape": "leadgen"}, source="mine")
        self.assertEqual({t["source"] for t in q["top"]}, {"mine"})
        self.assertGreater(pool.query({"shape": "leadgen"})["considered"], q["considered"])

    def test_cli_pool_query_mine(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["pool", "query", "--mine"])
        self.assertEqual({t["source"] for t in json.loads(buf.getvalue())["top"]}, {"mine"})

    def test_dh_next_on_path_mine_shows_only_his_bases(self):
        root = self.tmp / "p"
        state.init(root, "Bakery", "phased", "mine")
        write_json(root / ".deckhand" / "brief.json", {"shape": "leadgen", "business": "bread"})
        for ph in ("define", "research"):
            state.phase_done(root, ph, force_reason="test walk")
        out = guide.next_step(root)
        self.assertEqual([t["name"] for t in out["pool_top"]], ["bakery-base"])
        self.assertIn("pool query --mine", " ".join(out["do"]))


class PlanShowsTheResearch(Base):
    def test_plan_md_opens_with_what_research_found(self):
        root = self.tmp / "p"
        state.init(root, "Bakery", "phased", "scratch")
        plan.init(root)
        write_json(root / ".deckhand" / "research.json", {
            "competitors": [{"name": "Crumb & Co", "url": "https://crumb.test", "gaps": ["no online ordering"]}],
            "conversion": {"plays": ["first loaf free"]}, "features": {"now": ["ordering"]}})
        plan.render(root)
        text = (root / ".deckhand" / "PLAN.md").read_text(encoding="utf-8")
        self.assertIn("## What the research found", text)
        self.assertIn("Crumb & Co", text)
        self.assertIn("no online ordering", text)
        self.assertIn("first loaf free", text)
        self.assertLess(text.index("What the research found"), text.index("```mermaid"))

    def test_no_research_no_box(self):
        root = self.tmp / "q"
        state.init(root, "Bakery", "phased", "scratch")
        plan.init(root)
        (root / ".deckhand" / "research.json").unlink()
        plan.render(root)
        self.assertNotIn("What the research found", (root / ".deckhand" / "PLAN.md").read_text(encoding="utf-8"))


class BrandNameAtDefine(Base):
    def test_define_warns_when_the_brand_name_is_missing(self):
        root = self.tmp / "p"
        state.init(root, "Bakery", "phased", "pool")
        brief = {"business": "bread", "shape": "leadgen", "languages": ["en"], "audience": "locals"}
        write_json(root / ".deckhand" / "brief.json", brief)
        r = checks.define(root, state.load(root))
        self.assertTrue(r["ok"])                              # an owner fact: never blocks (a workflow carries none)
        self.assertIn("brand.name", " ".join(r["warnings"]))
        write_json(root / ".deckhand" / "brief.json", {**brief, "brand": {"name": "Golden Crust"}})
        self.assertNotIn("warnings", checks.define(root, state.load(root)))


if __name__ == "__main__":
    unittest.main()
