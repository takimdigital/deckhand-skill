"""F23: a stray package.json in the home folder (or above it) is never the project."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
from dhlib import util  # noqa: E402


class F23(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_F23_home_package_json_is_ignored(self):
        home = self.tmp / "h"
        work = home / "work" / "empty"
        work.mkdir(parents=True)
        (home / "package.json").write_text("{}", encoding="utf-8")
        os.chdir(work)
        with mock.patch("pathlib.Path.home", return_value=home):
            self.assertEqual(util.project_root(), work.resolve())

    def test_F23_a_run_json_in_home_is_ignored_too(self):
        home = self.tmp / "h"
        (home / ".deckhand").mkdir(parents=True)
        work = home / "w"
        work.mkdir()
        (home / ".deckhand" / "run.json").write_text("{}", encoding="utf-8")
        os.chdir(work)
        with mock.patch("pathlib.Path.home", return_value=home):
            self.assertEqual(util.project_root(), work.resolve())

    def test_F23_a_subfolder_of_a_real_app_still_finds_it(self):
        app = self.tmp / "app"
        (app / "src").mkdir(parents=True)
        (app / "package.json").write_text("{}", encoding="utf-8")
        os.chdir(app / "src")
        with mock.patch("pathlib.Path.home", return_value=self.tmp / "elsewhere"):
            self.assertEqual(util.project_root(), app.resolve())

    def test_F23_a_project_folder_that_is_home_itself_is_still_refused(self):
        home = self.tmp / "h"
        home.mkdir()
        (home / "package.json").write_text("{}", encoding="utf-8")
        os.chdir(home)
        with mock.patch("pathlib.Path.home", return_value=home):
            self.assertEqual(util.project_root(), home.resolve())      # falls back to cwd; nothing above or at home is "found"


if __name__ == "__main__":
    unittest.main()
