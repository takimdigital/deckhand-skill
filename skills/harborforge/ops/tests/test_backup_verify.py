"""Cold-read audit controls for backup_verify.py: the gate must fail on an empty
schedule list and on a failed newest execution (previously both passed silently)."""
import importlib, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class BackupVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sec = Path(self.tmp.name) / ".vps-ops" / "secrets"
        sec.mkdir(parents=True)
        (sec / "env.sh").write_text("export COOLIFY_TOKEN='1|tok'\nexport B2_BUCKET='b2-bucket'\n", encoding="utf-8")
        (sec / "backup.env.sh").write_text("", encoding="utf-8")
        (sec / "b2-scoped.env.sh").write_text("", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp.name, "USERPROFILE": self.tmp.name})
        self.env.start()
        self.bv = importlib.reload(importlib.import_module("backup_verify"))

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def _run(self, backups, executions):
        import contextlib, io
        self.bv.call = lambda method, path: executions if "executions" in path else backups
        self.bv.b2_list = lambda: ["obj-1.dmp"]
        self.bv.tigris_list = lambda bucket: ["obj-2.dmp"]
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["backup_verify.py", "db-uuid", "tigris-bucket"]), \
             contextlib.redirect_stdout(buf):
            rc = self.bv.main()
        return rc, buf.getvalue()

    def test_empty_schedule_list_fails(self):
        rc, out = self._run([], [{"status": "success"}])
        self.assertEqual(rc, 1)
        self.assertIn("no backup schedule", out)

    def test_failed_newest_execution_fails(self):
        rc, out = self._run([{"uuid": "b1", "frequency": "0 2 * * *"}], [{"status": "failed"}])
        self.assertEqual(rc, 1)
        self.assertIn("VERIFY FAILED", out)
        self.assertIn("schedule ran and broke", out)

    def test_all_legs_proven_passes(self):
        rc, out = self._run([{"uuid": "b1", "frequency": "0 2 * * *"}], [{"status": "success"}])
        self.assertEqual(rc, 0)
        self.assertIn("VERIFY OK", out)


if __name__ == "__main__":
    unittest.main()
