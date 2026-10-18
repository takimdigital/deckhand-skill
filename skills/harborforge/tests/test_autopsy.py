"""dh autopsy — deterministic session analysis (stdlib unittest)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)

from dhlib import autopsy as AU, learn  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import read_jsonl  # noqa: E402


def transcript(steps, cwd="/work/shop"):
    """A Claude Code JSONL: each step is (tool, input, output, is_error)."""
    lines = []
    for n, (tool, inp, out, err) in enumerate(steps):
        uid = f"toolu_{n:03d}"
        lines.append({"type": "assistant", "cwd": cwd, "sessionId": "s-1", "message": {"content": [{"type": "tool_use", "id": uid, "name": tool, "input": inp}]}})
        lines.append({"type": "user", "cwd": cwd, "sessionId": "s-1", "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": out, "is_error": err}]}})
    return "".join(json.dumps(l) + "\n" for l in lines)


B = lambda cmd, out="", code=0: ("Bash", {"command": cmd}, (f"Exit code {code}\n" if code else "") + out, bool(code))  # noqa: E731
E = lambda path: ("Edit", {"file_path": path}, "The file has been updated.", False)  # noqa: E731

SESSION = [
    B("ls app && cat package.json"),
    B("npm run build 2>&1 | tail -20", "Failed to compile.\nModule not found: Can't resolve 'lucide-react' in '/work/shop/app'", 1),
    B("npm install lucide-react", "added 1 package"),
    B("npm run build 2>&1 | tail -5", "Compiled successfully"),
    B("grep -rn TODO app", "", 1),                                               # grep with no match is an answer
    B("python3 -c 'import json; json.load(open(\"x\"))'", "Traceback (most recent call last):\nFileNotFoundError", 1),   # scratch
    B("node --test skills/deckhand/tryon/test/*.test.mjs 2>&1 | tail -3", "not ok 3 - bake keeps the owner copy\n# pass 30\n# fail 1"),
    E("/work/shop/skills/deckhand/tryon/lib/engine.mjs"),
    B("node --test skills/deckhand/tryon/test/*.test.mjs 2>&1 | tail -3", "# pass 31\n# fail 0"),
    B("pkill -f 'next dev'", "", 144),
    B("pkill -f 'next dev'", "", 144),
    ("Edit", {"file_path": "/work/shop/app/page.tsx"}, "<tool_use_error>String to replace not found in file.</tool_use_error>", True),
    B("npx prisma migrate deploy", "Error: P1001: Can't reach database server at `localhost:5432`", 1),
    B("npm install zod && python3 /skill/dh.py compose --sections hero", '{"ok": true}'),
    B("python3 /skill/dh.py phase done build", '{"ok": true, "phase": "build"}'),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        (self.root / ".deckhand").mkdir(parents=True)
        self.src = self.tmp / "session.jsonl"
        self.src.write_text(transcript(SESSION), encoding="utf-8")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)


class Analysis(Base):
    def rep(self):
        events, meta = AU.load_claude(self.src)
        return AU.analyze(events, meta, [])

    def ep(self, rep, needle):
        return next(e for e in rep["episodes"] if needle in e["signature"])

    def test_failures_include_the_ones_a_pipe_hid_and_exclude_answers_and_scratch(self):
        rep = self.rep()
        self.assertEqual(rep["failures"], 5)              # build, masked test, 2x pkill, prisma — not grep, not the scratch script
        self.assertEqual(rep["masked_failures"], 1)
        self.assertEqual(rep["tool_errors"], [{"tool": "Edit", "signature": "<tool_use_error>String to replace not found in file.</tool_use_error>", "count": 1}])

    def test_the_working_recipe_owner_and_rung_come_from_evidence(self):
        rep = self.rep()
        b = self.ep(rep, "Module not found")
        self.assertEqual((b["owner"], b["rung"], b["resolved"]), ("project", "eliminate", True))
        self.assertEqual([tuple(x) for x in b["recipe"]], [("run", "npm install lucide-react")])
        t = self.ep(rep, "not ok")
        self.assertEqual((t["owner"], t["rung"], t["test_in_fix"], t["masked"]), ("skill", "eliminate", True, True))
        self.assertEqual([tuple(x) for x in t["recipe"]], [("edit", "<project>/skills/deckhand/tryon/lib/engine.mjs")])
        k = self.ep(rep, "killed by signal")
        self.assertEqual((k["owner"], k["rung"], k["attempts"]), ("environment", "preflight", 2))
        p = self.ep(rep, "reach database")
        self.assertEqual((p["resolved"], p["rung"], p["recipe"]), (False, "gate", []))

    def test_same_session_same_bytes(self):
        a = json.dumps(self.rep(), sort_keys=True)
        b = json.dumps(self.rep(), sort_keys=True)
        self.assertEqual(a, b)
        r1 = AU.autopsy(self.root, str(self.src))
        md1 = Path(r1["report"]).read_bytes()
        r2 = AU.autopsy(self.root, str(self.src))
        self.assertEqual(Path(r2["report"]).read_bytes(), md1)
        self.assertIn("what fixed it", md1.decode())

    def test_a_known_lesson_that_recurs_climbs_the_ladder(self):
        events, meta = AU.load_claude(self.src)
        rep = AU.analyze(events, meta, [{"id": "L-0001", "signature": r"Module not found", "rung": "eliminate"}])
        self.assertEqual(self.ep(rep, "Module not found")["known"], ["L-0001"])
        rep = AU.analyze(events, meta, [{"id": "L-0002", "signature": r"reach database server", "rung": "pitfall"}])
        p = self.ep(rep, "reach database")
        self.assertEqual(p["rung"], "gate")
        self.assertIn("happened again", p["why"])

    def test_playbooks_are_the_actions_that_finished_a_phase_fixes_included(self):
        # the fix found mid-way (npm install lucide-react) is part of the workflow: next time it runs up front
        self.assertEqual(self.rep()["playbooks"], [{"phase": "build", "steps": [
            "npm install lucide-react", "npm install zod && python3 /skill/dh.py compose --sections hero"]}])


class Apply(Base):
    def test_apply_writes_lessons_with_recipes_proposals_and_playbooks_never_the_skill(self):
        before = {p: p.stat().st_mtime for p in SKILL.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        r = AU.autopsy(self.root, str(self.src), apply=True)
        ap = r["applied"]
        self.assertEqual(len(ap["lessons"]), 1)
        les = read_jsonl(Path(os.environ["DECKHAND_HOME"]) / "lessons.jsonl")
        self.assertEqual(les[0]["recipe"], [["run", "npm install lucide-react"]])
        self.assertTrue(les[0]["auto"])
        hit = learn.match(None, "Module not found: Can't resolve 'lucide-react' in '/other/app'")
        self.assertEqual(hit[0]["recipe"], [["run", "npm install lucide-react"]])
        prop = Path(ap["proposals"][0]).read_text(encoding="utf-8")
        self.assertIn("## Repro", prop)
        self.assertIn("present in the fix", prop)
        self.assertEqual(ap["playbooks"][0]["phase"], "build")
        after = {p: p.stat().st_mtime for p in SKILL.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p in before}
        self.assertEqual(before, after)                          # the autopsy proposes; it never edits the skill


class Runs(Base):
    def test_dh_run_logs_every_command_and_replays_a_proven_auto_recipe(self):
        script = self.root / "check.py"
        script.write_text("import os, sys\nif not os.path.exists('ready.flag'):\n    print('MISSING READY FLAG'); sys.exit(1)\nprint('ok')\n", encoding="utf-8")
        r = learn.run_cmd(self.root, [sys.executable, str(script)])
        self.assertFalse(r["ok"])
        touch = "mkdir ready.flag"            # not `touch`: cmd.exe has none (field test F1); mkdir quotes nothing in either shell
        learn.add(None, "build", "MISSING READY FLAG", "not prepared", "create the flag", signature="MISSING READY FLAG",
                  extra={"recipe": [["run", touch]], "auto": True})
        r = learn.run_cmd(self.root, [sys.executable, str(script)], fix=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["replayed"], [{"run": touch, "exit": 0}])
        runs = read_jsonl(self.root / ".deckhand" / "runs.jsonl")
        self.assertEqual([x["exit"] for x in runs], [1, 1, 0, 0])
        rep = AU.autopsy(self.root)                              # default source: the harness-neutral run log
        self.assertEqual(rep["kind"], "runs")
        self.assertEqual(rep["episodes"][0]["resolved"], True)

    def test_every_dh_call_is_logged_for_the_autopsy(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--project", str(self.root), "learn", "list"])
        self.assertTrue(any(x["cmd"].startswith("dh --project") and "learn list" in x["cmd"] for x in read_jsonl(self.root / ".deckhand" / "runs.jsonl")))


class Next(Base):
    def test_a_workflow_confirmed_by_two_sessions_is_shown_by_dh_next(self):
        from dhlib import guide, state
        state.init(self.root, "Shop", "phased", "scratch")
        r1 = AU.autopsy(self.root, str(self.src), apply=True)
        self.assertNotIn("worked_before", guide.next_step(self.root))          # one session is an anecdote
        other = self.tmp / "session2.jsonl"
        other.write_text(transcript(SESSION) + "\n", encoding="utf-8")                          # a second session, same workflow
        AU.autopsy(self.root, str(other), apply=True)
        self.assertTrue(r1["applied"]["playbooks"])
        rows = read_jsonl(Path(os.environ["DECKHAND_HOME"]) / "playbooks.jsonl")
        self.assertEqual([(r["phase"], r["seen"]) for r in rows], [("build", 2)])
        self.assertEqual(guide._playbook("build"), ["npm install lucide-react", "npm install zod && python3 /skill/dh.py compose --sections hero"])


if __name__ == "__main__":
    unittest.main()
