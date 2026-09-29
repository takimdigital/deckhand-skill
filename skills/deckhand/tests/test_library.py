"""Personal boilerplate library on the owner's GitHub — offline: a mock GitHub API + file:// git remotes."""
import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import build, harvest, pool, profile  # noqa: E402
from dhlib.util import DhError, rmtree, write_json  # noqa: E402


class MockGitHub(http.server.BaseHTTPRequestHandler):
    repos, files, git_root = {}, {}, None

    def _send(self, code, body=None):
        raw = json.dumps(body or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer tok-123":
            return self._send(401, {"message": "Bad credentials"})
        p = self.path
        if p == "/user":
            return self._send(200, {"login": "maison"})
        parts = p.strip("/").split("/")
        if parts[0] == "repos" and len(parts) == 3:
            full = "/".join(parts[1:3])
            return self._send(200, self.repos[full]) if full in self.repos else self._send(404, {"message": "Not Found"})
        if parts[0] == "repos" and parts[3] == "contents":
            key = ("/".join(parts[1:3]), "/".join(parts[4:]))
            if key not in self.files:
                return self._send(404, {"message": "Not Found"})
            text, sha = self.files[key]
            return self._send(200, {"content": base64.b64encode(text.encode()).decode(), "sha": sha})
        self._send(404)

    def do_POST(self):
        if self.path == "/user/repos":
            b = self._body()
            full = f"maison/{b['name']}"
            self.repos[full] = {"private": b["private"], "size": 0}
            subprocess.run(["git", "init", "-q", "--bare", str(Path(self.git_root) / f"{full}.git")], check=True)
            return self._send(201, {"private": b["private"]})
        self._send(404)

    def do_PUT(self):
        parts = self.path.strip("/").split("/")
        key = ("/".join(parts[1:3]), "/".join(parts[4:]))
        b = self._body()
        old = self.files.get(key)
        if old and b.get("sha") != old[1]:
            return self._send(409, {"message": "sha mismatch"})
        self.files[key] = (base64.b64decode(b["content"]).decode(), f"sha{len(self.files) + 1}")
        self._send(201, {})


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env0 = {k: os.environ.get(k) for k in ("DECKHAND_HOME", "DH_GITHUB_API", "DH_GITHUB_GIT", "GITHUB_TOKEN")}
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        os.environ.pop("GITHUB_TOKEN", None)                     # the vault is the source under test
        MockGitHub.repos, MockGitHub.files = {}, {}
        MockGitHub.git_root = str(self.tmp / "gh")
        (self.tmp / "gh").mkdir()
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), MockGitHub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        os.environ["DH_GITHUB_API"] = f"http://127.0.0.1:{self.srv.server_port}"
        os.environ["DH_GITHUB_GIT"] = (self.tmp / "gh").as_uri()
        profile.vault_set("GITHUB_TOKEN", "tok-123")
        self.site = self.tmp / "levain"
        self.site.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.site)
        (self.site / "package.json").write_text('{"name": "maison-levain", "scripts": {"dev": "next dev", "build": "next build"}, "dependencies": {"next": "16"}}', encoding="utf-8")
        (self.site / "app").mkdir()
        (self.site / "app" / "page.tsx").write_text("export default () => <h1>Maison Levain — sourdough in Lyon</h1>\n", encoding="utf-8")
        (self.site / ".gitignore").write_text(".env\n", encoding="utf-8")
        (self.site / ".env").write_text("SECRET=1\n", encoding="utf-8")
        write_json(self.site / ".deckhand" / "brief.json", {"shape": "catalogue", "features": ["ordering"], "brand": {"name": "Maison Levain"}})
        write_json(self.site / ".deckhand" / "sitemap.json", {"pages": [{"route": "/"}, {"route": "/menu"}]})
        write_json(self.site / ".deckhand" / "verify.json", {"ok": True, "at": "2026-09-25", "rows": [{"check": "build", "ok": True}]})
        write_json(self.site / ".deckhand" / "deploy.json", {"url": "https://maisonlevain.fr", "smoke": {"ok": True}})
        subprocess.run(["git", "add", "-A"], cwd=self.site)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for k, v in self.env0.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        rmtree(self.tmp)

    def test_secrets_block_the_push_then_a_clean_base_lands_private_indexed_syncable_clonable(self):
        (self.site / "lib").mkdir()
        (self.site / "lib" / "pay.ts").write_text('export const key = "sk_live_' + "a1B2c3D4e5F6g7H8i9J0" + '"\n', encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.site)
        with self.assertRaises(DhError) as e:
            harvest.harvest(self.site, "bakery-base", push=True)
        self.assertEqual(e.exception.code, "SECRETS_IN_BASE")
        self.assertEqual(e.exception.extra["files"], ["lib/pay.ts:1"])
        self.assertEqual(MockGitHub.repos, {})                                  # nothing left the machine
        (self.site / "lib" / "pay.ts").write_text("export const key = process.env.STRIPE_KEY\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.site)

        r = harvest.harvest(self.site, "bakery-base", push=True)
        self.assertEqual(r["pushed"]["repo"], "maison/deckhand-base-bakery-base")
        self.assertTrue(MockGitHub.repos["maison/deckhand-base-bakery-base"]["private"])
        self.assertTrue(r["proven"]["verify"] and r["proven"]["live"])
        log = subprocess.run(["git", "--git-dir", str(self.tmp / "gh" / "maison/deckhand-base-bakery-base.git"), "log", "--oneline", "main"], capture_output=True, text=True, encoding="utf-8").stdout
        self.assertIn("base: bakery-base", log)
        lib = json.loads(MockGitHub.files[("maison/deckhand-library", "library.json")][0])
        self.assertEqual([b["name"] for b in lib["bases"]], ["bakery-base"])
        self.assertNotIn("path", lib["bases"][0])                                   # machine paths never go to GitHub
        self.assertIn("verified + live", MockGitHub.files[("maison/deckhand-library", "README.md")][0])

        # another machine: an empty home, the same token
        os.environ["DECKHAND_HOME"] = str(self.tmp / "laptop")
        profile.vault_set("GITHUB_TOKEN", "tok-123")
        s = harvest.library_sync()
        self.assertEqual(s["bases"], ["bakery-base"])
        top = pool.query({"shape": "catalogue", "features": ["ordering"]}, 1)["top"][0]
        self.assertEqual((top["name"], top["source"]), ("bakery-base", "mine"))
        c = build.clone("bakery-base", self.tmp / "new-site", do_install=False)
        page = (self.tmp / "new-site" / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("Bakery Base", page)
        self.assertNotIn("Maison Levain", page)
        self.assertFalse((self.tmp / "new-site" / ".env").exists())
        self.assertTrue(c["project"].endswith("new-site"))


if __name__ == "__main__":
    unittest.main()
