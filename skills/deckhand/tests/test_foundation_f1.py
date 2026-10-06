"""F1 (foundation audit 2026-10-06): auto mode never goes live on its own.

Auto mode lets G1–G3 pass themselves (a plan, a local app, a design are reversible). G4 publishes a public site and can
spend money: it is a real fork, so it waits for the owner's own words in every mode.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import guide, state  # noqa: E402
from dhlib.util import DhError, write_json  # noqa: E402


class AutoModeG4(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "p"
        state.init(self.root, "Bakery", "auto", "scratch")
        for ph in ("define", "research", "plan", "build", "brand", "tryon"):
            state.phase_done(self.root, ph, force_reason="test walk")
        write_json(self.root / ".deckhand" / "verify.json",
                   {"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "rows": []})
        self.assertTrue(state.phase_done(self.root, "review")["ok"])

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def test_g1_to_g3_passed_themselves_but_g4_waits(self):
        s = state.load(self.root)
        self.assertEqual([s["gates"][g]["status"] for g in ("G1", "G2", "G3")], ["passed"] * 3)
        self.assertEqual(s["gates"]["G4"]["status"], "pending")
        self.assertEqual(state.blocking_gate(s), "G4")

    def test_deploy_is_refused_until_the_owner_says_go(self):
        with self.assertRaises(DhError) as e:
            state.reached(state.load(self.root), "deploy")
        self.assertEqual(e.exception.code, "GATE_BLOCKED")
        state.gate_pass(self.root, "G4", quote="go live")
        state.reached(state.load(self.root), "deploy")          # no raise

    def test_dh_next_tells_the_agent_to_ask(self):
        out = guide.next_step(self.root)
        self.assertEqual(out.get("gate"), "G4")
        self.assertIn("gate pass G4", " ".join(out["do"]))

    def test_the_review_line_keeps_the_owner_wait_in_auto(self):
        lines = guide._fit(["dh phase done review  → owner says go live (G4)"], "auto", "scratch")
        self.assertIn("owner", lines[0])
        self.assertNotIn("passes by itself", lines[0])

    def test_the_cli_needs_a_quote_for_g4_in_auto(self):
        import io
        from contextlib import redirect_stdout
        from dhlib.cli import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["gate", "pass", "G4", "--project", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buf.getvalue())["code"], "NEED_QUOTE")


if __name__ == "__main__":
    unittest.main()
