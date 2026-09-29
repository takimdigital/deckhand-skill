"""Suggestions after PENDING (computed, ranked, dismissable) and the audit's edge cases (a locked folder mid-hold,
a hostile community index, secrets in chat answers and in pending items, CRLF ledgers, compaction summaries)."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import build, pending, state, suggest, wfautopsy, workflow as WF  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, append_jsonl, read_json, write_json  # noqa: E402


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Base(unittest.TestCase):
    ENV = ("DECKHAND_HOME", "DECKHAND_OFFLINE", "HERMES_AGENT", "HERMES_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "DECKHAND_WORKFLOWS_URL")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in self.ENV}
        for k in self.ENV:
            os.environ.pop(k, None)
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["DECKHAND_OFFLINE"] = "1"
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def ids(self, limit=0):
        return [i["id"] for i in suggest.compute(self.root, limit=limit)["items"]]

    def run_log(self, cmd, code=0, ago=0):
        append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": iso(time.time() - ago), "cmd": cmd, "exit": code, "out": "boom" if code else ""})


class Suggestions(Base):
    def test_nothing_without_a_project(self):
        self.assertEqual(suggest.compute(self.root)["items"], [])

    def test_define_suggests_access_then_a_proven_path_and_forgets_them_once_done(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        self.assertEqual(set(self.ids()[:2]), {"workflow-query", "profile"})
        code, n = self.dh("next")
        self.assertFalse({i["id"] for i in n["suggest"]["items"]} & {"workflow-query", "profile"})    # `do` says them already: never twice
        self.assertTrue(any("workflow query" in x for x in n["do"]))
        self.dh("profile", "doctor", "--offline")
        self.dh("workflow", "query")
        self.assertEqual(self.ids(), [])

    def test_repeated_failures_rank_first_with_the_right_autopsy_command(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        for _ in range(3):
            self.run_log("npm run build", 1)
        items = {i["id"]: i for i in suggest.compute(self.root, limit=0)["items"]}
        self.assertEqual(items["stuck"]["level"], "now")
        self.assertEqual(items["autopsy"]["cmd"], "dh autopsy --apply")               # unknown harness: the run log
        os.environ["HERMES_AGENT"] = "1"
        items = {i["id"]: i for i in suggest.compute(self.root, limit=0)["items"]}
        self.assertEqual(items["autopsy"]["cmd"], "dh autopsy --latest --apply")      # inside Hermes: this very session
        self.run_log("npm run build", 0)
        self.assertNotIn("stuck", self.ids())                                        # it succeeded since: not stuck anymore

    def test_order_is_deterministic_and_limited(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        for _ in range(3):
            self.run_log("npm test", 1)
        a, b = suggest.compute(self.root), suggest.compute(self.root)
        self.assertEqual(a, b)
        self.assertLessEqual(len(a["items"]), suggest.SHOW)
        scores = [i["score"] for i in a["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(a["more"], len(suggest.compute(self.root, limit=0)["items"]) - len(a["items"]))

    def test_the_gate_is_the_owners_turn(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "saas", "languages": ["en"], "audience": "a"})
        state.phase_done(self.root, "define")
        state.phase_skip(self.root, "research", "declined")
        sm = json.loads((SKILL / "templates" / "sitemap.json").read_text(encoding="utf-8"))
        sm["pages"][0]["title"] = "Bakery home"                               # the untouched example does not pass
        write_json(self.root / ".deckhand" / "sitemap.json", sm)
        state.phase_done(self.root, "plan")
        g = next(i for i in suggest.compute(self.root, limit=0)["items"] if i["id"] == "gate")
        self.assertEqual((g["level"], g["what"]), ("now", "Your turn (G1): approve the plan, or say what to change"))
        state.gate_pass(self.root, "G1", quote="ok go")
        time.sleep(0.01)
        os.utime(self.root / ".deckhand" / "sitemap.json", (time.time() + 60, time.time() + 60))
        self.assertIn("plan-drift", self.ids(limit=0))                                 # the approved plan changed afterwards

    def test_pending_reminders_and_deferred_items_that_come_due(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        old = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 10 * 86400))
        (self.root / "PENDING.md").write_text(
            "# PENDING\n\n## Open\n"
            f"- [ ] P-001 · Send the logo · WHY: header · HOW: email · WHERE: hello@… · asked {old} · status: open · nag: yes\n"
            f"- [ ] P-002 · Buy the domain · WHY: launch · HOW: register · WHERE: registrar · asked {old} · status: open · nag: no · when: deploy\n\n## Done\n",
            encoding="utf-8")
        items = {i["id"]: i for i in suggest.compute(self.root, limit=0)["items"]}
        self.assertIn("P-001 has waited 10 days", items["pending-age:P-001"]["what"])
        self.assertNotIn("due:P-002", items)                                          # not deploy yet
        s = state.load(self.root)
        for ph in ("define", "research", "plan", "build", "brand", "tryon", "review"):
            s["phases"][ph] = {"status": "done"}
        for g in s["gates"]:
            s["gates"][g] = {"status": "passed"}
        state.save(self.root, s)
        items = {i["id"]: i for i in suggest.compute(self.root, limit=0)["items"]}
        self.assertEqual(items["due:P-002"]["level"], "now")

    def test_dismiss_hides_until_the_date_and_all_shows_it(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        code, out = self.dh("suggest", "dismiss", "workflow-query", "--days", "3")
        self.assertEqual(code, 0)
        self.assertNotIn("workflow-query", self.ids(limit=0))
        code, out = self.dh("suggest", "--all")
        self.assertIn("workflow-query", [i["id"] for i in out["items"]])
        self.assertTrue(out["lines"][0].startswith(("NOW · ", "SOON · ", "LATER · ")))
        doc = read_json(self.root / ".deckhand" / "suggest.json")
        doc["dismissed"]["workflow-query"] = "2000-01-01"                               # expired
        write_json(self.root / ".deckhand" / "suggest.json", doc)
        self.assertIn("workflow-query", self.ids(limit=0))
        code, out = self.dh("suggest", "dismiss", "../x")
        self.assertEqual(out["code"], "BAD_ID")

    def test_workflow_proposals_wait_for_the_owners_choice(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        write_json(self.root / ".deckhand" / "autopsy" / "workflow-latest.json", {"id": "W-abc", "proposals": ["P1", "P3"]})
        it = next(i for i in suggest.compute(self.root, limit=0)["items"] if i["id"] == "proposals:W-abc")
        self.assertEqual(it["cmd"], "dh workflow save --from-autopsy W-abc --proposals P1,P3")
        state.log(self.root, {"event": "workflow_saved", "autopsy": "W-abc"})
        self.assertNotIn("proposals:W-abc", self.ids(limit=0))

    def test_a_finished_run_suggests_keeping_its_path(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        s = state.load(self.root)
        for ph in s["phases"]:
            s["phases"][ph] = {"status": "done"}
        for g in s["gates"]:
            s["gates"][g] = {"status": "passed"}
        state.save(self.root, s)
        state.log(self.root, {"event": "phase_done", "phase": "deploy"})
        write_json(self.root / ".deckhand" / "deploy.json", {"url": "https://x.example"})
        ids = self.ids(limit=0)
        for want in ("extract", "handoff", "harvest", "bots"):
            self.assertIn(want, ids)
        self.assertIn("dh workflow new --from-run", json.dumps(suggest.compute(self.root, limit=0)))

    def test_resume_prints_them_after_the_pending_list(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        for _ in range(3):
            self.run_log("npm run build", 1)
        self.dh("status")
        text = (self.root / ".deckhand" / "RESUME.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## Waiting on the owner"), text.index("## Next (optional"))
        self.assertIn("→ `dh autopsy --apply`", text)
        self.assertNotIn("→ `dh profile doctor`", text)                             # already the first `do` step

    def test_a_refused_gate_is_a_decision_not_a_failure(self):
        state.init(self.root, "Bakery", "phased", "scratch")
        append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": iso(time.time()), "cmd": "dh gate pass G1 --quote make it real", "exit": 1,
                                                               "out": "CHANGE_REQUEST: the owner's words read as a change request"})
        from dhlib import resume
        self.assertIsNone(resume._last_failure(self.root))
        self.assertTrue(resume.safe(resume.safety_facts(self.root), self.root)[0])
        self.assertNotIn("unsaved", self.ids(limit=0))


class AuditEdges(Base):
    def test_a_locked_file_mid_hold_puts_everything_back(self):
        state.init(self.root, "Bakery", "phased", "mine")
        before = sorted(p.name for p in self.root.iterdir())
        real = shutil.move
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PermissionError("in use by another process")
            return real(src, dst)
        with mock.patch.object(build.shutil, "move", side_effect=flaky):
            with self.assertRaises(DhError) as e:
                build._hold(self.root)
        self.assertEqual(e.exception.code, "DEST_BUSY")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        self.assertFalse((self.root.parent / ".proj.deckhand-hold").exists())

    def test_a_leftover_hold_is_never_overwritten(self):
        state.init(self.root, "Bakery", "phased", "mine")
        hold = self.root.parent / ".proj.deckhand-hold"
        hold.mkdir()
        (hold / "run.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(DhError) as e:
            build._hold(self.root)
        self.assertEqual(e.exception.code, "HOLD_EXISTS")
        self.assertTrue((hold / "run.json").exists())

    def test_a_hostile_community_index_is_ignored(self):
        com = self.tmp / "community"
        com.mkdir()
        rows = [{"id": "../../evil", "version": 1, "sha": "0" * 16, "file": "x.json", "match": {"deliverable": ["own"]}, "title": "t", "level": "draft"},
                {"id": "ok-flow", "version": "1; rm", "sha": "0" * 16, "file": "ok-flow.json"},
                {"id": "ok-flow", "version": 1, "sha": "0" * 16, "file": "../../../etc/passwd"},
                {"id": "no-sha", "version": 1, "file": "no-sha.json"}]
        (com / "index.json").write_text(json.dumps({"workflows": rows}), encoding="utf-8")
        os.environ["DECKHAND_WORKFLOWS_URL"] = "file://" + str(com)
        WF.sync()
        self.assertEqual(WF._community_rows(), [])

    def test_a_key_pasted_in_chat_never_reaches_the_report(self):
        state.init(self.root, "X", "phased", "scratch")
        key = "sk-or-v1-9f3c2a8b7d6e5f4a3b2c1d0e9f8a7b6c5d4e"
        log = self.tmp / "chat.jsonl"
        log.write_text("\n".join(json.dumps(x) for x in (
            {"role": "assistant", "content": "Which provider key should I use?"}, {"role": "user", "content": f"use this {key}"},
            {"role": "user", "content": "[CONTEXT COMPACTION] Summary of the earlier conversation: what did we decide?"})) + "\n", encoding="utf-8")
        rep = wfautopsy.run(self.root, str(log))
        text = Path(rep["report"]).read_text(encoding="utf-8") + Path(rep["report"]).with_suffix(".json").read_text(encoding="utf-8")
        self.assertNotIn(key, text)
        self.assertIn("use this ***", text)
        self.assertEqual(rep["summary"]["questions"], 1)                              # a compaction summary is not the owner

    def test_a_reopened_phase_becomes_an_upfront_question_even_without_a_transcript(self):
        state.init(self.root, "X", "phased", "scratch")
        state.log(self.root, {"event": "phase_done", "phase": "define"})
        state.log(self.root, {"event": "reopen", "phase": "plan", "reason": "owner: make it like a real business"})
        rep = wfautopsy.run(self.root)
        p = rep["proposals"][0]
        self.assertEqual(p["target"], "ask_upfront")
        self.assertIn("make it like a real business", p["change"])
        self.assertIn("--proposals P1", rep["ask_owner"])

    def test_pending_refuses_secrets_and_hand_closed_seo_lines(self):
        state.init(self.root, "X", "phased", "scratch")
        with self.assertRaises(DhError) as e:
            pending.add(self.root, "Paste the key", "api", "use ghp_" + "a" * 36, "here")
        self.assertEqual(e.exception.code, "SECRET_IN_TEXT")
        with self.assertRaises(DhError) as e:
            pending.close(self.root, "P-SEO-domain")
        self.assertEqual(e.exception.code, "SEO_ITEM")

    def test_a_hand_edited_crlf_ledger_still_works(self):
        (self.tmp / "home").mkdir(parents=True, exist_ok=True)
        (self.tmp / "home" / "pending.md").write_bytes(
            b"# PENDING\r\n\r\n## Open\r\n- [ ] P-007 \xc2\xb7 Renew the domain \xc2\xb7 HOW: pay \xc2\xb7 WHERE: registrar \xc2\xb7 asked 2026-09-01\r\n\r\n## Done\r\n")
        self.assertEqual([i["id"] for i in pending.summary(None)["items"]], ["P-007"])
        out = pending.add(None, "Rotate the token", "leaked", "new one", "Coolify → Keys", machine=True)
        self.assertEqual(out["added"], "P-008")
        pending.close(None, "P-007", machine=True)
        text = (self.tmp / "home" / "pending.md").read_text(encoding="utf-8")
        self.assertIn("P-008", text.split("## Done")[0])
        self.assertIn("P-007", text.split("## Done")[1])

    def test_gates_in_auto_mode_need_no_quote_and_empty_quotes_are_refused(self):
        state.init(self.root, "X", "auto", "scratch")
        for p in ("define", "research", "plan"):
            state.phase_done(self.root, p, force_reason="test")
        code, out = self.dh("gate", "pass", "G1")
        self.assertEqual(code, 0)
        other = self.tmp / "p2"
        other.mkdir()
        state.init(other, "Y", "phased", "scratch")
        for p in ("define", "research", "plan"):
            state.phase_done(other, p, force_reason="test")
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--project", str(other), "gate", "pass", "G1", "--quote", ""])
        self.assertEqual(json.loads(buf.getvalue())["code"], "NEED_QUOTE")

    def test_pinning_the_same_workflow_again_keeps_its_progress(self):
        state.init(self.root, "X", "phased", "scratch")
        wf = {"schema": WF.SCHEMA, "id": "tiny-flow", "version": 1, "title": "T", "summary": "s", "match": {"deliverable": ["own"]},
              "phases": [{"id": "define", "steps": [{"id": "D1", "do": "dh profile doctor", "expect": "ok"}, {"id": "D2", "do": "dh plan init", "expect": "ok"}]}]}
        write_json(WF.mine_dir() / "tiny-flow.json", wf)
        self.dh("workflow", "use", "mine:tiny-flow")
        self.dh("profile", "doctor", "--offline")
        code, out = self.dh("workflow", "use", "mine:tiny-flow")
        self.assertEqual(out["kept_progress"], 1)
        self.assertEqual(state.load(self.root)["workflow"]["done"], ["D1"])

    def test_commands_without_a_workflow_explain_themselves(self):
        state.init(self.root, "X", "phased", "scratch")
        for args, code in ((("workflow", "todo"), "NO_WORKFLOW"), (("workflow", "use", "nope-nope"), "NO_SUCH_WORKFLOW"),
                           (("workflow", "step", "D1", "done"), "NO_WORKFLOW"), (("pending", "done"), "USAGE")):
            c, out = self.dh(*args)
            self.assertEqual((c, out["code"]), (1, code), args)


if __name__ == "__main__":
    unittest.main()
