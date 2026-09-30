"""Workflows (query → use → steps tick themselves → todo → extract → publish) and the workflow autopsy (any source,
Hermes state.db included; questions, late asks, direction changes, lost messages, proposals, save)."""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)

from dhlib import autopsy, state, wfautopsy, workflow as WF  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, append_jsonl, read_json, write_json  # noqa: E402


DH = "dh"           # built, so the repo's command-coherence scan does not read these deliberately wrong commands


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def tiny(wid="tiny-flow", **over):
    wf = {"schema": WF.SCHEMA, "id": wid, "version": 1, "title": "Tiny", "summary": "a test path",
          "match": {"deliverable": ["own"], "shape": ["booking"], "industry": ["bakery"]},
          "ask_upfront": [{"id": "Q-lang", "q": "Languages?", "default": "en"}],
          "params": {"agents": {"default": "2"}},
          "phases": [{"id": "define", "steps": [{"id": "D1", "do": "dh profile doctor", "expect": "ok"},
                                                {"id": "D2", "ask": ["Q-lang"]},
                                                {"id": "D3", "do": "dh pool query --shape booking", "expect": "top 3"}], "exit": "dh phase done define"},
                     {"id": "plan", "steps": [{"id": "P1", "do": "dh plan init", "expect": "created"},
                                              {"id": "P2", "do": "dh plan split --agents {{agents}}", "expect": "AGENT files"}], "exit": "dh phase done plan"}]}
    wf.update(over)
    return wf


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "DECKHAND_OFFLINE", "DECKHAND_WORKFLOWS_URL", "HERMES_SESSION_ID", "HERMES_HOME")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["DECKHAND_OFFLINE"] = "1"
        for k in ("DECKHAND_WORKFLOWS_URL", "HERMES_SESSION_ID", "HERMES_HOME"):
            os.environ.pop(k, None)
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        for k, v in self.env.items():
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

    def mine(self, wf):
        write_json(WF.mine_dir() / f"{wf['id']}.json", wf)


class Lint(Base):
    def test_every_shipped_base_workflow_is_strictly_valid(self):
        files = list((SKILL / "workflows").glob("*.json"))
        self.assertTrue(files)
        for f in files:
            r = WF.lint(read_json(f), strict=True)
            self.assertTrue(r["ok"], (f.name, r["errors"]))

    def test_lint_refuses_what_an_ai_must_not_run(self):
        bad = tiny(phases=[{"id": "build", "steps": [
            {"id": "B1", "do": "py -c \"from dhlib.build import _record_base\"", "expect": "x"},
            {"id": "B2", "do": "cat C:\\Users\\alex\\secrets.txt", "expect": "x"},
            {"id": "B3", "do": DH + " frobnicate", "expect": "x"},
            {"id": "B4", "do": DH + " plan explode", "expect": "x"},
            {"id": "B5", "do": "dh plan lint"},
            {"id": "B6", "ask": ["Q-nope"]},
            {"id": "B7", "do": "make deploy", "expect": "x"},
            {"id": "B7", "write": "dup id"}]}])
        errs = "\n".join(WF.lint(bad, strict=True)["errors"])
        for needle in ("private call", "absolute path", f"`{DH} frobnicate` does not exist", f"`{DH} plan explode` does not exist",
                       "B5: `expect` missing", "unknown question", "custom command `make deploy`", "unique"):
            self.assertIn(needle, errs)
        self.assertNotIn("custom command", "\n".join(WF.lint(bad, strict=False)["errors"]))    # personal: a warning, shown at use

    def test_rendered_text_never_carries_placeholders_hermes_refuses(self):
        line = WF.step_line({"id": "X", "do": "dh plan split --agents {{agents}} --x {{unknown}}", "expect": "ok"}, {"agents": "3"})
        self.assertIn("--agents 3", line)
        self.assertIn("[unknown]", line)
        self.assertNotRegex(line, r"[{}<>]")


