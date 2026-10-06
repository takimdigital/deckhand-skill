"""`dh harness detect|install|doctor|uninstall` — the hooks written into each harness's own configuration.

Merged, idempotent, other hooks kept, `--dry` writes nothing; Hermes' config.yaml is never edited (its block is printed
for the owner); OpenCode gets a small plugin file that calls the same `dh hook`.
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

from dhlib import harness  # noqa: E402
from dhlib.util import DhError, read_json, write_json  # noqa: E402

FOREIGN = {"type": "command", "command": "echo mine"}


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "DH_HARNESS_HOME")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "dhome")
        os.environ["DH_HARNESS_HOME"] = str(self.tmp / "home")       # every ~ in a config path resolves here in tests

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tmpclean.rmtree(self.tmp)

    def cfg(self, h):
        return harness.config_path(h)

    def ours(self, data, event):
        return [x for e in data["hooks"].get(event, []) for x in e.get("hooks", [e]) if "dh.py" in x.get("command", "")]

    def test_json_harnesses_get_one_entry_per_event_idempotently(self):
        for h, events in (("claude-code", ("PreToolUse", "PostToolUse", "SessionStart", "Stop")),
                          ("codex", ("PreToolUse", "PostToolUse", "SessionStart", "Stop")),
                          ("gemini-cli", ("BeforeTool", "AfterTool", "SessionStart", "AfterAgent"))):
            harness.install(h)
            harness.install(h)
            data = read_json(self.cfg(h))
            for ev in events:
                self.assertEqual(len(self.ours(data, ev)), 1, (h, ev))
            self.assertIn(f"hook pre --harness {h}", self.ours(data, events[0])[0]["command"])

    def test_foreign_hooks_survive_install_and_uninstall(self):
        p = self.cfg("claude-code")
        write_json(p, {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [FOREIGN]}]}})
        harness.install("claude-code")
        harness.uninstall("claude-code")
        data = read_json(p)
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": [FOREIGN]}])
        self.assertNotIn("Stop", data["hooks"])

    def test_the_old_resume_hook_is_replaced_not_doubled(self):
        p = self.cfg("claude-code")
        write_json(p, {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": 'py "x/dh.py" resume --hook'}]}]}})
        harness.install("claude-code")
        cmds = [x["command"] for e in read_json(p)["hooks"]["SessionStart"] for x in e["hooks"]]
        self.assertEqual(len(cmds), 1)
        self.assertIn("hook start", cmds[0])

    def test_dry_writes_nothing(self):
        out = harness.install("claude-code", dry=True)
        self.assertFalse(self.cfg("claude-code").exists())
        self.assertIn("PreToolUse", json.dumps(out["would_write"]))

    def test_unreadable_settings_are_never_overwritten(self):
        p = self.cfg("claude-code")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(DhError) as e:
            harness.install("claude-code")
        self.assertEqual(e.exception.code, "BAD_SETTINGS")
        self.assertEqual(p.read_text(encoding="utf-8"), "{ broken")

    def test_cursor_shape(self):
        harness.install("cursor")
        data = read_json(self.cfg("cursor"))
        self.assertEqual(data["version"], 1)
        self.assertIn("hook pre --harness cursor", data["hooks"]["preToolUse"][0]["command"])

    def test_opencode_gets_a_plugin_file_calling_dh_hook(self):
        harness.install("opencode")
        js = self.cfg("opencode").read_text(encoding="utf-8")
        self.assertIn("tool.execute.before", js)
        self.assertIn("--harness", js)
        self.assertNotIn("__DH__", js)
        harness.uninstall("opencode")
        self.assertFalse(self.cfg("opencode").exists())

    def test_hermes_is_printed_never_written(self):
        out = harness.install("hermes")
        self.assertIn("pre_tool_call", out["paste"])
        self.assertIn("hook pre --harness hermes", out["paste"])
        self.assertIn("hermes hooks doctor", out["verify"])
        self.assertFalse((self.tmp / "home" / ".hermes").exists())

    def test_doctor_proves_the_guard_end_to_end(self):
        harness.install("claude-code")
        d = harness.doctor("claude-code")
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["guard"]["exit"], 2)
        self.assertTrue(all(e["installed"] for e in d["events"].values()))

    def test_doctor_says_what_is_missing(self):
        d = harness.doctor("codex")
        self.assertFalse(d["ok"])
        self.assertIn("dh harness install", d["fix"])

    def test_unknown_harness_is_a_clear_error(self):
        with self.assertRaises(DhError) as e:
            harness.install("unknown")
        self.assertEqual(e.exception.code, "NO_HOOKS")


if __name__ == "__main__":
    unittest.main()
