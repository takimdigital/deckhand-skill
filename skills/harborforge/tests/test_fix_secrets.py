"""Package 3: secrets and personal data hygiene, plus the learning loop (B6, C6-C11). Only FAKE secrets are used."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)

from dhlib import autopsy as AU, handoff, learn as LE, profile as PROFILE, resume, state, workflow as WF  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import append_jsonl, read_jsonl, write_json  # noqa: E402

FAKE = "FAKE-SECRET-123456"
FAKE2 = "FAKE-PROJECT-SECRET-7654321"
WIN_A = "C:\\Users\\Bob\\AppData\\Local\\Temp\\x"


def cat(root: Path, home: Path) -> str:
    """Every byte the project and the owner's home hold, as text."""
    out = []
    for base in (root, home):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != "vault.env" and ".git" not in p.parts:
                out.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


class Base(unittest.TestCase):
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
        (self.root / ".deckhand" / "vault.env").write_text(f"FAKE_PROJECT_KEY={FAKE2}\n", encoding="utf-8")
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
            code = main(["--project", str(self.root), *args])
        return code, buf.getvalue()


class Scrubber(Base):
    def test_b6_redact_module_covers_vault_shapes_and_key_blocks(self):
        from dhlib import redact as R
        cases = [f"key {FAKE} now", f"proj {FAKE2}", "sk-abcdefghijklmnopqrstuvwxyz123456", "ghp_" + "a1B2" * 10,
                 "github_pat_" + "a1B2c3" * 10, "AKIAABCDEFGHIJKLMNOP", "xoxb-1234567890-abcdefghij", "password=hunter2-secret",
                 "token: abcDEF123456xyz", "postgres://admin:s3cr3tpw@db.example.com/x", "12|" + "aB3dE5" * 7 + "aB",
                 "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "a1B2c3D4" * 5,
                 "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123\nzzz\n-----END RSA PRIVATE KEY-----"]
        for c in cases:
            out = R.scrub_text("note: " + c + " end")
            for frag in (FAKE, FAKE2, "hunter2", "s3cr3tpw", "abcDEF123456xyz", "MIIEabc123", "a1B2c3D4a1B2", "aB3dE5aB3dE5", "sk-abcdefghij"):
                self.assertNotIn(frag, out, (c, out))
        # ordinary prose, paths and slugs survive
        for ok in ("build the booking page for the bakery", "skills/deckhand/tests/test_fix_secrets_2026_09_30_final.py",
                   "my-long-project-name-2026-final-version-of-it", "commit e68adfe5a6f6d0a1b2c3d4e5f6a7b8c9d0e1f2a3"):
            self.assertEqual(R.scrub_text(ok), ok)

    def test_b6_free_text_commands_never_store_or_echo_a_vault_value(self):
        # bb post / brief set / pending add live in plan.py / state.py+cli.py / pending.py (other packages): the parent wires
        # redact.scrub_text into them; here the commands this package owns
        steps = [("learn", "add", "--symptom", f"boom {FAKE}", "--cause", f"c {FAKE2}", "--fix", f"use {FAKE}"),
                 ("research", "add", "https://example.com/pricing", "--by", "a1", "--kind", "pricing", "--note", f"€25/h standard, key {FAKE} min 2 h")]
        echoed = ""
        for s in steps:
            code, out = self.dh(*s)
            echoed += out
        self.assertNotIn(FAKE, echoed + cat(self.root, self.home))
        self.assertNotIn(FAKE2, echoed + cat(self.root, self.home))

    def test_b6_learn_and_research_scrub_pasted_shapes_too(self):
        self.dh("learn", "add", "--symptom", "login fails", "--cause", "password=Sup3rSecretPw", "--fix", "postgres://u:hunter2abc@h/db")
        self.dh("research", "add", "https://example.com/p", "--by", "a1", "--note", "€25/h standard plus sk-abcdefghijklmnopqrstuvwxyz123456 min 2 h")
        blob = cat(self.root, self.home)
        for frag in ("Sup3rSecretPw", "hunter2abc", "sk-abcdefghijklmnop"):
            self.assertNotIn(frag, blob)

    def test_c6_resume_and_handoff_scrub_stored_text(self):
        append_jsonl(self.root / ".deckhand" / "notes.jsonl", {"at": "2026-09-30T00:00:00Z", "ts": 1.0, "kind": "decision", "phase": "define",
                                                              "text": f"use {FAKE} and password=Sup3rSecretPw at postgres://u:hunter2abc@h/db " + "a1B2c3D4" * 5})
        (self.root / "PENDING.md").write_text(f"# P\n- [ ] P-001 rotate {FAKE} password=Sup3rSecretPw\n", encoding="utf-8")
        resume.write(self.root)
        handoff.write(self.root)
        for name in (".deckhand/RESUME.md", "HANDOFF.md"):
            t = (self.root / name).read_text(encoding="utf-8")
            for frag in (FAKE, "Sup3rSecretPw", "hunter2abc", "a1B2c3D4a1B2"):
                self.assertNotIn(frag, t, name)

    def test_c6_runs_jsonl_scrubs_long_keys_and_url_credentials(self):
        LE.log_run(self.root, "curl https://u:hunter2abc@host/x", 1, "password=Sup3rSecretPw key " + "a1B2c3D4" * 5)
        t = (self.root / ".deckhand" / "runs.jsonl").read_text(encoding="utf-8")
        for frag in ("hunter2abc", "Sup3rSecretPw", "a1B2c3D4a1B2"):
            self.assertNotIn(frag, t)


