"""dh slop — AI-sounding copy found by script: one engine, one data pack per language, every pack proved on its own
examples (stdlib unittest; pages come from a fake fetch)."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import brand, slop as S, state  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import read_json, write_json  # noqa: E402

SLOP_EN = ("In today's fast-paced world, our cutting-edge platform empowers businesses to unlock their full potential. "
           "Furthermore, we leverage state-of-the-art technology to deliver seamless, robust, and scalable solutions.")
CLEAN_EN = "Sourdough, baguettes and croissants, baked every morning from 5 am in Lyon 2e. Order before 8 pm and collect the next day."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "shop"
        self.root.mkdir()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args, stdin=None):
        buf = io.StringIO()
        old = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(buf):
                code = main(["--project", str(self.root), *args])
        finally:
            sys.stdin = old
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class Packs(Base):
    def test_every_shipped_pack_passes_its_own_test(self):
        packs = S.shipped()
        self.assertTrue({"en", "fr", "es", "de", "it", "pt", "nl", "pl", "ja", "ko", "zh"} <= set(packs))
        for lang, p in packs.items():
            r = S.lint(read_json(p))
            self.assertTrue(r["ok"], f"{lang}: {r['errors']}")

    def test_every_example_is_detected_as_its_own_language(self):
        for lang, p in S.shipped().items():
            ex = read_json(p)["examples"]
            for t in ex["slop"] + ex["clean"]:
                self.assertEqual(S.detect(t), lang, t[:60])

    def test_lint_refuses_what_would_break_or_hang_the_engine(self):
        bad = read_json(S.shipped()["en"])
        bad["phrases"] = [{"id": "x", "kind": "filler", "w": 3, "rx": "(a+)+b", "example": "aaab"},
                          {"id": "y", "kind": "filler", "w": 3, "rx": "ready to go", "example": "never matches"},
                          {"id": "z", "kind": "vibes", "w": 9, "rx": "(?<=x)y", "example": "xy"}]
        bad["words"]["strong"].append("dел[ve]")
        errs = " ".join(S.lint(bad)["errors"])
        for want in ("nested quantifier", "does not match its own example", "kind must be", "not a plain word"):
            self.assertIn(want, errs)

    def test_a_pack_whose_examples_disagree_with_its_rules_fails(self):
        d = read_json(S.shipped()["en"])
        d["examples"]["clean"].append("Our seamless, cutting-edge service will elevate your day.")
        self.assertFalse(S.lint(d)["ok"])
        d = read_json(S.shipped()["en"])
        d["examples"]["slop"].append(CLEAN_EN)
        self.assertFalse(S.lint(d)["ok"])


class Engine(Base):
    def test_slop_and_clean_and_the_fix_is_given(self):
        r = S.check_text(SLOP_EN, "en")
        self.assertEqual(r["verdict"], "slop")
        by = {h["id"]: h for h in r["hits"]}
        self.assertEqual(by["leverage"]["fix"], "use")
        self.assertIn("in-todays-world", by)
        self.assertEqual(S.check_text(CLEAN_EN, "en")["verdict"], "clean")

    def test_a_word_inside_a_phrase_counts_once(self):
        r = S.check_text("Unlock your full potential with us today.", "en")
        self.assertEqual([h["id"] for h in r["hits"]], ["unlock-potential"])
        r = S.check_text("Dans un monde en constante évolution, rien ne change.", "fr")
        self.assertEqual([h["id"] for h in r["hits"]], ["monde-en-evolution"])

    def test_one_transition_is_human_two_are_a_tic(self):
        one = S.check_text("We bake at 5 am. However, we close on Mondays.", "en")
        self.assertFalse([h for h in one["hits"] if h["rule"] == "transition"])
        two = S.check_text("We bake at 5 am. Moreover, we deliver. Furthermore, we cater weddings.", "en")
        self.assertEqual(len([h for h in two["hits"] if h["rule"] == "transition"]), 2)

    def test_a_superlative_needs_its_proof_in_the_same_sentence(self):
        self.assertTrue([h for h in S.check_text("The best bread in town.", "en")["hits"] if h["rule"] == "superlative"])
        self.assertFalse([h for h in S.check_text("Voted best bakery in Lyon by Le Progrès in 2023.", "en")["hits"] if h["rule"] == "superlative"])

    def test_punctuation_emoji_and_flat_rhythm(self):
        r = S.check_text("Fast — simple — honest — local. We bake 🚀 daily! Come in! Say hi! Now!", "en")
        rules = {h["rule"] for h in r["hits"]}
        self.assertTrue({"em-dash", "emoji", "exclaim"} <= rules)
        flat = " ".join(f"Our team prepares every single order with care on day number {i} here." for i in range(9))
        self.assertIn("rhythm", {h["rule"] for h in S.check_text(flat, "en")["hits"]})

    def test_a_chat_reply_pasted_on_a_page_is_always_slop(self):
        r = S.check_text("Certainly! Here is a hero section for your bakery. Fresh bread daily, from 5 am, on Rue Mercière, since 2009, "
                         "baked by Ana and her team of eleven people who love what they do every single day of the week.", "en")
        self.assertEqual(r["verdict"], "slop")

    def test_no_pack_still_gets_the_language_free_features(self):
        r = S.check_text("Мы печём хлеб — каждый день — с 5 утра — на улице Ленина 🚀🚀", "ru")
        self.assertTrue({"em-dash", "emoji"} <= {h["rule"] for h in r["hits"]})

    def test_language_follows_the_script_then_the_stopwords(self):
        self.assertEqual(S.detect("毎朝5時からパンを焼いています。"), "ja")
        self.assertEqual(S.detect("매일 아침 빵을 굽습니다."), "ko")
        self.assertEqual(S.detect("每天早上烤面包。"), "zh")
        self.assertEqual(S.detect("Nous cuisons le pain dans notre four chaque matin."), "fr")
        self.assertEqual(S.detect("the bread", candidates=["fr", "en"]), "en")
        self.assertEqual(S.lang_code("Français"), "fr")
        self.assertEqual(S.lang_code("pt-BR"), "pt")


class Extraction(Base):
    def test_jsx_text_and_prose_strings_not_code_or_classes(self):
        src = '''import { Button } from "@/components/ui/button";
// this component leverages a seamless pattern (a comment, never read)
export default function Hero() {
  const items = [{ title: "Unlock seamless synergy today", href: "/order" }];
  return (<section className="flex items-center gap-4 md:grid">
    <h1>Elevate your mornings</h1>
    <p>It's not just a bakery — it's a community.</p>
    <Button aria-label="Order your bread now">Order</Button>
  </section>);
}
'''
        frags = S.markup_fragments(src)
        texts = [t for _, t in frags]
        self.assertIn((6, "Elevate your mornings"), frags)
        self.assertIn("It's not just a bakery — it's a community.", texts)
        self.assertIn("Unlock seamless synergy today", texts)
        self.assertIn("Order your bread now", texts)
        self.assertFalse([t for t in texts if "flex" in t or "leverages" in t or "components" in t])
        self.assertEqual(len([t for t in texts if "not just" in t]), 1)       # the apostrophes never pair into a fake string

    def test_markdown_html_and_copy_json(self):
        md = "---\ntitle: Our seamless story\n---\n# Welcome\n\nWe bake bread.\n\n```js\nconst x = 'delve into code';\n```\n"
        texts = [t for _, t in S.md_fragments(md)]
        self.assertIn("Our seamless story", texts)
        self.assertFalse([t for t in texts if "delve" in t])
        html = "<html><head><title>Maison</title><meta name='description' content='Elevate your mornings'><script>var a='seamless synergy'</script></head><body><p>We bake.</p><li>Rye</li></body></html>"
        texts = [t for _, t in S.html_fragments(html)]
        self.assertIn("Elevate your mornings", texts)
        self.assertIn("We bake.", texts)
        self.assertFalse([t for t in texts if "synergy" in t])
        frags = S.json_fragments({"hero": {"heading": "Hi there", "actions": [{"label": "Order now", "href": "/order"}]}})
        self.assertEqual(frags, [("hero.heading", "Hi there"), ("hero.actions[0].label", "Order now")])


class Project(Base):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        (self.root / "app").mkdir()
        (self.root / "components" / "ui").mkdir(parents=True)
        (self.root / "package.json").write_text('{"name": "maison-levain"}\n', encoding="utf-8")
        (self.root / "app" / "page.tsx").write_text(
            "export default function P(){return <main>\n<h1>Elevate your mornings</h1>\n"
            "<p>Nestled in the heart of Lyon, our bakery is a testament to the timeless art of bread.</p>\n"
            "<p>Whether you're a busy professional or a curious foodie, we've got you covered.</p>\n"
            "<blockquote>Seamless service, the best croissant I have had. dh:slop-ok</blockquote>\n</main>}\n", encoding="utf-8")
        (self.root / "app" / "about.tsx").write_text("export default function A(){return <p>Ana has baked on Rue Mercière since 2009. We open at 7 am.</p>}\n", encoding="utf-8")
        (self.root / "components" / "ui" / "button.tsx").write_text('export const b = "a seamless cutting-edge synergy button";\n', encoding="utf-8")
        (self.root / "README.md").write_text("A cutting-edge, seamless starter that will elevate your workflow.\n", encoding="utf-8")
        state.init(self.root, "Bakery", "auto", "pool")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "Sourdough in Lyon", "languages": ["en", "fr"], "brand": {"name": "Maison Levain"}})
        subprocess.run(["git", "add", "-A"], cwd=self.root)

    def test_project_scan_reads_site_copy_only_and_points_at_lines(self):
        units = {u["where"]: u for u in S.project_units(self.root)}
        self.assertEqual(set(units), {"app/page.tsx", "app/about.tsx"})               # not README, not components/ui
        page = units["app/page.tsx"]
        self.assertEqual(page["verdict"], "slop")
        self.assertEqual({h["line"] for h in page["hits"] if h["id"] in ("elevate", "nestled")}, {2, 3})
        self.assertFalse([h for h in page["hits"] if h["line"] == 5])                   # a real customer's quote: dh:slop-ok
        self.assertEqual(units["app/about.tsx"]["verdict"], "clean")

    def test_copy_json_is_read_per_section_with_its_key(self):
        write_json(self.root / ".deckhand" / "copy.json", {
            "hero": {"heading": "Pain au levain, cuit chaque matin", "text": ["Dans un monde en constante évolution, nous sublimons le pain."]},
            "cta": {"heading": "Order before 8 pm", "actions": [{"label": "Order now", "href": "/order"}]}})
        units = {u["where"]: u for u in S.project_units(self.root)}
        hero = units[".deckhand/copy.json → hero"]
        self.assertEqual(hero["lang"], "fr")
        self.assertEqual(hero["verdict"], "slop")
        self.assertIn("hero.text[0]", {h.get("key") for h in hero["hits"]})
        self.assertEqual(units[".deckhand/copy.json → cta"]["verdict"], "clean")

    def test_rebrand_check_blocks_slop_and_allow_skips_it(self):
        r = brand.check(self.root)
        slop = [f for f in r["findings"] if f["kind"] == "ai-slop"]
        self.assertTrue(slop and all(f["severity"] == "block" and f["file"] == "app/page.tsx" for f in slop))
        self.assertFalse([f for f in brand.check(self.root, allow=("ai-slop",))["findings"] if f["kind"] == "ai-slop"])

    def test_brand_words_and_the_allow_list_are_never_slop(self):
        write_json(self.root / ".deckhand" / "brief.json", {"languages": ["en"], "brand": {"name": "Elevate Fitness"}})
        (self.root / "app" / "about.tsx").write_text("export default function A(){return <p>Elevate Fitness opens at 6 am on Rue Mercière. A robust squat rack for every member.</p>}\n", encoding="utf-8")
        hits = {h["id"] for u in S.project_units(self.root) if u["where"] == "app/about.tsx" for h in u["hits"]}
        self.assertNotIn("elevate", hits)
        self.assertIn("robust", hits)
        code, out = self.dh("slop", "allow", "robust")
        self.assertEqual(code, 0)
        hits = {h["id"] for u in S.project_units(self.root) if u["where"] == "app/about.tsx" for h in u["hits"]}
        self.assertNotIn("robust", hits)

    def test_dh_slop_check_writes_the_report_and_fails_on_slop(self):
        code, out = self.dh("slop", "check")
        self.assertEqual(code, 1)
        self.assertEqual(out["code"], "SLOP")
        self.assertEqual(out["worst"][0]["where"], "app/page.tsx")
        self.assertIn("Elevate", (self.root / ".deckhand" / "SLOP.md").read_text(encoding="utf-8"))
        code, out = self.dh("slop", "check", "--text", "-", stdin=CLEAN_EN)
        self.assertEqual((code, out["verdict"]), (0, "clean"))
        code, out = self.dh("slop", "check", str(self.root / "app" / "about.tsx"))
        self.assertEqual((code, out["verdict"]), (0, "clean"))

    def test_rendered_pages_of_any_site(self):
        pages = {"http://x.test/": (200, {}, '<html><body><a href="/about">About</a><p>We bake at 5 am on Rue Mercière.</p></body></html>'),
                 "http://x.test/about": (200, {}, "<html><body><h1>Elevate your mornings</h1><p>Nestled in the heart of Lyon, our bakery is a testament to bread. "
                                                  "We've got you covered.</p></body></html>")}
        units = {u["where"]: u for u in S.url_units("http://x.test", get=lambda u, **k: pages.get(u, (404, {}, "")))}
        self.assertEqual(units["/"]["verdict"], "clean")
        self.assertEqual(units["/about"]["verdict"], "slop")


class Community(Base):
    def test_the_owners_find_applies_at_once_then_exports_as_a_bundle(self):
        self.assertFalse([h for h in S.check_text("Our pastries are simply scrumptious.", "en")["hits"] if h["id"] == "scrumptious"])
        code, out = self.dh("slop", "add", "scrumptious", "--lang", "en", "--fix", "say what it tastes of")
        self.assertEqual(code, 0)
        hits = S.check_text("Our pastries are simply scrumptious.", "en")["hits"]
        self.assertEqual([h["fix"] for h in hits if h["id"] == "scrumptious"], ["say what it tastes of"])
        self.dh("slop", "add", "a feast for the senses", "--lang", "en")
        self.assertIn("a-feast-for-the-senses", {h["id"] for h in S.check_text("A feast for the senses awaits.", "en")["hits"]})
        code, out = self.dh("slop", "export", "--lang", "en")
        self.assertEqual(code, 0)
        bundle = read_json(Path(out["bundle"]))
        self.assertIn("scrumptious", bundle["words"]["strong"])
        self.assertNotIn("allow", bundle)
        self.assertTrue(read_json(S.shipped()["en"]))                                   # the shipped pack is never edited

    def test_brief_is_short_and_names_what_not_to_write(self):
        code, out = self.dh("slop", "brief", "--lang", "fr")
        b = out["briefs"][0]
        self.assertIn("sublimer", b["avoid_words"])
        self.assertIn("Dans un monde en constante évolution, tout va vite.", b["avoid_patterns"])
        self.assertLess(len(json.dumps(out, ensure_ascii=False)), 6000)

    def test_lint_cli_checks_a_contributed_file(self):
        f = self.tmp / "xx.json"
        d = read_json(S.shipped()["en"])
        d["examples"]["clean"] = ["Our cutting-edge synergy will elevate you.", CLEAN_EN]
        write_json(f, d)
        code, out = self.dh("slop", "lint", str(f))
        self.assertEqual((code, out["code"]), (1, "PACK_INVALID"))
        code, out = self.dh("slop", "lint")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
