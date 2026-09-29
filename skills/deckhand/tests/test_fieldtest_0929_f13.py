"""F13: a dead link recorded by compose blocks the honesty check."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
from dhlib import brand  # noqa: E402


class F13(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        self.root = self.tmp / "p"
        (self.root / ".deckhand").mkdir(parents=True)
        (self.root / "components").mkdir()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_F13_dead_links_and_demo_prices_in_the_ledger_are_blocking(self):
        (self.root / "components" / "f.tsx").write_text('<a href="#">x</a><span>$19 / mo</span>', encoding="utf-8")
        (self.root / ".deckhand" / "demo-copy.json").write_text(json.dumps({"entries": [
            {"file": "components/f.tsx", "text": 'href="#"', "kind": "dead-link"},
            {"file": "components/f.tsx", "text": "$19 / mo"}]}), encoding="utf-8")
        r = brand.check(self.root)
        kinds = {f["kind"] for f in r["findings"]}
        self.assertIn("dead-link", kinds, r["findings"])
        self.assertIn("demo-copy", kinds, r["findings"])
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
