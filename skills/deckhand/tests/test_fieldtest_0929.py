"""Regressions from the 2026-09-29 field test (docs/field-tests/2026-09-29-report.md, a real Windows run): each test is
one finding, reproduced, and now impossible. IDs = the report's F-numbers."""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import build, plan, profile, resume, state, verify, workflow  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, read_json, run as real_run, write_json  # noqa: E402


def reach(root, upto):
    s = state.load(root)
    for p in state.PHASES[:state.PHASE_IDS.index(upto) + 1]:
        s["phases"][p["id"]] = {"status": "done"}
        if p.get("gate"):
            s["gates"][p["gate"]] = {"status": "passed", "by": "test"}
    state.save(root, s)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        self.cwd = os.getcwd()
        self.root = self.tmp / "proj"
        self.root.mkdir()

    def tearDown(self):
        os.chdir(self.cwd)
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


def fake_run(fail=False):
    """create-next-app without the network: it must be handed a folder that does not exist yet, as the real one."""
    def run(argv, cwd=None, timeout=900, env=None, check=False):
        if argv[0] == "npx":
            dest = Path(argv[3])
            if fail:
                return {"cmd": "npx", "code": 1, "out": "", "err": "npm ERR! network", "ms": 0}
            assert not dest.exists(), "create-next-app refuses a folder that exists"
            (dest / "app").mkdir(parents=True)
            (dest / "package.json").write_text('{"name": "x", "scripts": {"dev": "next dev"}}', encoding="utf-8")
            (dest / "app" / "page.tsx").write_text("export default function P(){return null}\n", encoding="utf-8")
            return {"cmd": "npx", "code": 0, "out": "", "err": "", "ms": 0}
        if argv[0] in ("npm", "pnpm", "bun", "yarn"):
            return {"cmd": argv[0], "code": 0, "out": "", "err": "", "ms": 0}
        return real_run(argv, cwd=cwd, timeout=timeout, env=env, check=check)
    return run


