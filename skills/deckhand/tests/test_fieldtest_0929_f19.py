"""F19: seo apply must never touch brief.json (its mtime is the approved plan's, resume --check compares it to G1)."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
from dhlib import seo as SEO, state  # noqa: E402
from dhlib.util import read_json, write_json  # noqa: E402

BRIEF = {"name": "Maison Pain", "business": "Artisan bakery", "shape": "booking", "languages": ["en"],
         "audience": "Lyon locals", "brand": {"name": "Maison Pain"}}


class F19(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        self.root = self.tmp / "shop"
        self.root.mkdir()
        state.init(self.root, "Maison Pain", path="existing")

    def tearDown(self):
        self.env.stop()
        tmpclean.rmtree(self.tmp)

    def test_F19_planning_seo_never_writes_brief_json_and_the_key_is_stable(self):
        p = self.root / ".deckhand" / "brief.json"
        write_json(p, BRIEF)
        before, mt = p.read_bytes(), p.stat().st_mtime_ns
        k1 = SEO.indexnow_key(self.root, read_json(p), create=True)
        SEO.plan(self.root)
        k2 = SEO.indexnow_key(self.root, read_json(p))
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), (before, mt))
        self.assertEqual(k1, k2)
        self.assertRegex(k1, r"^[0-9a-f]{32}$")

    def test_F19_a_key_already_in_an_old_brief_is_still_used(self):
        write_json(self.root / ".deckhand" / "brief.json", {**BRIEF, "seo": {"indexnow_key": "a" * 32}})
        self.assertEqual(SEO.indexnow_key(self.root, read_json(self.root / ".deckhand" / "brief.json")), "a" * 32)


    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_F19_resume_check_is_not_drift_after_seo_apply(self):
        """The reported repro: G1 passed, a minimal app, `dh seo apply`, then `dh resume --check` must not call the brief edited."""
        import io
        import json
        import time
        from contextlib import redirect_stdout
        from dhlib.cli import main
        from dhlib.util import now
        write_json(self.root / ".deckhand" / "brief.json", {**BRIEF, "domain": "maisonpain.fr"})
        (self.root / "package.json").write_text(json.dumps({"name": "shop", "dependencies": {"next": "16.3.6", "react": "19.0.0"}}), encoding="utf-8")
        (self.root / "app").mkdir()
        (self.root / "app" / "layout.tsx").write_text("export default function L({ children }: { children: React.ReactNode }) {\n  return <html><body>{children}</body></html>;\n}\n", encoding="utf-8")
        (self.root / "app" / "page.tsx").write_text("export default function P() { return <main><h1>Maison Pain</h1></main>; }\n", encoding="utf-8")
        s = state.load(self.root)
        s["gates"]["G1"] = {"status": "passed", "at": now(), "by": "owner"}
        state.save(self.root, s)
        brief = self.root / ".deckhand" / "brief.json"
        back = time.time() - 30                           # clearly before G1: only a write by `seo apply` can move it past G1
        os.utime(brief, (back, back))
        time.sleep(1.5)
        with redirect_stdout(io.StringIO()):
            main(["--project", str(self.root), "seo", "apply"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--project", str(self.root), "resume", "--check"])
        out = json.loads(buf.getvalue().strip().splitlines()[-1])
        bad = [c for c in out.get("claims", []) if not c["ok"] and "approved plan" in c["claim"]]
        self.assertEqual(bad, [], out)
        self.assertAlmostEqual(brief.stat().st_mtime, back, delta=1.0)        # and the brief itself was not rewritten


if __name__ == "__main__":
    unittest.main()
