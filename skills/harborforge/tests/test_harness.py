"""Harness support is data: every harness gets every line (its own row, else `unknown`'s); no harness tool name is
hard-coded in dhlib; Hermes' own tools are named; Hermes cron bots and .hermes.md are supported."""
import ast
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
from dhlib import guide, workflow  # noqa: E402
from dhlib.util import read_json  # noqa: E402

DATA = read_json(SKILL / "data" / "harness.json", {})
ROWS = [k for k in DATA if k != "why"]
TOOL_NAMES = ("TodoWrite", "todo_list", "delegate_task", "run_in_background", "process_manage", "cronjob", "browser_navigate",
              "vision_analyze", "execute_code", "skill_view", "session_search")
PARSERS = {"autopsy.py", "wfautopsy.py"}          # they PARSE transcripts that contain these names


class Harness(unittest.TestCase):
    def test_every_phase_key_resolves_for_every_harness(self):
        for name in ROWS:
            with mock.patch.object(workflow, "harness", return_value=name):
                for phase, want in guide.HARNESS_KEYS.items():
                    got = guide.harness_notes(phase)
                    self.assertTrue(got and all(got.get(k) for k in want), (name, phase, got))

    def test_every_detected_harness_has_a_row(self):
        src = (SKILL / "dhlib" / "workflow.py").read_text(encoding="utf-8")
        body = src[src.index("def harness()"):]
        body = body[:body.index("\ndef ", 1)]
        import re
        names = set(re.findall(r'return "([a-z-]+)"', body)) - {"unknown"}
        self.assertEqual(names - set(ROWS), set())

    def test_no_harness_tool_name_is_hard_coded_in_dhlib(self):
        bad = []
        for f in (SKILL / "dhlib").glob("*.py"):
            if f.name in PARSERS:
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                    bad += [f"{f.name}:{n.lineno} {t}" for t in TOOL_NAMES if t in n.value]
        self.assertEqual(bad, [], "harness syntax lives in data/harness.json (read it with guide.harness_row)")

    def test_hermes_row_names_its_real_tools(self):
        h = DATA["hermes"]
        self.assertIn("todo_list", h["todo"])
        self.assertIn("cronjob", h["cron"])
        self.assertIn(".hermes.md", h["context"])
        self.assertIn("HERMES_HOME", h["install"])

    def test_todo_how_and_the_plan_browser_line_follow_the_harness(self):
        for name, word in (("hermes", "todo_list"), ("claude-code", "TodoWrite")):
            with mock.patch.object(workflow, "harness", return_value=name):
                self.assertIn(word, workflow.todo_how())
        with mock.patch.object(workflow, "harness", return_value="hermes"):
            self.assertIn("browser_navigate", guide.harness_row()["browser"])
        with mock.patch.object(workflow, "harness", return_value="claude-code"):
            self.assertNotIn("browser_navigate", guide.harness_row()["browser"])

    def test_a_named_harness_gets_every_unknown_line_it_does_not_override(self):
        with mock.patch.object(workflow, "harness", return_value="cursor"):
            row = guide.harness_row()
        self.assertEqual(row["background"], DATA["cursor"]["background"])          # its own
        for k in DATA["unknown"]:
            self.assertTrue(row.get(k), k)                                          # the rest from unknown


class HermesFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "dh"), "HERMES_HOME": str(self.tmp / "hh")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        tmpclean.rmtree(self.tmp)

    def test_hermes_md_wins_over_agents_md_so_it_carries_the_resume_block_too(self):
        from dhlib import resume
        root = self.tmp / "site"
        root.mkdir()
        (root / ".hermes.md").write_text("# owner rules\nAlways answer in French.\n", encoding="utf-8")
        resume.agent_entry(root)
        text = (root / ".hermes.md").read_text(encoding="utf-8")
        self.assertIn("Always answer in French.", text)
        self.assertIn("dh resume", text)
        self.assertTrue((root / "AGENTS.md").exists())

    def test_no_hermes_md_is_created_when_the_owner_has_none(self):
        from dhlib import resume
        root = self.tmp / "site2"
        root.mkdir()
        resume.agent_entry(root)
        self.assertFalse((root / ".hermes.md").exists())

    def test_ops_hermes_runner_writes_a_script_in_HERMES_HOME_and_a_no_agent_cron_call(self):
        import py_compile
        from dhlib import ops, state
        root = self.tmp / "site3"
        root.mkdir()
        state.init(root, "site3", "auto", "scratch")
        r = ops.add(root, "watchdog", "hermes")
        w = self.tmp / "hh" / "scripts" / r["hermes_cron"]["script"]
        self.assertTrue(w.is_file(), r)
        py_compile.compile(str(w), doraise=True)
        self.assertTrue(r["hermes_cron"]["no_agent"])
        self.assertEqual(r["hermes_cron"]["action"], "create")
        self.assertEqual(r["hermes_cron"]["schedule"], "*/15 * * * *")
        self.assertNotIn("TOKEN=", w.read_text(encoding="utf-8"))            # secret NAMES only, never a value

    def test_ops_hermes_runner_outside_hermes_is_refused_with_the_other_runners_named(self):
        from dhlib import ops, state
        from dhlib.util import DhError
        root = self.tmp / "site4"
        root.mkdir()
        state.init(root, "site4", "auto", "scratch")
        os.environ.pop("HERMES_HOME", None)
        with self.assertRaises(DhError) as e:
            ops.add(root, "watchdog", "hermes")
        self.assertEqual(e.exception.code, "NOT_HERMES")

    def test_notify_stdout_mode_prints_instead_of_sending(self):
        import importlib.util
        import io
        from contextlib import redirect_stdout
        spec = importlib.util.spec_from_file_location("notify", SKILL / "templates" / "bots" / "notify.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"DECKHAND_NOTIFY": "stdout"}), redirect_stdout(buf):
            self.assertEqual(m.deliver("site down", "watchdog"), ["stdout"])
        self.assertIn("site down", buf.getvalue())

    def test_the_installers_update_every_hermes_profile(self):
        root = SKILL.parent.parent
        for f in ("install.ps1", "install.sh"):
            text = (root / f).read_text(encoding="utf-8")
            self.assertIn("HERMES_HOME", text, f)
            self.assertIn("profiles", text, f)


if __name__ == "__main__":
    unittest.main()
