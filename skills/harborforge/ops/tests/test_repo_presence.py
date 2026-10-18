"""Tests for repo_presence.py — render from one JSON, fail loudly, never leave a half-README."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
rp = importlib.import_module("repo_presence")

BASE = {
    "repo": "o/n",
    "name": "App Name",
    "tagline": "One line.",
    "live_url": "https://example.com",
    "version": "1.0.0",
    "intro": "What it is.",
    "stack": "Next.js · Postgres",
    "deploy_notes": "Builds from `main`; deploys are explicit.",
}


class RepoPresenceTests(unittest.TestCase):
    def test_render_full_readme(self):
        data = dict(
            BASE,
            features=["**F** — x"],
            setup_commands=["pnpm install", "pnpm dev"],
            env_note="Vars in `.env`.",
            env_table=["| `DB` | conn string |"],
            layout=["app/  routes"],
            ci_line="CI runs on push.",
            status="Live since today.",
        )
        out = rp.render_readme(data)
        for frag in ("# App Name", "## Features", "**F** — x", "## Local development", "pnpm install",
                     "| `DB` | conn string |", "## Project layout", "app/  routes", "## Deploy & ops",
                     "CI runs on push.", "## Status", "Live since today."):
            self.assertIn(frag, out)
        self.assertNotIn("{{", out)

    def test_render_drops_empty_sections(self):
        out = rp.render_readme(dict(BASE))
        self.assertNotIn("## Features", out)
        self.assertNotIn("## Local development", out)
        self.assertNotIn("## Status", out)
        self.assertIn("## Deploy & ops", out)
        self.assertIn("**Version:** 1.0.0", out)

    def test_missing_required_field_fails(self):
        d = dict(BASE)
        del d["tagline"]
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "repo.json"
            p.write_text(json.dumps(d), encoding="utf-8")
            with self.assertRaises(SystemExit):
                rp.load_data(str(p))

    def test_license_proprietary_with_derived(self):
        lic = rp.render_license(dict(BASE, license="proprietary", license_owner="Takim",
                                     license_derived_from="nextjs/saas-starter"))
        self.assertIn("Takim", lic)
        self.assertIn("MIT License", lic)
        self.assertIn("Vercel", lic)
        self.assertIsNone(rp.render_license(dict(BASE)))

    def test_package_json_patch_preserves_everything_else(self):
        with tempfile.TemporaryDirectory() as t:
            pj = Path(t) / "package.json"
            pj.write_text(json.dumps({"private": True, "scripts": {"dev": "x"}}, indent=2), encoding="utf-8")
            out, changed = rp.patch_package_json(pj, dict(BASE, description="desc", package_json=True))
            obj = json.loads(out)
            self.assertEqual(obj["version"], "1.0.0")
            self.assertEqual(obj["license"], "UNLICENSED")
            self.assertEqual(obj["scripts"], {"dev": "x"})
            self.assertTrue(obj["private"])
            self.assertEqual(changed["name"], "app-name")

    def test_gh_commands_prefill(self):
        cmds = rp.gh_commands(dict(BASE, description="d", topics=["nextjs", "canada"]))
        joined = "\n".join(cmds)
        self.assertIn("gh repo set-default o/n", joined)
        self.assertIn("gh repo edit o/n --description \"d\"", joined)
        self.assertIn("names[]=canada", joined)

    def test_init_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            data = dict(BASE, description="d", package_json=True, license="proprietary",
                        license_owner="T", status="Live.")
            dp = Path(t) / "repo.json"
            dp.write_text(json.dumps(data), encoding="utf-8")
            (Path(t) / "package.json").write_text(json.dumps({"private": True}), encoding="utf-8")
            rc = rp.main(["init", str(dp), "--dir", t, "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse((Path(t) / "README.md").exists())  # dry-run writes nothing
            rc = rp.main(["init", str(dp), "--dir", t])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(t) / "README.md").exists())
            self.assertTrue((Path(t) / "LICENSE").exists())
            self.assertIn("app-name", (Path(t) / "package.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
