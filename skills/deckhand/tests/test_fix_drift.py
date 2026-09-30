"""Drift after G1 (resume --check, dh next): the gate of an older run has no content hashes, so a fresh clone (new file
times) read as "edited after G1"; and nothing told the owner how to accept an edit they had seen."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402

from dhlib import guide, state  # noqa: E402
from dhlib.util import write_json  # noqa: E402


def git(root, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=root, env=env,
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


class Drift(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = {k: os.environ.get(k) for k in ("DECKHAND_HOME",)}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        self.root.mkdir()
        state.init(self.root, "Drift", "phased", "scratch")
        git(self.root, "init", "-q")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b"})
        write_json(self.root / ".deckhand" / "sitemap.json", {"pages": []})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "plan", date="2026-01-01T10:00:00Z")
        s = state.load(self.root)
        for p in state.PHASES[:state.PHASE_IDS.index("plan") + 1]:
            s["phases"][p["id"]] = {"status": "done"}
        s["gates"]["G1"] = {"status": "passed", "at": "2026-01-02T10:00:00Z", "by": "owner"}        # an older run: no plan_hashes
        state.save(self.root, s)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "G1 passed", date="2026-01-02T10:00:00Z")

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tmpclean.rmtree(self.tmp)

    def test_a_fresh_clone_of_an_older_run_is_no_drift(self):
        git(self.tmp, "clone", "-q", str(self.root), str(self.tmp / "clone"))             # every file gets a new mtime
        clone = self.tmp / "clone"
        s = state.load(clone)
        self.assertEqual(state.plan_drift(clone, s), [])

    def test_a_plan_edit_committed_after_the_gate_is_drift_in_the_clone_too(self):
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "seo": "added later"})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seo keywords", date="2026-01-03T10:00:00Z")
        git(self.tmp, "clone", "-q", str(self.root), str(self.tmp / "clone"))
        for where in (self.root, self.tmp / "clone"):
            self.assertEqual(state.plan_drift(where, state.load(where)), ["brief.json"], where)

    def test_the_drift_line_says_how_to_accept_or_undo_the_edit(self):
        write_json(self.root / ".deckhand" / "brief.json", {"business": "edited"})
        line = guide.next_step(self.root).get("drift", "")
        self.assertIn("brief.json", line)
        self.assertIn("gate pass G1", line)
        self.assertIn("reopen plan", line)

    def test_passing_g1_again_on_the_owners_words_accepts_the_edit(self):
        write_json(self.root / ".deckhand" / "brief.json", {"business": "edited"})
        self.assertEqual(state.plan_drift(self.root, state.load(self.root)), ["brief.json"])
        state.gate_pass(self.root, "G1", quote="looks good, go ahead")
        s = state.load(self.root)
        self.assertEqual(state.plan_drift(self.root, s), [])
        self.assertIn("brief.json", s["gates"]["G1"]["plan_hashes"])
        self.assertNotIn("drift", guide.next_step(self.root))


if __name__ == "__main__":
    unittest.main()
