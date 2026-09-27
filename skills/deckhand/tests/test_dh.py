"""dh control-plane tests — stdlib unittest: `python3 -m unittest discover -s skills/deckhand/tests`."""
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

from dhlib import brand, deploy, handoff, harvest, learn, ops, plan, pool, profile, state  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, read_json, write_json  # noqa: E402

EXAMPLE = json.loads((SKILL / "templates" / "sitemap.json").read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_home = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class StateMachine(Base):
    def test_phases_run_in_order_and_gates_block_in_phased_mode(self):
        state.init(self.root, "Bakery", "phased", "pool")
        with self.assertRaises(DhError) as e:
            state.phase_done(self.root, "plan")
        self.assertEqual(e.exception.code, "OUT_OF_ORDER")
        r = state.phase_done(self.root, "define")
        self.assertFalse(r["ok"])                                          # empty brief: the check fails
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "saas", "languages": ["en"], "audience": "a"})
        self.assertTrue(state.phase_done(self.root, "define")["ok"])
        state.phase_skip(self.root, "research", "owner declined")
        plan.init(self.root)
        write_json(plan.sitemap_path(self.root), EXAMPLE)
        self.assertTrue(state.phase_done(self.root, "plan")["ok"])
        s = state.load(self.root)
        self.assertEqual(state.blocking_gate(s), "G1")
        with self.assertRaises(DhError) as e:
            state.phase_done(self.root, "build")
        self.assertEqual(e.exception.code, "GATE_BLOCKED")
        state.gate_pass(self.root, "G1", "looks right")
        self.assertIsNone(state.blocking_gate(state.load(self.root)))
        state.reopen(self.root, "plan", "owner wants a booking page")
        self.assertEqual(state.load(self.root)["phases"]["plan"]["status"], "pending")

    def test_auto_mode_passes_gates_itself(self):
        state.init(self.root, "X", "auto", "scratch")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "leadgen", "languages": ["en"], "audience": "a"})
        state.phase_done(self.root, "define")
        state.phase_skip(self.root, "research", "r")
        write_json(plan.sitemap_path(self.root), EXAMPLE)
        state.phase_done(self.root, "plan")
        self.assertEqual(state.load(self.root)["gates"]["G1"]["by"], "auto")


class Planner(Base):
    def test_example_is_clean(self):
        r = plan.lint(self.root, EXAMPLE)
        self.assertTrue(r["ok"], r["errors"])

    def test_every_class_of_dead_end_is_caught(self):
        sm = json.loads(json.dumps(EXAMPLE))
        sm["nav"] = {}
        sm["pages"].append({"id": "orphan", "route": "/orphan", "sections": [{"id": "x"}]})
        sm["pages"][0]["sections"][0]["actions"].append({"id": "bad", "label": "Go", "to": "route:/nowhere"})
        sm["pages"][0]["sections"][0]["actions"].append({"id": "noscroll", "label": "More", "to": "anchor:#missing"})
        sm["pages"][3]["actions"][0].pop("error")
        sm["pages"][3]["actions"].append({"id": "pay", "label": "Pay", "to": "api:POST /api/pay", "then": "route:/order/thanks", "error": "state:order.error"})
        sm["forms"][0].pop("error")
        codes = {e["code"] for e in plan.lint(self.root, sm)["errors"]}
        self.assertTrue({"E2", "E3", "E4", "E5", "E6", "E9"} <= codes, codes)

    def test_protected_pages_need_a_way_in(self):
        sm = json.loads(json.dumps(EXAMPLE))
        sm["pages"] = [p for p in sm["pages"] if p["id"] != "login"]
        sm["nav"]["header"] = [t for t in sm["nav"]["header"] if "login" not in t]
        sm["features"][1]["pages"] = ["account"]
        msgs = [e["msg"] for e in plan.lint(self.root, sm)["errors"]]
        self.assertTrue(any("no login page" in m for m in msgs), msgs)

    def test_render_and_split_for_parallel_agents(self):
        write_json(plan.sitemap_path(self.root), EXAMPLE)
        plan.render(self.root)
        md = (self.root / ".deckhand" / "PLAN.md").read_text(encoding="utf-8")
        self.assertIn("flowchart LR", md)
        self.assertIn("home -->|Order your first loaf| order", md)
        idx = plan.split(self.root, agents=2)
        ids = [p["id"] for p in idx["packages"]]
        self.assertIn("WP-00", ids)
        self.assertEqual({p["agent"] for p in idx["packages"]}, {0, 1, 2})          # 0 = the orchestrator's shell, before dispatch
        self.assertEqual(idx["agents"], 2)
        self.assertEqual([d["give"] for d in idx["dispatch"]], [".deckhand/work/AGENT-1.md", ".deckhand/work/AGENT-2.md"])
        wp = next(self.root.glob(".deckhand/work/WP-01-*.md")).read_text(encoding="utf-8")
        self.assertIn("MUST NOT edit files owned by another package", wp)
        self.assertIn("POST /api/orders", wp)
        a1 = (self.root / ".deckhand" / "work" / "AGENT-1.md").read_text(encoding="utf-8")
        self.assertIn("`/order/**`", a1)
        self.assertNotIn("/order/thanks/**", a1)                                        # inside /order already
        conv = (self.root / ".deckhand" / "work" / "CONVENTIONS.md").read_text(encoding="utf-8")
        self.assertIn("Never run a production build", conv)
        self.assertIn("| A2 |", conv)
        # packages sharing a folder never go to two agents: 5 agents asked, 2 independent groups exist
        idx5 = plan.split(self.root, agents=5)
        self.assertEqual(idx5["agents"], 2)
        self.assertIn("independent folder groups", idx5["note"])
        self.assertFalse((self.root / ".deckhand" / "work" / "AGENT-3.md").exists())
        plan.bb_post(self.root, "WP-01", "contract", "Order total is in cents")
        self.assertEqual(plan.bb_read(self.root, "WP-02")[0]["msg"], "Order total is in cents")   # contracts reach everyone

    def test_flags_are_bounded_handoffs(self):
        plan.bb_flag(self.root, "A1-done", "3 routes")
        r = plan.bb_wait(self.root, "A1-done", max_s=1)
        self.assertTrue(r["present"])
        with self.assertRaises(DhError) as e:
            plan.bb_wait(self.root, "never-set", max_s=1)
        self.assertEqual(e.exception.code, "TIMEOUT")
        self.assertIn("A1-done", e.exception.extra["flags_present"])
        with self.assertRaises(DhError):
            plan.bb_flag(self.root, "../escape")


