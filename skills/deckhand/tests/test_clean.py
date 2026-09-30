"""dh clean: dry run by default, strict name patterns, age filter, no links followed, read-only git objects, and the
autopsy temp copy leaving nothing behind. Every test works in its own fake temp root, never the real one."""
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import autopsy, clean as CLEAN  # noqa: E402
from dhlib.cli import main  # noqa: E402


def _force_rm(path):
    def fix(func, p, _):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def _make_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":                                       # a junction needs no privilege
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return r.returncode == 0
    return False


class CleanTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="dh-test-clean-"))
        self.addCleanup(_force_rm, self.base)
        self.temp = self.base / "tmp"
        self.temp.mkdir()
        self.proj_parent = self.base / "work"
        self.proj_parent.mkdir()

    def mk(self, name, mb=0, old=True, where=None, files=None):
        d = (where or self.temp) / name
        d.mkdir(parents=True)
        if mb:
            (d / "blob.bin").write_bytes(b"x" * int(mb * 1024 * 1024))
        for rel in files or []:
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
        if old:
            self.age(d)
        return d

    def age(self, d, hours=5):
        t = time.time() - hours * 3600
        for root, dirs, fs_ in os.walk(d):
            for n in dirs + fs_:
                os.utime(os.path.join(root, n), (t, t))
        os.utime(d, (t, t))

    def names(self, r):
        return sorted(Path(f["path"]).name for f in r["found"])

    def test_dry_run_lists_and_deletes_nothing(self):
        a = self.mk("dh-tryon-abc", mb=2)
        b = self.mk("cdp-chrome-xyz")
        r = CLEAN.clean(self.temp)
        self.assertFalse(r["applied"])
        self.assertEqual(r["next"], "dh clean --apply")
        self.assertEqual(self.names(r), ["cdp-chrome-xyz", "dh-tryon-abc"])
        self.assertTrue(a.exists() and b.exists())
        f = next(x for x in r["found"] if x["kind"] == "temp")
        self.assertEqual(set(f) & {"path", "kind", "mb", "age_hours"}, {"path", "kind", "mb", "age_hours"})
        self.assertGreaterEqual(f["age_hours"], 4.9)
        self.assertAlmostEqual(r["total_mb"], 2.0, delta=0.2)

    def test_apply_removes_old_matches_only(self):
        for n in ("dh-tryon-1", "dh-cache-2", "dh-lib-3", "dh-seo-4", "dh-seo-vite-5", "dh-fx-6", "dh-cb-7", "dh-fit-home-8", "dh-fit-site-9",
                  "dh-fitcheck-a", "dh-vet-fx-b", "dh-playground-c", "dh-scaffold-d", "dh-hermes-e", "dh-test-f", "cdp-chrome-g",
                  "puppeteer_dev_chrome_profile-h", "playwright_chromium_profile-i", "playwright_chromiumdev_profile-j"):
            self.mk(n)
        young = self.mk("dh-tryon-young", old=False)
        keep = [self.mk("my-project"), self.mk("dh-other-thing"), self.mk("chrome-profile-x"), self.mk("tmpabcd1234")]   # no marker: not ours
        r = CLEAN.clean(self.temp, apply=True)
        self.assertEqual(len(r["removed"]), 19)
        self.assertEqual(r["failed"], [])
        self.assertTrue(young.exists())
        self.assertEqual(r["skipped_young"], 1)
        for k in keep:
            self.assertTrue(k.exists(), k.name)
        self.assertEqual(sorted(p.name for p in self.temp.iterdir()), sorted(["dh-tryon-young", "my-project", "dh-other-thing", "chrome-profile-x", "tmpabcd1234"]))

    def test_older_than_flag(self):
        self.mk("dh-tryon-old")
        self.assertEqual(self.names(CLEAN.clean(self.temp, older_than=10)), [])
        self.assertEqual(self.names(CLEAN.clean(self.temp, older_than=1)), ["dh-tryon-old"])

    def test_python_tmp_only_when_clearly_ours(self):
        ours = self.mk("tmpab12cd34", files=["proj/.git/HEAD"])
        self.mk("tmpzz99yy88", files=["something.txt"])
        r = CLEAN.clean(self.temp, apply=True)
        self.assertEqual([Path(p).name for p in r["removed"]], ["tmpab12cd34"])
        self.assertFalse(ours.exists())
        self.assertTrue((self.temp / "tmpzz99yy88").exists())

    def test_name_match_outside_root_is_kept(self):
        outside = self.mk("dh-tryon-elsewhere", where=self.base)          # not directly in the temp root
        (self.temp / "deeper").mkdir()
        nested = self.mk("dh-tryon-nested", where=self.temp / "deeper")
        r = CLEAN.clean(self.temp, apply=True)
        self.assertEqual(r["found"], [])
        self.assertTrue(outside.exists() and nested.exists())

    def test_link_is_removed_but_never_followed(self):
        target = self.mk("precious", files=["keep.txt"], where=self.base)
        link = self.temp / "dh-tryon-link"
        if not _make_link(link, target):
            self.skipTest("cannot create a symlink or junction here")
        r = CLEAN.clean(self.temp, apply=True, older_than=0)
        self.assertEqual(len(r["found"]), 1)
        self.assertTrue(r["found"][0].get("link"))
        self.assertEqual(r["found"][0]["mb"], 0.0)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue((target / "keep.txt").exists(), "the link's target must survive")

    def test_link_inside_a_match_is_not_descended(self):
        target = self.mk("precious2", files=["keep.txt"], where=self.base)
        d = self.mk("dh-cache-x")
        if not _make_link(d / "inner", target):
            self.skipTest("cannot create a symlink or junction here")
        r = CLEAN.clean(self.temp, apply=True, older_than=0)          # (the fresh link makes the folder "young" otherwise)
        self.assertEqual(r["failed"], [])
        self.assertFalse(d.exists())
        self.assertTrue((target / "keep.txt").exists())

    def test_removes_read_only_git_objects(self):
        d = self.mk("dh-tryon-git", files=["proj/.git/objects/ab/cdef", "proj/.git/HEAD"])
        for f in (d / "proj" / ".git").rglob("*"):
            if f.is_file():
                os.chmod(f, stat.S_IREAD)
        r = CLEAN.clean(self.temp, apply=True, older_than=0)          # (the fresh link makes the folder "young" otherwise)
        self.assertEqual(r["failed"], [])
        self.assertFalse(d.exists())

    def test_reports_total_mb_and_freed(self):
        self.mk("dh-tryon-a", mb=3)
        self.mk("dh-cache-b", mb=2)
        r = CLEAN.clean(self.temp, apply=True)
        self.assertAlmostEqual(r["total_mb"], 5.0, delta=0.3)
        self.assertAlmostEqual(r["freed_mb"], 5.0, delta=0.3)

    def test_project_siblings(self):
        proj = self.proj_parent / "site"
        proj.mkdir()
        held = self.mk(".site.deckhand-hold", where=self.proj_parent)                    # empty hold: nothing stranded
        scaf = self.mk("dh-scaffold-site-abc123", mb=1, where=self.proj_parent)
        other = self.mk(".other.deckhand-hold", where=self.proj_parent, files=["x"])       # another project's
        self.mk("innocent", where=self.proj_parent)
        r = CLEAN.clean(self.temp, project=proj, apply=True)
        self.assertFalse(held.exists() or scaf.exists())
        self.assertTrue(other.exists() and (self.proj_parent / "innocent").exists())
        self.assertTrue(proj.exists())

    def test_stranded_hold_is_kept(self):
        proj = self.proj_parent / "site"
        proj.mkdir()
        held = self.mk(".site.deckhand-hold", where=self.proj_parent, files=[".deckhand/run.json"])
        r = CLEAN.clean(self.temp, project=proj, apply=True)
        self.assertTrue(held.exists())
        self.assertIn("holds Deckhand files", json.dumps(r["skipped"]))
        (proj / ".deckhand").mkdir()                                                       # the project has its own: safe to drop
        r = CLEAN.clean(self.temp, project=proj, apply=True)
        self.assertFalse(held.exists())

    def test_cli_dry_run_by_default_and_help(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--project", str(self.proj_parent), "clean", "--older-than", "1000000"])
        self.assertEqual(code, 0)
        j = json.loads(out.getvalue())
        self.assertTrue(j["ok"])
        self.assertFalse(j["applied"])
        r = subprocess.run([sys.executable, str(SKILL / "dh.py"), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("clean", r.stdout)

    def test_data_file_lists_the_patterns(self):
        cfg = json.loads((SKILL / "data" / "clean.json").read_text(encoding="utf-8"))
        for p in ("dh-tryon-", "dh-cache-", "dh-hermes-", "dh-scaffold-", "dh-test-"):
            self.assertIn(p, cfg["temp_prefixes"])
        self.assertEqual(cfg["min_age_hours"], 2)


class AutopsyCopyTest(unittest.TestCase):
    def test_db_copy_leaves_no_dh_hermes_folder(self):
        base = Path(tempfile.mkdtemp(prefix="dh-test-autopsy-"))
        self.addCleanup(_force_rm, base)
        tmp = base / "tmp"
        tmp.mkdir()
        db = base / "state.db"
        con = sqlite3.connect(db)
        con.execute("create table sessions (id text, started_at real, parent_session_id text)")
        con.execute("create table messages (id integer, session_id text, role text, content text, timestamp real)")
        con.execute("insert into sessions values ('s1', 1, null)")
        con.execute("insert into messages values (1, 's1', 'user', 'hi', 1)")
        con.commit()
        con.close()
        old = tempfile.tempdir
        tempfile.tempdir = str(tmp)
        try:
            real_connect = sqlite3.connect
            calls = []

            def connect(target, *a, **k):
                if k.get("uri"):                                   # force the "locked live store" path: fall back to a copy
                    raise sqlite3.OperationalError("locked")
                calls.append(target)
                return real_connect(target, *a, **k)
            sqlite3.connect = connect
            try:
                rows, meta = autopsy.load_hermes_db(db, session="s1")
            finally:
                sqlite3.connect = real_connect
        finally:
            tempfile.tempdir = old
        self.assertTrue(calls and "dh-hermes-" in calls[0], "the copy path ran")
        self.assertEqual(meta["session"], "s1")
        self.assertEqual(list(tmp.iterdir()), [], "no dh-hermes-* folder left behind")

    def test_db_copy_failure_removes_the_folder(self):
        base = Path(tempfile.mkdtemp(prefix="dh-test-autopsy2-"))
        self.addCleanup(_force_rm, base)
        tmp = base / "tmp"
        tmp.mkdir()
        old, real = tempfile.tempdir, shutil.copy2
        tempfile.tempdir = str(tmp)
        shutil.copy2 = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            (base / "state.db").write_bytes(b"x")
            with self.assertRaises(OSError):
                autopsy._db_copy(base / "state.db")
        finally:
            shutil.copy2, tempfile.tempdir = real, old
        self.assertEqual(list(tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
