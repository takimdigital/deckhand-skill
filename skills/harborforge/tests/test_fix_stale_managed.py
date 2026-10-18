"""verify_stale must ignore the files deckhand writes itself: `dh verify` adds SEO owner items to PENDING.md, and that
must not make the verify it just wrote look stale (the real deploy of the journey site was refused by exactly this)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402

from dhlib import checks  # noqa: E402


def git(root, *a):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@l", "-c", "user.name=t", *a],
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


class StaleIgnoresManagedFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        git(self.root, "init", "-q")
        (self.root / "app.txt").write_text("code\n", encoding="utf-8")
        (self.root / "PENDING.md").write_text("# PENDING\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "c1")
        self.c1 = git(self.root, "rev-parse", "HEAD")

    def tearDown(self):
        tmpclean.rmtree(self.root)

    def commit(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "c2")

    def test_a_pending_md_the_verify_itself_wrote_is_not_a_change(self):
        self.commit("PENDING.md", "# PENDING\n- [ ] P-SEO-x\n")
        self.assertEqual(checks.verify_stale(self.root, {"commit": self.c1}), "")

    def test_handoff_and_resume_are_managed_too(self):
        self.commit("HANDOFF.md", "# HANDOFF\n")
        self.commit("RESUME.md", "# RESUME\n")
        self.assertEqual(checks.verify_stale(self.root, {"commit": self.c1}), "")

    def test_a_code_change_is_still_stale(self):
        self.commit("app.txt", "changed code\n")
        self.assertIn("app.txt", checks.verify_stale(self.root, {"commit": self.c1}))

    def test_code_plus_a_managed_file_names_only_the_code(self):
        self.commit("PENDING.md", "# PENDING\nmore\n")
        self.commit("app.txt", "changed code\n")
        msg = checks.verify_stale(self.root, {"commit": self.c1})
        self.assertIn("app.txt", msg)
        self.assertNotIn("PENDING.md", msg)


if __name__ == "__main__":
    unittest.main()