class LessonIds(Base):
    def test_c7_ids_never_collide_even_with_gaps_and_threads(self):
        append_jsonl(self.home / "lessons.jsonl", {"id": "L-0100", "signature": "zzz", "symptom": "s", "cause": "c", "fix": "f", "phase": "build"})
        r = LE.add(None, "build", "first problem", "c", "f")
        self.assertEqual(r["added"], "L-0101")
        r = LE.add(self.root, "build", "project problem", "c", "f", scope="project")
        self.assertEqual(r["added"], "L-0102")
        errs = []

        def work(i):
            try:
                LE.add(None, "build", f"concurrent problem number {i}", "c", "f")
            except Exception as e:     # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        ids = [x["id"] for x in read_jsonl(self.home / "lessons.jsonl")] + [x["id"] for x in read_jsonl(self.root / ".deckhand" / "lessons.jsonl")]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(len(LE.all_lessons(self.root)), len([l for l in LE.all_lessons(self.root)]))
        self.assertEqual(len(ids), 11)


class Paths(Base):
    def test_c8_windows_paths_are_placeholders_and_signatures_match_another_user(self):
        LE.add(None, "build", f"ENOENT: no such file {WIN_A}\\a.txt", "c", f"recreate {WIN_A}", scope="global")
        t = (self.home / "lessons.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("Bob", t)
        self.assertTrue(LE.match(None, "ENOENT: no such file D:\\Users\\Alice\\AppData\\Local\\Temp\\y\\a.txt"))
        LE.add(None, "build", "EACCES: permission denied, open C:/Users/Bob/app/x.ts", "c", "f")
        self.assertNotIn("Bob", (self.home / "lessons.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(LE.match(None, "EACCES: permission denied, open E:/Users/Carol/other/y.ts"))

    def test_c8_from_failure_signature_survives_windows_paths(self):
        append_jsonl(self.root / ".deckhand" / "failures.jsonl", {"at": "x", "cmd": "npm run build", "code": 1, "phase": "build",
                                                                 "tail": "Error: EPERM: operation not permitted, unlink C:\\Users\\Bob\\proj\\node_modules\\x.node"})
        LE.from_failure(self.root, "close the dev server", "a locked file")
        self.assertNotIn("Bob", (self.home / "lessons.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(LE.match(None, "Error: EPERM: operation not permitted, unlink D:\\Users\\Alice\\other\\node_modules\\x.node"))

    def test_c11_autopsy_proposals_do_not_copy_personal_paths(self):
        e = {"id": "E-1", "rung": "gate", "why": "w", "first_cmd": "py C:\\Users\\Bob\\code\\dh.py next", "exit": 1, "masked": False,
             "tail": "Traceback:\n  File \"C:\\Users\\Bob\\code\\x.py\", line 3\n  /home/bob/app/y.py", "recipe": [["run", "npm i"]], "test_in_fix": False}
        p = Path(AU._proposal(e, "A-1")).read_text(encoding="utf-8")
        self.assertNotIn("Bob", p)
        self.assertNotIn("/home/bob", p)
        self.assertIn("<home>", p)


class Workflow(Base):
    def _runs(self):
        for cmd in ("dh init --name \"Mock Cleaners\" --mode phased", "dh init --name Acme",
                    "dh pending add \"call the landlord on 0612345678\" --why w --how h --where e",
                    "dh scaffold --to " + str(self.root), "dh phase done define"):
            append_jsonl(self.root / ".deckhand" / "runs.jsonl", {"at": "2026-09-30T00:00:00Z", "cmd": cmd, "exit": 0})

    def test_c9_extraction_never_carries_client_name_or_pending_text(self):
        write_json(self.root / ".deckhand" / "brief.json", {"deliverable": "own", "shape": "booking", "category": "bakery", "name": "Mock Cleaners"})
        self._runs()
        code, out = self.dh("workflow", "new", "--from-run", "--id", "clean-flow")
        self.assertEqual(code, 0, out)
        saved = Path(json.loads(out.strip().splitlines()[-1])["saved"]).read_text(encoding="utf-8")
        for frag in ("Mock", "Cleaners", "landlord", "0612345678"):
            self.assertNotIn(frag, saved)
        self.assertIn("{{name}}", saved)

    def test_c9_publish_refuses_a_bundle_naming_the_project_owner_or_domain(self):
        PROFILE.use_project(None)
        write_json(self.home / "profile.json", {"owner": {"name": "Takim Ouzzine"}, "domain": {"default": "acme-bakery.example"}})
        PROFILE.use_project(self.root)
        base = {"schema": WF.SCHEMA, "version": 1, "title": "Tiny", "summary": "a test path",
                "match": {"deliverable": ["own"], "shape": ["booking"], "industry": ["bakery"]},
                "phases": [{"id": "define", "steps": [{"id": "D1", "do": "dh profile doctor", "expect": "ok"}], "exit": "dh phase done define"}]}
        for i, frag in enumerate(("Mock Cleaners", "Takim Ouzzine", "acme-bakery.example")):
            wf = dict(base, id=f"leaky-{i}", summary=f"made for {frag} last week")
            write_json(WF.mine_dir() / f"leaky-{i}.json", wf)
            code, out = self.dh("workflow", "publish", f"mine:leaky-{i}")
            self.assertNotEqual(code, 0, out)
            self.assertIn("PRIVATE_NAME_IN_BUNDLE", out)
        write_json(WF.mine_dir() / "clean.json", dict(base, id="clean"))
        code, out = self.dh("workflow", "publish", "mine:clean")
        self.assertEqual(code, 0, out)


class Idempotent(Base):
    def test_c10_autopsy_apply_twice_counts_once(self):
        from test_autopsy import SESSION, transcript
        src = self.tmp / "s.jsonl"
        src.write_text(transcript(SESSION), encoding="utf-8")
        AU.autopsy(self.root, str(src), apply=True)
        r2 = AU.autopsy(self.root, str(src), apply=True)
        les = read_jsonl(self.home / "lessons.jsonl")
        self.assertTrue(les)
        self.assertEqual([l["seen"] for l in les], [1] * len(les))
        books = read_jsonl(self.home / "playbooks.jsonl")
        self.assertEqual([b["seen"] for b in books], [1] * len(books))
        self.assertIn("skipped", json.dumps(r2["applied"]))


if __name__ == "__main__":
    unittest.main()