class Pool(Base):
    def test_ranking_is_deterministic_and_explained(self):
        brief = {"shape": "saas", "features": ["accounts", "payments"], "languages": ["en"]}
        a, b = pool.query(brief, 5), pool.query(brief, 5)
        self.assertEqual([x["name"] for x in a["top"]], [x["name"] for x in b["top"]])
        self.assertTrue(all(x["reasons"] for x in a["top"]))

    def test_blockers_and_personal_bases_first(self):
        s, _, blockers = pool.score({"license": "AGPL-3.0", "archived": True}, {})
        self.assertEqual(len(blockers), 2)
        pool.add_local(self.tmp, {"name": "my-bakery-base", "path": str(self.tmp), "license": "owner", "lane": "web", "shape": "catalogue",
                                  "stack": {"framework": "next", "db": "postgres"}, "features": ["accounts"], "vendors": []})
        top = pool.query({"shape": "catalogue", "features": ["accounts"]}, 3)["top"]
        self.assertEqual(top[0]["name"], "my-bakery-base")

    def test_stack_detection(self):
        st = pool.detect_stack({"dependencies": {"next": "16", "drizzle-orm": "1", "pg": "8", "better-auth": "1", "class-variance-authority": "0.7", "tailwindcss": "4"}},
                               ["tsconfig.json", "Dockerfile", "pnpm-lock.yaml"])
        self.assertEqual((st["framework"], st["db"], st["orm"], st["auth"], st["docker"], st["package_manager"]),
                         ("next", "postgres", "drizzle", "better-auth", True, "pnpm"))