class Scaffold(Base):
    def setUp(self):
        super().setUp()
        state.init(self.root, "Bakery", "auto", "scratch")
        reach(self.root, "plan")

    def leftovers(self):
        return sorted(p.name for p in self.root.parent.iterdir() if "deckhand-" in p.name or p.name.startswith("dh-scaffold-"))

    def test_F8_scaffold_into_the_shells_own_folder_keeps_the_folder(self):
        # `dh next` prints `dh scaffold --to .`: the folder was emptied, then rmdir'd (POSIX) or crashed (Windows)
        os.chdir(self.root)
        with mock.patch.object(build, "run", fake_run()):
            code, out = self.dh("scaffold", "--to", ".")
        self.assertEqual(code, 0, out)
        self.assertEqual(Path(out["project"]), self.root)
        self.assertTrue(Path.cwd().exists())                                     # the shell is not left in a deleted folder
        self.assertEqual(Path.cwd().resolve(), self.root)
        self.assertTrue((self.root / "app" / "page.tsx").exists())
        self.assertEqual(state.load(self.root)["name"], "Bakery")               # the same run, now with its base
        self.assertIn(".deckhand", out["kept"])
        self.assertEqual(self.leftovers(), [])

    def test_F8_a_failed_scaffold_puts_the_folder_back(self):
        os.chdir(self.root)
        before = sorted(p.name for p in self.root.iterdir())
        with mock.patch.object(build, "run", fake_run(fail=True)):
            code, out = self.dh("scaffold", "--to", ".")
        self.assertEqual((code, out["code"]), (1, "SCAFFOLD_FAILED"))           # JSON, never a traceback
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        self.assertEqual(self.leftovers(), [])

    def test_F7_a_relative_to_is_the_projects_not_the_shells(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        os.chdir(elsewhere)
        with mock.patch.object(build, "run", fake_run()):
            code, out = self.dh("scaffold", "--to", "app")
        self.assertEqual(code, 0, out)
        self.assertEqual(Path(out["project"]), self.root / "app")
        self.assertEqual(list(elsewhere.iterdir()), [])                          # nothing lands in the shell's folder


class SmallFindings(Base):
    def test_F11_a_second_init_says_what_it_kept_and_what_changed(self):
        self.assertTrue(state.init(self.root, "alpha", "auto", "pool", "client")["created"])
        out = state.init(self.root, "beta", "phased", "mine", "me")
        self.assertFalse(out["created"])
        self.assertEqual(out["kept"], {"name": "alpha", "mode": "auto", "path": "pool"})
        self.assertIn("a new run = a new folder", out["note"])
        self.assertEqual(out["scope_changed"], {"from": "client", "to": "me"})
        again = state.init(self.root, "alpha", "auto", "pool", "me")          # the same call twice: nothing to report
        self.assertNotIn("kept", again)
        self.assertNotIn("scope_changed", again)

    def test_F14_plan_init_writes_no_research_template_once_research_was_skipped(self):
        state.init(self.root, "p", "phased", "pool")
        state.phase_done(self.root, "define", force_reason="test")
        state.phase_skip(self.root, "research", "not needed")
        made = plan.init(self.root)["created"]
        self.assertFalse((self.root / ".deckhand" / "research.json").exists(), made)
        self.assertTrue((self.root / ".deckhand" / "sitemap.json").exists())

    def test_F20_a_forced_phase_is_not_drift(self):
        state.init(self.root, "g", "phased", "scratch")
        state.phase_done(self.root, "define", force_reason="test")
        state.phase_done(self.root, "research", force_reason="owner said skip research")
        claims = {c["claim"]: c for c in resume.check(self.root)["claims"]}
        self.assertTrue(claims["research done"]["ok"])
        self.assertIn("owner said skip research", claims["research done"]["detail"])

    def test_F18_an_empty_kit_is_not_a_kit(self):
        for f in ("README.md", "LICENSE", "CUSTOMIZE.md"):
            (self.root / f).write_text("", encoding="utf-8")
        self.assertEqual(len(verify.product_kit(self.root, {"seed": "", "reset": ""})), 5)
        for f in ("README.md", "LICENSE", "CUSTOMIZE.md"):
            (self.root / f).write_text("x", encoding="utf-8")
        self.assertEqual(verify.product_kit(self.root, {"seed": "node seed.js", "reset": "node reset.js"}), [])

    def test_F3_doctor_asks_for_the_piece_that_is_missing(self):
        state.init(self.root, "d", "phased", "pool")
        os.chdir(self.root)
        with mock.patch.dict(os.environ, {"COOLIFY_TOKEN": "tok"}), mock.patch.object(profile, "_get", lambda p, k: None):
            os.environ.pop("COOLIFY_URL", None)
            asks = profile.doctor(online=False)["one_batched_ask"]
        coolify = [a for a in asks if a.startswith("Coolify")]
        self.assertEqual(len(coolify), 1, coolify)
        self.assertIn("coolify.url", coolify[0])
        self.assertNotIn("COOLIFY_TOKEN", coolify[0])

    def test_F4_considered_counts_what_was_looked_at(self):
        rows = [{"id": "a", "source": "base", "version": 1, "level": "draft", "title": "a", "steps": []},
                {"id": "b", "source": "base", "version": 1, "level": "draft", "title": "b", "steps": []}]
        with mock.patch.object(workflow, "rows", lambda refresh=False: rows), \
             mock.patch.object(workflow, "score", lambda r, f: (0, [], [])):
            out = workflow.query({"business": "bakery"}, {})
        self.assertEqual((out["considered"], out["matched"]), (2, 0))


class Portability(unittest.TestCase):
    """F1: 6 of the 7 Windows-only failures were text read or written in the locale's code page (cp1252), not UTF-8."""

    def test_F1_every_text_read_and_write_names_utf8(self):
        bad = []
        for top in ("dhlib", "tests", "ops"):
            for f in sorted((SKILL / top).rglob("*.py")):
                for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                    if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
                        continue
                    name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                    kws = {k.arg for k in n.keywords}
                    mode = next((a.value for a in n.args[1:2] if isinstance(a, ast.Constant)), None) or next(
                        (k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), "r")
                    if (name in ("read_text", "write_text")
                            or name == "open" and isinstance(n.func, ast.Name) and "b" not in str(mode)
                            or name in ("run", "check_output", "Popen") and ("text" in kws or "universal_newlines" in kws)):
                        bad.append(f"{f.relative_to(SKILL)}:{n.lineno} {name}")
        self.assertEqual(bad, [], "pass encoding=\"utf-8\": Windows reads cp1252 otherwise")


if __name__ == "__main__":
    unittest.main()
