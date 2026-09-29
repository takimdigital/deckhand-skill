"""The scaffold folder create-next-app is given must be a legal npm package name (found by a real-browser run: the sibling
folder was `.app.deckhand-scaffold`, which npm rejects: "name cannot start with a period")."""
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
from dhlib import build, state  # noqa: E402
from dhlib.util import run as real_run  # noqa: E402

# npm's validate-npm-package-name, for a NEW package: no leading . or _, no uppercase, no spaces, <= 214 chars
def npm_name_problem(name: str):
    if not name or len(name) > 214:
        return "empty or too long"
    if name[0] in "._":
        return "name cannot start with a period or underscore"
    if name != name.lower():
        return "name can no longer contain capital letters"
    if re.search(r"[\s~'!()*]", name) or re.search(r"[^a-z0-9\-._~@/]", name):
        return "name contains a character npm forbids"
    return None


class ScaffoldNpmName(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        self.cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.cwd)
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, seen):
        def run(argv, cwd=None, timeout=900, env=None, check=False):
            if argv[0] == "npx":
                dest = Path(argv[3])
                seen.append(dest.name)
                problem = npm_name_problem(dest.name)
                if problem:
                    return {"cmd": "npx", "code": 1, "out": "", "err": f'Could not create a project called "{dest.name}" because of npm naming restrictions: {problem}', "ms": 0}
                (dest / "app").mkdir(parents=True)
                (dest / "package.json").write_text('{"name": "x", "scripts": {"dev": "next dev"}}', encoding="utf-8")
                (dest / "app" / "page.tsx").write_text("export default function P(){return null}\n", encoding="utf-8")
                return {"cmd": "npx", "code": 0, "out": "", "err": "", "ms": 0}
            if argv[0] in ("npm", "pnpm", "bun", "yarn"):
                return {"cmd": argv[0], "code": 0, "out": "", "err": "", "ms": 0}
            return real_run(argv, cwd=cwd, timeout=timeout, env=env, check=check)
        return run

    def scaffold_into(self, name):
        root = self.tmp / "proj"
        root.mkdir(exist_ok=True)
        state.init(root, "Bakery", "auto", "scratch")
        seen = []
        with mock.patch.object(build, "run", self.fake(seen)):
            out = build.scaffold(root / name, "npm")
        return out, seen

    def test_the_scaffold_sibling_is_a_legal_npm_name_for_ordinary_folder_names(self):
        for name in ("app", "My Shop", "Site_2", "shop.v2", "a"):
            out, seen = self.scaffold_into(name)
            self.assertEqual([npm_name_problem(s) for s in seen], [None], (name, seen))
            self.assertTrue((self.tmp / "proj" / name / "app" / "page.tsx").exists(), name)
            shutil.rmtree(self.tmp / "proj" / name, ignore_errors=True)

    def test_the_leftover_folder_never_survives(self):
        self.scaffold_into("app")
        self.assertEqual([p.name for p in (self.tmp / "proj").iterdir() if "deckhand-scaffold" in p.name], [])


if __name__ == "__main__":
    unittest.main()
