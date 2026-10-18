"""F5 (foundation audit 2026-10-06): on a client project the CLIENT approves, and the handoff transfers ownership.

Before: gates said "the owner" and HANDOFF.md read like the builder keeps everything. Now `dh next` names who gives the
go (the client, when the project is for one), the gate records it, and the handoff lists what moves to the client —
each as a PENDING item so nothing is forgotten.
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

from dhlib import guide, handoff, pending, state  # noqa: E402
from dhlib.util import write_json  # noqa: E402


class ClientProject(unittest.TestCase):
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

    def at_g1(self, for_):
        root = self.tmp / for_
        state.init(root, "Bakery", "phased", "scratch", for_)
        for ph in ("define", "research", "plan"):
            state.phase_done(root, ph, force_reason="test walk")
        return root

    def test_approver_follows_the_project(self):
        self.assertEqual(state.approver(self.at_g1("client")), "client")
        self.assertEqual(state.approver(self.at_g1("me")), "owner")
        mine = self.at_g1("me")
        write_json(mine / ".deckhand" / "brief.json", {"deliverable": "client"})
        self.assertEqual(state.approver(mine), "client")

    def test_dh_next_asks_the_client_and_the_gate_records_it(self):
        root = self.at_g1("client")
        out = guide.next_step(root)
        self.assertEqual(out["approver"], "client")
        self.assertIn("client", out["do"][0])
        state.gate_pass(root, "G1", quote="approved")
        self.assertEqual(state.load(root)["gates"]["G1"]["by"], "client")

    def test_own_project_wording_is_unchanged(self):
        out = guide.next_step(self.at_g1("me"))
        self.assertEqual(out["approver"], "owner")
        self.assertIn("owner", out["do"][0])

    def test_handoff_transfers_to_the_client(self):
        root = self.at_g1("client")
        handoff.write(root)
        text = (root / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("## Transfer to the client", text)
        open_ = " | ".join(i["what"] for i in pending.items(root / "PENDING.md") if i["open"]).lower()
        for word in ("repository", "domain", "server", "secrets"):
            self.assertIn(word, open_)
        handoff.write(root)                                   # twice: nothing doubled
        self.assertEqual(len([i for i in pending.items(root / "PENDING.md") if "Transfer" in i["what"]]), 4)

    def test_own_handoff_has_no_transfer(self):
        root = self.at_g1("me")
        handoff.write(root)
        self.assertNotIn("Transfer to the client", (root / "HANDOFF.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
