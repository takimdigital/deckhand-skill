"""F2 (foundation audit 2026-10-06): the `existing` path starts from the app the owner already has.

Before: `dh next` told an existing-app run to write the sitemap from nothing, approve "the chosen base" and build a shell —
an agent re-planned pages that already existed. Now: adopt (read-only) at define, the sitemap starts from the app's real
routes (each marked change=keep), and only the pages marked edit/new become work.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import guide, plan, state  # noqa: E402
from dhlib.util import DhError, read_json  # noqa: E402

APP_FILES = ("app/page.tsx", "app/menu/page.tsx", "app/(marketing)/about/page.tsx", "app/blog/[slug]/page.tsx",
             "app/api/orders/route.ts", "app/layout.tsx", "pages/contact.tsx", "pages/_app.tsx", "pages/api/ping.ts")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "app"
        for f in APP_FILES:
            p = self.root / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("export default function P() { return null }\n", encoding="utf-8")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def walk_to(self, phase, path="existing"):
        state.init(self.root, "Bakery", "phased", path)
        for ph in state.PHASE_IDS[:state.PHASE_IDS.index(phase)]:
            state.phase_done(self.root, ph, force_reason="test walk")
            g = state.blocking_gate(state.load(self.root))
            if g:
                state.gate_pass(self.root, g, quote="ok go")


class RoutesFromApp(Base):
    def test_app_and_pages_router_routes_groups_dropped_api_excluded(self):
        self.assertEqual(plan.routes_from_app(self.root), ["/", "/about", "/blog/[slug]", "/contact", "/menu"])

    def test_src_folder_is_read_too(self):
        (self.root / "src" / "app" / "shop").mkdir(parents=True)
        (self.root / "src" / "app" / "shop" / "page.jsx").write_text("x", encoding="utf-8")
        self.assertIn("/shop", plan.routes_from_app(self.root))


class InitFromApp(Base):
    def test_sitemap_starts_from_the_real_routes_all_kept(self):
        state.init(self.root, "Bakery", "phased", "existing")
        out = plan.init(self.root, from_app=True)
        sm = read_json(self.root / ".deckhand" / "sitemap.json")
        self.assertEqual([p["route"] for p in sm["pages"]], ["/", "/about", "/blog/[slug]", "/contact", "/menu"])
        self.assertTrue(all(p["change"] == "keep" for p in sm["pages"]))
        self.assertEqual(len(out["routes"]), 5)
        self.assertNotEqual(sm, read_json(SKILL / "templates" / "sitemap.json"))   # not the example: the plan check can pass

    def test_no_routes_is_a_clear_error_and_an_existing_sitemap_is_kept(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        state.init(empty, "X", "phased", "existing")
        with self.assertRaises(DhError) as e:
            plan.init(empty, from_app=True)
        self.assertEqual(e.exception.code, "NO_ROUTES")
        state.init(self.root, "Bakery", "phased", "existing")
        plan.init(self.root, from_app=True)
        sm = read_json(self.root / ".deckhand" / "sitemap.json")
        sm["pages"][0]["change"] = "edit"
        (self.root / ".deckhand" / "sitemap.json").write_text(json.dumps(sm), encoding="utf-8")
        plan.init(self.root, from_app=True)                                   # no --force: the owner's edits stay
        self.assertEqual(read_json(self.root / ".deckhand" / "sitemap.json")["pages"][0]["change"], "edit")

    def test_split_builds_only_what_changes(self):
        state.init(self.root, "Bakery", "phased", "existing")
        plan.init(self.root, from_app=True)
        sm = read_json(self.root / ".deckhand" / "sitemap.json")
        for p in sm["pages"]:
            if p["route"] == "/menu":
                p["change"] = "edit"
        (self.root / ".deckhand" / "sitemap.json").write_text(json.dumps(sm), encoding="utf-8")
        idx = plan.split(self.root, agents=2)
        built = [pid for pkg in idx["packages"] for pid in pkg["pages"]]
        self.assertEqual(built, ["menu"])
        self.assertEqual(sorted(idx["kept"]), ["/", "/about", "/blog/[slug]", "/contact"])


class NextSteps(Base):
    def lines(self, phase, path="existing"):
        self.walk_to(phase, path)
        return " | ".join(guide.next_step(self.root)["do"])

    def test_define_adopts_first(self):
        self.assertIn("adopt", self.lines("define"))

    def test_plan_starts_from_the_app_and_names_no_base(self):
        txt = self.lines("plan")
        self.assertIn("plan init --from-app", txt)
        self.assertNotIn("chosen base", txt)

    def test_build_has_no_shell_package(self):
        txt = self.lines("build")
        self.assertNotIn("WP-00", txt)
        self.assertIn("change=edit", txt)

    def test_other_paths_keep_their_shell_and_scratch_names_no_base(self):
        self.assertIn("WP-00", self.lines("build", "scratch"))

    def test_scratch_g1_line_names_no_base(self):
        self.assertNotIn("chosen base", self.lines("plan", "scratch"))


if __name__ == "__main__":
    unittest.main()