class Query(Base):
    def test_plumbing_finds_the_cleaning_product_through_its_family(self):
        r = WF.query({"deliverable": "product", "category": "plumbing company software"}, {"features": ["scheduling"]})
        top = r["top"][0]
        self.assertEqual(top["ref"], "base:home-services-saas-product@1")
        self.assertIn("+30 industry plumbing", top["reasons"])
        r2 = WF.query({"deliverable": "product", "category": "window cleaning"}, {})           # the longest keyword wins: window-cleaning
        self.assertEqual(r2["for"]["industry"], "window-cleaning")
        self.assertIn("+20 same family (home-services): the path transfers, the words change", r2["top"][0]["reasons"])
        self.assertEqual(WF.query({"deliverable": "own", "category": "bakery in Lyon"}, {})["top"], [])     # nothing fits: none offered

    def test_own_workflows_rank_first_and_levels_filter(self):
        self.mine(tiny())
        r = WF.query({"deliverable": "own", "shape": "booking", "category": "bakery"}, {})
        self.assertEqual(r["top"][0]["ref"], "mine:tiny-flow@1")
        self.assertIn("+50 your own workflow", r["top"][0]["reasons"])
        self.assertEqual(WF.query({"deliverable": "own", "shape": "booking"}, {"min_level": "proven"})["top"], [])
        wf = WF.add_run(tiny(), {"complete": True, "errors": 0, "harness": "hermes", "os": "windows", "minutes": 90})
        self.assertEqual(WF.level(wf), "proven")
        for h in ("claude-code", "codex"):
            wf = WF.add_run(wf, {"complete": True, "errors": 0, "harness": h, "os": "linux"})
        self.assertEqual(WF.level(wf), "proven")                               # 3 green runs, but not reviewed
        wf["proof"]["reviewed"] = True
        self.assertEqual(WF.level(wf), "trusted")

    def test_community_pool_is_read_through_its_index_and_verified(self):
        com = self.tmp / "community"
        com.mkdir()
        wf = tiny("shared-flow")
        (com / "shared-flow.json").write_text(json.dumps(wf), encoding="utf-8")
        row = {**WF.row_of(wf, "community"), "file": "shared-flow.json"}
        row.pop("source")
        (com / "index.json").write_text(json.dumps({"workflows": [row]}), encoding="utf-8")
        os.environ["DECKHAND_WORKFLOWS_URL"] = "file://" + str(com)
        self.assertTrue(WF.sync()["synced"])
        refs = [r["ref"] for r in WF.query({"deliverable": "own", "shape": "booking"}, {})["top"]]
        self.assertIn("community:shared-flow@1", refs)
        loaded, src = WF.load("community:shared-flow")
        self.assertEqual((loaded["id"], src), ("shared-flow", "community"))
        # a file that no longer matches its index entry is refused
        for f in (WF._cache()).glob("shared-flow@*.json"):
            f.unlink()
        (com / "shared-flow.json").write_text(json.dumps({**wf, "title": "tampered"}), encoding="utf-8")
        with self.assertRaises(DhError) as e:
            WF.load("community:shared-flow")
        self.assertEqual(e.exception.code, "SHA_MISMATCH")


