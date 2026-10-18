"""Harborforge lab regressions: source-copied suite with isolated home."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dhlib import hooks, ops, state
from dhlib.util import DhError, write_json


class LabRegressions(unittest.TestCase):
    def test_skill_is_separately_named_and_tryon_is_optional(self):
        self.assertIn("name: harborforge", (ROOT / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue(next(p for p in state.PHASES if p["id"] == "tryon")["optional"])

    def test_deploy_guard_handles_current_and_legacy_state(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            project.mkdir()
            with mock.patch.dict(os.environ, {"DECKHAND_HOME": str(project.parent / "hf-state")}):
                state.init(project, "Bakery", "phased", "pool")
            for key in ("app_uuid", "app"):
                write_json(project / ".deckhand" / "deploy.json", {key: "uuid", "url": "https://example.invalid"})
                self.assertTrue(hooks._g4_owed(project), key)

    def test_workflow_only_bots_rejected_without_side_effects(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for runner in ("cron", "hermes", "local"):
                with self.assertRaises(DhError) as raised:
                    ops.add(root, "deps-audit", runner)
                self.assertEqual(raised.exception.code, "UNSUPPORTED_BOT_RUNNER")
                self.assertFalse((root / "ops").exists())


if __name__ == "__main__":
    unittest.main()
