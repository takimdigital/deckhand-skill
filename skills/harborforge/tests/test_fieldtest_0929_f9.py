"""F9: the build check must fail while planned public pages 404 or a planned form is missing."""
import http.server
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import tmpclean  # noqa: E402  (read-only-safe removal of temp folders)
from dhlib import checks, state  # noqa: E402
from dhlib.util import write_json  # noqa: E402

SITEMAP = {"pages": [{"id": "home", "route": "/"}, {"id": "pricing", "route": "/pricing"},
                     {"id": "contact", "route": "/contact"}, {"id": "acct", "route": "/account", "auth": "user"},
                     {"id": "post", "route": "/blog/[slug]"}],
           "forms": [{"id": "contact-form", "page": "contact", "submit": "api:POST /api/contact",
                      "success": "state:ok", "error": "state:err"}]}


def serve(pages):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            st, body = pages.get(self.path.split("?")[0], (404, "not found"))
            b = body.encode("utf-8")
            self.send_response(st)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class F9(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.env = mock.patch.dict(os.environ, {"DECKHAND_HOME": str(self.tmp / "home")})
        self.env.start()
        self.root = self.tmp / "p"
        self.root.mkdir()
        state.init(self.root, "p", "auto", "scratch")
        (self.root / "package.json").write_text("{}", encoding="utf-8")
        write_json(self.root / ".deckhand" / "sitemap.json", SITEMAP)
        self.s = state.load(self.root)
        self.s["base"] = {"kind": "scratch"}

    def tearDown(self):
        self.env.stop()
        tmpclean.rmtree(self.tmp)

    def run_check(self, pages):
        srv = serve(pages)
        try:
            write_json(self.root / ".deckhand" / "dev.json", {"url": f"http://127.0.0.1:{srv.server_port}"})
            return checks.build(self.root, self.s)
        finally:
            srv.shutdown()

    def test_F9_a_planned_page_that_404s_fails_the_build(self):
        r = self.run_check({"/": (200, "<a href='/pricing'>p</a>"), "/contact": (200, "<form></form>")})
        self.assertFalse(r["ok"])
        self.assertIn("/pricing -> 404", " ".join(r["why"]))
        self.assertNotIn("/account", " ".join(r["why"]))                 # signed-in pages and dynamic routes are not probed

    def test_F9_a_planned_form_missing_from_its_page_fails_the_build(self):
        r = self.run_check({"/": (200, "ok"), "/pricing": (200, "ok"), "/contact": (200, "<p>write to us</p>")})
        self.assertFalse(r["ok"])
        self.assertIn("contact-form", " ".join(r["why"]))

    def test_F9_every_page_and_form_there_passes(self):
        r = self.run_check({"/": (200, "ok"), "/pricing": (200, "ok"), "/contact": (200, "<FORM action='/x'></FORM>")})
        self.assertTrue(r["ok"], r["why"])

    def test_F9_a_client_drawn_page_is_not_failed_for_a_form_it_cannot_show_yet(self):
        spa = '<html><body><div id="root"></div></body></html>'
        r = self.run_check({"/": (200, spa), "/pricing": (200, spa), "/contact": (200, spa)})
        self.assertTrue(r["ok"], r["why"])

    def test_F9_without_a_plan_only_the_root_is_judged_as_before(self):
        (self.root / ".deckhand" / "sitemap.json").unlink()
        r = self.run_check({"/": (200, "ok")})
        self.assertTrue(r["ok"], r["why"])


if __name__ == "__main__":
    unittest.main()
