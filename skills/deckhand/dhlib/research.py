"""RESEARCH evidence: facts you can re-check, sources nobody reads twice, and a measure of what a run cost.

  dh research brief --focus F --agent ID   one agent's brief: the card, pre-filled questions (TARGET · PRIMARY ·
                                           DONE_WHEN · FRESH) from data/research.json + the brief, budget, pages
                                           already read by other agents, vocabulary so far
  dh research add URL --by ID --kind K --note "…"   the shared source list (.deckhand/research/sources.jsonl,
                                           append-only: parallel agents never race); returns earlier notes
  dh research seen [URL]                   has anyone read it? (use their note instead of reopening)
  dh research merge                        agents' files (.deckhand/research/agents/ID.json) → research.json
                                           claims[] + vocabulary[] (single writer; the agents never share a file)
  dh research verify [--refresh|--offline] fetch every cited page and check each quote is really on it;
                                           labels validated (VERIFIED/SECONDARY need url+quote, INFERRED needs
                                           from[], NOT_FOUND needs tried); vocabulary quotes must contain the term
  dh research score [LOG] [--baseline LOG] a research run measured from its session log: searches, page reads,
                                           repeated queries, duplicate reads, zero-gain streaks, tokens; + the
                                           outcome (verified claims per search, tokens per verified claim)
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .util import DATA, REFS, DhError, append_jsonl, now, read_json, read_jsonl, write_json

POLICY = json.loads((DATA / "research.json").read_text(encoding="utf-8"))
LABELS = tuple(POLICY["labels"])
CARD = REFS / "research-card.md"
AGENT_RX = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
MAX_PAGE = 3_000_000
MIN_TEXT = 200                     # less visible text than this = the page is drawn by JavaScript: unchecked, not failed


def _dir(root) -> Path:
    return Path(root) / ".deckhand" / "research"


def _rj(root) -> Path:
    return Path(root) / ".deckhand" / "research.json"


def url_ok(u) -> bool:
    try:
        p = urllib.parse.urlsplit(str(u or ""))
        return p.scheme in ("http", "https") and bool(p.netloc) and "." in p.netloc
    except ValueError:
        return False


def url_key(u: str) -> str:
    """The same page however it was written: no fragment, no tracking params, no www., no trailing slash."""
    p = urllib.parse.urlsplit(str(u).strip())
    host = p.netloc.lower().removeprefix("www.")
    q = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))])
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}" + (f"?{q}" if q else "")


# ------------------------------------------------------------------ brief + shared source list

def short_business(b: dict) -> str:
    """What goes into search queries: brief.category ("commercial cleaning software"), else the business
    sentence cut at its first clause — a 300-character pitch is not a search query (D14)."""
    cat = str(b.get("category") or "").strip()
    if cat:
        return cat
    text = str(b.get("business") or "").strip()
    if not text:
        return "this business"
    first = re.split(r"[.;:(—–\n]| - |, (?:with|for|that|which|where|so)\b", text)[0].strip()
    words = first.split()
    return " ".join(words[:10]) if words else "this business"


def _ctx(root) -> dict:
    b = read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}
    langs = b.get("languages") or ["en"]
    seo = b.get("seo") or {}
    market = b.get("market") or ", ".join(seo.get("locations") or []) or "the owner's market"
    aud = b.get("audience")
    aud = aud.get("primary") if isinstance(aud, dict) else aud
    return {"business": short_business(b), "audience": aud or "its customers", "market": market,
            "language": langs[0] if isinstance(langs, list) else str(langs)}


def brief(root, focus: str, agent: str) -> dict:
    if focus not in POLICY["focus"]:
        raise DhError("BAD_FOCUS", f"focus must be one of {', '.join(POLICY['focus'])}")
    if not AGENT_RX.match(agent or ""):
        raise DhError("BAD_ID", "agent id: letters, digits, - or _ (≤ 16), e.g. A2")
    ctx = _ctx(root)
    f = POLICY["focus"][focus]
    fill = lambda s: s.format(**ctx)  # noqa: E731
    qs = [{**q, "target": fill(q["target"]), "primary": fill(q["primary"])} for q in f["questions"]]
    mine = read_json(_dir(root) / "agents" / f"{agent}.json", {}) or {}
    return {"agent": agent, "focus": focus, "read": str(CARD), "questions": qs, "budget": f["budget"],
            "write_to": f".deckhand/research/agents/{agent}.json", "id_prefix": f"C-{agent}-",
            "language": ctx["language"], "market": ctx["market"],
            "seen": seen(root)["sources"][-40:], "vocabulary_so_far": sorted({v.get("term", "") for v in _all_vocab(root)} - {""}),
            "yours_so_far": {"claims": len(mine.get("claims", [])), "vocabulary": len(mine.get("vocabulary", []))},
            "then": f"dh research verify (after `{agent}.json` is written) — every quote is fetched and checked"}


THIN_NOTE = re.compile(r"(?i)^\s*(|opened|open|seen|read|visited|checked|ok|done|page|looked|skimmed|n/?a|-+|\.+|todo|see page|useful|relevant)\s*$")


def add_source(root, url: str, by: str, kind: str = "", note: str = "") -> dict:
    if not url_ok(url):
        raise DhError("BAD_URL", f"not an http(s) URL: {url!r}")
    if not AGENT_RX.match(by or ""):
        raise DhError("BAD_ID", "--by: the agent id (letters, digits, - or _)")
    note = (note or "").strip()
    if THIN_NOTE.match(note) or (len(note) < 12 and not re.search(r"\d", note)):
        raise DhError("NOTE_TOO_THIN", f"--note {note!r} tells the next agent nothing: write the dense facts found on the page "
                      "(\"€25/h standard, €35/h deep, min 2 h\"), or \"nothing usable: <why>\"")
    before = [s for s in read_jsonl(_dir(root) / "sources.jsonl") if url_key(s.get("url", "")) == url_key(url)]
    row = {"at": now(), "url": url.strip(), "by": by, "kind": kind, "note": note[:800]}
    if not any(s.get("by") == by and s.get("note") == row["note"] for s in before):
        append_jsonl(_dir(root) / "sources.jsonl", row)
    return {"added": row["url"], "read_before_by": [{"by": s.get("by"), "note": s.get("note", "")[:300]} for s in before if s.get("by") != by]}


def seen(root, url: str | None = None) -> dict:
    rows = read_jsonl(_dir(root) / "sources.jsonl")
    if url:
        hits = [s for s in rows if url_key(s.get("url", "")) == url_key(url)]
        return {"url": url, "new": not hits, "read_by": [{"by": s.get("by"), "kind": s.get("kind"), "note": s.get("note", "")} for s in hits],
                "do": "open it, then `dh research add`" if not hits else "use these notes — do not reopen"}
    last = {}
    for s in rows:
        last[url_key(s.get("url", ""))] = s
    return {"count": len(last), "sources": [{"url": s.get("url"), "by": s.get("by"), "kind": s.get("kind"), "note": s.get("note", "")[:160]}
                                            for s in last.values()]}


# ------------------------------------------------------------------ merge (single writer)

def _agent_files(root) -> list:
    d = _dir(root) / "agents"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _all_vocab(root) -> list:
    out = list((read_json(_rj(root), {}) or {}).get("vocabulary") or [])
    for f in _agent_files(root):
        out += (read_json(f, {}) or {}).get("vocabulary") or []
    return out


def merge(root) -> dict:
    files = _agent_files(root)
    r = read_json(_rj(root), None, expect=dict)
    if r is None:
        r = json.loads((Path(__file__).resolve().parent.parent / "templates" / "research.json").read_text(encoding="utf-8"))
    if not files:
        return {"merged": 0, "claims": len(r.get("claims") or []), "vocabulary": len(r.get("vocabulary") or [])}
    agents, claims, vocab, bad = set(), [], [], []
    for f in files:
        data = read_json(f, None, expect=dict)
        if not isinstance(data, dict):
            bad.append(f.name)
            continue
        agents.add(f.stem)
        claims += [{**c, "by": c.get("by") or f.stem} for c in data.get("claims") or [] if isinstance(c, dict)]
        vocab += [{**v, "by": v.get("by") or f.stem} for v in data.get("vocabulary") or [] if isinstance(v, dict)]
    if bad:
        raise DhError("BAD_AGENT_FILE", f"not valid JSON: {', '.join(bad)} — fix it, nothing was merged")
    keep_c = [c for c in r.get("claims") or [] if c.get("by") not in agents]          # written straight into research.json
    keep_v = [v for v in r.get("vocabulary") or [] if v.get("by") not in agents]
    all_c = keep_c + claims
    ids = [c.get("id") for c in all_c]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    if dup:
        raise DhError("DUP_ID", f"claim ids used twice: {', '.join(dup)} — use the agent prefix (C-ID-NN)")
    terms, all_v = set(), []
    for v in keep_v + vocab:
        k = _n(v.get("term", ""))
        if k and k not in terms:
            terms.add(k)
            all_v.append(v)
    new = {**r, "claims": all_c, "vocabulary": all_v}
    if new != r:
        write_json(_rj(root), new)
    return {"merged": len(files), "agents": sorted(agents), "claims": len(all_c), "vocabulary": len(all_v)}


# ------------------------------------------------------------------ verify

def _n(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = s.translate({0x2019: "'", 0x2018: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0x00A0: " ", 0x00AD: None})
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in(quote: str, text: str) -> bool:
    """Every part of the quote, in order (`…` or `...` joins two parts of one page)."""
    parts = [p for p in (_n(x) for x in re.split(r"\s*(?:\.\.\.|…)\s*", quote or "")) if p]
    t, i = _n(text), 0
    for p in parts:
        j = t.find(p, i)
        if j < 0:
            return False
        i = j + len(p)
    return bool(parts)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        a = dict(attrs)
        for k in ("alt", "title", "aria-label", "placeholder"):
            if a.get(k):
                self.out.append(a[k])
        if tag == "meta" and a.get("content") and (a.get("name") or a.get("property") or "").lower() in (
                "description", "og:title", "og:description", "twitter:title", "twitter:description"):
            self.out.append(a["content"])

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(raw: str) -> str:
    p = _Text()
    try:
        p.feed(raw)
        p.close()
    except Exception:  # noqa: BLE001 — broken markup still yields the text read so far
        pass
    return re.sub(r"[ \t\r\f\v]+", " ", "\n".join(x.strip() for x in p.out if x and x.strip()))


def page_text(root, url: str, refresh: bool = False, offline: bool = False) -> tuple:
    """(status, text, detail) — status ok | blocked | error | unsupported | offline. Cached per URL."""
    c = _dir(root) / "cache"
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    tp, mp = c / f"{h}.txt", c / f"{h}.json"
    if tp.exists() and mp.exists() and not refresh:
        m = read_json(mp, {}) or {}
        return m.get("status", "ok"), tp.read_text(encoding="utf-8"), m.get("detail", "cached")
    if offline:
        return "offline", "", "not fetched yet (--offline)"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; deckhand-research/2; quote check)",
                                                   "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            raw = r.read(MAX_PAGE)
            charset = r.headers.get_content_charset() or "utf-8"
        if "pdf" in ct or raw[:5] == b"%PDF-":
            status, text, detail = "unsupported", "", "PDF — check the quote by hand"
        else:
            body = raw.decode(charset, errors="replace")
            text = html_text(body) if ("html" in ct or "<html" in body[:2000].lower()) else body
            status, detail = "ok", f"{len(text)} chars"
    except urllib.error.HTTPError as e:
        status, text, detail = ("blocked" if e.code in (401, 403, 429, 451, 503) else "error"), "", f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        status, text, detail = "error", "", str(e)[:120]
    c.mkdir(parents=True, exist_ok=True)
    tp.write_text(text, encoding="utf-8")
    write_json(mp, {"url": url, "status": status, "detail": detail, "at": now()})
    return status, text, detail


def _problems(item: dict, kind: str, ids: set) -> list:
    p = []
    if kind == "term":
        if not str(item.get("term") or "").strip():
            p.append("term missing")
        if item.get("kind") not in POLICY["vocabulary_kinds"]:
            p.append(f"kind must be one of {POLICY['vocabulary_kinds']}")
        if not url_ok(item.get("url")):
            p.append("url missing — a term comes from a real page")
        if len(str(item.get("quote") or "")) < 8:
            p.append("quote missing (verbatim, containing the term)")
        elif item.get("term") and _n(item["term"]) not in _n(item["quote"]):
            p.append("the quote does not contain the term")
        return p
    if not str(item.get("id") or "").strip():
        p.append("id missing")
    if not str(item.get("claim") or "").strip():
        p.append("claim text missing")
    lab = item.get("label")
    if lab not in LABELS:
        return p + [f"label must be one of {', '.join(LABELS)}"]
    if lab in ("VERIFIED", "SECONDARY"):
        if not url_ok(item.get("url")):
            p.append(f"{lab} needs the url of the page you opened")
        q = str(item.get("quote") or "")
        if len(q) < 8:
            p.append(f"{lab} needs a verbatim quote from that page")
        elif len(q) > 400:
            p.append("quote longer than 400 characters — quote the sentence, not the page")
    elif lab == "INFERRED":
        src = item.get("from") or []
        if not src:
            p.append("INFERRED needs from: [the claim ids it is derived from]")
        missing = [x for x in src if x not in ids]
        if missing:
            p.append(f"from: unknown claim ids {', '.join(missing)}")
    elif lab == "NOT_FOUND" and not str(item.get("tried") or "").strip():
        p.append("NOT_FOUND needs tried: the angles searched")
    return p


def verify(root, refresh: bool = False, offline: bool = False) -> dict:
    root = Path(root)
    m = merge(root)
    r = read_json(_rj(root), None, expect=dict)
    if r is None:
        raise DhError("NO_RESEARCH", "no .deckhand/research.json (and no agent files to merge) — research first")
    claims, vocab = r.get("claims") or [], r.get("vocabulary") or []
    ids = {c.get("id") for c in claims}
    known = {url_key(s.get("url", "")) for s in read_jsonl(_dir(root) / "sources.jsonl")}
    items = []

    def check(it, kind):
        key = it.get("id") if kind == "claim" else it.get("term")
        row = {"kind": kind, "id": key, "url": it.get("url"), "label": it.get("label") if kind == "claim" else None}
        probs = _problems(it, kind, ids)
        if probs:
            return {**row, "status": "invalid", "why": "; ".join(probs)}
        if kind == "claim" and it["label"] in ("INFERRED", "NOT_FOUND"):
            return {**row, "status": "ok"}
        st, text, detail = page_text(root, it["url"], refresh=refresh, offline=offline)
        if st != "ok":
            return {**row, "status": "unchecked", "why": f"{st}: {detail}"}
        if len(text.strip()) < MIN_TEXT:
            return {**row, "status": "unchecked", "why": "the page is drawn by JavaScript (no text in its HTML) — check by hand"}
        if not quote_in(it["quote"], text):
            return {**row, "status": "mismatch", "why": "the quote is not on this page — copy it verbatim, or relabel"}
        return {**row, "status": "found", **({"unlisted": True} if url_key(it["url"]) not in known else {})}

    for c in claims:
        items.append(check(c, "claim"))
    for v in vocab:
        items.append(check(v, "term"))
    count = lambda k, st: sum(1 for i in items if i["kind"] == k and i["status"] == st)  # noqa: E731
    labels = {lab: sum(1 for c in claims if c.get("label") == lab) for lab in LABELS}
    summary = {"claims": len(claims), "labels": labels, "found": count("claim", "found"), "mismatch": count("claim", "mismatch"),
               "invalid": count("claim", "invalid"), "unchecked": count("claim", "unchecked"),
               "vocabulary": len(vocab), "terms_found": count("term", "found"), "terms_bad": count("term", "mismatch") + count("term", "invalid"),
               "unlisted_sources": sum(1 for i in items if i.get("unlisted"))}
    ok = summary["mismatch"] == 0 and summary["invalid"] == 0 and summary["terms_bad"] == 0
    rj = _rj(root).read_bytes()
    report = {"ok": ok, "at": now(), "research_sha": hashlib.sha1(rj).hexdigest(), "summary": summary, "merge": m, "items": items}
    write_json(_dir(root) / "verify.json", report)
    return {"ok": ok, "summary": summary, "problems": [i for i in items if i["status"] in ("mismatch", "invalid")][:25],
            "unchecked": [{"id": i["id"], "why": i["why"]} for i in items if i["status"] == "unchecked"][:10],
            "file": ".deckhand/research/verify.json"}


def verified_now(root) -> dict | None:
    """The last verify, only if research.json has not changed since (else None)."""
    v = read_json(_dir(root) / "verify.json", None, expect=dict)
    p = _rj(root)
    if not v or not p.exists() or v.get("research_sha") != hashlib.sha1(p.read_bytes()).hexdigest():
        return None
    return v


# ------------------------------------------------------------------ score (before / after)

SEARCH_TOOLS = re.compile(r"(^|_)(web_?search|search)$", re.I)
FETCH_TOOLS = re.compile(r"(web_?fetch|fetch|browse|open_?url|read_?url)$", re.I)
STOP = set("a an and are as at be by for from how in is it of on or that the this to was what when where which who why with "
           "de la le les des du et en pour un une".split())


def _qt(q: str) -> frozenset:
    return frozenset((w[:-1] if len(w) > 3 and w.endswith("s") else w) for w in re.findall(r"\w+", (q or "").lower()) if w not in STOP)


def near_repeat(a: str, b: str) -> bool:
    """The same query in disguise: identical words, one word added or removed, or ≥ 80% of words shared."""
    x, y = _qt(a), _qt(b)
    if not x or not y:
        return False
    small, big = (x, y) if len(x) <= len(y) else (y, x)
    return x == y or (small <= big and len(big - small) <= 1) or len(x & y) / len(x | y) >= 0.8


def _urls_in(obj) -> list:
    return re.findall(r"https?://[^\s\"'<>)\]\\]+", json.dumps(obj) if not isinstance(obj, str) else obj)


def load_trace(path) -> dict:
    """Events from a Claude Code session log (a file, or a folder of them incl. sub-agents), or from a generic trace
    (one JSON per line: {agent?, query?, results?, url?, opened?})."""
    path = Path(path)
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    if not files or not all(f.exists() for f in files):
        raise DhError("NO_TRACE", f"no session log at {path}")
    events, pending, seen_msg, seen_use, tokens = [], {}, set(), set(), {"input": 0, "output": 0, "cache_read": 0}
    for f in files:
        default = "main" if f.parent == (path if path.is_dir() else f.parent) else f.stem
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            agent = r.get("agentId") or r.get("agent") or ("sidechain" if r.get("isSidechain") else default)
            if "message" not in r and ("query" in r or "url" in r or "opened" in r):          # generic trace
                if r.get("query"):
                    events.append({"agent": agent, "kind": "search", "query": r["query"], "results": list(r.get("results") or [])})
                for u in ([r["url"]] if r.get("url") else []) + list(r.get("opened") or []):
                    events.append({"agent": agent, "kind": "fetch", "url": u})
                continue
            msg = r.get("message") or {}
            usage, mid = msg.get("usage"), msg.get("id") or r.get("requestId")
            if isinstance(usage, dict) and mid and mid not in seen_msg:
                seen_msg.add(mid)
                tokens["input"] += int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
                tokens["output"] += int(usage.get("output_tokens") or 0)
                tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for x in content:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_use":
                    if x.get("id") in seen_use:                  # a log row written twice is one call
                        continue
                    seen_use.add(x.get("id"))
                    name, inp = str(x.get("name") or ""), x.get("input") or {}
                    if SEARCH_TOOLS.search(name) and inp.get("query"):
                        ev = {"agent": agent, "kind": "search", "query": inp["query"], "results": []}
                    elif FETCH_TOOLS.search(name) and inp.get("url"):
                        ev = {"agent": agent, "kind": "fetch", "url": inp["url"]}
                    else:
                        continue
                    events.append(ev)
                    pending[x.get("id")] = ev
                elif x.get("type") == "tool_result" and x.get("tool_use_id") in pending:
                    ev = pending.pop(x["tool_use_id"])
                    if ev["kind"] == "search":
                        tur = r.get("toolUseResult")
                        urls = [c.get("url") for res in (tur.get("results") or []) if isinstance(res, dict)
                                for c in (res.get("content") or []) if isinstance(c, dict) and c.get("url")] if isinstance(tur, dict) else []
                        ev["results"] = urls or _urls_in(x.get("content"))
    return {"events": events, "tokens": tokens, "files": len(files)}


def metrics(trace: dict) -> dict:
    ev = trace["events"]
    searches = [e for e in ev if e["kind"] == "search"]
    fetches = [e for e in ev if e["kind"] == "fetch"]
    repeats = cross = 0
    by_agent: dict = {}
    for i, s in enumerate(searches):
        earlier = searches[:i]
        if any(near_repeat(s["query"], e["query"]) for e in earlier if e["agent"] == s["agent"]):
            repeats += 1
        elif any(near_repeat(s["query"], e["query"]) for e in earlier if e["agent"] != s["agent"]):
            cross += 1
        by_agent.setdefault(s["agent"], []).append(s)
    zero_max = 0
    for runs in by_agent.values():
        seen_u, streak = set(), 0
        for s in runs:
            new = {url_key(u) for u in s["results"]} - seen_u
            seen_u |= new
            streak = 0 if new else streak + 1
            zero_max = max(zero_max, streak)
    read, dup, dup_cross = {}, 0, 0
    for f in fetches:
        k = url_key(f["url"])
        if k in read:
            dup += 1
            dup_cross += read[k] != f["agent"]
        else:
            read[k] = f["agent"]
    hosts = {urllib.parse.urlsplit(u).netloc.lower().removeprefix("www.") for e in ev for u in (e.get("results") or []) + ([e["url"]] if e.get("url") else [])}
    t = trace["tokens"]
    return {"searches": len(searches), "page_reads": len(fetches), "unique_pages": len(read), "duplicate_reads": dup,
            "duplicate_reads_across_agents": dup_cross, "repeated_queries": repeats, "repeated_across_agents": cross,
            "zero_gain_streak_max": zero_max, "domains": len(hosts - {""}), "agents": len({e["agent"] for e in ev}),
            "tokens_in": t["input"], "tokens_out": t["output"], "tokens_cache_read": t["cache_read"]}


def outcome(research_file) -> dict:
    r = read_json(research_file, None, expect=dict) if research_file else None
    if not r:
        return {}
    claims = r.get("claims") or []
    v = read_json(Path(research_file).parent / "research" / "verify.json", None, expect=dict) or {}
    s = v.get("summary") or {}
    return {"claims": len(claims), "verified": sum(1 for c in claims if c.get("label") == "VERIFIED"),
            "quotes_found": s.get("found"), "quote_mismatches": s.get("mismatch"), "vocabulary": len(r.get("vocabulary") or []),
            "competitors": len([c for c in r.get("competitors") or [] if url_ok(c.get("url"))])}


def _with_ratios(m: dict, o: dict) -> dict:
    out = {**m, **o}
    good = o.get("quotes_found") if o.get("quotes_found") is not None else o.get("verified")
    if good:
        out["searches_per_proven_claim"] = round(m["searches"] / good, 2)
        out["tokens_out_per_proven_claim"] = round(m["tokens_out"] / good)
    return out


def _combine(paths) -> dict:
    out = {"events": [], "tokens": {"input": 0, "output": 0, "cache_read": 0}, "files": 0}
    for p in paths:
        tr = load_trace(p)
        out["events"] += tr["events"]
        out["files"] += tr["files"]
        for k in out["tokens"]:
            out["tokens"][k] += tr["tokens"][k]
    return out


def score(root, log=None, baseline=None, research=None, baseline_research=None) -> dict:
    root = Path(root)
    if log:
        paths = [Path(log)]
    else:                                                   # this project's latest Claude Code session (+ its sub-agents)
        from . import autopsy as AU
        d = AU.claude_dir_for(root)
        logs = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
        if not logs:
            raise DhError("NO_TRACE", "no Claude Code session log for this project — pass one: dh research score <log.jsonl|folder>")
        sub = logs[-1].with_suffix("")
        paths = [logs[-1]] + ([sub] if sub.is_dir() and any(sub.rglob("*.jsonl")) else [])
    trace = _combine(paths)
    rf = Path(research) if research else _rj(root)
    run = _with_ratios(metrics(trace), outcome(rf if rf.exists() else None))
    run["logs"] = [str(p) for p in paths]
    if not baseline:
        return {"run": run, "note": "compare two runs: dh research score NEW_LOG --baseline OLD_LOG (--baseline-research OLD/research.json)"}
    base = _with_ratios(metrics(load_trace(baseline)), outcome(baseline_research))
    delta = {k: round(run[k] - base[k], 2) for k in run if isinstance(run.get(k), (int, float)) and isinstance(base.get(k), (int, float))}
    return {"run": run, "baseline": base, "delta": delta,
            "read": "negative delta = fewer (searches, reads, repeats, tokens); positive = more (claims, quotes found)"}
