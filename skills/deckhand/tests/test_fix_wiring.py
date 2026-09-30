"""Wiring of the shared scrubber into the free-text writers that live outside the learning loop (B6).

`bb post`, `brief set` and `pending add` used to write a stored secret straight to disk (and echo it on stdout).
Only FAKE secrets are used.
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
import tmpclean  # noqa: E402

from dhlib import profile as PROFILE, state  # noqa: E402
from dhlib.cli import main  # noqa: E402

FAKE = "FAKE-SECRET-123456"


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "DECKHAND_OFFLINE", "HERMES_SESSION_ID")}
        self.home = self.tmp / "home"
        self.home.mkdir()
        os.environ["DECKHAND_HOME"] = str(self.home)
        os.environ["DECKHAND_OFFLINE"] = "1"
        os.environ.pop("HERMES_SESSION_ID", None)
        self.root = self.tmp / "proj"
        self.root.mkdir()
        state.init(self.root, "Mock Cleaners", "phased", "scratch")
        (self.home / "vault.env").write_text(f"FAKE_TOKEN={FAKE}\n", encoding="utf-8")
        PROFILE.use_project(self.root)

    def tearDown(self):
        PROFILE.use_project(None)
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tmpclean.rmtree(self.tmp)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--project", str(self.root), *args])
        out = buf.getvalue()
        return rc, out

    def on_disk(self):
        parts = []
        for p in sorted((self.root).rglob("*")):
            if p.is_file() and ".git" not in p.parts and p.name != "vault.env":
                parts.append(p.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)

    def test_bb_post_never_stores_or_echoes_a_vault_value(self):
        rc, out = self.dh("bb", "post", "--wp", "A1", "--kind", "note", "--msg", f"the key is {FAKE} ok")
        self.assertNotIn(FAKE, out)
        self.assertNotIn(FAKE, self.on_disk())

    def test_brief_set_never_stores_a_vault_value(self):
        rc, out = self.dh("brief", "set", f"business={FAKE} bakery")
        self.assertNotIn(FAKE, out)
        self.assertNotIn(FAKE, self.on_disk())

    def test_pending_add_refuses_a_vault_value_like_any_secret(self):
        rc, out = self.dh("pending", "add", f"rotate {FAKE}", "--how", "open the dashboard", "--where", "https://example.com/keys")
        self.assertEqual(json.loads(out.strip().splitlines()[-1]).get("code"), "SECRET_IN_TEXT")
        self.assertNotIn(FAKE, self.on_disk())
        self.assertNotIn(FAKE, out)

    def test_clean_text_still_passes_untouched(self):
        rc, out = self.dh("brief", "set", "business=Mock Cleaners, Lyon")
        self.assertEqual(rc, 0)
        self.assertIn("Mock Cleaners, Lyon", self.on_disk())


if __name__ == "__main__":
    unittest.main()
