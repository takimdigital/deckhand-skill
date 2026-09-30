"""Fix package 2 (audit B1-B9, C3, C5, F11): the CLI answers JSON for every usage error, validates --project once,
refuses writers outside a project, survives corrupt state, is safe under parallel processes, and its hints run verbatim."""
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmpclean  # noqa: E402

DH = str(SKILL / "dh.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dh-fixcli-")).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {**os.environ, "DECKHAND_HOME": str(self.home / ".deckhand"), "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        self.addCleanup(tmpclean.rmtree, self.tmp)

    def dh(self, *args, cwd=None, stdin=None):
        p = subprocess.run([sys.executable, DH, *map(str, args)], cwd=str(cwd or self.tmp), env=self.env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", input=stdin, timeout=120)
        return p

    def js(self, *args, **kw):
        p = self.dh(*args, **kw)
        try:
            return json.loads(p.stdout), p
        except Exception:
            self.fail(f"not one JSON object: rc={p.returncode} stdout={p.stdout!r} stderr={p.stderr[-300:]!r}")

    def project(self, name="proj", init=True):
        d = self.tmp / name
        d.mkdir()
        if init:
            o, _ = self.js("init", "--name", "x", "--project", d)
            self.assertTrue(o["ok"], o)
        return d


class TestUsageJson(Base):                                                   # B1
    def test_bad_flag_missing_arg_bad_subcommand_are_json(self):
        for args in (["status", "--bogus"], ["init"], [], ["nosuch"], ["note", "decision"], ["phase", "done", "nope"]):
            o, p = self.js(*args)
            self.assertEqual(p.returncode, 2, args)
            self.assertFalse(o["ok"], args)
            self.assertEqual(o["code"], "USAGE", args)
            self.assertTrue(o["message"] and o["usage"], args)

    def test_help_is_json_with_the_text_inside(self):
        for args in (["--help"], ["init", "--help"], ["deploy", "-h"]):
            o, p = self.js(*args)
            self.assertEqual(p.returncode, 0, args)
            self.assertTrue(o["ok"])
            self.assertIn("usage:", o["help"])


class TestProjectRoot(Base):                                                 # B2 / B3 / B4
    def test_project_that_is_a_file(self):
        f = self.tmp / "afile.txt"
        f.write_text("x", encoding="utf-8")
        for args in (["init", "--name", "x"], ["brief", "set", "a=b"], ["bb", "post", "--msg", "m"], ["compose"], ["handoff"], ["seo", "audit"], ["verify"], ["plan", "init"]):
            o, p = self.js(*args, "--project", f)
            self.assertEqual((p.returncode, o["code"]), (1, "BAD_PROJECT"), args)

    def test_missing_project_is_not_created_except_by_init(self):
        for args in (["brief", "set", "a=b"], ["plan", "init"], ["bb", "post", "--msg", "m"], ["seo", "audit"], ["compose"], ["handoff"], ["learn", "list"],
                     ["deploy", "target", "--app", "a", "--url", "http://x"], ["dev", "start"]):
            miss = self.tmp / "not" / "there"
            o, p = self.js(*args, "--project", miss)
            self.assertEqual((p.returncode, o["code"]), (1, "BAD_PROJECT"), (args, o))
            self.assertIn("init", o["message"])
            self.assertFalse((self.tmp / "not").exists(), args)
        o, _ = self.js("init", "--name", "x", "--project", self.tmp / "made" / "deep")
        self.assertTrue(o["ok"], o)
        self.assertTrue((self.tmp / "made" / "deep" / ".deckhand" / "run.json").exists())

    def test_writers_in_a_folder_without_a_project_answer_no_run_and_write_nothing(self):
        for args in (["compose"], ["plan", "init"], ["seo", "audit"], ["verify"], ["brief", "set", "a=b"], ["bb", "post", "--msg", "m"],
                     ["dev", "start"], ["handoff"], ["pending", "add", "x", "--how", "h", "--where", "w"], ["rebrand", "apply"]):
            d = self.tmp / "empty"
            d.mkdir()
            o, p = self.js(*args, "--project", d)
            self.assertEqual((p.returncode, o["code"]), (1, "NO_RUN"), (args, o))
            self.assertIn("init", o["message"])
            self.assertEqual(list(d.iterdir()), [], args)
            d.rmdir()

    def test_read_only_and_global_commands_still_work_without_a_project(self):
        d = self.tmp / "empty2"
        d.mkdir()
        for args in (["next"], ["resume"], ["workflow", "list"], ["learn", "list"], ["pool", "list"], ["profile", "show"], ["vault", "list"], ["suggest"],
                     ["bb", "read"], ["pending", "list"], ["clean"]):
            o, p = self.js(*args, "--project", d)
            self.assertNotEqual(o.get("code"), "NO_RUN", (args, o))
            self.assertNotEqual(o.get("code"), "INTERNAL", (args, o))


class TestCorruptState(Base):                                                # B5 / C5
    def test_invalid_utf8_lines_are_skipped_and_counted(self):
        d = self.project()
        dk = d / ".deckhand"
        junk = b"\xff\xfe\x80 not json\n"
        good = {"history.jsonl": b'{"at":"2026-01-01T00:00:00Z","event":"x"}\n', "notes.jsonl": b'{"at":"2026-01-02T00:00:00Z","kind":"doing","text":"t"}\n',
                "runs.jsonl": b'{"at":"2026-01-02T00:00:00Z","cmd":"dh x","exit":0,"out":""}\n',
                "blackboard.jsonl": b'{"at":"2026-01-02T00:00:00Z","wp":"all","kind":"note","msg":"m"}\n'}
        for n, row in good.items():
            (dk / n).write_bytes(row + junk + row + b'\xc3\x28 {"at":"x\xff"}\n')
        for args in (["resume"], ["resume", "--check"], ["next"], ["note", "doing", "hello"], ["suggest"], ["autopsy"], ["bb", "read"]):
            o, p = self.js(*args, "--project", d)
            self.assertNotEqual(o.get("code"), "INTERNAL", (args, o))
            self.assertNotIn("UnicodeDecodeError", json.dumps(o), args)
        o, _ = self.js("bb", "read", "--project", d)
        self.assertGreaterEqual(o.get("skipped_lines", 0), 1, o)

    def test_wrong_type_json_is_never_internal(self):
        d = self.project()
        dk = d / ".deckhand"
        names = ("brief", "profile", "sitemap", "deploy", "verify", "seo", "dev", "slop", "swap-map", "services")
        for payload in ("5", '"str"', "[1,2]", '{"a": 5}'):
            for n in names:
                (dk / f"{n}.json").write_text(payload, encoding="utf-8")
            for args in (["status"], ["next"], ["resume"], ["resume", "--check"], ["handoff"], ["suggest"], ["brief", "show"], ["dev", "status"],
                         ["plan", "lint"], ["swap", "check"]):
                o, p = self.js(*args, "--project", d)
                self.assertNotEqual(o.get("code"), "INTERNAL", (payload, args, o))
        for payload in ("5", "[]", '{"phases": 5}', '{"phases": {"define": 3}, "gates": {}}'):
            (dk / "run.json").write_text(payload, encoding="utf-8")
            for args in (["status"], ["next"], ["resume"], ["handoff"], ["phase", "done", "define"]):
                o, p = self.js(*args, "--project", d)
                self.assertEqual(o.get("code"), "RUN_CORRUPT", (payload, args, o))

    def test_init_repairs_a_corrupt_run_and_keeps_a_copy(self):
        d = self.project()
        rj = d / ".deckhand" / "run.json"
        rj.write_text("{ not json", encoding="utf-8")
        o, _ = self.js("init", "--name", "again", "--project", d)
        self.assertTrue(o["ok"], o)
        self.assertEqual(json.loads(rj.read_text(encoding="utf-8"))["name"], "again")
        kept = list((d / ".deckhand").glob("run.json.corrupt-*"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "{ not json")

    def test_brief_set_refuses_a_corrupt_brief(self):
        d = self.project()
        bj = d / ".deckhand" / "brief.json"
        for junk in ("", "{ trunc", "\ufeff{ bad", "[1]"):
            bj.write_text(junk, encoding="utf-8")
            o, p = self.js("brief", "set", "business=x", "--project", d)
            self.assertEqual((p.returncode, o["code"]), (1, "BRIEF_CORRUPT"), (junk, o))
            self.assertEqual(bj.read_text(encoding="utf-8"), junk)
        bj.unlink()
        o, _ = self.js("brief", "set", "business=x", "--project", d)
        self.assertTrue(o["ok"])

    def test_resume_and_handoff_say_run_corrupt(self):
        d = self.project()
        (d / ".deckhand" / "run.json").write_text("{ broken", encoding="utf-8")
        for args in (["resume"], ["resume", "--check"], ["handoff"], ["status"], ["next"]):
            o, p = self.js(*args, "--project", d)
            self.assertEqual(o.get("code"), "RUN_CORRUPT", (args, o))


class TestParallel(Base):                                                    # C3
    def run_parallel(self, cmds):
        with ThreadPoolExecutor(max_workers=len(cmds)) as ex:
            return list(ex.map(lambda a: self.js(*a), cmds))

    def test_ten_parallel_brief_set_keep_every_key(self):
        d = self.project()
        res = self.run_parallel([("brief", "set", f"k{i}=v{i}", "--project", d) for i in range(1, 11)])
        for o, p in res:
            self.assertTrue(o["ok"], o)
        b = json.loads((d / ".deckhand" / "brief.json").read_text(encoding="utf-8"))
        self.assertEqual({f"k{i}": f"v{i}" for i in range(1, 11)}, {k: b.get(k) for k in (f"k{i}" for i in range(1, 11))})
        self.assertEqual([p.name for p in (d / ".deckhand").glob("*.tmp")], [])
        self.assertFalse((d / ".deckhand" / ".lock").exists())

    def test_parallel_pending_add_gives_distinct_ids(self):
        d = self.project()
        res = self.run_parallel([("pending", "add", f"task {i}", "--how", "h", "--where", "w", "--project", d) for i in range(8)])
        ids = [o["added"] for o, _ in res if o.get("ok")]
        self.assertEqual(len(ids), 8, [o for o, _ in res])
        self.assertEqual(len(set(ids)), 8, ids)

    def test_stale_lock_is_cleaned(self):
        d = self.project()
        lock = d / ".deckhand" / ".lock"
        lock.write_text("99999999", encoding="utf-8")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        o, _ = self.js("brief", "set", "a=b", "--project", d)
        self.assertTrue(o["ok"], o)


class TestDeployProjectOrder(Base):                                          # B7
    def test_project_after_the_subcommand(self):
        d = self.project()
        o, p = self.js("deploy", "target", "--app", "abc", "--url", "https://example.com", "--project", d, cwd=self.tmp)
        self.assertTrue(o["ok"], o)
        o2, _ = self.js("--project", d, "deploy", "target", "--app", "abc", "--url", "https://example.com")
        self.assertTrue(o2["ok"], o2)


class TestTryonSetupExit(unittest.TestCase):                                 # B8
    def test_unsupported_framework_exits_1(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        tmp = Path(tempfile.mkdtemp(prefix="dh-tryon-")).resolve()
        self.addCleanup(tmpclean.rmtree, tmp)
        (tmp / "package.json").write_text(json.dumps({"name": "x", "dependencies": {}}), encoding="utf-8")
        p = subprocess.run([node, str(SKILL / "tryon" / "cli.mjs"), "setup", "--project", str(tmp)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "UNSUPPORTED_FRAMEWORK")
        self.assertEqual(p.returncode, 1)


class TestHintsRunVerbatim(unittest.TestCase):                               # B9
    RX = re.compile(r"(?<![\w./\\-])dh (?=(?:next|init|status|resume|note|brief|phase|gate|reopen|profile|vault|pending|pool|plan|bb|clone|adopt|scaffold|"
                    r"compose|dev|suggest|workflow|base|rebrand|slop|swap|verify|deploy|ops|learn|run|autopsy|harvest|research|seo|handoff|clean|tryon)\b)")

    def test_no_bare_dh_in_output_strings_of_the_hint_builders(self):
        """Every hint a command PRINTS (as a value, not prose in backticks) must start with the runnable prefix."""
        sys.path.insert(0, str(SKILL))
        from dhlib import guide, suggest, workflow
        self.assertTrue(guide.DH.startswith(("py ", "python3 ")))
        self.assertNotRegex(suggest.autopsy_cmd(True), r"^dh ")
        self.assertNotRegex(suggest.autopsy_cmd(False), r"^dh ")
        d = Path(tempfile.mkdtemp(prefix="dh-hint-")).resolve()
        self.addCleanup(tmpclean.rmtree, d)
        env = {**os.environ, "DECKHAND_HOME": str(d / "h"), "HOME": str(d), "USERPROFILE": str(d), "PYTHONUTF8": "1"}
        run = lambda *a: json.loads(subprocess.run([sys.executable, DH, *map(str, a)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120).stdout)
        (d / "p").mkdir()
        run("init", "--name", "x", "--project", d / "p")
        outs = [run("next", "--project", d / "p"), run("workflow", "query", "--project", d / "p"), run("workflow", "status", "--project", d / "p"),
                run("suggest", "--project", d / "p")]
        bad = []

        def walk(v, key=""):
            if isinstance(v, dict):
                for k, x in v.items():
                    walk(x, k)
            elif isinstance(v, list):
                for x in v:
                    walk(x, key)
            elif isinstance(v, str) and key in ("cmd", "then", "next", "do", "workflow_hint"):
                if re.match(r"^\s*dh ", v) or re.match(r"^`dh ", v):
                    bad.append((key, v[:80]))
        for o in outs:
            walk(o)
        self.assertEqual(bad, [])

    def test_guide_steps_are_shell_safe(self):
        from dhlib import guide
        bad = []
        for phase, steps in guide.STEPS.items():
            for s in steps:
                s = s.format(dh="DH", tryon="TRYON", skill="SKILL")
                if not s.startswith("DH "):
                    continue
                cmd = s.split("   #")[0].split("  →")[0]
                cmd = re.sub(r"\"[^\"]*\"|\[[^\]]*\]", "", cmd)
                if re.search(r"[<>|;]", cmd.replace("&&", "")):
                    bad.append((phase, s[:90]))
        self.assertEqual(bad, [])
        self.assertNotIn("shape=saas|", "".join(guide.STEPS["define"]))

    def test_bare_dh_becomes_the_runnable_prefix_on_the_way_out(self):
        from dhlib.util import DH, runnable_obj
        o = runnable_obj({"next": "dh rebrand check", "then": "`dh autopsy --apply` after", "do": ["dh workflow query  # x"], "say": "dh next"})
        self.assertEqual(o["next"], DH + " rebrand check")
        self.assertIn(DH + " autopsy --apply", o["then"])
        self.assertEqual(o["do"], [DH + " workflow query  # x"])
        self.assertEqual(o["say"], "dh next")                      # prose is left alone
        self.assertEqual(runnable_obj({"next": "see dh.py and the dh folder"}), {"next": "see dh.py and the dh folder"})

    def test_commands_print_runnable_hints(self):
        d = Path(tempfile.mkdtemp(prefix="dh-hint2-")).resolve()
        self.addCleanup(tmpclean.rmtree, d)
        env = {**os.environ, "DECKHAND_HOME": str(d / "h"), "HOME": str(d), "USERPROFILE": str(d), "PYTHONUTF8": "1"}
        (d / "p").mkdir()
        subprocess.run([sys.executable, DH, "init", "--name", "x", "--project", str(d / "p")], env=env, capture_output=True, timeout=120)
        r = subprocess.run([sys.executable, DH, "workflow", "status", "--project", str(d / "p")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        o = json.loads(r.stdout)
        self.assertNotRegex(o["next"], r"^dh ")
        self.assertTrue(o["next"].startswith(("py ", "python3 ")), o)


class TestDevPidIsTheListener(Base):                                         # F11
    def test_dev_start_stores_listener_pid_and_stop_stops_it(self):
        if not shutil.which("npm"):
            self.skipTest("npm not installed")
        d = self.project()
        (d / "server.py").write_text(
            "import sys, http.server\n"
            "port = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8000\n"
            "http.server.ThreadingHTTPServer(('127.0.0.1', port), http.server.SimpleHTTPRequestHandler).serve_forever()\n", encoding="utf-8")
        py = sys.executable.replace("\\", "/")
        (d / "package.json").write_text(json.dumps({"name": "x", "version": "1.0.0", "scripts": {"dev": f'"{py}" server.py'}}), encoding="utf-8")
        o, p = self.js("dev", "start", "--project", d)
        pid = None
        try:
            self.assertTrue(o.get("running"), o)
            port = int(o["url"].rsplit(":", 1)[1])
            pid = o["pid"]
            from dhlib.util import listener_pid
            self.assertEqual(listener_pid(port), pid, o)
            self.assertIn("wrapper_pid", o)
            self.assertNotEqual(o["wrapper_pid"], pid)
            st = json.loads((d / ".deckhand" / "dev.json").read_text(encoding="utf-8"))
            self.assertEqual(st["pid"], pid)
            s, _ = self.js("dev", "stop", "--project", d)
            self.assertTrue(s["stopped"], s)
            for _ in range(40):
                with socket.socket() as sk:
                    sk.settimeout(0.3)
                    if sk.connect_ex(("127.0.0.1", port)) != 0:
                        break
                time.sleep(0.25)
            else:
                self.fail("the server still listens after dev stop")
            pid = None
        finally:
            if pid:
                from dhlib.build import kill_tree
                try:
                    kill_tree(pid)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
