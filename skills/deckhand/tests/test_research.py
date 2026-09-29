"""Research evidence: briefs pre-filled from the brief, one shared source list, a single-writer merge, quotes
re-checked on their real pages (served locally here), and a run measured from its session log."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from dhlib import checks, research, state  # noqa: E402
from dhlib.cli import main  # noqa: E402
from dhlib.util import DhError, write_json  # noqa: E402

PAGES = {
    "/pricing": ("text/html; charset=utf-8",
                 '<html><head><meta name="description" content="Maison Propre, home cleaning in Lyon"><title>Tarifs</title>'
                 '<script>var hidden = "Deep clean free for everyone";</script></head><body><h1>Our prices</h1>'
                 '<p>Standard clean from&nbsp;€25 per hour, minimum 2 hours.</p><p>Deep clean: €35 per hour.</p>'
                 '<p>We offer an “end of tenancy clean” for students and families moving out.</p>' + "<p>filler text</p>" * 30 + "</body></html>"),
    "/spa": ("text/html", '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'),
}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/blocked":
            self.send_response(403)
            self.end_headers()
            return
        ct, body = PAGES.get(self.path, ("text/plain", None))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = os.environ.get("DECKHAND_HOME")
        os.environ["DECKHAND_HOME"] = str(self.tmp / "home")
        self.root = self.tmp / "proj"
        state.init(self.root, "Maison Propre")
        write_json(self.root / ".deckhand" / "brief.json", {"business": "home cleaning", "audience": "busy families", "market": "Lyon", "languages": ["fr", "en"]})

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DECKHAND_HOME", None)
        else:
            os.environ["DECKHAND_HOME"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def u(self, path):
        # 127.0.0.1 has no dot-less host problem, but url_ok wants a dotted host: it has one
        return self.base + path

    def agent_file(self, agent, claims=(), vocabulary=()):
        write_json(self.root / ".deckhand" / "research" / "agents" / f"{agent}.json", {"claims": list(claims), "vocabulary": list(vocabulary)})

    def dh(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--project", str(self.root), *args])
        return code, json.loads(buf.getvalue().strip().splitlines()[-1])


class BriefAndSources(Base):
    def test_the_brief_is_filled_from_the_owners_brief_and_shows_what_others_read(self):
        research.add_source(self.root, "https://www.maisonpropre.fr/tarifs/?utm_source=x#top", "A1", "pricing", "€25/h standard, €35/h deep")
        b = research.brief(self.root, "pricing", "A2")
        self.assertIn("home cleaning", b["questions"][0]["target"])
        self.assertIn("Lyon", b["questions"][0]["target"])
        self.assertEqual(b["write_to"], ".deckhand/research/agents/A2.json")
        self.assertEqual(b["id_prefix"], "C-A2-")
        self.assertTrue(b["read"].endswith("research-card.md"))
        self.assertEqual(b["seen"][0]["by"], "A1")
        with self.assertRaises(DhError) as e:
            research.brief(self.root, "gossip", "A2")
        self.assertEqual(e.exception.code, "BAD_FOCUS")
        with self.assertRaises(DhError) as e:
            research.brief(self.root, "pricing", "../x")
        self.assertEqual(e.exception.code, "BAD_ID")

    def test_one_page_is_one_page_however_it_is_written_and_nobody_reads_it_twice(self):
        r1 = research.add_source(self.root, "https://www.maisonpropre.fr/tarifs/?utm_source=google#prices", "A1", "pricing", "€25/h")
        self.assertEqual(r1["read_before_by"], [])
        s = research.seen(self.root, "https://maisonpropre.fr/tarifs")
        self.assertFalse(s["new"])
        self.assertEqual(s["read_by"][0]["note"], "€25/h")
        r2 = research.add_source(self.root, "http://maisonpropre.fr/tarifs/", "A3", "pricing", "min 2h")
        self.assertEqual(r2["read_before_by"], [{"by": "A1", "note": "€25/h"}])      # A3 learns A1's note at once
        self.assertTrue(research.seen(self.root, "https://maisonpropre.fr/avis")["new"])
        research.add_source(self.root, "https://maisonpropre.fr/tarifs", "A1", "pricing", "€25/h")   # same agent, same note: no duplicate
        self.assertEqual(research.seen(self.root)["count"], 1)
        with self.assertRaises(DhError) as e:
            research.add_source(self.root, "not a url", "A1")
        self.assertEqual(e.exception.code, "BAD_URL")

    def test_merge_is_single_writer_and_keeps_what_was_written_directly(self):
        write_json(self.root / ".deckhand" / "research.json", {"claims": [{"id": "C-ORCH-01", "claim": "x", "label": "NOT_FOUND", "tried": "y", "by": "ORCH"}]})
        self.agent_file("A1", [{"id": "C-A1-01", "claim": "a", "label": "NOT_FOUND", "tried": "t"}],
                        [{"term": "Ménage", "kind": "customer", "url": "https://a.fr", "quote": "le ménage"}])
        self.agent_file("A2", [{"id": "C-A2-01", "claim": "b", "label": "NOT_FOUND", "tried": "t"}],
                        [{"term": "ménage", "kind": "trade", "url": "https://b.fr", "quote": "ménage pro"}])
        m = research.merge(self.root)
        self.assertEqual((m["claims"], m["vocabulary"]), (3, 1))                   # the same term once
        self.agent_file("A1", [{"id": "C-A1-02", "claim": "a2", "label": "NOT_FOUND", "tried": "t"}])
        research.merge(self.root)
        ids = [c["id"] for c in json.loads((self.root / ".deckhand" / "research.json").read_text(encoding="utf-8"))["claims"]]
        self.assertEqual(sorted(ids), ["C-A1-02", "C-A2-01", "C-ORCH-01"])        # A1's old claim replaced, ORCH's kept
        self.agent_file("A3", [{"id": "C-A2-01", "claim": "clash", "label": "NOT_FOUND", "tried": "t"}])
        with self.assertRaises(DhError) as e:
            research.merge(self.root)
        self.assertEqual(e.exception.code, "DUP_ID")


class Verify(Base):
    def claims(self):
        return [
            {"id": "C-A1-01", "claim": "standard clean €25/h", "label": "VERIFIED", "url": self.u("/pricing"),
             "quote": "Standard clean from €25 per hour … Deep clean: €35 per hour"},              # nbsp + ellipsis join
            {"id": "C-A1-02", "claim": "an end-of-tenancy offer", "label": "SECONDARY", "url": self.u("/pricing"),
             "quote": 'offer an "end of tenancy clean" for students'},                            # curly vs straight quotes
            {"id": "C-A1-03", "claim": "deep clean free", "label": "VERIFIED", "url": self.u("/pricing"), "quote": "Deep clean free for everyone"},
            {"id": "C-A1-04", "claim": "spa claim", "label": "VERIFIED", "url": self.u("/spa"), "quote": "something on a JS page"},
            {"id": "C-A1-05", "claim": "blocked", "label": "SECONDARY", "url": self.u("/blocked"), "quote": "whatever is there"},
            {"id": "C-A1-06", "claim": "no quote", "label": "VERIFIED", "url": self.u("/pricing")},
            {"id": "C-A1-07", "claim": "derived", "label": "INFERRED", "from": ["C-A1-01", "C-A9-99"]},
            {"id": "C-A1-08", "claim": "licence", "label": "NOT_FOUND"},
            {"id": "C-A1-09", "claim": "sure thing", "label": "CERTAIN", "url": self.u("/pricing"), "quote": "Our prices"},
        ]

    def test_quotes_are_checked_on_the_real_page_and_every_label_has_its_rule(self):
        self.agent_file("A1", self.claims(), [
            {"term": "end of tenancy clean", "kind": "customer", "url": self.u("/pricing"), "quote": "an “end of tenancy clean” for students"},
            {"term": "turnover clean", "kind": "trade", "url": self.u("/pricing"), "quote": "Standard clean from €25 per hour"}])
        code, out = self.dh("research", "verify")
        self.assertEqual((code, out["code"]), (1, "RESEARCH_UNVERIFIED"))
        st = {i["id"]: i["status"] for i in json.loads((self.root / ".deckhand" / "research" / "verify.json").read_text(encoding="utf-8"))["items"]}
        self.assertEqual(st["C-A1-01"], "found")
        self.assertEqual(st["C-A1-02"], "found")
        self.assertEqual(st["C-A1-03"], "mismatch")          # it is in a <script>, not on the page a person reads
        self.assertEqual(st["C-A1-04"], "unchecked")         # drawn by JavaScript: unchecked, not failed
        self.assertEqual(st["C-A1-05"], "unchecked")         # 403: blocked, not failed
        for i in ("C-A1-06", "C-A1-07", "C-A1-08", "C-A1-09"):
            self.assertEqual(st[i], "invalid", i)
        self.assertEqual(st["end of tenancy clean"], "found")
        self.assertEqual(st["turnover clean"], "invalid")    # the quote does not contain the term
        s = out["summary"]
        self.assertEqual((s["found"], s["mismatch"], s["invalid"], s["unchecked"]), (2, 1, 4, 2))

    def test_a_fixed_research_passes_and_the_page_cache_works_offline(self):
        good = [c for c in self.claims() if c["id"] in ("C-A1-01", "C-A1-02", "C-A1-04")] + [
            {"id": "C-A1-08", "claim": "licence", "label": "NOT_FOUND", "tried": "regulator site, trade body, 'licence ménage Lyon'"},
            {"id": "C-A1-07", "claim": "derived", "label": "INFERRED", "from": ["C-A1-01"]}]
        self.agent_file("A1", good, [{"term": "end of tenancy clean", "kind": "customer", "url": self.u("/pricing"), "quote": "end of tenancy clean"}])
        r = research.verify(self.root)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["summary"]["unlisted_sources"], 3)             # cited (2 claims + 1 term) but never `dh research add`-ed
        r2 = research.verify(self.root, offline=True)                      # cached page text: no network needed
        self.assertTrue(r2["ok"])


class PhaseCheck(Base):
    def test_research_with_nothing_found_on_its_pages_is_not_done(self):
        # finding 14: every fetch blocked, every item unchecked, and the phase still passed
        base = {"competitors": [{"name": n, "url": f"https://{n}.fr", "strengths": ["s"], "gaps": ["g"]} for n in ("a", "b", "c")],
                "audience": {"primary": "families"}, "conversion": {"plays": ["instant quote"]}, "features": {"now": ["booking"]},
                "claims": [{"id": "C-1", "claim": "x", "label": "VERIFIED", "url": "https://a.fr", "quote": "x"}],
                "vocabulary": [{"term": t, "kind": "customer", "url": "https://a.fr", "quote": t} for t in ("a1", "b2", "c3")]}
        p = self.root / ".deckhand" / "research.json"
        write_json(p, base)
        import hashlib
        write_json(self.root / ".deckhand" / "research" / "verify.json", {"ok": True, "research_sha": hashlib.sha1(p.read_bytes()).hexdigest(),
                   "summary": {"found": 0, "terms_found": 0, "unchecked": 1, "mismatch": 0, "invalid": 0, "terms_bad": 0}})
        why = checks.research(self.root, {})["why"]
        self.assertTrue(any("found 0 quotes" in w for w in why), why)

    def test_research_is_done_only_with_claims_vocabulary_and_a_verify_after_the_last_edit(self):
        base = {"competitors": [{"name": n, "url": f"https://{n}.fr", "strengths": ["s"], "gaps": ["g"]} for n in ("a", "b", "c")],
                "audience": {"primary": "families"}, "conversion": {"plays": ["instant quote"]}, "features": {"now": ["booking"]}}
        write_json(self.root / ".deckhand" / "research.json", base)
        why = checks.research(self.root, {})["why"]
        self.assertTrue(any("claims[]" in w for w in why))
        self.assertTrue(any("vocabulary" in w for w in why))
        self.assertTrue(any("dh research verify" in w for w in why))
        vocab = [{"term": t, "kind": "customer", "url": self.u("/pricing"), "quote": q} for t, q in
                 (("standard clean", "Standard clean from"), ("deep clean", "Deep clean: €35"), ("minimum 2 hours", "minimum 2 hours"))]
        write_json(self.root / ".deckhand" / "research.json", {**base, "claims": [
            {"id": "C-1", "claim": "€25/h", "label": "VERIFIED", "url": self.u("/pricing"), "quote": "from €25 per hour"}], "vocabulary": vocab})
        self.assertTrue(research.verify(self.root)["ok"])
        self.assertTrue(checks.research(self.root, {})["ok"], checks.research(self.root, {})["why"])
        time.sleep(0.01)
        p = self.root / ".deckhand" / "research.json"
        p.write_text(p.read_text(encoding="utf-8").replace("€25/h", "€26/h"), encoding="utf-8")   # edited after the verify
        self.assertFalse(checks.research(self.root, {})["ok"])


def _cc(rows):
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def _search(i, query, urls, mid, out_tokens=10):
    use = {"type": "assistant", "message": {"id": mid, "usage": {"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": out_tokens},
                                           "content": [{"type": "tool_use", "id": f"t{i}", "name": "WebSearch", "input": {"query": query}}]}}
    res = {"type": "user", "toolUseResult": {"query": query, "results": [{"tool_use_id": "s", "content": [{"title": "x", "url": u} for u in urls]}]},
           "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "Links: …"}]}}
    return [use, res]


def _fetch(i, url, mid):
    return [{"type": "assistant", "message": {"id": mid, "usage": {"input_tokens": 1, "output_tokens": 5},
                                              "content": [{"type": "tool_use", "id": f"f{i}", "name": "WebFetch", "input": {"url": url, "prompt": "p"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"f{i}", "content": "page"}]}}]


class Score(Base):
    def test_near_repeats_are_the_same_query_in_disguise(self):
        self.assertTrue(research.near_repeat("postgres jit threshold", "postgres jit threshold setting"))   # one word added
        self.assertTrue(research.near_repeat("cleaning prices Lyon", "Lyon cleaning price"))               # reordered, plural
        self.assertFalse(research.near_repeat("cleaning prices Lyon", "end of tenancy clean Lyon regulations"))

    def test_a_run_is_measured_from_its_session_log_and_compared_with_a_baseline(self):
        d = self.tmp / "session"
        (d / "subagents").mkdir(parents=True)
        main_rows = (_search(1, "cleaning prices Lyon", ["https://a.fr/tarifs", "https://b.fr"], "m1")
                     + _search(2, "cleaning prices Lyon 2026", ["https://a.fr/tarifs/", "https://b.fr"], "m2")      # paraphrase, zero gain
                     + _fetch(3, "https://a.fr/tarifs", "m3") + _fetch(4, "https://www.a.fr/tarifs/?utm_source=x", "m4"))
        main_rows.append(dict(main_rows[0]))                                   # a streamed duplicate of message m1: tokens counted once
        (d / "main.jsonl").write_text(_cc(main_rows), encoding="utf-8")
        (d / "subagents" / "agent-A2.jsonl").write_text(_cc(_search(5, "Lyon cleaning price", ["https://c.fr"], "s1") + _fetch(6, "https://a.fr/tarifs", "s2")), encoding="utf-8")
        m = research.metrics(research.load_trace(d))
        self.assertEqual((m["searches"], m["page_reads"], m["unique_pages"]), (3, 3, 1))
        self.assertEqual((m["repeated_queries"], m["repeated_across_agents"]), (1, 1))
        self.assertEqual((m["duplicate_reads"], m["duplicate_reads_across_agents"]), (2, 1))
        self.assertEqual(m["zero_gain_streak_max"], 1)
        self.assertEqual(m["agents"], 2)
        self.assertEqual(m["tokens_out"], 10 + 10 + 5 + 5 + 10 + 5)
        generic = self.tmp / "old.jsonl"                                       # any harness: one JSON per search
        generic.write_text(_cc([{"query": "menage lyon", "results": ["https://a.fr"]}, {"query": "menage lyon prix", "results": ["https://a.fr"]},
                                {"query": "menage lyon prix tarif", "results": ["https://a.fr"], "opened": ["https://a.fr", "https://a.fr/"]}]), encoding="utf-8")
        write_json(self.root / ".deckhand" / "research.json", {"claims": [{"id": "C-1", "label": "VERIFIED"}, {"id": "C-2", "label": "VERIFIED"}]})
        code, out = self.dh("research", "score", str(d), "--baseline", str(generic))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["baseline"]["repeated_queries"], 2)
        self.assertEqual(out["delta"]["searches"], 0)
        self.assertEqual(out["run"]["searches_per_proven_claim"], 1.5)
        self.assertIn("tokens_out_per_proven_claim", out["run"])


if __name__ == "__main__":
    unittest.main()
