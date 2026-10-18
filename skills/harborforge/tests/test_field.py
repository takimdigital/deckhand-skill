"""Regressions from a real field run (Hermes, Windows, a cleaning-company boilerplate sold as a product): each test is
one defect the run hit, reproduced, and now impossible or caught early. IDs = the review's D-numbers."""
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
import hermetic  # noqa: E402  (no secrets of the machine the suite runs on)

from dhlib import brand, build, learn, pool, research, resume, seo, state, util, verify  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, read_json, write_json  # noqa: E402


def reach(root, upto):
    """Walk a test run to just after `upto` (every phase up to it done, its gates passed): gates and clone refuse earlier."""
    s = state.load(root)
    for p in state.PHASES[:state.PHASE_IDS.index(upto) + 1]:
        s["phases"][p["id"]] = {"status": "done"}
        if p.get("gate"):
            s["gates"][p["gate"]] = {"status": "passed", "by": "test"}
    state.save(root, s)


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
        tmpclean.rmtree(self.tmp)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class GateQuote(Base):
    """D2: G1 was passed by the agent on its own paraphrase of a change request."""

    def setUp(self):
        super().setUp()
        state.init(self.root, "CleanKit", "phased", "scratch")
        reach(self.root, "research")
        state.phase_done(self.root, "plan", force_reason="test")          # G1 is due once the plan is done

    def test_phased_gate_needs_the_owners_words(self):
        code, out = self.dh("gate", "pass", "G1", "--note", "Owner approved with change: realistic demo business")
        self.assertEqual((code, out["code"]), (1, "NEED_QUOTE"))

    def test_a_change_request_reopens_instead_of_passing(self):
        code, out = self.dh("gate", "pass", "G1", "--quote", "make it ike a real buisness")
        self.assertEqual((code, out["code"]), (1, "CHANGE_REQUEST"))
        self.assertIn("reopen plan", out["do"][0])            # B9: printed as the runnable `py \"…/dh.py\" reopen plan`
        self.assertNotEqual(state.load(self.root)["gates"]["G1"]["status"], "passed")

    def test_a_go_passes_and_keeps_the_quote(self):
        code, out = self.dh("gate", "pass", "G1", "--quote", "ok go")
        self.assertEqual(code, 0)
        g = state.load(self.root)["gates"]["G1"]
        self.assertEqual((g["status"], g["quote"], g["verdict"]), ("passed", "ok go", "approve"))
        self.assertIn('owner: ok go', resume.render(resume.gather(self.root)))

    def test_a_go_with_a_change_passes_and_asks_to_record_it(self):
        code, out = self.dh("gate", "pass", "G1", "--quote", "G1 ok, but add a pricing page")
        self.assertEqual(code, 0)
        self.assertIn("dh note decision", out["changes_asked"])

    def test_classifier(self):
        c = state.classify_quote
        self.assertEqual([c(q) for q in ("approved", "looks good", "oui vas-y", "👍", "not yet", "no, change the hero", "")],
                         ["approve", "approve", "approve", "approve", "change_request", "change_request", "change_request"])

    def test_a_no_never_passes(self):
        # the simulation: each of these passed a gate
        c = state.classify_quote
        for q in ("don't ship it", "wait, do not proceed", "this is not good", "ok but add a blog page", "please don't go live",
                  "c'est pas bon", "stop"):
            self.assertEqual(c(q), "change_request", q)
        for q in ("ok no problem", "yes, no changes", "approved", "G1 ok, but add a pricing page"):
            self.assertNotEqual(c(q), "change_request", q)
        code, out = self.dh("gate", "pass", "G1", "--quote", "don't ship it")
        self.assertEqual((code, out["code"]), (1, "HOLD"))                         # a hold: wait, never reopen

    def test_a_hold_waits_and_never_reopens(self):
        # field test 2026-09-29 F6: a hold got the change-request answer, whose first step reopens the plan
        for q in ("hold on, give me a day to think about it", "wait, dont ship this yet", "stop", "not yet"):
            code, out = self.dh("gate", "pass", "G1", "--quote", q)
            self.assertEqual((code, out["code"]), (1, "HOLD"), q)
            self.assertFalse(any(d.startswith("dh reopen") for d in out["do"]), out["do"])
        code, out = self.dh("gate", "pass", "G1", "--quote", "no, change the hero")    # a change is still a change
        self.assertEqual(out["code"], "CHANGE_REQUEST")
        self.assertEqual(state.load(self.root)["phases"]["plan"]["status"], "done")
        self.assertNotEqual(state.load(self.root)["gates"]["G1"]["status"], "passed")


