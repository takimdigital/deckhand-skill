"""Credentials never reach disk or git through deckhand: one secret policy, redacted logs and reports, run logs
gitignored in every project, a vault that is safe to source, v1 tokens still honoured (stdlib unittest)."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "ops" / "scripts"))

from dhlib import autopsy as AU, harvest, learn, profile, state, util  # noqa: E402
from dhlib.cli import main  # noqa: E402
import coolify_api as CA  # noqa: E402

COOLIFY = "7|" + "Zk3" * 15                     # the shape Coolify API tokens have
GITHUB = "ghp_" + "a1B2" * 9
TELEGRAM = "123456789:AA" + "x" * 33


class Sec(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "VPS_OPS_HOME", "COOLIFY_TOKEN", "GITHUB_TOKEN")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["VPS_OPS_HOME"] = str(self.tmp / "vps-ops")
        for k in ("COOLIFY_TOKEN", "GITHUB_TOKEN"):
            os.environ.pop(k, None)
        self.root = self.tmp / "proj"
        self.root.mkdir()
        profile.use_project(None)                      # the machine layer, whatever project an earlier test left active

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        profile.use_project(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_redact_patterns_context_and_known_values(self):
        text = (f"token {COOLIFY} and {GITHUB} bot {TELEGRAM}\nAuthorization: Bearer abc.def-123\n"
                "https://u:hunter2secret@db.example.com/x?api_key=zzz999&ok=1\nMY_API_KEY=plainvalue123 vault-only-value-42")
        out = util.redact(text, ["vault-only-value-42"])
        for leaked in (COOLIFY, GITHUB, TELEGRAM, "abc.def-123", "hunter2secret", "zzz999", "plainvalue123", "vault-only-value-42"):
            self.assertNotIn(leaked, out)
        self.assertIn("ok=1", out)
        self.assertIn("db.example.com", out)

    def test_run_logs_never_hold_a_credential(self):
        state.init(self.root, "Shop")
        profile.vault_set("SMTP_PASSWORD", "only-in-the-vault-77")
        code, out = self.dh("run", "--", sys.executable, "-c", f"print('{GITHUB} only-in-the-vault-77'); raise SystemExit(3)")
        self.assertEqual(code, 1)
        disk = (self.root / ".deckhand" / "runs.jsonl").read_text() + (self.root / ".deckhand" / "failures.jsonl").read_text()
        self.assertNotIn(GITHUB, disk)
        self.assertNotIn("only-in-the-vault-77", disk)
        self.assertNotIn(GITHUB, json.dumps(out))

    def test_every_project_gitignores_deckhand_run_logs(self):
        state.init(self.root, "Shop")
        state.init(self.root, "Shop")                                   # idempotent
        gi = (self.root / ".gitignore").read_text()
        self.assertEqual(gi.count(util.GITIGNORE_MARK), 1)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        for probe in util.RUNTIME_STATE:
            r = subprocess.run(["git", "check-ignore", "-q", probe], cwd=self.root)
            self.assertEqual(r.returncode, 0, probe)
        self.assertNotEqual(subprocess.run(["git", "check-ignore", "-q", ".deckhand/brief.json"], cwd=self.root).returncode, 0,
                            "the plan (brief, sitemap, PLAN.md) stays committable")

    def test_vault_is_safe_to_source_in_a_shell(self):
        tricky = "1|abc$(touch pwned) 'q' \"d\" `x`"
        profile.vault_set("COOLIFY_TOKEN", tricky)
        self.assertEqual(profile.vault_read()["COOLIFY_TOKEN"], tricky)
        if shutil.which("bash") and os.name != "nt":
            r = subprocess.run(["bash", "-c", f'set -a; . "{profile.vault_path()}"; set +a; printf %s "$COOLIFY_TOKEN"'],
                               cwd=self.tmp, capture_output=True, text=True)
            self.assertEqual(r.stdout, tricky)
            self.assertFalse((self.tmp / "pwned").exists(), "sourcing the vault executed a value")

    def test_v1_tokens_still_work_and_the_ops_clients_read_the_vault(self):
        sec = self.tmp / "vps-ops" / "secrets"
        sec.mkdir(parents=True)
        (sec / "env.sh").write_text(f"export HOSTINGER_API_TOKEN='legacy-host-tok'\nexport COOLIFY_TOKEN=\"{COOLIFY}\"\n")
        self.assertEqual(profile.secret("HOSTINGER_API_TOKEN"), "legacy-host-tok")
        self.assertEqual(profile.secret("COOLIFY_TOKEN"), COOLIFY)
        profile.vault_set("COOLIFY_TOKEN", "vault-wins-" + "t" * 10)
        self.assertEqual(profile.secret("COOLIFY_TOKEN"), "vault-wins-" + "t" * 10)
        profile.set_fields(["coolify.url=http://127.0.0.1:8000"])
        url, tok = CA.resolve(env={"DECKHAND_HOME": os.environ["DECKHAND_HOME"]}, home=self.tmp / "none")
        self.assertEqual((url, tok), ("http://127.0.0.1:8000", "vault-wins-" + "t" * 10))

    def test_scanners_share_one_policy(self):
        base = self.tmp / "base"
        base.mkdir()
        (base / "bot.ts").write_text(f'const t = "{TELEGRAM}"\n')
        (base / "deploy.sh").write_text(f"curl -H 'Authorization: Bearer {COOLIFY}'\n")
        (base / "id_ed25519").write_text("x")
        (base / ".env.example").write_text("COOLIFY_TOKEN=\n")
        hits = harvest.secret_scan(base)
        self.assertEqual(sorted(h.split(":")[0] for h in hits), ["bot.ts", "deploy.sh", "id_ed25519"])
        self.assertTrue(util.SECRET_RX.search("sk_live_" + "9" * 20))
        self.assertIsNone(util.SECRET_RX.search("eyJ" + "a" * 30 + "." + "b" * 30 + ".c"), "public JWTs (Supabase anon) are app code")
        self.assertTrue(util.SECRET_STRICT_RX.search("eyJ" + "a" * 30 + "." + "b" * 30 + ".c"))

    def test_autopsy_reports_and_lessons_are_redacted(self):
        lines = []
        for n, (cmd, out, err) in enumerate([
            (f"curl -H 'Authorization: Bearer {COOLIFY}' https://c.example/api/v1/deploy", "Exit code 22\ncurl: (22) 401 Unauthorized", True),
            (f"export COOLIFY_TOKEN={COOLIFY}", "", False),
            (f"curl -H 'Authorization: Bearer {COOLIFY}' https://c.example/api/v1/deploy", "ok", False)]):
            uid = f"toolu_{n}"
            lines.append({"type": "assistant", "cwd": "/w/shop", "message": {"content": [{"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": cmd}}]}})
            lines.append({"type": "user", "cwd": "/w/shop", "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": out, "is_error": err}]}})
        src = self.tmp / "s.jsonl"
        src.write_text("".join(json.dumps(l) + "\n" for l in lines))
        res = AU.autopsy(self.root, str(src), apply=True)
        written = Path(res["report"]).read_text() + Path(res["report"]).with_suffix(".json").read_text()
        home = Path(os.environ["DECKHAND_HOME"])
        for f in home.rglob("*"):
            if f.is_file():
                written += f.read_text(errors="replace")
        self.assertNotIn(COOLIFY, written)
        for l in learn.all_lessons(None):
            self.assertFalse(l.get("auto") and any("***" in step for _, step in l.get("recipe", [])), "a redacted recipe is never replayed")


if __name__ == "__main__":
    unittest.main()
