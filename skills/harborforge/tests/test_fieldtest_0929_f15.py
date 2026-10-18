"""Field test 2026-09-29, findings that were left open: F15."""
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))

from dhlib import guide, workflow  # noqa: E402
from dhlib.cli import build_parser  # noqa: E402
from dhlib.util import read_json  # noqa: E402

ENV_KEYS = ("HERMES_AGENT", "HERMES_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CURSOR_TRACE_ID",
            "CURSOR_AGENT", "GEMINI_CLI", "OPENCODE", "OPENCODE_SESSION")


class F15Harness(unittest.TestCase):
    def detect(self, **env):
        clean = {k: v for k, v in os.environ.items() if k not in ENV_KEYS and not k.startswith("CODEX_")}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            return workflow.harness(), guide.harness_notes("build")

    def test_F15_gemini_cli_and_opencode_get_their_own_harness_row(self):
        data = read_json(SKILL / "data" / "harness.json", {})
        for var, name in (("GEMINI_CLI", "gemini-cli"), ("OPENCODE", "opencode")):
            got, notes = self.detect(**{var: "1"})
            self.assertEqual(got, name)
            self.assertIn(name, data, f"data/harness.json has no `{name}` row: dh next falls back to `unknown`")
            self.assertNotEqual(data[name], data["unknown"], f"`{name}` row is a copy of `unknown`")
            for k in ("background", "delegate", "todo", "transcript"):        # every key `unknown` answers, this row answers too
                self.assertTrue(data[name].get(k), f"{name}.{k} is empty")

    def test_F15_every_detected_harness_has_a_row(self):
        src = (SKILL / "dhlib" / "workflow.py").read_text(encoding="utf-8")
        body = src[src.index("def harness()"):]
        body = body[:body.index("\ndef ", 1)]
        names = set(re.findall(r'return "([a-z-]+)"', body)) - {"unknown"}
        rows = set(read_json(SKILL / "data" / "harness.json", {}))
        self.assertEqual(names - rows, set())


if __name__ == "__main__":
    unittest.main()