class OrderIsEnforced(Base):
    """Review 2026-09-27 (findings 4, 5, N3): gates, skips and phase commands obeyed the order only in `phase done`."""

    def setUp(self):
        super().setUp()
        state.init(self.root, "CleanKit", "phased", "scratch")
        reach(self.root, "plan")                                           # at build, G1 passed

    def test_a_gate_is_not_passed_before_its_phase_is_done(self):
        code, out = self.dh("gate", "pass", "G2", "--quote", "looks good")
        self.assertEqual((code, out["code"], out["phase"]), (1, "GATE_NOT_DUE", "build"))
        self.assertEqual(state.load(self.root)["gates"]["G2"]["status"], "pending")

    def test_only_the_current_phase_can_be_skipped_and_review_never(self):
        code, out = self.dh("phase", "skip", "brand", "--reason", "x")
        self.assertEqual((code, out["code"]), (1, "OUT_OF_ORDER"))
        reach(self.root, "tryon")
        code, out = self.dh("phase", "skip", "review", "--reason", "x")
        self.assertEqual((code, out["code"]), (1, "NOT_SKIPPABLE"))

    def test_skipping_tryon_in_phased_mode_still_asks_the_owner_for_the_design(self):
        reach(self.root, "brand")
        code, _ = self.dh("phase", "skip", "tryon", "--reason", "owner happy with the brand")
        self.assertEqual(code, 0)
        self.assertEqual(state.blocking_gate(state.load(self.root)), "G3")
        code, out = self.dh("phase", "done", "review")
        self.assertEqual((code, out["code"]), (1, "GATE_BLOCKED"))
        self.assertEqual(self.dh("gate", "pass", "G3", "--quote", "approved")[0], 0)

    def test_skipping_tryon_in_auto_mode_passes_g3(self):
        s = state.load(self.root); s["mode"] = "auto"; state.save(self.root, s)
        reach(self.root, "brand")
        self.dh("phase", "skip", "tryon", "--reason", "x")
        self.assertIsNone(state.blocking_gate(state.load(self.root)))

    def test_phase_commands_wait_for_their_phase(self):
        s = state.load(self.root); s["phases"]["plan"] = {"status": "pending"}; s["gates"]["G1"] = {"status": "pending"}
        state.save(self.root, s)
        code, out = self.dh("scaffold", "--to", str(self.tmp / "app"))
        self.assertEqual((code, out["code"]), (1, "OUT_OF_ORDER"))                 # no clone/scaffold before the plan
        self.assertFalse((self.tmp / "app").exists())
        code, out = self.dh("rebrand", "apply", "brand.name=X")
        self.assertEqual((code, out["code"]), (1, "OUT_OF_ORDER"))
        self.assertNotEqual(self.dh("rebrand", "apply", "brand.name=X", "--dry")[1].get("code"), "OUT_OF_ORDER")
        reach(self.root, "tryon")
        code, out = self.dh("deploy", "ship")
        self.assertEqual((code, out["code"]), (1, "OUT_OF_ORDER"))                 # no deploy before review + G4


