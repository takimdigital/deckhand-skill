"""F6 (foundation audit 2026-10-06): what launch needs from the owner is asked at define, not discovered at deploy.

A server and a domain take the owner time (an account, a payment, DNS that can need a day). When define closes, every
missing launch prerequisite becomes a PENDING item at once, so it is done in parallel with research, plan and build.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import hermetic  # noqa: E402,F401
import tmpclean  # noqa: E402

from dhlib import pending, profile, state  # noqa: E402
from dhlib.cli import main  # noqa: E402


class LaunchAsksAtDefine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "COOLIFY_URL")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ.pop("COOLIFY_URL", None)
        self.root = self.tmp / "p"
        state.init(self.root, "Bakery", "phased", "pool")

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
            code = main([*args, "--project", str(self.root)])
        return code, json.loads(buf.getvalue())

    def brief(self, **extra):
        pairs = ["business=bread", "shape=leadgen", "languages=en", "audience=locals", *[f"{k}={v}" for k, v in extra.items()]]
        self.assertEqual(self.dh("brief", "set", *pairs)[0], 0)

    def open_items(self):
        return [i["what"] for i in pending.items(self.root / "PENDING.md") if i["open"]]

    def test_server_and_domain_become_pending_when_define_closes(self):
        self.brief()
        code, out = self.dh("phase", "done", "define")
        self.assertEqual(code, 0, out)
        items = " | ".join(self.open_items()).lower()
        self.assertIn("server", items)
        self.assertIn("domain", items)
        self.assertEqual(len(out["launch"]["asked"]), 2)

    def test_what_is_already_there_is_not_asked(self):
        self.brief(domain="goldencrust.test")
        profile.set_fields(["vps.ip=203.0.113.7", "coolify.url=https://coolify.goldencrust.test"], where="machine")
        profile.vault_set("COOLIFY_TOKEN", "1|abcdefghijklmnopqrstuvwxyz0123456789", where="machine")
        code, out = self.dh("phase", "done", "define")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["launch"]["asked"], [])
        self.assertEqual(self.open_items(), [])

    def test_asking_twice_adds_nothing_twice(self):
        self.brief()
        self.dh("phase", "done", "define")
        self.dh("reopen", "define", "--reason", "owner changed the audience")
        self.dh("phase", "done", "define")
        self.assertEqual(len(self.open_items()), 2)


if __name__ == "__main__":
    unittest.main()
