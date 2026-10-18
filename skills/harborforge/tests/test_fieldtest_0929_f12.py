"""F12: a workflow extracted from a run must replay green: its define step needs the brief (keys kept, values never)."""
import io
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
from dhlib import workflow as WF  # noqa: E402
from dhlib.cli import main  # noqa: E402


class F12(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        tmpclean.rmtree(self.tmp)

    def dh(self, root, line):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(root), *shlex.split(line)[1:]])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_F12_extracted_workflow_replays_define_green_and_copies_no_owner_fact(self):
        a = self.tmp / "alpha"
        a.mkdir()
        self.assertEqual(self.dh(a, "dh init --name alpha --mode auto --path pool")[0], 0)
        self.assertEqual(self.dh(a, 'dh brief set business="Maison Pain bakery" shape=booking languages=fr audience="Lyon locals"')[0], 0)
        self.assertEqual(self.dh(a, "dh phase done define")[0], 0)
        out = WF.new_from_run(a, "alphapath")
        wf = json.loads(Path(out["saved"]).read_text(encoding="utf-8"))
        self.assertNotIn("Maison", json.dumps(wf))                              # the owner's values are never copied
        steps = [s for ph in wf["phases"] for s in ph["steps"]]
        brief = next((s for s in steps if s.get("do", "").startswith("dh brief set")), None)
        self.assertIsNotNone(brief, [s.get("do") for s in steps])
        self.assertIn('business="{{business}}"', brief["do"])
        for k in ("business", "shape", "languages", "audience"):
            self.assertIn(k, wf["params"])
        # replay on a fresh project with the new owner's answers: every recorded command must succeed
        b = self.tmp / "beta"
        b.mkdir()
        vals = {"business": "Beta bikes", "shape": "saas", "languages": "en", "audience": "riders", "dir": str(b)}
        for s in steps:
            if "do" not in s:
                continue
            code, res = self.dh(b, WF.fill(s["do"], vals))
            self.assertEqual(code, 0, (s["do"], res))


if __name__ == "__main__":
    unittest.main()