class NextFitsTheRun(Base):
    """Review 2026-09-27 (N1, N2): auto runs were told to wait for the owner; scratch runs never asked for copy.json."""

    def test_auto_mode_never_says_wait_and_lines_follow_the_path(self):
        from dhlib import guide
        state.init(self.root, "A", "auto", "scratch")
        reach(self.root, "research")
        do = "\n".join(guide.next_step(self.root)["do"])
        self.assertIn("copy.json", do)
        self.assertNotIn("pool query", do)                                      # pool/mine only
        self.assertNotIn("wait for", do)
        self.assertIn("gate passes by itself", do)
        reach(self.root, "plan")
        do = "\n".join(guide.next_step(self.root)["do"])
        self.assertNotIn("clone", do.split("base record")[0])                   # scratch: no clone line
        self.assertIn("scaffold", do)
        self.assertNotIn("wait for", do)

    def test_phased_pool_keeps_the_owner_gate_and_the_pool_query(self):
        from dhlib import guide
        state.init(self.root, "B", "phased", "pool")
        reach(self.root, "research")
        do = "\n".join(guide.next_step(self.root)["do"])
        self.assertIn("pool query", do)
        self.assertNotIn("copy.json", do)
        self.assertIn("wait for the owner's go (G1)", do)

    def test_no_angle_or_brace_placeholders_for_hermes(self):
        # findings 18, 22: one `<x>` or `{x}` in a delegate_task refuses the whole batch
        import re
        from dhlib import guide, plan
        bad = re.compile(r"<[^<>\s][^<>]*>|\{[a-z_]+\}")
        state.init(self.root, "H", "phased", "pool")
        for upto in (None, "define", "research", "plan", "build", "brand", "tryon", "review", "deploy"):
            if upto:
                reach(self.root, upto)
            for line in guide.next_step(self.root)["do"]:
                self.assertIsNone(bad.search(line), line)
        plan.init(self.root)
        plan.split(self.root, 2)
        for f in (self.root / ".deckhand" / "work").glob("*.md"):
            if f.name.startswith(("AGENT-", "CONVENTIONS")):
                text = f.read_text(encoding="utf-8")
                self.assertIsNone(bad.search(text), (f.name, bad.search(text)))

    def test_compose_without_copy_says_what_to_write(self):
        state.init(self.root, "C", "phased", "scratch")
        with self.assertRaises(DhError) as e:
            build.compose(self.root, "app/page.tsx", ["hero"], ".deckhand/copy.json")
        self.assertEqual(e.exception.code, "NO_COPY")


