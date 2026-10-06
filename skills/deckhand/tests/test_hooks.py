"""HOOKS: deckhand guards its own records and feeds its learning loop from the harness itself.

`dh hook pre|post|start|stop --harness H` — stdin is the harness's own hook JSON (recorded shapes below, from each
harness's documentation, checked 2026-10-06). One policy, six harnesses; outside a deckhand project nothing happens.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import hooks, profile, state  # noqa: E402
from dhlib.util import read_jsonl, write_json  # noqa: E402

SECRET = "re_supersecretvalue123456"


def write_payload(h, path, content):
    """A file write, as each harness sends it."""
    return {
        "claude-code": {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}},
        "codex": {"tool_name": "apply_patch", "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n+{content}\n*** End Patch"}},
        "gemini-cli": {"tool_name": "write_file", "tool_input": {"file_path": path, "content": content}},
        "cursor": {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}},
        "hermes": {"tool_name": "write_file", "tool_input": {"path": path, "content": content}},
        "opencode": {"tool_name": "write", "tool_input": {"filePath": path, "content": content}},
    }[h]


def shell_payload(h, cmd):
    return {"claude-code": "Bash", "codex": "Bash", "gemini-cli": "run_shell_command", "cursor": "Shell",
            "hermes": "terminal", "opencode": "bash"}[h], {"command": cmd}


HARNESSES = ("claude-code", "codex", "gemini-cli", "cursor", "hermes", "opencode")


class HookBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        state.init(self.root, "Bakery", "phased", "pool")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        tmpclean.rmtree(self.tmp)

    def call(self, event, h, payload):
        return hooks.handle(event, json.dumps({"cwd": str(self.root), **payload}), h)

    def pre_write(self, h, path, content="x"):
        return self.call("pre", h, write_payload(h, path, content))

    def pre_shell(self, h, cmd):
        tool, inp = shell_payload(h, cmd)
        return self.call("pre", h, {"tool_name": tool, "tool_input": inp})


class Guard(HookBase):
    def test_a_hand_edit_of_the_run_state_is_blocked_in_every_harness(self):
        for h in HARNESSES:
            for path in (str(self.root / ".deckhand" / "run.json"), ".deckhand/verify.json"):
                code, out, err = self.pre_write(h, path, "{}")
                self.assertEqual(code, 2, (h, path))
                self.assertIn("deckhand's own record", err)

    def test_shell_writes_onto_the_records_are_blocked(self):
        for cmd in ("echo {} > .deckhand/run.json", "sed -i s/pending/done/ .deckhand/run.json", "cp x.json .deckhand/deploy.json"):
            self.assertEqual(self.pre_shell("claude-code", cmd)[0], 2, cmd)

    def test_reading_the_records_is_fine(self):
        for cmd in ("cat .deckhand/run.json", "git diff .deckhand/run.json", "dh phase done define"):
            self.assertEqual(self.pre_shell("hermes", cmd)[0], 0, cmd)

    def test_ordinary_work_passes(self):
        for h in HARNESSES:
            code, out, _ = self.pre_write(h, str(self.root / "app" / "page.tsx"), "export default 1")
            self.assertEqual(code, 0, h)

    def test_cursor_pass_is_an_explicit_allow(self):
        _, out, _ = self.pre_write("cursor", str(self.root / "a.ts"))
        self.assertEqual(json.loads(out), {"permission": "allow"})          # empty output would BLOCK in Cursor

    def test_cursor_block_shape(self):
        code, out, _ = self.pre_write("cursor", ".deckhand/run.json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["permission"], "deny")

    def test_git_push_is_blocked_only_while_g4_is_owed_and_autodeploy_is_wired(self):
        self.assertEqual(self.pre_shell("claude-code", "git push origin main")[0], 0)
        write_json(self.root / ".deckhand" / "deploy.json", {"app": "abc", "url": "https://x.test"})
        self.assertEqual(self.pre_shell("claude-code", "git add . && git push origin main")[0], 2)
        s = state.load(self.root)
        s["gates"]["G4"] = {"status": "passed", "by": "owner"}
        state.save(self.root, s)
        self.assertEqual(self.pre_shell("claude-code", "git push origin main")[0], 0)

    def test_a_vault_value_in_a_write_is_blocked_and_never_echoed(self):
        profile.vault_set("RESEND_API_KEY", SECRET, where="machine")
        for h in HARNESSES:
            code, out, err = self.pre_write(h, str(self.root / "lib" / "mail.ts"), f"const k = '{SECRET}'")
            self.assertEqual(code, 2, h)
            self.assertNotIn(SECRET, out + err)

    def test_outside_a_project_nothing_happens(self):
        other = self.tmp / "elsewhere"
        other.mkdir()
        payload = {"cwd": str(other), **write_payload("claude-code", str(other / ".deckhand" / "run.json"), "{}")}
        self.assertEqual(hooks.handle("pre", json.dumps(payload), "claude-code"), (0, "", ""))

    def test_garbage_never_raises(self):
        for stdin in ("{not json", "[]", "", "null"):
            self.assertEqual(hooks.handle("pre", stdin, "claude-code")[0], 0)


class Observe(HookBase):
    def runs(self):
        return read_jsonl(self.root / ".deckhand" / "runs.jsonl")

    def test_shell_commands_land_in_the_run_log(self):
        cases = {
            "claude-code": {"tool_response": {"stdout": "error TS2304: Cannot find name 'x'", "stderr": ""}},
            "cursor": {"tool_output": json.dumps({"exitCode": 1, "stdout": "error TS2304"})},
            "hermes": {"extra": {"result": "npm ERR! missing script", "status": "error"}},
        }
        for h, extra in cases.items():
            tool, inp = shell_payload(h, f"npm run build-{h}")
            self.call("post", h, {"tool_name": tool, "tool_input": inp, **extra})
        cmds = [r["cmd"] for r in self.runs()]
        for h in cases:
            self.assertIn(f"npm run build-{h}", cmds)
        cursor = next(r for r in self.runs() if r["cmd"].endswith("cursor"))
        self.assertEqual(cursor["exit"], 1)

    def test_dh_commands_are_not_logged_twice(self):
        tool, inp = shell_payload("claude-code", "dh next")
        self.call("post", "claude-code", {"tool_name": tool, "tool_input": inp})
        self.assertEqual(self.runs(), [])

    def test_a_secret_in_the_output_is_scrubbed(self):
        profile.vault_set("RESEND_API_KEY", SECRET, where="machine")
        tool, inp = shell_payload("claude-code", "printenv")
        self.call("post", "claude-code", {"tool_name": tool, "tool_input": inp, "tool_response": {"stdout": f"KEY={SECRET}"}})
        self.assertNotIn(SECRET, (self.root / ".deckhand" / "runs.jsonl").read_text(encoding="utf-8"))


class Start(HookBase):
    def test_each_harness_gets_its_own_shape(self):
        _, out, _ = self.call("start", "claude-code", {})
        self.assertIn("Deckhand project detected", out)
        _, out, _ = self.call("start", "hermes", {"extra": {"is_first_turn": True}})
        self.assertIn("Deckhand project detected", json.loads(out)["context"])
        _, out, _ = self.call("start", "gemini-cli", {})
        self.assertIn("Deckhand", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        _, out, _ = self.call("start", "cursor", {})
        self.assertIn("Deckhand", json.loads(out)["additional_context"])

    def test_hermes_injects_once_not_every_turn(self):
        self.assertEqual(self.call("start", "hermes", {"extra": {"is_first_turn": False}}), (0, "", ""))


class Stop(HookBase):
    def unsafe(self):
        (self.root / "app.ts").write_text("x", encoding="utf-8")
        import subprocess as sp
        sp.run(["git", "init", "-q"], cwd=self.root)
        sp.run(["git", "add", "-A"], cwd=self.root)
        sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], cwd=self.root)
        time.sleep(0.05)
        (self.root / "app.ts").write_text("changed", encoding="utf-8")

    def test_stopping_with_unexplained_edits_asks_for_a_note_once(self):
        self.unsafe()
        code, _, err = self.call("stop", "claude-code", {})
        self.assertEqual(code, 2)
        self.assertIn("dh note doing", err)
        self.assertEqual(self.call("stop", "claude-code", {})[0], 0)          # nagged: not again for 10 minutes

    def test_never_loops(self):
        self.unsafe()
        self.assertEqual(self.call("stop", "claude-code", {"stop_hook_active": True})[0], 0)
        self.assertEqual(self.call("stop", "cursor", {"loop_count": 1})[0], 0)

    def test_cursor_stop_is_a_followup_message(self):
        self.unsafe()
        code, out, _ = self.call("stop", "cursor", {"loop_count": 0})
        self.assertEqual(code, 0)
        self.assertIn("dh note doing", json.loads(out)["followup_message"])

    def test_a_safe_project_stops_quietly(self):
        self.assertEqual(self.call("stop", "claude-code", {}), (0, "", ""))


class Cli(HookBase):
    def test_dh_hook_end_to_end_and_fast(self):
        payload = json.dumps({"cwd": str(self.root), **write_payload("claude-code", ".deckhand/run.json", "{}")})
        t0 = time.time()
        r = subprocess.run([sys.executable, str(SKILL / "dh.py"), "hook", "pre", "--harness", "claude-code"], input=payload,
                           capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("deckhand's own record", r.stderr)
        self.assertLess(time.time() - t0, 3.0)                                 # generous for CI; ~0.2 s locally


if __name__ == "__main__":
    unittest.main()
