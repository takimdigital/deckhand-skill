"""dh pool vet/add — written criteria, evidence in, verdict out (offline: rows are built, not fetched)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)

from dhlib import pool, vet  # noqa: E402
from dhlib.util import DhError, read_json  # noqa: E402

TODAY = time.strftime("%Y-%m-%d")


def row(**over):
    pkg = over.pop("pkg", {"license": "MIT", "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
                           "dependencies": {"next": "16", "react": "19"}, "engines": {"node": ">=20"}})
    tree = over.pop("tree", ["package.json", "app/page.tsx", ".env.example", "tsconfig.json"])
    readme = over.pop("readme", "A Next.js starter for bakeries.")
    r = {"name": "shop-starter", "repo": "acme/shop-starter", "license": "MIT", "stars": 420, "pushed_at": TODAY, "archived": False,
         "stack": pool.detect_stack(pkg, tree), "vendors": [], "evidence": vet.evidence(pkg, tree, readme, True)}
    r.update(over)
    return r


class Verdict(unittest.TestCase):
    def ids(self, v, key):
        return [x["id"] for x in v[key]]

    def test_a_clean_permissive_web_app_is_accepted(self):
        v = vet.verdict(row())
        self.assertEqual(v["verdict"], "accepted")
        self.assertEqual(self.ids(v, "fails"), [])
        self.assertNotIn("acceptable", v)

    def test_every_hard_criterion_refuses_with_its_reason_and_says_what_is_acceptable(self):
        cases = {
            "licence": row(license="AGPL-3.0"),
            "consistent": row(pkg={"license": "UNLICENSED", "scripts": {"dev": "x", "build": "y"}, "dependencies": {"next": "16"}}),
            "runnable": row(pkg={"license": "MIT", "scripts": {"test": "x"}, "dependencies": {"next": "16"}}),
            "clean": row(tree=["package.json", ".env", "app/page.tsx", "certs/server.pem"]),
            "free": row(pkg={"license": "MIT", "scripts": {"dev": "x", "build": "y"}, "dependencies": {"next": "16", "@tailwindplus/elements": "1"}}),
        }
        for cid, r in cases.items():
            v = vet.verdict(r)
            self.assertEqual(v["verdict"], "refused", cid)
            self.assertIn(cid, self.ids(v, "fails"), cid)
            self.assertIn("permissive licence", v["acceptable"])
        self.assertIn("network copyleft", vet.verdict(row(license="AGPL-3.0"))["fails"][0]["detail"])
        self.assertIn("all rights reserved", vet.verdict(row(license=None))["fails"][0]["detail"])
        self.assertIn(".env", vet.verdict(cases["clean"])["fails"][0]["detail"])
        self.assertEqual(vet.verdict(row(archived=True))["verdict"], "refused")
        self.assertEqual(vet.verdict(row(pushed_at="2019-01-01"))["verdict"], "refused")

    def test_soft_criteria_warn_but_do_not_refuse(self):
        v = vet.verdict(row(stars=2, vendors=["clerk", "neon"], swap_burden="light", readme="Get the pro version for more blocks",
                            pkg={"license": "MIT", "scripts": {"dev": "astro dev", "build": "astro build"}, "dependencies": {"astro": "5", "ui": "github:acme/ui"}}))
        self.assertEqual(v["verdict"], "accepted")
        self.assertEqual(sorted(self.ids(v, "warnings")), ["git-dependency", "paid-tier", "rented-services", "traction", "tryon"])
        self.assertEqual(vet.verdict(row(license="BSD-3-Clause"))["verdict"], "accepted")       # permissive family, not only MIT


class Add(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def test_refused_is_never_written_and_accepted_is_written_without_raw_evidence(self):
        with self.assertRaises(DhError) as e:
            pool.add("acme/gpl-thing", mine=True, row=row(license="GPL-3.0", repo="acme/gpl-thing"))
        self.assertEqual(e.exception.code, "REFUSED")
        self.assertIn("acceptable", e.exception.extra)
        self.assertFalse(pool.personal_path().exists())
        r = pool.add("acme/shop-starter", mine=True, row=row())
        self.assertTrue(r["added"])
        saved = read_json(pool.personal_path())["templates"][0]
        self.assertNotIn("evidence", saved)
        self.assertIn("vetted", saved)


if __name__ == "__main__":
    unittest.main()
