"""F3 (foundation audit 2026-10-06): the owner's first look at his app (G2) shows HIS brand, not the template's.

Rebrand is a deterministic script (seconds), so it runs at the end of build — before G2 — on every path that starts from
someone else's code or a blank scaffold. The brand phase keeps the leak check, the SEO decision and the design gate (G3).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import brand, guide, state  # noqa: E402
from dhlib.util import DhError  # noqa: E402


class BrandBeforeG2(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def at_build(self, path):
        root = self.tmp / path
        state.init(root, "Bakery", "phased", path)
        for ph in ("define", "research", "plan"):
            state.phase_done(root, ph, force_reason="test walk")
        state.gate_pass(root, "G1", quote="ok go")
        return root

    def test_rebrand_apply_is_allowed_during_build(self):
        root = self.at_build("pool")
        state.require(root, "build")                       # what `dh rebrand apply` now checks: no raise at build
        (root / "package.json").write_text('{"name": "template-saas"}', encoding="utf-8")
        out = brand.apply(root, {"name": "Golden Crust"})
        self.assertTrue(any(c["file"] == "package.json" for c in out["changes"]))

    def test_cli_rebrand_apply_at_build_is_not_out_of_order(self):
        import io
        import json
        from contextlib import redirect_stdout
        from dhlib.cli import main
        root = self.at_build("pool")
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["rebrand", "apply", "brand.name=Golden Crust", "--project", str(root)])
        self.assertNotIn(json.loads(buf.getvalue()).get("code"), ("OUT_OF_ORDER", "GATE_BLOCKED"))

    def test_build_steps_rebrand_before_the_owner_sees_it(self):
        for path in ("pool", "mine", "scratch"):
            do = guide.next_step(self.at_build(path))["do"]
            rb = next(i for i, x in enumerate(do) if "rebrand apply" in x)
            g2 = next(i for i, x in enumerate(do) if "phase done build" in x)
            self.assertLess(rb, g2, path)

    def test_existing_app_keeps_its_own_brand_at_build(self):
        do = " | ".join(guide.next_step(self.at_build("existing"))["do"])
        self.assertNotIn("rebrand apply", do)

    def test_before_the_plan_is_approved_rebrand_is_still_refused(self):
        root = self.tmp / "early"
        state.init(root, "Bakery", "phased", "pool")
        with self.assertRaises(DhError):
            state.require(root, "build")


if __name__ == "__main__":
    unittest.main()