class Use(Base):
    def setUp(self):
        super().setUp()
        state.init(self.root, "Bakery", "phased", "scratch")

    def test_steps_tick_themselves_and_deviations_are_recorded(self):
        self.mine(tiny())
        code, out = self.dh("workflow", "use", "mine:tiny-flow")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["ask_upfront"][0]["id"], "Q-lang")
        self.dh("profile", "doctor", "--offline")
        self.dh("pool", "query", "--shape", "booking")
        code, nxt = self.dh("next")
        self.assertEqual(nxt["do"][0][:2], "D2")                       # the next open step of the workflow, not generic steps
        self.assertIn("WORKFLOW tiny-flow@1", nxt["workflow"]["line"])
        self.dh("brief", "set", "audience=bakers")                    # an owner decision: not a path deviation
        self.dh("dev", "add", "db", "--cmd", "echo db", "--port", "5999")   # building, and not in the workflow: a deviation
        write_json(self.root / ".deckhand" / "brief.json", {"business": "b", "shape": "booking", "languages": ["en"], "audience": "a"})
        self.dh("phase", "done", "define")
        pin = state.load(self.root)["workflow"]
        self.assertEqual(pin["done"][:2], ["D1", "D3"])
        self.assertIn("D2", pin["done"])                              # an ask step closes with its phase (the Q&A ledger judges it)
        self.assertEqual([d["kind"] for d in pin["deviations"]], ["unplanned"])
        self.assertIn("dev add", pin["deviations"][0]["cmd"])
        text = (self.root / ".deckhand" / "RESUME.md").read_text(encoding="utf-8")
        self.assertIn("WORKFLOW tiny-flow@1", text)

    def test_todo_for_any_harness_and_manual_steps(self):
        self.mine(tiny())
        self.dh("workflow", "use", "mine:tiny-flow", "--set", "agents=4")
        code, t = self.dh("workflow", "todo")
        self.assertEqual([i["status"] for i in t["todo"]][:2], ["in_progress", "pending"])
        self.assertIn("--agents 4", t["todo"][4]["content"])
        code, md = self.dh("workflow", "todo", "--format", "md")
        self.assertTrue(md["markdown"].startswith("- [ ] D1"))
        code, out = self.dh("workflow", "step", "D1", "skip")
        self.assertEqual(out["code"], "NEED_REASON")
        code, out = self.dh("workflow", "step", "D1", "done")
        self.assertEqual(code, 0)

    def test_non_dh_commands_need_the_owners_ok(self):
        wf = tiny("with-make")
        wf["phases"][0]["steps"].append({"id": "D9", "do": "make assets", "expect": "built"})
        self.mine(wf)
        code, out = self.dh("workflow", "use", "mine:with-make")
        self.assertEqual((code, out["code"], out["commands"]), (1, "NEEDS_ACCEPT", ["make assets"]))
        code, out = self.dh("workflow", "use", "mine:with-make", "--accept")
        self.assertEqual(code, 0)

    def test_a_changed_pinned_file_is_caught(self):
        self.mine(tiny())
        self.dh("workflow", "use", "mine:tiny-flow")
        wf = read_json(self.root / ".deckhand" / "workflow.json")
        wf["title"] = "edited behind our back"
        write_json(self.root / ".deckhand" / "workflow.json", wf)
        code, out = self.dh("workflow", "todo")
        self.assertEqual(out["code"], "WORKFLOW_CHANGED")

    def test_a_run_becomes_a_draft_workflow(self):
        write_json(self.root / ".deckhand" / "brief.json", {"deliverable": "own", "shape": "booking", "category": "bakery", "languages": ["fr"]})
        for cmd, code in (("dh profile doctor", 0), ("dh plan init", 0), ("dh scaffold --to /x/y", 1), ("dh scaffold --to " + str(self.root), 0),
                          ("npm install", 0), ("dh phase done define", 0)):
            append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": iso(time.time()), "cmd": cmd, "exit": code})
        self.dh("note", "decision", "owner wants French only")
        code, out = self.dh("workflow", "new", "--from-run", "--id", "bakery-booking")
        self.assertEqual(code, 0, out)
        wf = read_json(Path(out["saved"]))
        dos = [st["do"] for st in wf["phases"][0]["steps"]]
        self.assertIn("dh scaffold --to {{dir}}", dos)                              # generic path, the failed attempt left out
        self.assertEqual(wf["proof"]["runs"][0]["errors"], 1)
        self.assertEqual(WF.level(wf), "draft")
        self.assertTrue(any("French" in q["q"] for q in wf["ask_upfront"]))
        self.assertTrue(out["lint"]["ok"], out["lint"])

    def test_publish_is_strict_and_sends_nothing(self):
        self.mine(tiny())
        out = WF.publish_bundle(WF.load("mine:tiny-flow")[0])
        self.assertTrue(Path(out["bundle"]).exists())
        self.assertIn("nothing was sent", out["note"])
        leaky = tiny("leaky")
        leaky["phases"][0]["steps"].append({"id": "D8", "do": "curl -s -H 'Authorization: Bearer ghp_" + "a" * 36 + "' https://api.github.com", "expect": "x"})
        with self.assertRaises(DhError):
            WF.publish_bundle(leaky)


