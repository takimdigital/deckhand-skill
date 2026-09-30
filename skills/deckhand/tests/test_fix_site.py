"""Fix package 4: site-building bugs from the owner journey (plan split, scaffold layout, rebrand check, seo prefix i18n)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402
from dhlib import brand, build, plan, seo  # noqa: E402
from dhlib.util import write_json  # noqa: E402


def w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        tmpclean.rmtree(self.tmp)


SM = {
    "pages": [
        {"id": "home", "route": "/", "title": "Home", "sections": [{"slot": "hero"}]},
        {"id": "catalogue", "route": "/catalogue", "title": "Catalogue", "entry": True, "sections": [{"slot": "grid"}]},
        {"id": "home-en", "route": "/en", "title": "Home", "entry": True, "sections": [{"slot": "hero"}]},
        {"id": "catalogue-en", "route": "/en/catalogue", "title": "Catalogue", "entry": True, "sections": [{"slot": "grid"}]},
    ],
    "nav": {"header": ["/catalogue"], "footer": []},
    "features": [
        {"id": "catalogue", "title": "Catalogue", "pages": ["home", "catalogue", "home-en", "catalogue-en"], "done": "x"},
        {"id": "i18n", "title": "Two languages", "pages": ["home", "home-en", "catalogue-en"], "done": "x"},
    ],
}


class PlanSplit(Tmp):
    def test_a_page_listed_by_two_features_has_one_deterministic_owner_and_no_package_is_empty(self):
        write_json(plan.sitemap_path(self.root), SM)
        idx = plan.split(self.root, agents=1)
        pk = {p["context"]: p for p in idx["packages"]}
        allp = [pg for p in idx["packages"] for pg in p["pages"]]
        self.assertEqual(sorted(allp), sorted(set(allp)), "a page is owned twice")
        self.assertIn("home", pk["shell"]["pages"], "the shared home belongs to the shell")
        self.assertIn("home-en", pk["i18n"]["pages"])        # /en/** belongs to the feature that holds the /en pages
        for p in idx["packages"]:
            if p["context"] != "shell":
                self.assertTrue(p["pages"] or p["api"], f"{p['context']} is an empty package")
        for f in (self.root / ".deckhand" / "work").glob("AGENT-*.md"):
            self.assertNotIn("(none)", f.read_text(encoding="utf-8").split("Pages")[1][:80] if "Pages" in f.read_text(encoding="utf-8") else "")

    def test_a_feature_without_pages_is_merged_and_said(self):
        sm = json.loads(json.dumps(SM))
        sm["features"][1]["pages"] = ["home"]                       # only the shared home: nothing of its own
        write_json(plan.sitemap_path(self.root), sm)
        idx = plan.split(self.root, agents=1)
        self.assertNotIn("i18n", [p["context"] for p in idx["packages"]])
        self.assertTrue(any("i18n" in s for s in idx.get("say", [])), idx.get("say"))


class ScaffoldLayout(Tmp):
    def test_layout_props_global_is_replaced_by_a_plain_children_type(self):
        w(self.root, "app/layout.tsx", 'export default function RootLayout({\n  children,\n}: Readonly<{ children: React.ReactNode }>) {}\n')
        self.assertFalse(build.plain_layout(self.root))
        w(self.root, "app/layout.tsx", 'export default function RootLayout({ children }: LayoutProps<"/">) {\n  return null;\n}\n')
        self.assertTrue(build.plain_layout(self.root))
        s = (self.root / "app/layout.tsx").read_text(encoding="utf-8")
        self.assertNotIn("LayoutProps", s)
        self.assertIn("children: React.ReactNode", s)


class Rebrand(Tmp):
    def setUp(self):
        super().setUp()
        write_json(self.root / ".deckhand" / "brief.json", {"name": "Atelier Nour", "brand": {"name": "Atelier Nour"}})

    def kinds(self):
        return [(f["kind"], f["severity"], f["file"]) for f in brand.check(self.root)["findings"]]

    def test_real_owner_label_company_name_is_not_demo_content(self):
        w(self.root, "app/mentions/page.tsx", 'export default function P(){return <dl><dt>Company name</dt><dd>[to be completed by the owner]</dd></dl>}\n')
        self.assertNotIn("demo-content", [k for k, _, _ in self.kinds()])
        w(self.root, "app/legal/page.tsx", 'export default function P(){return <p>Company Name: [to be completed by the owner]</p>}\n')
        self.assertNotIn("demo-content", [k for k, _, f in self.kinds() if f.startswith("app/legal")])

    def test_titlecase_company_name_fill_in_is_still_demo_content(self):
        w(self.root, "app/page.tsx", 'export default function P(){return <h1>Company Name</h1>}\n')
        self.assertIn(("demo-content", "block", "app/page.tsx"), self.kinds())

    def test_placeholder_image_on_a_live_route_blocks(self):
        w(self.root, "app/page.tsx", 'import Hero from "@/components/sections/x/hero";\nexport default function P(){return <Hero/>}\n')
        w(self.root, "components/sections/x/hero.tsx", 'export default function H(){return <img src="/deckhand-placeholder.svg" alt="watch in dark"/>}\n')
        r = brand.check(self.root)
        f = [x for x in r["findings"] if x["kind"] == "placeholder-image"]
        self.assertEqual([x["severity"] for x in f], ["block"])
        self.assertIn("public/", f[0]["text"] + "")
        self.assertFalse(r["ok"])

    def test_vendor_logo_in_a_staged_section_blocks_unless_replaced(self):
        svg = '<svg viewBox="0 0 10 10"><path d="M0 0h10"/></svg>'
        w(self.root, "components/sections/tailark-oss-x/logo.tsx", f'export const Logo = () => ({svg})\n')
        self.assertIn(("vendor-logo", "block", "components/sections/tailark-oss-x/logo.tsx"), self.kinds())
        w(self.root, "components/sections/tailark-oss-x/logo.tsx", 'export const Logo = () => (<span>Atelier Nour</span>)\n')
        self.assertNotIn("vendor-logo", [k for k, _, _ in self.kinds()])

    def test_deckhand_managed_docs_are_not_scanned(self):
        w(self.root, "PENDING.md", "- [ ] P-001 · Public contact email (your company address, john doe)\n")
        w(self.root, "HANDOFF.md", "Company Name: your company\n")
        self.assertEqual([k for k in self.kinds() if k[2] in ("PENDING.md", "HANDOFF.md")], [])


class PrefixI18n(Tmp):
    def setUp(self):
        super().setUp()
        write_json(self.root / ".deckhand" / "brief.json", {"name": "Nour", "languages": ["fr", "en"], "brand": {"name": "Nour"}})
        write_json(self.root / ".deckhand" / "sitemap.json", {"pages": [
            {"id": "home", "route": "/"}, {"id": "about", "route": "/a-propos"},
            {"id": "home-en", "route": "/en"}, {"id": "about-en", "route": "/en/about"}]})

    def test_prefix_languages_and_alternates_come_from_the_plan_routes(self):
        ctx = seo.ctx_of(self.root)
        self.assertEqual(seo.prefix_langs(ctx), ["en"])
        alts = seo.alternates_of(ctx)
        self.assertEqual(alts["/en"], {"fr": "/", "en": "/en", "x-default": "/"})
        self.assertEqual(alts["/a-propos"]["en"], "/en/about")
        self.assertEqual(seo.plan(self.root)["i18n"], "prefix")

    def test_html_lang_fr_on_an_en_route_is_reported_as_a_manual_edit(self):
        ctx = seo.ctx_of(self.root)
        html = '<html lang="fr"><head><title>t</title></head><body></body></html>'
        f, _ = seo.check_page("/en/about", 200, {}, html, {**ctx, "url": "http://localhost:3000"})
        m = [x for x in f if x["rule"] == "M07"]
        self.assertTrue(m and not m[0]["auto"] and "manual edit" in m[0]["fix"], m)


if __name__ == "__main__":
    unittest.main()