class Brand(Base):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        (self.root / "app").mkdir()
        (self.root / "package.json").write_text('{"name": "next-saas-starter", "version": "1.0.0"}\n')
        (self.root / "app" / "layout.tsx").write_text('export const metadata = { title: "Next SaaS Starter", description: "The best starter" };\nexport default function L({children}){return <html lang="en"><body>{children}</body></html>}\n')
        (self.root / "app" / "globals.css").write_text(":root {\n  --primary: oklch(0.2 0 0);\n}\n")
        (self.root / "app" / "page.tsx").write_text('export default function P(){return <main><h1>Next SaaS Starter</h1><p>Lorem ipsum dolor sit amet</p></main>}\n')
        (self.root / "LICENSE").write_text("MIT License — Next SaaS Starter authors\n")
        state.init(self.root, "Bakery", "auto", "pool")
        s = state.load(self.root)
        s["base"] = {"kind": "template", "name": "next-saas-starter", "repo": "someone/next-saas-starter"}
        state.save(self.root, s)
        write_json(self.root / ".deckhand" / "brief.json", {"business": "Sourdough in Lyon", "brand": {"name": "Maison Levain", "primary": "#b45309"}})
        subprocess.run(["git", "add", "-A"], cwd=self.root)

    def test_check_blocks_then_apply_fixes_identity(self):
        r = brand.check(self.root)
        self.assertFalse(r["ok"])
        kinds = {f["kind"] for f in r["findings"]}
        self.assertTrue({"template-name", "demo-content"} <= kinds)
        brand.apply(self.root)
        self.assertEqual(read_json(self.root / "package.json")["name"], "maison-levain")
        lay = (self.root / "app" / "layout.tsx").read_text()
        self.assertIn('title: "Maison Levain"', lay)
        self.assertIn('description: "Sourdough in Lyon"', lay)
        self.assertIn("--primary: #b45309;", (self.root / "app" / "globals.css").read_text())
        self.assertTrue((self.root / "app" / "icon.svg").exists())
        self.assertIn("Next SaaS Starter", (self.root / "LICENSE").read_text())          # the licence is never rewritten
        left = {f["kind"] for f in brand.check(self.root)["findings"] if f["severity"] == "block"}
        self.assertEqual(left, {"demo-content", "lorem"})                                 # lorem ipsum is content work, not a rename

    def test_demo_copy_blocks_but_ai_written_copy_the_owner_saw_labelled_only_warns(self):
        (self.root / "app" / "page.tsx").write_text("export default function P(){return <main><h1>Maison Levain</h1><p>Talk to Sales</p><p>Fresh every morning</p></main>}\n")
        write_json(self.root / ".deckhand" / "demo-copy.json", {"entries": [
            {"file": "app/page.tsx", "text": "Talk to Sales"}, {"file": "app/page.tsx", "text": "Fresh every morning", "ai": True}]})
        f = {x["kind"]: x["severity"] for x in brand.check(self.root, allow=("template-name",))["findings"] if x["file"] == "app/page.tsx"}
        self.assertEqual(f, {"demo-copy": "block", "ai-copy": "warn"})


class Learn(Base):
    def test_seed_lessons_match_real_errors_and_run_records_failures(self):
        hits = learn.match(None, "Error: listen EACCES: permission denied 127.0.0.1:5432")
        self.assertTrue(hits and "5770" in hits[0]["fix"])
        state.init(self.root, "X", "auto", "pool")
        r = learn.run_cmd(self.root, [sys.executable, "-c", "import sys; print('Module not found: Can\\'t resolve \\'./logo.tsx.tsx\\''); sys.exit(1)"])
        self.assertFalse(r["ok"])
        self.assertTrue(any("as:" in k["fix"] or "`as`" in k["fix"] for k in r["known_fixes"]))
        fails = (self.root / ".deckhand" / "failures.jsonl").read_text()
        self.assertIn("tsx.tsx", fails)

    def test_from_failure_then_preflight_then_promote(self):
        state.init(self.root, "X", "auto", "pool")
        learn.run_cmd(self.root, [sys.executable, "-c", "import sys; print('Error: ZZ_WIDGET_7 exploded at /srv/app/x.js:12'); sys.exit(2)"], phase="build")
        a = learn.from_failure(self.root, fix="set WIDGET=off", cause="widget needs a flag")
        self.assertIn("added", a)
        self.assertTrue(learn.match(self.root, "Error: ZZ_WIDGET_7 exploded at /other/path/y.js:99"))
        learn.run_cmd(self.root, [sys.executable, "-c", "import sys; print('Error: ZZ_WIDGET_7 exploded at /srv/app/x.js:12'); sys.exit(2)"], phase="build")
        learn.from_failure(self.root, fix="set WIDGET=off", cause="widget needs a flag")
        self.assertTrue(any("ZZ_WIDGET" in l for l in learn.preflight(self.root, "build")))
        props = learn.promote(self.root)["proposals"]
        self.assertEqual(len(props), 1)
        self.assertIn("references/30-build.md", Path(props[0]["proposal"]).read_text())


