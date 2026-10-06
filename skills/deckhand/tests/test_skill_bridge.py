"""SKILL BRIDGE: `dh next` names the agent skills already installed that make the current phase better.

Agent Skills (SKILL.md) are an open format every major harness loads (Claude Code, Codex, Cursor, Gemini CLI, OpenCode,
Hermes). Which skill helps which phase is DATA (data/skills.json); only skills found on this machine are named, at most
four, each with why — and how THIS harness loads one (data/harness.json → skill_load).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import guide, skillbridge, state, workflow  # noqa: E402
from dhlib.util import read_json  # noqa: E402


def make_skill(base: Path, rel: str, name: str):
    d = base / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n# {name}\n", encoding="utf-8")


class Bridge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "DH_HARNESS_HOME", "HERMES_HOME")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "dhome")
        os.environ["DH_HARNESS_HOME"] = str(self.tmp / "home")
        os.environ["HERMES_HOME"] = str(self.tmp / "hermes")
        self.root = self.tmp / "p"
        state.init(self.root, "Bakery", "phased", "pool")

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tmpclean.rmtree(self.tmp)

    def to_brand(self):
        for ph in ("define", "research", "plan", "build"):
            state.phase_done(self.root, ph, force_reason="test walk")
            g = state.blocking_gate(state.load(self.root))
            if g:
                state.gate_pass(self.root, g, quote="ok go")

    def test_installed_finds_skills_in_every_known_place(self):
        make_skill(self.tmp / "hermes" / "skills", "creative/humanizer", "humanizer")
        make_skill(self.tmp / "home" / ".claude" / "skills", "design-md", "design-md")
        make_skill(self.root / ".agents" / "skills", "dogfood", "dogfood")
        got = skillbridge.installed(self.root)
        self.assertEqual(set(got), {"humanizer", "design-md", "dogfood"})
        self.assertTrue(got["humanizer"].endswith("SKILL.md"))

    def test_only_installed_skills_for_this_phase_are_named(self):
        make_skill(self.tmp / "hermes" / "skills", "creative/humanizer", "humanizer")
        make_skill(self.tmp / "hermes" / "skills", "software-development/dogfood", "dogfood")     # a review skill
        self.to_brand()
        out = guide.next_step(self.root)
        names = [s["name"] for s in out["skills"]["load"]]
        self.assertEqual(names, ["humanizer"])
        self.assertTrue(out["skills"]["load"][0]["why"])

    def test_nothing_installed_nothing_said(self):
        self.to_brand()
        self.assertNotIn("skills", guide.next_step(self.root))

    def test_how_to_load_follows_the_harness(self):
        make_skill(self.tmp / "hermes" / "skills", "creative/humanizer", "humanizer")
        self.to_brand()
        with mock.patch.object(workflow, "harness", return_value="hermes"):
            self.assertIn("skill_view", guide.next_step(self.root)["skills"]["how"])
        with mock.patch.object(workflow, "harness", return_value="cursor"):
            self.assertNotIn("skill_view", guide.next_step(self.root)["skills"]["how"])

    def test_at_most_four(self):
        for n in read_json(SKILL / "data" / "skills.json")["phases"]["review"]:
            make_skill(self.tmp / "hermes" / "skills", n["name"], n["name"])
        self.assertLessEqual(len(skillbridge.for_phase(self.root, "review")), 4)

    def test_the_map_is_data_and_every_phase_is_known(self):
        data = read_json(SKILL / "data" / "skills.json")
        self.assertLessEqual(set(data["phases"]), set(state.PHASE_IDS))
        for rows in data["phases"].values():
            for r in rows:
                self.assertTrue(r["name"] and r["why"], r)


if __name__ == "__main__":
    unittest.main()
