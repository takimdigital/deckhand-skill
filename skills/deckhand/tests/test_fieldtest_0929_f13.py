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


    def test_F13_every_dead_link_still_on_the_page_is_its_own_finding_and_clears_one_by_one(self):
        """Found on a real compose: six href="#" in one footer were one ledger entry, reported at line 1, and fixing one link
        would have cleared them all."""
        f = self.root / "components" / "f.tsx"
        f.write_text('<a href="#">a</a>\n<a href="#">b</a>\n<a href="/menu">ok</a>\n<a href="#">c</a>\n', encoding="utf-8")
        (self.root / ".deckhand" / "demo-copy.json").write_text(json.dumps({"entries": [
            {"file": "components/f.tsx", "text": 'href="#"', "kind": "dead-link"}]}), encoding="utf-8")
        dead = [x for x in brand.check(self.root)["findings"] if x["kind"] == "dead-link"]
        self.assertEqual(sorted(x["line"] for x in dead), [1, 2, 4], dead)
        f.write_text('<a href="/a">a</a>\n<a href="#">b</a>\n<a href="/menu">ok</a>\n<a href="/c">c</a>\n', encoding="utf-8")
        dead = [x for x in brand.check(self.root)["findings"] if x["kind"] == "dead-link"]
        self.assertEqual([x["line"] for x in dead], [2], dead)               # only the one still dead
        f.write_text('<a href="/a">a</a>\n', encoding="utf-8")
        self.assertEqual([x for x in brand.check(self.root)["findings"] if x["kind"] == "dead-link"], [])

    def test_F13_the_ledger_is_not_re_recorded_as_dead_once_the_owner_replaced_every_link(self):
        f = self.root / "components" / "f.tsx"
        f.write_text('<a href="/a">a</a>', encoding="utf-8")
        (self.root / ".deckhand" / "demo-copy.json").write_text(json.dumps({"entries": [
            {"file": "components/f.tsx", "text": 'href="#"', "kind": "dead-link"}]}), encoding="utf-8")
        self.assertTrue(brand.check(self.root)["ok"] or not [x for x in brand.check(self.root)["findings"] if x["kind"] == "dead-link"])


if __name__ == "__main__":
    unittest.main()