class Ops(Base):
    def test_suggest_by_shape_and_add_with_github_schedule(self):
        write_json(self.root / ".deckhand" / "brief.json", {"shape": "booking", "features": ["accounts", "email"]})
        ids = [b["id"] for b in ops.suggest(self.root)["bots"]]
        self.assertIn("booking-reminder", ids)
        self.assertNotIn("low-stock", ids)
        r = ops.add(self.root, "watchdog", "github")
        self.assertTrue((self.root / "ops" / "bots" / "watchdog.py").exists())
        wf = (self.root / ".github" / "workflows" / "deckhand-watchdog.yml").read_text()
        self.assertIn("*/15 * * * *", wf)
        self.assertIn("actions/cache@v4", wf)
        self.assertIn("secrets.COOLIFY_TOKEN", wf)
        self.assertIn("gh workflow run deckhand-watchdog.yml", r["verify_by_its_own_trigger"])
        app = ops.add(self.root, "booking-reminder", "cron")
        self.assertIn("NotImplementedError", (self.root / "ops" / "bots" / "booking_reminder.py").read_text())
        self.assertIn("crontab", app["verify_by_its_own_trigger"])

    def test_watchdog_runs_and_reports_down(self):
        (self.root / "ops").mkdir()
        ops.add(self.root, "watchdog", "local")
        env = {**os.environ, "SITE_URLS": "http://127.0.0.1:9/", "BOT_STATE_DIR": str(self.tmp / "state")}
        for k in ("TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL", "NOTIFY_WEBHOOK_URL", "SMTP_URL", "COOLIFY_URL", "VPS_SSH"):
            env.pop(k, None)
        p = subprocess.run([sys.executable, str(self.root / "ops" / "bots" / "watchdog.py")], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 1)
        self.assertIn("DOWN", p.stdout)


class Deploy(Base):
    def test_no_domain_preview_passes_smoke_with_a_tls_warning_and_the_handoff_says_preview(self):
        import http.server
        import threading

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body><h1>Maison Levain</h1></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            write_json(self.root / ".deckhand" / "brief.json", {"brand": {"name": "Maison Levain"}})
            deploy.target(self.root, "app-uuid", f"http://127.0.0.1:{srv.server_port}")
            sm = deploy.smoke(self.root)
            self.assertTrue(sm["ok"], sm)
            self.assertIn("NO_TLS", sm["warning"])
            handoff.write(self.root)
            text = (self.root / "HANDOFF.md").read_text(encoding="utf-8")
            self.assertIn("(PREVIEW)", text.splitlines()[0])
            self.assertIn("do not take logins, payments", text)
        finally:
            srv.shutdown()


class Verify(Base):
    @unittest.skipUnless(shutil.which("npm"), "npm not on PATH")
    def test_routes_are_proved_on_the_production_build_which_is_stopped_after(self):
        from dhlib import verify
        (self.root / "package.json").write_text(json.dumps({"name": "shop", "private": True, "scripts": {
            "build": "node -e \"require('fs').writeFileSync('built.txt','ok')\"", "start": "node server.js"}}))
        (self.root / "server.js").write_text(
            "require('http').createServer((q, s) => { const ok = q.url === '/' || q.url === '/menu';"
            " s.writeHead(ok ? 200 : 404, {'content-type': 'text/html'}); s.end(ok ? '<a href=\"/menu\">Menu</a>' : 'no'); })"
            ".listen(Number(process.env.PORT));")
        (self.root / ".gitignore").write_text(".env\n")
        write_json(self.root / ".deckhand" / "sitemap.json", {"pages": [{"route": "/"}, {"route": "/menu"}, {"route": "/order"}]})
        rep = verify.run_verify(self.root, skip=("audit",))
        routes = next(r for r in rep["rows"] if r["check"] == "routes")
        self.assertFalse(routes["ok"])
        self.assertIn("on the production build", routes["detail"])
        self.assertEqual(routes["evidence"], "/order -> 404")
        seo = next(r for r in rep["rows"] if r["check"] == "seo")           # SEO is proved on the same served build
        self.assertIn("launch-breakers", seo["detail"])
        self.assertFalse(seo["ok"])                                          # no <title> on that build = a launch-breaker
        import re
        import socket
        port = int(re.search(r"localhost:(\d+)", routes["detail"]).group(1))
        with socket.socket() as sk:   # the server verify started is gone
            self.assertNotEqual(sk.connect_ex(("127.0.0.1", port)), 0)


class Profile(Base):
    def test_secrets_never_enter_the_profile_and_the_vault_is_private(self):
        with self.assertRaises(DhError):
            profile.set_fields(["coolify.token=abc"])
        profile.set_fields(["owner.name=Takim", "owner.languages=fr,ar"])
        self.assertEqual(profile.load()["owner"]["languages"], ["fr", "ar"])
        profile.vault_set("COOLIFY_TOKEN", "s3cr3t")
        self.assertEqual(profile.secret("COOLIFY_TOKEN"), "s3cr3t")
        if os.name != "nt":
            self.assertEqual(oct(os.stat(profile.vault_path()).st_mode)[-3:], "600")
        d = profile.doctor(online=False)
        self.assertIn("COOLIFY_TOKEN", d["secrets_present"])
        self.assertNotIn("s3cr3t", json.dumps(d))