class HermesAndWorkflowAutopsy(Base):
    """The autopsy reads a Hermes session (state.db, read-only) and turns what happened into owner-facing proposals."""

    def build(self):
        state.init(self.root, "CleanKit", "phased", "scratch")
        t0 = time.time() - 10000
        hist = [{"at": iso(t0), "event": "init"}, {"at": iso(t0 + 1000), "event": "phase_done", "phase": "define"},
                {"at": iso(t0 + 2000), "event": "phase_done", "phase": "research"}, {"at": iso(t0 + 3000), "event": "phase_done", "phase": "plan"},
                {"at": iso(t0 + 3700), "event": "reopen", "phase": "plan", "reason": "owner: make it like a real business"},
                {"at": iso(t0 + 4200), "event": "gate", "gate": "G1", "note": "Owner approved with change: realistic demo business"}]
        (self.root / ".deckhand" / "history.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hist), encoding="utf-8")
        append_jsonl(self.root / ".deckhand" / "notes.jsonl", {"at": iso(t0 + 5200), "ts": t0 + 5200, "kind": "decision", "text": "fictional demo company in the seed"})
        for i, (cmd, code) in enumerate((("dh profile doctor", 0), ("npx pglite-server -p 8188", 1), ("npx pglite-server -p 5772", 0))):
            append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": iso(t0 + 100 + i * 60), "cmd": cmd, "exit": code,
                                                                   "out": "Error: listen EACCES: permission denied 0.0.0.0:8188" if code else "ok"})
        db = self.tmp / "hermes" / "state.db"
        db.parent.mkdir()
        con = sqlite3.connect(db)
        con.executescript("""CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, parent_session_id TEXT, started_at REAL NOT NULL, cwd TEXT);
            CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT, tool_call_id TEXT,
                                   tool_calls TEXT, tool_name TEXT, timestamp REAL NOT NULL);
            CREATE TABLE async_delegations (delegation_id TEXT, parent_session_id TEXT, state TEXT, dispatched_at REAL, completed_at REAL, result_json TEXT, task_json TEXT);""")
        con.execute("insert into sessions values ('S1','desktop',NULL,?,?)", (t0, str(self.root)))
        con.execute("insert into sessions values ('S2','desktop','S1',?,?)", (t0 + 4000, str(self.root)))
        con.execute("insert into sessions values ('K1','subagent','S2',?,?)", (t0 + 4100, str(self.root)))
        call = lambda i, c: json.dumps([{"id": i, "function": {"name": "terminal", "arguments": json.dumps({"command": c})}}])  # noqa: E731
        rows = [("S1", "user", "build me a cleaning boilerplate to sell", None, None, 0),
                ("S1", "assistant", "7 questions, reply '1a 2a' or 'default':\n1) Who is it for?\n2) Languages?", None, None, 100),
                ("S1", "user", "default", None, None, 160),
                ("S1", "assistant", None, None, call("c1", "npm run build"), 300),
                ("S1", "tool", json.dumps({"output": "error TS2322: Type 'x' is not assignable", "exit_code": 2}), "c1", None, 320),
                ("S1", "assistant", None, None, call("c2", "npm run build"), 700),
                ("S1", "tool", json.dumps({"output": "Compiled", "exit_code": 0, "error": None}), "c2", None, 720),
                ("S1", "assistant", "The plan is ready (46 pages, 3 roles). DECISION NEEDED — reply 'G1 ok' to approve?", None, None, 3100),
                ("S2", "user", "make it ike a real buisness", None, None, 3600),
                ("S2", "assistant", "Should the demo company carry a real address and insurance details?", None, None, 5000),
                ("S2", "user", "no, a fictional one", None, None, 5100),
                ("S2", "user", "run the try on", None, None, 5300),
                ("S2", "assistant", "Your request was not processed.", None, None, 5310),
                ("K1", "assistant", "child chatter must not count", None, None, 4200)]
        for sid, role, content, tcid, calls, dt in rows:
            con.execute("insert into messages (session_id, role, content, tool_call_id, tool_calls, timestamp) values (?,?,?,?,?,?)",
                        (sid, role, content, tcid, calls, t0 + dt))
        con.execute("insert into async_delegations values ('deleg_1','S2','error',?,?,?,?)", (t0 + 4100, t0 + 5000, json.dumps([{"status": "interrupted"}] * 4), "[]"))
        con.commit()
        con.close()
        return db

    def test_loader_reads_hermes_lineage_and_delegations(self):
        db = self.build()
        self.assertEqual(autopsy.detect(db), "hermes-db")
        events, meta = autopsy.load_hermes_db(db, "S2")
        self.assertEqual(meta["lineage"], ["S1", "S2"])                              # ancestors, not the sub-agent
        self.assertFalse(any("child chatter" in m["text"] for m in meta["messages"]))
        cmds = [(e["cmd"], e["exit"]) for e in events if e["kind"] == "cmd"]
        self.assertEqual(cmds, [("npm run build", 2), ("npm run build", 0)])
        self.assertEqual(meta["delegations"][0]["results"], ["interrupted"] * 4)
        os.environ["HERMES_HOME"] = str(db.parent)
        os.environ["HERMES_SESSION_ID"] = "S2"
        self.assertEqual(autopsy.latest_source(self.root), db)                       # inside Hermes: this very session
        rep = autopsy.autopsy(self.root, str(db), session="S2")                      # D11: the plain autopsy reads Hermes too
        self.assertEqual(rep["kind"], "hermes-db")
        self.assertEqual(rep["summary"]["failures"], 1)

    def test_workflow_autopsy_finds_late_questions_direction_changes_and_lost_messages(self):
        db = self.build()
        code, out = self.dh("autopsy", "--workflow", str(db), "--session", "S2")
        self.assertEqual(code, 0, out)
        rep = read_json(Path(out["report"]).with_suffix(".json"))
        led = rep["questions"]["ledger"]
        kinds = [(q["kind"], q["flags"]) for q in led]
        self.assertEqual(kinds[0], ("define", []))
        self.assertEqual(kinds[1], ("gate", ["DIRECTION-CHANGE"]))                   # "make it like a real business" is not a go
        self.assertEqual(kinds[2], ("late", ["LATE", "DIRECTION-CHANGE"]))
        self.assertEqual(rep["questions"]["lost"][0]["message"], "run the try on")
        self.assertEqual(rep["timeline"]["gates"][0]["flag"], "PARAPHRASED: passed without the owner's own words")
        self.assertIn("gate G1 passed without the owner's words", rep["maintainer"][0]["what"])
        p1 = rep["proposals"][0]
        self.assertEqual((p1["target"], p1["rung"]), ("ask_upfront", "reorder"))
        self.assertIn("real address", p1["change"])
        self.assertTrue(any(p["target"] == "delegate" for p in rep["proposals"]))
        self.assertIn("dh workflow save --from-autopsy " + out["id"], out["ask_owner"])
        self.assertIn("[1] my workflows", out["ask_owner"])
        md = Path(out["report"]).read_text(encoding="utf-8")
        self.assertIn("LATE DIRECTION-CHANGE", md)
        # one section for a sub-agent, and the same input gives the same report
        code, part = self.dh("autopsy", "--workflow", str(db), "--session", "S2", "--part", "questions")
        self.assertEqual((part["id"], part["part"]), (out["id"], "questions"))
        self.assertEqual(part["questions"]["late"], 1)
        # it never touches the skill
        self.assertFalse(list((SKILL / "workflows").glob("*cleankit*")))

    def test_accepted_proposals_make_the_next_version(self):
        db = self.build()
        self.mine(tiny("cleaning-flow"))
        self.dh("workflow", "use", "mine:cleaning-flow")
        code, out = self.dh("autopsy", "--workflow", str(db), "--session", "S2")
        code, saved = self.dh("workflow", "save", "--from-autopsy", out["id"], "--proposals", "P1")
        self.assertEqual(code, 0, saved)
        wf = read_json(Path(saved["saved"]))
        self.assertEqual(wf["version"], 2)
        learned = [q for q in wf["ask_upfront"] if q["id"].startswith("Q-learned")]
        self.assertEqual(len(learned), 1)
        self.assertIn("real address", learned[0]["q"])
        self.assertIn("Q-learned-2", wf["phases"][0]["steps"][1]["ask"])            # asked in the define round from now on
        self.assertEqual(wf["proof"]["runs"][-1]["autopsy"], out["id"])
        self.assertIn(out["id"], wf["changelog"][-1]["evidence"])
        code, bad = self.dh("workflow", "save", "--from-autopsy", out["id"], "--proposals", "P99")
        self.assertEqual(bad["code"], "NO_SUCH_PROPOSAL")

    def test_chat_logs_from_any_harness(self):
        state.init(self.root, "X", "phased", "scratch")
        log = self.tmp / "chat.jsonl"
        log.write_text("\n".join(json.dumps(x) for x in ({"role": "assistant", "content": "Which languages?"}, {"role": "user", "content": "fr"})) + "\n",
                       encoding="utf-8")
        self.assertEqual(autopsy.detect(log), "chat")
        rep = wfautopsy.run(self.root, str(log))
        self.assertEqual(rep["summary"]["questions"], 1)


if __name__ == "__main__":
    unittest.main()
