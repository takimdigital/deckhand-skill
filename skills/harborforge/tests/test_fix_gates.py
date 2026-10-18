"""Gates, phase machine and verify guards (audit A1 A2 A3 A8 A11, C1 C2 C12-C17, journey R1): each test is one reproduction."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402

from dhlib import checks, guide, pending, resume, state, suggest, verify  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, read_json, write_json  # noqa: E402


def reach(root, upto):
    s = state.load(root)
    for p in state.PHASES[:state.PHASE_IDS.index(upto) + 1]:
        s["phases"][p["id"]] = {"status": "done"}
        if p.get("gate"):
            s["gates"][p["gate"]] = {"status": "passed", "by": "test"}
    state.save(root, s)


def git(root, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "HOME", "USERPROFILE")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tmpclean.rmtree(self.tmp)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class A1Classifier(unittest.TestCase):
    CHANGES = ("ok, make the hero bigger", "yes, swap the colours for green", "ok, the second section is confusing",
               "ok make the logo bigger", "yes but change the title", "good, add a contact page", "approved, make the hero bigger",
               "looks good, rename the about page", "ok, move the pricing up", "yes, remove the blog", "ok, can you use blue instead",
               "perfect, the footer needs more links", "ok, la section deux est confuse", "oui, change les couleurs en vert",
               "oui, agrandis le hero", "d'accord, ajoute une page contact", "c'est bon, mais le titre est trop long",
               "ok, خلي الصورة أكبر", "naam, ghayyer el alwan", "ok, the plan is missing a faq", "yes, hero bigger")
    GOS = ("ok", "ok go", "yes", "yes!", "Yes, go ahead", "approved", "looks good", "looks good to me, go ahead", "perfect, ship it",
           "lgtm", "G1 ok", "go", "let's go", "love it", "I love it, go ahead", "sounds good", "ok thanks", "yes please go ahead",
           "okay, the plan looks great", "👍", "oui", "oui vas-y", "oui c'est bon", "d'accord, merci", "parfait", "c'est validé",
           "ok pour moi", "j'adore", "nickel", "très bien, go", "نعم", "موافق", "تمام", "ok tamam", "naam mwafiq", "yalla", "ok no problem",
           "yes, no changes", "super, on y va", "Looks great — ship it!")

    def test_a_change_request_is_never_a_go(self):
        for q in self.CHANGES:
            self.assertEqual(state.classify_quote(q), "change_request", q)

    def test_a_go_is_a_go(self):
        for q in self.GOS:
            self.assertEqual(state.classify_quote(q), "approve", q)

    def test_a_go_carrying_a_named_change_is_kept(self):
        self.assertEqual(state.classify_quote("G1 ok, but add a pricing page"), "approve_with_changes")

    def test_unsure_is_a_change_request(self):
        for q in ("hmm", "maybe", "what about the footer", "ok???? are you sure about the pricing", "", "   "):
            self.assertEqual(state.classify_quote(q), "change_request", q)


class Gates(Base):
    def test_gate_refuses_the_probe_quote(self):
        state.init(self.root, "K", "phased", "scratch")
        reach(self.root, "research")
        state.phase_done(self.root, "plan", force_reason="test")
        code, out = self.dh("gate", "pass", "G1", "--quote", "ok, make the hero bigger")
        self.assertEqual((code, out["code"]), (1, "CHANGE_REQUEST"))
        self.assertNotEqual(state.load(self.root)["gates"]["G1"]["status"], "passed")


class A2A3Verify(Base):
    def _project(self):
        (self.root / "package.json").write_text(json.dumps({"name": "x", "scripts": {"build": "node -e 0"}}), encoding="utf-8")
        (self.root / "README.md").write_text("x\n", encoding="utf-8")

    def test_skipped_blocking_rows_are_reported_and_not_green(self):
        self._project()
        r = verify.run_verify(self.root, skip=("build", "routes", "seo"))
        self.assertFalse(r["ok"])
        rows = {x["check"]: x for x in r["rows"]}
        for name in ("build", "routes", "seo"):
            self.assertTrue(rows[name].get("skipped"), name)
            self.assertFalse(rows[name]["ok"], name)
            self.assertTrue(rows[name]["blocking"], name)
        self.assertEqual(sorted(r["skipped"]), ["build", "routes", "seo"])

    def test_a_recorded_reason_is_kept_in_the_report(self):
        self._project()
        r = verify.run_verify(self.root, skip=("build",), skip_reason="CI builds it")
        self.assertEqual(r["skip_reason"], "CI builds it")
        self.assertIn("CI builds it", [x for x in r["rows"] if x["check"] == "build"][0]["detail"])

    def test_phase_done_review_refuses_a_report_that_skipped_a_blocking_row(self):
        state.init(self.root, "K", "auto", "scratch")
        reach(self.root, "brand")
        write_json(self.root / ".deckhand" / "verify.json",
                   {"ok": True, "at": "2999-01-01T00:00:00Z", "rows": [{"check": "build", "ok": True, "blocking": True, "skipped": True, "detail": "skipped"}]})
        self.assertFalse(checks.review(self.root, state.load(self.root))["ok"])
        write_json(self.root / ".deckhand" / "verify.json",
                   {"ok": True, "at": "2999-01-01T00:00:00Z", "skipped": ["build"], "rows": []})
        self.assertFalse(checks.review(self.root, state.load(self.root))["ok"])

    def test_routes_that_could_not_run_block(self):
        self._project()
        r = verify.run_verify(self.root, skip=())
        row = [x for x in r["rows"] if x["check"] == "routes"][0]
        self.assertTrue(row["blocking"])
        self.assertFalse(row["ok"])
        self.assertFalse(r["ok"])


class A8A11(Base):
    def test_define_validates_shape(self):
        state.init(self.root, "K", "phased", "scratch")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "banana", "languages": ["en"], "audience": "a"})
        r = checks.define(self.root, state.load(self.root))
        self.assertFalse(r["ok"])
        self.assertIn("shape", " ".join(r["why"]))
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "SaaS", "languages": ["en"], "audience": "a"})
        self.assertTrue(checks.define(self.root, state.load(self.root))["ok"])

    def test_operate_needs_a_recorded_deploy_target(self):
        state.init(self.root, "K", "phased", "scratch")
        self.assertFalse(checks.operate(self.root, state.load(self.root))["ok"])
        write_json(self.root / ".deckhand" / "deploy.json", {"url": "https://x.example.com"})
        self.assertTrue(checks.operate(self.root, state.load(self.root))["ok"])


class PhaseMachine(Base):
    def setUp(self):
        super().setUp()
        state.init(self.root, "K", "phased", "scratch")

    def test_c1_skip_refuses_a_done_phase(self):
        reach(self.root, "research")
        code, out = self.dh("phase", "skip", "plan", "--reason", "x")      # plan is current: fine
        self.assertEqual(code, 0)
        reach(self.root, "research")                                     # research is done, G1 passed? (plan not) -> skip research
        code, out = self.dh("phase", "skip", "research", "--reason", "x")
        self.assertEqual((code, out["code"]), (1, "ALREADY_DONE"))
        self.assertEqual(state.load(self.root)["phases"]["research"]["status"], "done")

    def test_c1_skip_keeps_done_phase_with_passed_gate(self):
        reach(self.root, "plan")
        code, out = self.dh("phase", "skip", "plan", "--reason", "x")
        self.assertEqual((code, out["code"]), (1, "ALREADY_DONE"))
        s = state.load(self.root)
        self.assertEqual((s["phases"]["plan"]["status"], s["gates"]["G1"]["status"]), ("done", "passed"))

    def test_c2_reopen_refuses_a_phase_never_reached(self):
        code, out = self.dh("reopen", "deploy", "--reason", "x")
        self.assertEqual((code, out["code"]), (1, "NOT_REACHED"))
        self.assertEqual(state.load(self.root)["gates"]["G4"]["status"], "pending")
        self.assertEqual(self.dh("reopen", "define", "--reason", "x")[0], 0)        # the current phase is reached
        reach(self.root, "plan")
        self.assertEqual(self.dh("reopen", "plan", "--reason", "x")[0], 0)           # a done one too

    def test_c14_force_needs_a_reason(self):
        reach(self.root, "research")
        code, out = self.dh("phase", "done", "plan", "--force")
        self.assertEqual((code, out["code"]), (1, "NEED_REASON"))
        code, out = self.dh("phase", "done", "plan", "--force", "  ")
        self.assertEqual((code, out["code"]), (1, "NEED_REASON"))
        self.assertEqual(state.load(self.root)["phases"]["plan"]["status"], "pending")
        code, out = self.dh("phase", "done", "plan", "--force", "--reason", "owner accepted the example plan")
        self.assertEqual(code, 0)
        self.assertEqual(state.load(self.root)["phases"]["plan"]["forced"], "owner accepted the example plan")
        with self.assertRaises(DhError):
            state.phase_done(self.root, "research", force_reason="")


class Staleness(Base):
    def _review_ready(self):
        state.init(self.root, "K", "auto", "scratch")
        reach(self.root, "brand")

    def test_c13_no_git_old_verify_is_stale(self):
        self._review_ready()
        (self.root / "app.js").write_text("a\n", encoding="utf-8")
        write_json(self.root / ".deckhand" / "verify.json", {"ok": True, "at": "2001-01-01T00:00:00Z", "rows": []})
        r = checks.review(self.root, state.load(self.root))
        self.assertFalse(r["ok"], r)
        write_json(self.root / ".deckhand" / "verify.json", {"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)), "rows": []})
        self.assertTrue(checks.review(self.root, state.load(self.root))["ok"])

    def test_c13_uncommitted_edit_after_verify_is_stale(self):
        self._review_ready()
        git(self.root, "init", "-q")
        (self.root / "app.js").write_text("a\n", encoding="utf-8")
        git(self.root, "add", "app.js")
        git(self.root, "commit", "-qm", "c")
        head = git(self.root, "rev-parse", "HEAD")
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_json(self.root / ".deckhand" / "verify.json", {"ok": True, "at": at, "commit": head, "rows": []})
        self.assertTrue(checks.review(self.root, state.load(self.root))["ok"])
        time.sleep(2.2)
        (self.root / "app.js").write_text("changed\n", encoding="utf-8")
        self.assertFalse(checks.review(self.root, state.load(self.root))["ok"])

    def test_c13_smoke_older_than_the_deploy_is_stale(self):
        state.init(self.root, "K", "auto", "scratch")
        reach(self.root, "review")
        (self.root / "HANDOFF.md").write_text("h\n", encoding="utf-8")
        d = {"url": "https://x.example.com", "smoke": {"ok": True, "at": "2026-09-01T10:00:00Z"}, "last": {"commit": "a", "at": "2026-09-01T11:00:00Z"}}
        write_json(self.root / ".deckhand" / "deploy.json", d)
        r = checks.deploy(self.root, state.load(self.root))
        self.assertFalse(r["ok"], r)
        d["smoke"]["at"] = "2026-09-01T11:00:05Z"
        write_json(self.root / ".deckhand" / "deploy.json", d)
        self.assertTrue(checks.deploy(self.root, state.load(self.root))["ok"])


class Suggest(Base):
    def setUp(self):
        super().setUp()
        state.init(self.root, "K", "phased", "scratch")

    def test_c12_days_are_bounded(self):
        known = suggest.compute(self.root, limit=0, include_dismissed=True)["items"][0]["id"]
        for d in (0, -5, 99999999, 366):
            code, out = self.dh("suggest", "dismiss", known, "--days", str(d))
            self.assertEqual((code, out["code"]), (1, "BAD_DAYS"), d)
        self.assertEqual(self.dh("suggest", "dismiss", known, "--days", "365")[0], 0)

    def test_c12_unknown_ids_are_refused(self):
        code, out = self.dh("suggest", "dismiss", "no-such-suggestion")
        self.assertEqual((code, out["code"]), (1, "BAD_ID"))
        self.assertIsNone(read_json(self.root / ".deckhand" / "suggest.json"))


class Pending(Base):
    def setUp(self):
        super().setUp()
        state.init(self.root, "K", "phased", "scratch")

    def test_c15_exact_duplicates_are_not_added(self):
        a = pending.add(self.root, "Send the logo", how="email it", where="inbox")
        b = pending.add(self.root, "  send the logo ", how="email it", where="inbox")
        self.assertEqual(b.get("duplicate"), a["added"])
        self.assertEqual(len([i for i in pending.items(self.root / "PENDING.md") if i["open"]]), 1)

    def test_c15_ids_are_case_insensitive(self):
        a = pending.add(self.root, "Send the logo", how="email it", where="inbox")
        self.assertEqual(pending.close(self.root, a["added"].lower())["closed"], a["added"])
        c = pending.add(self.root, "Other", how="h", where="w")
        self.assertEqual(pending.set_status(self.root, c["added"].lower(), "waiting-confirm")["id"], c["added"])


class Drift(Base):
    def _g1(self):
        state.init(self.root, "K", "phased", "scratch")
        reach(self.root, "research")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b"})
        state.phase_done(self.root, "plan", force_reason="test")
        state.gate_pass(self.root, "G1", quote="ok go")

    def test_r1_next_shows_drift(self):
        self._g1()
        self.assertNotIn("drift", guide.next_step(self.root))
        write_json(self.root / ".deckhand" / "brief.json", {"business": "edited"})
        out = guide.next_step(self.root)
        self.assertIn("brief.json", out.get("drift", ""))

    def test_c17_a_touch_or_fresh_clone_is_no_drift(self):
        self._g1()
        b = self.root / ".deckhand" / "brief.json"
        future = time.time() + 600
        os.utime(b, (future, future))                                     # mtime moves, the content does not
        self.assertNotIn("drift", guide.next_step(self.root))
        self.assertTrue(resume.check(self.root)["ok"] or all("approved plan" not in c["claim"] for c in resume.check(self.root)["claims"] if not c["ok"]))


if __name__ == "__main__":
    unittest.main()