class BaseIntoInitFolder(Base):
    """D3: `dh init` fills the folder, then clone/scaffold refused it (DEST_NOT_EMPTY); D4: the agent imported a
    private function to record the base."""

    def _local_base(self) -> str:
        src = self.tmp / "mybase"
        (src / "app").mkdir(parents=True)
        (src / "package.json").write_text(json.dumps({"name": "mybase", "scripts": {"dev": "next dev"}}), encoding="utf-8")
        (src / "app" / "page.tsx").write_text("export default function P(){return null}\n", encoding="utf-8")
        (src / ".gitignore").write_text("node_modules\n", encoding="utf-8")
        pool.add_local(src, {"name": "mybase", "path": str(src), "license": "owner", "source": "mine", "lane": "web"})
        return "mybase"

    def test_clone_lands_in_the_planning_folder_and_keeps_its_state(self):
        state.init(self.root, "CleanKit", "phased", "mine")
        reach(self.root, "plan")
        (self.root / ".deckhand" / "brief.json").write_text('{"business": "x"}', encoding="utf-8")
        name = self._local_base()
        out = build.clone(name, self.root, do_install=False)
        self.assertIn(".deckhand", out["kept"])
        self.assertTrue((self.root / "app" / "page.tsx").exists())
        s = state.load(self.root)
        self.assertEqual((s["name"], s["base"]["name"]), ("CleanKit", "mybase"))         # the same run, now with its base
        self.assertEqual(read_json(self.root / ".deckhand" / "brief.json"), {"business": "x"})
        gi = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules", gi)
        self.assertIn(".deckhand/runs.jsonl", gi)
        self.assertFalse(any(p.name.endswith(".deckhand-hold") for p in self.tmp.iterdir()))

    def test_a_base_built_in_another_folder_continues_the_same_run_there(self):
        # the simulation: `--to OTHERDIR` started the app folder over at define; the planning folder never finished
        state.init(self.root, "CleanKit", "phased", "mine")
        reach(self.root, "plan")
        (self.root / ".deckhand" / "brief.json").write_text('{"business": "x"}', encoding="utf-8")
        (self.root / ".deckhand" / "sitemap.json").write_text('{"pages": []}', encoding="utf-8")
        s = state.load(self.root)
        s["phases"]["define"]["status"] = "done"
        state.save(self.root, s)
        app = self.tmp / "cleankit-app"
        code, out = self.dh("clone", self._local_base(), "--to", str(app), "--no-install")
        self.assertEqual(code, 0, out)
        self.assertEqual(Path(out["run_moved"]["to"]), app.resolve())
        moved = state.load(app)
        self.assertEqual((moved["name"], moved["phases"]["define"]["status"], moved["base"]["name"]), ("CleanKit", "done", "mybase"))
        self.assertEqual(read_json(app / ".deckhand" / "brief.json"), {"business": "x"})
        self.assertTrue((app / ".deckhand" / "sitemap.json").exists())
        code, out = self.dh("next")                                                   # the planning folder points there
        self.assertEqual((out["state"], Path(out["to"])), ("moved", app.resolve()))
        code, out = self.dh("phase", "done", "build")
        self.assertEqual((code, out["code"]), (1, "MOVED"))

    def test_a_clone_run_from_inside_another_business_takes_nothing_of_it(self):
        # the simulation: cloning from client A's folder copied A's Stripe and Resend keys into the new project
        state.init(self.root, "ClientA", "phased", "mine")
        reach(self.root, "plan")
        s = state.load(self.root)
        s["base"] = {"kind": "scratch"}
        state.save(self.root, s)
        (self.root / ".deckhand" / "vault.env").write_text("STRIPE_SECRET_KEY='sk_client_a'\n", encoding="utf-8")
        app = self.tmp / "client-b"
        code, out = self.dh("clone", self._local_base(), "--to", str(app), "--no-install")
        self.assertEqual(code, 0, out)
        self.assertNotIn("carried", out)
        self.assertNotIn("run_moved", out)
        self.assertFalse((app / ".deckhand" / "vault.env").exists())
        self.assertNotEqual(state.load(app)["name"], "ClientA")

    def test_a_folder_with_other_files_is_still_refused(self):
        state.init(self.root, "CleanKit", "phased", "mine")
        reach(self.root, "plan")
        (self.root / "notes.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(DhError) as e:
            build.clone(self._local_base(), self.root, do_install=False)
        self.assertEqual(e.exception.code, "DEST_NOT_EMPTY")
        self.assertIn("notes.txt", e.exception.message)

    def test_base_record_is_a_command(self):
        state.init(self.root, "CleanKit", "phased", "scratch")
        code, out = self.dh("base", "record", "--kind", "scratch", "--note", "hand-built Next app")
        self.assertEqual((code, out["code"]), (1, "NO_APP"))
        (self.root / "package.json").write_text('{"dependencies": {"next": "15"}}', encoding="utf-8")
        code, out = self.dh("base", "record", "--kind", "scratch", "--note", "hand-built Next app")
        self.assertEqual(code, 0)
        self.assertEqual(state.load(self.root)["base"]["recorded_by"], "dh base record")


class Ports(Base):
    """D6/D17: reserved Windows ranges (4097–4196 on the owner's machine held verify's fixed 4100)."""

    def test_a_listening_port_is_not_free(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            self.assertFalse(util.port_free(s.getsockname()[1]))

    def test_reserved_ranges_are_skipped(self):
        start = util.free_port(20000)
        old = util._RESERVED
        util._RESERVED = [(start, start + 5)]
        try:
            self.assertGreater(util.free_port(start), start + 5)
        finally:
            util._RESERVED = old

    def test_a_pinned_dev_port_is_kept(self):
        for script, port in (("next dev -p 3010", 3010), ("next dev --port=3011", 3011), ("PORT=3012 node server.js", 3012), ("next dev", None)):
            (self.root / "package.json").write_text(json.dumps({"scripts": {"dev": script}}), encoding="utf-8")
            self.assertEqual(build.pinned_port(self.root, "dev"), port, script)


class DevServices(Base):
    """D5: the database was run by hand for hours, then silently died during a pause."""

    def test_add_validates(self):
        self.dh("init", "--name", "x")                          # B4: writers need a project
        for args, code in ((("dev", "add", "app", "--cmd", "x", "--port", "1"), "BAD_NAME"),
                           (("dev", "add", "db", "--cmd", "x"), "NO_READY_SIGNAL")):
            c, out = self.dh(*args)
            self.assertEqual((c, out["code"]), (1, code))

    def test_a_service_starts_is_seen_up_then_down_and_resume_says_so(self):
        state.init(self.root, "CleanKit", "phased", "scratch")
        port = util.free_port(21000)
        py = sys.executable.replace("\\", "/")
        build.service_add(self.root, "db", f'"{py}" -m http.server {port} --bind 127.0.0.1', port=port)
        r = build._start_service(self.root, build.services(self.root)[0], wait=30)
        self.assertTrue(r["up"], r)
        write_json(self.root / ".deckhand" / "dev.json", {"services": {"db": r}})
        st = build.dev_status(self.root)
        self.assertEqual(st["services"], [{"name": "db", "up": True, "port": port}])
        stopped = build.dev_stop(self.root)
        self.assertIn("db", stopped["what"])
        for _ in range(30):
            if not build._port_open(port):
                break
            import time
            time.sleep(0.2)
        self.assertEqual(build.dev_status(self.root)["down"], ["db"])
        text = resume.render(resume.gather(self.root))
        self.assertIn("services DOWN: db", text)
        self.assertIn("dh dev start", text)


class SmallThings(Base):
    def test_dh_run_resolves_dh(self):
        """D18: `dh run -- py dh.py …` ran in the project folder, where dh.py does not exist."""
        me = str(SKILL / "dh.py")
        self.assertEqual(learn.resolve_dh(["dh", "status"], self.root), [sys.executable, me, "status"])
        self.assertEqual(learn.resolve_dh(["py", "dh.py", "next"], self.root), ["py", me, "next"])
        self.assertEqual(learn.resolve_dh(["npm", "test"], self.root), ["npm", "test"])
        (self.root / "dh.py").write_text("", encoding="utf-8")
        self.assertEqual(learn.resolve_dh(["python3", "dh.py"], self.root), ["python3", "dh.py"])   # a real local file wins

    def test_research_notes_must_carry_a_fact(self):
        """D19: five sources added with the note "opened"."""
        for note in ("opened", "", "read", "useful"):
            with self.assertRaises(DhError) as e:
                research.add_source(self.root, "https://example.org/pricing", "A1", "pricing", note)
            self.assertEqual(e.exception.code, "NOTE_TOO_THIN")
        research.add_source(self.root, "https://example.org/pricing", "A1", "pricing", "€25/h")

    def test_search_queries_use_a_short_category(self):
        """D14: a 300-character pitch was pasted into every research brief."""
        long = ("Premium production-ready boilerplate for commercial cleaning companies: owner dashboard, cleaner mobile app, "
                "client portal, scheduling, invoicing, quality inspections and a marketing site")
        self.assertEqual(research.short_business({"business": long}), "Premium production-ready boilerplate for commercial cleaning companies")
        self.assertEqual(research.short_business({"business": long, "category": "cleaning business software"}), "cleaning business software")

    def test_own_local_projects_join_the_personal_pool(self):
        """D13: the owner's real bases were local folders; `pool list --mine` ignored the flag."""
        src = self.tmp / "my-saas"
        src.mkdir()
        (src / "package.json").write_text(json.dumps({"description": "Exam prep SaaS", "dependencies": {"next": "15", "pg": "8"}}), encoding="utf-8")
        code, out = self.dh("pool", "add", str(src))
        self.assertEqual((code, out["code"]), (1, "USAGE"))
        code, out = self.dh("pool", "add", str(src), "--mine")
        self.assertEqual((code, out["row"]["license"], out["row"]["description"]), (0, "owner", "Exam prep SaaS"))
        code, out = self.dh("pool", "list", "--mine")
        self.assertEqual([t["name"] for t in out["templates"]], ["my-saas"])
        code, out = self.dh("pool", "show", "my-saas")
        self.assertEqual(code, 0)

    def test_brief_values_are_checked(self):
        self.dh("init", "--name", "x")                          # B4: writers need a project
        code, out = self.dh("brief", "set", "deliverable=boilerplate")
        self.assertEqual((code, out["code"]), (1, "BAD_VALUE"))
        code, out = self.dh("brief", "set", "deliverable=product", "category=cleaning business software")
        self.assertEqual((code, out["deliverable"]), (0, "product"))


class Product(Base):
    """D1: a boilerplate to sell was treated as a real business (PENDING asked for its address, insurance, reviews)."""

    def setUp(self):
        super().setUp()
        state.init(self.root, "CleanKit", "phased", "scratch")
        (self.root / "db").mkdir()
        (self.root / "app").mkdir()
        (self.root / "db" / "seed.ts").write_text("const c = { name: 'Acme Inc', phone: '+1 555 0100' }\n", encoding="utf-8")
        (self.root / "app" / "page.tsx").write_text("export const X = 'Acme Inc'\n", encoding="utf-8")

    def test_demo_company_in_the_seed_is_allowed_only_for_a_product(self):
        self.assertEqual(brand.check(self.root)["blocking"], 2)
        write_json(self.root / ".deckhand" / "brief.json", {"deliverable": "product"})
        r = brand.check(self.root)
        self.assertEqual(r["blocking"], 1)                                                      # app/page.tsx still blocks
        seed = [f for f in r["findings"] if f["file"] == "db/seed.ts"][0]
        self.assertEqual(seed["severity"], "warn")

    def test_the_buyer_kit_is_checked(self):
        miss = verify.product_kit(self.root, {"dev": "next dev"})
        self.assertEqual(len(miss), 5)
        for f in ("README.md", "LICENSE", "CUSTOMIZE.md"):
            (self.root / f).write_text("x", encoding="utf-8")
        self.assertEqual(verify.product_kit(self.root, {"db:seed": "x", "db:reset": "y"}), [])

    def test_seo_facts_are_the_buyers(self):
        write_json(self.root / ".deckhand" / "brief.json", {"deliverable": "product"})
        rep = {"score": 40, "blockers": [], "findings": [], "owner": [{"key": "seo.local.address", "kind": "fact", "required": True,
                                                                       "label": "Business address", "why": "w", "how": "h"}]}
        (self.root / "PENDING.md").write_text("# PENDING\n\n## Open\n\n## Done\n", encoding="utf-8")
        self.assertEqual(seo.sync_pending(self.root, rep)["open"], 0)
        text = (self.root / "PENDING.md").read_text(encoding="utf-8")
        self.assertNotIn("- [ ] P-SEO", text)
        self.assertIn("belong to each buyer", text)


if __name__ == "__main__":
    unittest.main()


class PendingLedger(Base):
    """The Hermes-learned `deckhand-profile` skill kept ~/.deckhand/pending.md and profile.md by hand-written rules; dh
    now owns both, in the same format, so that skill can be deleted without losing a line."""

    OLD = ("# PENDING — owner\n\n## Open\n"
           "- [ ] P-001 · Rotate the Coolify token · WHY: it was pasted in chat · HOW: create a new one, `dh vault set COOLIFY_TOKEN` · "
           "WHERE: Coolify → Keys & Tokens · asked 2026-09-20 · status: open · nag: yes\n"
           "- [ ] P-002 · Buy the domain · WHY: launch · HOW: register it · WHERE: registrar · asked 2026-09-21 · status: open · nag: no · when: before deploy\n"
           "- [x] P-004 · misfiled but closed · asked 2026-09-01 · status: done · done 2026-09-02\n"
           "- [ ] P-003 · Confirm the SMTP sender · asked 2026-09-22 · status: waiting-confirm\n\n"
           "## Done\n- [x] P-000 · old · done 2026-08-01\n\n## Decided, not built\n- a portal later\n")

    def setUp(self):
        super().setUp()
        (self.tmp / "home").mkdir(parents=True, exist_ok=True)
        (self.tmp / "home" / "pending.md").write_text(self.OLD, encoding="utf-8")

    def test_old_ledger_reads_with_ages_deferrals_and_misfiled_lines(self):
        from dhlib import pending
        s = pending.summary(None)
        self.assertEqual([i["id"] for i in s["items"]], ["P-001", "P-003"])      # P-002 deferred (when:), P-004 closed by its checkbox
        self.assertEqual(s["deferred"], 1)
        self.assertEqual(s["items"][1]["status"], "waiting-confirm")
        self.assertIsInstance(s["items"][0]["age_days"], int)
        self.assertEqual([i["id"] for i in pending.summary(None, include_deferred=True)["items"]], ["P-001", "P-002", "P-003"])

    def test_add_close_drop_keep_the_format(self):
        code, out = self.dh("pending", "add", "Create", "the", "Stripe", "account", "--machine")
        self.assertEqual(out["code"], "NEED_HOW_WHERE")
        code, out = self.dh("pending", "add", "Create the Stripe account", "--machine", "--why", "payments", "--how", "sign up",
                            "--where", "https://dashboard.stripe.com/register", "--for-project", "cleankit")
        self.assertEqual((code, out["added"]), (0, "P-005"))                      # after the highest, closed IDs stay spent
        self.assertTrue(out["say"].startswith("ACTION NEEDED — P-005"))
        text = (self.tmp / "home" / "pending.md").read_text(encoding="utf-8")
        self.assertIn("- [ ] P-005 · Create the Stripe account · WHY: payments · HOW: sign up · WHERE: https://dashboard.stripe.com/register · asked", text)
        self.assertIn("project: cleankit", text)
        self.assertLess(text.index("P-005"), text.index("## Done"))
        code, out = self.dh("pending", "done", "P-001", "--machine")
        text = (self.tmp / "home" / "pending.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"## Done\n- \[x\] P-001 .* · done \d{4}-\d{2}-\d{2}")
        code, out = self.dh("pending", "drop", "P-003", "--machine")
        self.assertEqual(out["code"], "NEED_REASON")
        self.dh("pending", "drop", "P-003", "--machine", "--reason", "owner switched to Resend")
        self.assertIn("dropped", (self.tmp / "home" / "pending.md").read_text(encoding="utf-8"))
        self.assertIn("## Decided, not built", (self.tmp / "home" / "pending.md").read_text(encoding="utf-8"))

    def test_project_and_machine_items_both_end_every_report(self):
        state.init(self.root, "Bakery", "phased", "pool")
        code, out = self.dh("pending", "add", "Send the logo", "--why", "the header", "--how", "email it", "--where", "hello@… or drop it in /assets")
        self.assertEqual(out["added"], "P-001")                                   # the project's own ledger, own numbering
        code, out = self.dh("pending", "decide", "Stripe now or later", "--rec", "later")
        self.assertIn("DECISION NEEDED", out["say"])
        code, nxt = self.dh("next")
        got = {(i["id"], i["from"]) for i in nxt["pending"]["items"]}
        self.assertTrue({("P-001", "project"), ("P-002", "project"), ("P-001", "machine")} <= got, got)
        text = (self.root / ".deckhand" / "RESUME.md").read_text(encoding="utf-8")
        self.assertIn("yours, all projects", text)

    def test_profile_md_is_read_and_never_reasked(self):
        (self.tmp / "home" / "profile.md").write_text("# Profile\n- Name: Alex\n- Hosting: Hostinger VPS + Coolify\n- Token: ghp_" + "b" * 36 + "\n",
                                                      encoding="utf-8")
        code, out = self.dh("profile", "show")
        facts = out["notes_md"]["facts"]
        self.assertIn("Name: Alex", facts)
        self.assertNotIn("b" * 36, json.dumps(out))                               # a secret in the notes is masked
