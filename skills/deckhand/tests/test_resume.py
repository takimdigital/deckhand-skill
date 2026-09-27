"""Session continuity: any AI, any fresh session, resumes a project from its files — never from a chat.

RESUME.md follows every dh command; notes carry what only the chat knew; the switch verdict is computed;
`dh resume --check` re-proves claims; AGENTS.md + the Claude Code hook make a cold start automatic; the
per-project profile/vault keeps a client's settings and secrets in that client's project, on this machine only.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import guide, profile, resume, state  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, GITIGNORE_BLOCK, GITIGNORE_LINES, append_jsonl, ensure_gitignore, now, write_json  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "VPS_OPS_HOME", *GIT_ENV)}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ["VPS_OPS_HOME"] = str(self.tmp / "vps-ops")
        os.environ.update(GIT_ENV)
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        profile.use_project(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args, root=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(root or self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])

    def git(self, *args, root=None):
        return subprocess.run(["git", *args], cwd=root or self.root, capture_output=True, text=True, check=True).stdout

    def repo(self):
        self.git("init", "-q", "-b", "main")
        (self.root / "app.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
        self.dh("init", "--name", "Maison Pain")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def resume_text(self):
        return (self.root / ".deckhand" / "RESUME.md").read_text(encoding="utf-8")


class Resume(Base):
    def test_every_command_refreshes_the_resume_success_or_failure_under_budget_with_the_exact_next_step(self):
        self.dh("init", "--name", "Maison Pain")
        text = self.resume_text()
        self.assertIn("**define**", text)
        self.assertIn("`dh profile doctor", text)                            # the exact next command, not a paraphrase
        self.assertIn("references/00-define.md", text)
        self.dh("brief", "set", "business=Artisan bakery", "shape=leadgen", "languages=en", "audience=locals")
        self.dh("phase", "done", "define")
        text = self.resume_text()
        self.assertIn("- define ", text)                                   # done, with its proof line
        self.assertIn("**research**", text)
        code, out = self.dh("phase", "done", "plan")                       # a refused command refreshes it too
        self.assertEqual((code, out["code"]), (1, "OUT_OF_ORDER"))
        text = self.resume_text()
        self.assertIn("last failure", text)
        self.assertIn("SAFE TO START A FRESH SESSION: NO", text)          # a failure nobody explained lives only in the chat
        self.assertLess(len(text), resume.BUDGET)
        self.dh("note", "doing", "research next: plan was refused because research is not done yet")
        code, out = self.dh("resume")
        self.assertEqual(code, 0)
        self.assertTrue(out["safe_to_switch"], out["why"])
        self.assertIn("SAFE TO START A FRESH SESSION: YES", out["resume"])

    def test_notes_are_redacted_rendered_and_doing_clears(self):
        self.dh("init", "--name", "Maison Pain")
        profile.use_project(self.root)
        tok = "cf_" + "Q7x9Lm2Rt5Vb8Nc4Zk1Hp6Wd3"
        profile.vault_set("CLOUDFLARE_API_TOKEN", tok, where="machine")
        self.dh("note", "decision", f"no online payments at launch; cloudflare token {tok} works")
        self.dh("note", "doing", "wiring the contact form to Resend")
        raw = (self.root / ".deckhand" / "notes.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(tok, raw)
        text = self.resume_text()
        self.assertNotIn(tok, text)
        self.assertIn("no online payments at launch", text)
        self.assertIn("doing (", text)
        self.dh("note", "doing", "done")
        self.assertNotIn("wiring the contact form", self.resume_text().split("## Owner decisions")[0])
        with self.assertRaises(SystemExit):                                 # argparse refuses unknown kinds (exit 2)
            main(["--project", str(self.root), "note", "maybe", "x"])

    def test_the_switch_verdict_follows_edits_made_after_the_last_note(self):
        self.repo()
        self.assertTrue(self.dh("resume")[1]["safe_to_switch"])
        app = self.root / "app.tsx"
        app.write_text("export default function App() { return <main />; }\n", encoding="utf-8")
        code, out = self.dh("resume")
        self.assertFalse(out["safe_to_switch"])
        self.assertIn("not described", out["why"][0])
        self.dh("note", "doing", "App renders <main/>: the shell for the home page")
        self.assertTrue(self.dh("resume")[1]["safe_to_switch"])
        later = time.time() + 5
        os.utime(app, (later, later))                                      # edited again after the note
        self.assertFalse(self.dh("resume")[1]["safe_to_switch"])
        self.git("commit", "-qam", "shell")                                # committed work is in the files: safe
        self.assertTrue(self.dh("resume")[1]["safe_to_switch"])
        for f in ("AGENTS.md", "CLAUDE.md", ".gitignore", "PENDING.md"):   # files dh itself manages never count
            self.assertNotIn(f, resume._dirty(self.root))

    def test_check_re_proves_claims_against_reality(self):
        self.repo()
        head = self.git("rev-parse", "HEAD").strip()
        s = state.load(self.root)
        s["phases"]["review"] = {"status": "done", "at": now()}
        s["gates"]["G1"] = {"status": "passed", "at": now(), "by": "owner"}
        state.save(self.root, s)
        write_json(self.root / ".deckhand" / "verify.json", {"ok": True, "at": now(), "commit": head, "rows": []})
        code, out = self.dh("resume", "--check")
        self.assertEqual(code, 0, out)
        (self.root / "app.tsx").write_text("// changed\n", encoding="utf-8")
        self.git("commit", "-qam", "after verify")
        brief = self.root / ".deckhand" / "brief.json"
        write_json(brief, {"business": "changed after the owner approved the plan"})
        later = time.time() + 5
        os.utime(brief, (later, later))
        code, out = self.dh("resume", "--check")
        self.assertEqual((code, out["code"]), (1, "DRIFT"))
        bad = {c["claim"]: c["detail"] for c in out["claims"] if not c["ok"]}
        self.assertIn("1 commit(s) since the last `dh verify`", bad["verify still describes the code"])
        self.assertIn("brief.json", bad["the approved plan is the current plan"])

    def test_verify_records_the_commit_it_proved(self):
        self.repo()
        from dhlib import verify
        r = verify.run_verify(self.root, skip=("typecheck", "lint", "build", "routes", "audit", "seo"))
        self.assertEqual(r["commit"], self.git("rev-parse", "HEAD").strip())


class ColdStart(Base):
    def test_agents_block_is_idempotent_upgradable_and_keeps_the_owners_words(self):
        (self.root / "AGENTS.md").write_text("# Our rules\nUse pnpm.\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("Be brief.\n", encoding="utf-8")
        code, out = self.dh("init", "--name", "Maison Pain")
        self.assertEqual(sorted(out["agents"]), ["AGENTS.md", "CLAUDE.md"])
        ag = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(ag.startswith("# Our rules\nUse pnpm.\n"))
        self.assertIn("dh resume", ag)
        cl = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(cl.startswith("Be brief.\n\n<!-- deckhand:begin"))      # only our block, not their whole AGENTS.md
        self.assertNotIn("@AGENTS.md", cl)
        self.assertEqual(self.dh("init", "--name", "Maison Pain")[1]["agents"], [])       # idempotent
        (self.root / "AGENTS.md").write_text(ag.replace("1. Run `dh resume`.", "1. (an older wording)"), encoding="utf-8")
        resume.agent_entry(self.root)                                        # an older block is replaced, not duplicated
        ag2 = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(ag2, ag)
        self.assertEqual(ag2.count("deckhand:begin"), 1)
        empty = self.tmp / "empty"
        empty.mkdir()
        resume.agent_entry(empty)
        self.assertEqual((empty / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")   # no CLAUDE.md: import AGENTS.md

    def test_hook_prints_the_resume_inside_a_project_and_nothing_outside(self):
        self.dh("init", "--name", "Maison Pain")
        sub = self.root / "app" / "deep"
        sub.mkdir(parents=True)
        text = resume.hook(json.dumps({"session_id": "x", "source": "compact", "cwd": str(sub)}))
        self.assertIn("Deckhand project detected", text)
        self.assertIn("# RESUME — Maison Pain", text)
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        self.assertEqual(resume.hook(json.dumps({"cwd": str(outside)})), "")
        self.assertEqual(resume.hook("not json"), "")                        # a hook never breaks the harness
        env = {**os.environ}
        p = subprocess.run([sys.executable, str(SKILL / "dh.py"), "resume", "--hook"], input=json.dumps({"cwd": str(sub)}),
                           capture_output=True, text=True, encoding="utf-8", cwd=str(outside), env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("Deckhand project detected"))    # plain text: the harness injects it as context

    def test_install_hook_merges_into_settings_idempotently_and_refuses_bad_json(self):
        settings = self.tmp / "claude" / "settings.json"
        mine = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
        write_json(settings, {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}], "SessionStart": [mine]}})
        r = resume.install_hook(settings)
        self.assertTrue(r["installed"])
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": []}])
        ss = data["hooks"]["SessionStart"]
        self.assertEqual(ss[0], mine)
        self.assertEqual(ss[1]["matcher"], "startup|resume|clear|compact")
        self.assertTrue(ss[1]["hooks"][0]["command"].endswith("resume --hook"))
        self.assertTrue(resume.install_hook(settings)["already"])
        self.assertEqual(len(json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"]), 2)
        settings.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(DhError) as e:
            resume.install_hook(settings)
        self.assertEqual(e.exception.code, "BAD_SETTINGS")
        self.assertEqual(settings.read_text(encoding="utf-8"), "{ not json")   # nothing was overwritten

    def test_dh_next_offers_a_fresh_session_right_after_a_gate_when_nothing_is_only_in_the_chat(self):
        state.init(self.root, "Maison Pain")
        self.assertNotIn("fresh_session", guide.next_step(self.root))
        state.gate_pass(self.root, "G1", "plan approved")
        self.assertIn("fresh_session", guide.next_step(self.root))
        state.gate_pass(self.root, "G2")
        append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": "2999-01-01T00:00:00Z", "cmd": "npm run build", "exit": 1, "out": "Error: boom"})
        self.assertNotIn("fresh_session", guide.next_step(self.root))


class LocalOnly(Base):
    def test_client_projects_keep_their_settings_and_secrets_and_never_see_another_clients(self):
        a, b = self.tmp / "client-a", self.tmp / "client-b"
        for r in (a, b):
            r.mkdir()
            self.assertEqual(self.dh("init", "--name", r.name, "--for", "client", root=r)[0], 0)
        profile.use_project(None)
        profile.vault_set("DH_TEST_SHARED_KEY", "machine-wide-value-123", where="machine")
        profile.set_fields(["owner.name=Takim"], where="machine")
        profile.use_project(a)
        self.assertEqual(profile.scope(), "client")
        self.assertEqual(profile.vault_set("DH_TEST_CLIENT_KEY", "client-a-secret-456")["scope"], "project")   # client default
        self.assertEqual(profile.set_fields(["domain.default=client-a.com"])["scope"], "project")
        self.assertEqual(profile.secret("DH_TEST_CLIENT_KEY"), "client-a-secret-456")
        self.assertEqual(profile.secret("DH_TEST_SHARED_KEY"), "machine-wide-value-123")   # the owner's keys stay a fallback
        self.assertEqual(profile.load()["owner"]["name"], "Takim")
        self.assertEqual(profile.load()["domain"]["default"], "client-a.com")
        self.assertIn("**for a client**", (a / ".deckhand" / "RESUME.md").read_text(encoding="utf-8"))   # a cold agent knows
        profile.use_project(b)
        self.assertIsNone(profile.secret("DH_TEST_CLIENT_KEY"))              # client A's key is invisible in client B
        self.assertNotIn("domain", profile.load())
        machine = (Path(os.environ["DECKHAND_HOME"]) / "vault.env").read_text(encoding="utf-8")
        self.assertNotIn("client-a-secret-456", machine)
        code, out = self.dh("vault", "list", root=a)
        self.assertEqual(out["by_layer"], {"machine": ["DH_TEST_SHARED_KEY"], "project": ["DH_TEST_CLIENT_KEY"]})
        self.assertNotIn("client-a-secret-456", json.dumps(out))              # names only
        self.git("init", "-q", root=a)
        for f in (".deckhand/vault.env", ".deckhand/profile.json", ".deckhand/RESUME.md", ".deckhand/notes.jsonl"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", f], cwd=a).returncode, 0, f)

    def test_the_app_folder_made_from_a_client_plan_stays_a_client_project(self):
        self.dh("init", "--name", "Client plan", "--for", "client")
        app = self.tmp / "client-app"
        app.mkdir()
        (app / "package.json").write_text('{"name": "client-app"}', encoding="utf-8")
        code, out = self.dh("adopt", str(app))
        self.assertEqual(code, 0, out)
        profile.use_project(app)
        self.assertEqual(profile.scope(), "client")
        self.assertEqual(profile.vault_set("DH_TEST_CLIENT_KEY", "client-app-secret-789")["scope"], "project")

    def test_handoff_points_to_where_the_key_really_is_and_to_dh_resume(self):
        self.dh("init", "--name", "Client", "--for", "client")
        profile.use_project(self.root)
        profile.vault_set("COOLIFY_TOKEN", "coolify-client-token-123")               # client default: the project layer
        self.dh("handoff")
        h = (self.root / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("`.deckhand/vault.env` in this project", h)
        self.assertNotIn("coolify-client-token-123", h)                               # locations, never values
        self.assertIn("dh resume", h)

    def test_personal_projects_keep_their_own_settings_the_owners_facts_stay_on_the_machine(self):
        self.dh("init", "--name", "Mine")
        code, out = self.dh("profile", "set", "defaults.hosting=vps")         # the owner's own default: every project
        self.assertEqual(out["scope"], "machine")
        code, out = self.dh("profile", "set", "domain.default=mine.dev")      # this project's: its own layer (2.3)
        self.assertEqual(out["scope"], "project")
        self.assertIn("ask_once", out)
        code, out = self.dh("profile", "set", "dns.provider=cloudflare", "--machine")
        self.assertEqual(out["scope"], "machine")
        code, out = self.dh("profile", "show")
        self.assertEqual((out["scope"], out["profile"]["domain"]["default"], out["profile"]["defaults"]["hosting"]), ("me", "mine.dev", "vps"))
        profile.use_project(None)
        self.assertNotIn("domain", profile.load())                           # the project layer stays in the project

    def test_an_older_gitignore_block_is_upgraded_in_place(self):
        old = "node_modules\n\n# deckhand: run logs and local state (old)\n.deckhand/runs.jsonl\n.deckhand/tryon/\n\n# mine\n*.bak\n"
        (self.root / ".gitignore").write_text(old, encoding="utf-8")
        self.assertTrue(ensure_gitignore(self.root))
        gi = (self.root / ".gitignore").read_text(encoding="utf-8")
        for line in GITIGNORE_LINES:
            self.assertEqual(gi.count(line + "\n"), 1, line)
        self.assertTrue(gi.startswith("node_modules\n"))
        self.assertTrue(gi.endswith("# mine\n*.bak\n"))
        self.assertLess(gi.index(".deckhand/vault.env"), gi.index("# mine"))  # inside the block, not after the owner's lines
        self.assertFalse(ensure_gitignore(self.root))
        fresh = self.tmp / "fresh"
        ensure_gitignore(fresh)
        self.assertEqual((fresh / ".gitignore").read_text(encoding="utf-8"), GITIGNORE_BLOCK)


if __name__ == "__main__":
    unittest.main()