class Harvest(Base):
    def test_project_becomes_a_private_base_with_brand_neutralised(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        (self.root / "package.json").write_text('{"name": "maison-levain", "dependencies": {"next": "16"}}')
        (self.root / "page.tsx").write_text("export default () => <h1>Maison Levain bakes daily</h1>")
        (self.root / ".env").write_text("SECRET=1")
        (self.root / ".gitignore").write_text(".env\n")
        write_json(self.root / ".deckhand" / "brief.json", {"shape": "catalogue", "features": ["accounts"], "brand": {"name": "Maison Levain"}})
        r = harvest.harvest(self.root, "bakery-base", to=self.tmp / "bases" / "bakery-base")
        dest = Path(r["path"])
        self.assertFalse((dest / ".env").exists())
        self.assertIn("Bakery Base bakes daily", (dest / "page.tsx").read_text())
        man = read_json(dest / "deckhand.template.json")
        self.assertEqual(man["template_names"][0], "Bakery Base")
        self.assertEqual(pool.query({"shape": "catalogue", "features": ["accounts"]}, 1)["top"][0]["name"], "bakery-base")

    def test_nothing_of_the_previous_business_reaches_the_next_one_and_its_data_blocks_until_replaced(self):
        # the simulation: client B's site showed client A's phone and owner name, and every check stayed green
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        (self.root / "package.json").write_text('{"name": "sunny-bakery", "dependencies": {"next": "16"}}')
        (self.root / "app").mkdir()
        (self.root / "app" / "page.tsx").write_text(
            'export default () => <main className="SunnyBakery"><h1>Sunny Bakery</h1><p>Warm bread before breakfast</p>'
            '<p>Call 06.12.34.56.78 or <a href="tel:+33612345678">+33 6 12 34 56 78</a>, write to orders@sunnybakery.fr or hi@gmail.com</p>'
            '<p>12 rue des Lilas, 69001 Lyon · founded by Amina Haddad</p><a href="https://instagram.com/sunnybakery">Instagram</a>'
            '<a href="https://www.sunnybakery.fr/menu">Menu</a></main>')
        (self.root / "data").mkdir()
        (self.root / "data" / "customers.json").write_text('[{"name": "Claire Martin", "orders": 12}]')
        (self.root / ".env.example").write_text("RESEND_API_KEY=\n")
        write_json(self.root / ".deckhand" / "brief.json", {"brand": {"name": "Sunny Bakery", "tagline": "Warm bread before breakfast",
                   "social": ["https://instagram.com/sunnybakery"]}, "domain": "sunnybakery.fr", "owner": {"name": "Amina Haddad"},
                   "seo": {"local": {"phone": "+33 6 12 34 56 78", "email": "orders@sunnybakery.fr",
                                     "address": {"street": "12 rue des Lilas", "postal": "69001", "city": "Lyon"}}}})
        r = harvest.harvest(self.root, "bakery-base", to=self.tmp / "bases" / "bakery-base")
        dest = Path(r["path"])
        page = (dest / "app" / "page.tsx").read_text()
        for old in ("Sunny", "sunny", "06.12", "612345678", "6 12 34", "orders@", "hi@gmail", "rue des Lilas", "69001", "Amina", "Haddad",
                    "instagram.com/sunnybakery", "sunnybakery.fr", "Warm bread"):
            self.assertNotIn(old, page, old)
        self.assertIn("BakeryBase", page, "the CamelCase spelling becomes the base's")
        self.assertIn("bakery-base", (dest / "package.json").read_text())
        self.assertTrue((dest / ".env.example").exists(), "an env template with no values is part of a base")
        man = read_json(dest / "deckhand.template.json")
        self.assertEqual([d["path"] for d in man["owner_data"]], ["/".join(("data", "customers.json"))])
        chk = brand.check(dest)
        kinds = {f["kind"] for f in chk["findings"] if f["severity"] == "block"}
        self.assertFalse(chk["ok"])
        self.assertTrue({"previous-business-data", "demo-content"} <= kinds, kinds)
        (dest / "data" / "customers.json").write_text("[]")
        self.assertNotIn("previous-business-data", {f["kind"] for f in brand.check(dest)["findings"]})


class Cli(Base):
    def test_next_without_a_run_explains_init(self):
        code, out = self.dh("next")
        self.assertEqual(code, 0)
        self.assertIn("init", out["do"][0])

    def test_errors_are_json_with_codes(self):
        code, out = self.dh("status")
        self.assertEqual((code, out["code"]), (1, "NO_RUN"))


if __name__ == "__main__":
    unittest.main()
