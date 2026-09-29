"""F10: clone keeps the base's NOTICE byte-exact and never commits what the base's git ignored."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
from dhlib import build  # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class F10(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        parent = self.tmp / "parent"
        self.src = parent / "src1"
        self.src.mkdir(parents=True)
        git(parent, "init", "-q")
        (parent / ".gitignore").write_text("*.sql\n", encoding="utf-8")                 # a parent repo's rule
        (self.src / ".gitignore").write_text("*.log\n", encoding="utf-8")              # the base's own rule
        for n, t in (("NOTICE", "Upstream MIT notice - Copyright (c) Upstream\n"), ("package.json", '{"name":"s"}'),
                     ("keep.js", "1"), ("junk.log", "x"), ("dump.sql", "x")):
            (self.src / n).write_text(t, encoding="utf-8")
        self.row = {"name": "src1", "path": str(self.src), "license": "MIT", "source": "pool"}

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def clone(self):
        with mock.patch.object(build.POOL, "rows", return_value=[self.row]):
            return build.clone("src1", self.tmp / "dest", do_install=False)

    def test_F10_notice_kept_and_ignored_files_never_copied(self):
        self.clone()
        dest = self.tmp / "dest"
        self.assertEqual((dest / "NOTICE").read_bytes(), (self.src / "NOTICE").read_bytes())
        tracked = set(git(dest, "ls-files").stdout.split())
        self.assertIn("keep.js", tracked)
        self.assertNotIn("junk.log", tracked)
        self.assertNotIn("dump.sql", tracked)
        self.assertFalse((dest / "junk.log").exists())

    def test_F10_a_base_outside_any_repo_still_honours_its_own_gitignore(self):
        lone = self.tmp / "lone"
        lone.mkdir()
        (lone / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
        (lone / "build").mkdir()
        for n, t in (("package.json", "{}"), ("a.js", "1"), ("x.log", "x"), ("build/out.js", "x")):
            (lone / n).write_text(t, encoding="utf-8")
        self.row = {"name": "src1", "path": str(lone), "license": "MIT", "source": "pool"}
        self.clone()
        tracked = set(git(self.tmp / "dest", "ls-files").stdout.split())
        self.assertIn("a.js", tracked)
        self.assertFalse({"x.log", "build/out.js"} & tracked, tracked)

    def test_F10_a_base_without_a_licence_file_is_not_said_to_keep_one(self):
        (self.src / "NOTICE").unlink()
        out = self.clone()
        text = (self.tmp / "dest" / "NOTICE").read_text(encoding="utf-8")
        self.assertNotIn("kept in LICENSE", text)
        self.assertIn("licence_warning", out)


if __name__ == "__main__":
    unittest.main()
