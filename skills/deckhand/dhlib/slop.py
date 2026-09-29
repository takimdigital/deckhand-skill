"""SLOP: AI-sounding copy, found by script — one engine for every language, one data pack per language.

The model writes the words; this proves they do not read like a model wrote them. No model call, no token, no
dependency: the same text always gets the same verdict.

  engine   this file. Features: cliché words (strong tells, weaker buzz words), cliché phrases (openers, hedges,
           "not X, it's Y" contrasts, CTAs, a chat voice leaked onto the page), sentence-initial transitions used
           more than once, superlatives with no number beside them, em dashes, exclamation marks and emoji above
           a rate, repeated triads, flat sentence rhythm (low burstiness). Points per 100 words → clean | review | slop.
  packs    data/slop/<lang>.json (schema deckhand.slop/1) — the words and patterns of one language, and examples
           that prove them: `lint` fails a pack whose slop examples score clean, whose clean examples do not, or
           whose phrase does not match its own example. data/slop/_common.json holds the weights and thresholds.
           A language with no pack still gets the language-free features (punctuation, emoji, rhythm).
  overlays ~/.deckhand/slop/<lang>.json (`dh slop add`: the owner's own finds, applied at once, exported as a
           community bundle by `dh slop export`) · <project>/.deckhand/slop.json (`dh slop allow`: brand words,
           `ignore` path globs). A line carrying `dh:slop-ok` is never read (a real customer's quote stays theirs).

Where it runs: `dh slop check` (text, files, a project, or rendered pages of any URL) · `dh rebrand check` (so the
brand phase and `dh verify` honesty row block a page that reads as slop) · `dh verify` (rendered pages, advisory) ·
`dh compose` (the copy.json it is given) · `dh slop brief` (what not to write, before writing).
"""
from __future__ import annotations

import fnmatch
import json
import re
import statistics
from pathlib import Path

from .util import DATA, DhError, git_files, home, read_json, today, write_json

SCHEMA = "deckhand.slop/1"
PACKS = DATA / "slop"
COMMON = json.loads((PACKS / "_common.json").read_text(encoding="utf-8"))
SCRIPTS = ("latin", "cjk", "hangul")
PHRASE_KINDS = ("opener", "hedge", "structure", "cta", "closer", "filler", "claim", "leak")
OK_MARK = "dh:slop-ok"
LANG_NAMES = {"english": "en", "french": "fr", "français": "fr", "francais": "fr", "spanish": "es", "español": "es", "german": "de",
              "deutsch": "de", "italian": "it", "italiano": "it", "portuguese": "pt", "português": "pt", "dutch": "nl",
              "nederlands": "nl", "polish": "pl", "polski": "pl", "japanese": "ja", "日本語": "ja", "korean": "ko", "한국어": "ko",
              "chinese": "zh", "中文": "zh"}
# a nested quantifier (`(a+)+`) can take a regex forever on the wrong input: packs are data anyone may send
NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*}]\)[+*{]")


# ------------------------------------------------------------------ packs

def lang_code(v) -> str:
    s = str(v or "").strip().lower()
    return LANG_NAMES.get(s) or re.split(r"[-_]", s)[0][:3]


def shipped() -> dict:
    """lang → path of every shipped pack (files starting with _ are shared settings, not languages)."""
    return {p.stem: p for p in sorted(PACKS.glob("*.json")) if not p.name.startswith("_")}


def overlay_path(lang: str) -> Path:
    return home() / "slop" / f"{lang}.json"


def project_conf(root) -> dict:
    return (read_json(Path(root) / ".deckhand" / "slop.json", {}) or {}) if root else {}


def _empty(lang: str) -> dict:
    return {"schema": SCHEMA, "lang": lang, "name": lang, "script": "latin", "words": {"strong": [], "buzz": []}, "phrases": [],
            "transitions": [], "superlatives": [], "and": [], "stopwords": [], "fixes": {}, "suffixes": [], "examples": {}}


def raw_pack(lang: str) -> dict:
    p = shipped().get(lang)
    return read_json(p, None) if p else _empty(lang)


def _merge(pack: dict, extra: dict) -> dict:
    out = json.loads(json.dumps(pack))
    extra = extra if isinstance(extra, dict) else {}     # a hand-edited layer of the wrong shape adds nothing, never crashes
    words = extra.get("words") if isinstance(extra.get("words"), dict) else {}
    for tier in ("strong", "buzz"):
        out.setdefault("words", {}).setdefault(tier, [])
        out["words"][tier] += [w for w in _list(words.get(tier)) if isinstance(w, str) and w not in out["words"][tier]]
    ids = {x["id"] for x in out.get("phrases", [])}
    out["phrases"] = out.get("phrases", []) + [x for x in _list(extra.get("phrases")) if isinstance(x, dict) and x.get("id") and x.get("id") not in ids]
    out["fixes"] = {**out.get("fixes", {}), **(extra.get("fixes") if isinstance(extra.get("fixes"), dict) else {})}
    for k in ("transitions", "superlatives"):
        out[k] = out.get(k, []) + [x for x in _list(extra.get(k)) if isinstance(x, str) and x not in out.get(k, [])]
    return out


def _list(v) -> list:
    return v if isinstance(v, list) else []


class Pack:
    """A pack compiled once: every entry becomes a regex; the thresholds are _common.json's, overridden by the pack's."""

    def __init__(self, data: dict, allow=()):
        self.data = data
        self.lang = data.get("lang", "und")
        self.script = data.get("script", "latin")
        self.th = {**COMMON["thresholds"], **(data.get("thresholds") or {})}
        self.wt = {**COMMON["weights"], **(data.get("weights") or {})}
        self.fixes = {k.lower(): v for k, v in (data.get("fixes") or {}).items()}
        self.allow = [a.lower() for a in allow if a]
        suf = data.get("suffixes") or []
        self.words = []
        for tier in ("strong", "buzz"):
            for entry in (data.get("words") or {}).get(tier, []):
                self.words.append((entry.split("|")[0], tier, self._word_rx(entry, suf, data.get("drop_e"))))
        self.phrases = [(p, re.compile(p["rx"], re.I)) for p in data.get("phrases", [])]
        self.trans = self._alt(data.get("transitions", []), start=True)
        self.sup = self._alt(data.get("superlatives", []))
        ands = data.get("and") or []
        if ands and self.script == "latin":
            item = r"[^\W\d_][\w'’-]*(?: [^\W\d_][\w'’-]*){0,2}"
            self.triad = re.compile(rf"(?<![\w-]){item}, {item},? (?:{'|'.join(map(re.escape, ands))}) {item}(?![\w-])", re.I)
        else:
            self.triad = None

    def _bound(self, body: str) -> str:
        return body if self.script != "latin" else rf"(?<![\w-])(?:{body})(?![\w-])"

    def _flex(self, form: str) -> str:
        return re.sub(r"(\\ |\\-|-| )+", r"[\\s-]+", re.escape(form))

    def _word_rx(self, entry: str, suffixes: list, drop_e) -> re.Pattern:
        alts = []
        for form in entry.split("|"):
            if self.script != "latin" or re.search(r"[\s-]", form) or not suffixes:
                alts.append(self._flex(form))
                continue
            alts.append(re.escape(form) + "(?:" + "|".join(map(re.escape, suffixes)) + ")?")
            if drop_e and form.endswith("e"):
                alts.append(re.escape(form[:-1]) + "(?:ing|ed|er|ers)")
        return re.compile(self._bound("|".join(alts)), re.I)

    def _alt(self, items: list, start: bool = False):
        if not items:
            return None
        body = "|".join(self._flex(x) for x in sorted(items, key=len, reverse=True))
        if start:
            return re.compile(rf"^(?:{body})(?=[\s,、，:;]|$)", re.I)
        return re.compile(self._bound(body), re.I)

    def allowed(self, text: str) -> bool:
        """Allowed when the match (or its base term) IS an allowed word, or sits inside an allowed phrase as whole words."""
        t = text.lower().strip()
        return bool(t) and any(t == a or re.search(rf"(?<!\w){re.escape(t)}(?!\w)", a) for a in self.allow)


def load(lang: str, root=None, allow=()) -> Pack:
    """The shipped pack + the owner's overlay (~/.deckhand/slop/<lang>.json) + the project's allow list and brand words."""
    data = raw_pack(lang)
    ov = read_json(overlay_path(lang), None)
    if ov:
        data = _merge(data, ov)
    conf = project_conf(root)
    brief = (read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}) if root else {}
    names = [(brief.get("brand") or {}).get("name") or "", brief.get("name") or ""]
    brand_words = [w for n in names for w in re.findall(r"[^\W\d_]{3,}", n)]
    return Pack(data, allow=[*allow, *conf.get("allow", []), *(ov or {}).get("allow", []), *brand_words])


# ------------------------------------------------------------------ language

def _script_counts(text: str) -> dict:
    return {"kana": len(re.findall(r"[぀-ヿ]", text)), "hangul": len(re.findall(r"[가-힯]", text)),
            "han": len(re.findall(r"[一-鿿]", text)), "letters": len(re.findall(r"[^\W\d_]", text))}


def detect(text: str, candidates=None) -> str:
    """Deterministic: the script first (kana → ja, hangul → ko, han → zh), then the pack whose stopwords the text uses most."""
    c = _script_counts(text)
    if c["letters"]:
        if c["hangul"] / c["letters"] > 0.2:
            return "ko"
        if c["kana"] / c["letters"] > 0.05:
            return "ja"
        if c["han"] / c["letters"] > 0.2:
            return "zh"
    packs = shipped()
    cands = [x for x in (candidates or []) if x in packs] or [x for x in packs if (read_json(packs[x], {}) or {}).get("script", "latin") == "latin"]
    tokens = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text.lower())
    best, top = None, 0
    for lang in cands:
        sw = set((read_json(packs[lang], {}) or {}).get("stopwords", []))
        n = sum(1 for t in tokens if t in sw)
        if n > top:
            best, top = lang, n
    return best or (cands[0] if candidates and cands else "en")


def _path_lang(rel: str) -> str | None:
    m = re.search(r"(?:^|[/._-])(en|fr|es|de|it|pt|nl|pl|ja|ko|zh)(?:[-_][A-Za-z]{2})?(?:[/.]|$)", rel)
    return m.group(1) if m and m.group(1) in shipped() else None


# ------------------------------------------------------------------ features

def _words(text: str, script: str) -> int:
    if script == "cjk":
        return round(len(re.findall(r"[぀-ヿ一-鿿]", text)) / 2) + len(re.findall(r"[A-Za-z]+", text))
    return len(re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", text))


def sentences(text: str) -> list:
    """(start, sentence) — split on . ! ? … and their CJK forms, and on every line break (a fragment never runs on)."""
    return [(m.start() + len(m.group(0)) - len(m.group(0).lstrip()), m.group(0).strip())
            for m in re.finditer(r"[^.!?…。！？\n]+[.!?…。！？]*", text) if m.group(0).strip()]


def analyze(text: str, pack: Pack) -> dict:
    """One unit of copy → hits, points, verdict. `text` joins fragments with newlines; offsets index into it."""
    hits = []

    def hit(rule, rid, m_text, at, w, fix="", kind=""):
        if pack.allowed(m_text) or (rid and pack.allowed(rid)):
            return
        hits.append({"rule": rule, "id": rid, "match": m_text.strip()[:80], "at": at, "w": round(w, 2),
                     **({"fix": fix} if fix else {}), **({"kind": kind} if kind else {})})

    found = sorted(((m.start(), m.end(), p) for p, rx in pack.phrases for m in rx.finditer(text)), key=lambda x: (x[0], x[0] - x[1]))
    spans = []
    for a, b, p in found:
        if any(x <= a and b <= y for x, y in spans):             # inside a longer phrase already counted: one cliché, one hit
            continue
        spans.append((a, b))
        hit("phrase", p["id"], text[a:b], a, p.get("w", pack.wt["phrase"]), p.get("fix", ""), p.get("kind", ""))
    for base, tier, rx in pack.words:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in spans):      # a phrase already explains this word
                continue
            hit("word", base, m.group(0), m.start(), pack.wt[tier], pack.fixes.get(base.lower(), ""), tier)
    sents = sentences(text)
    if pack.trans:
        found = [(s, m) for s, t in sents if (m := pack.trans.match(t))]
        if len(found) >= pack.th["transitions_min"]:
            for s, m in found:
                hit("transition", m.group(0).lower(), m.group(0), s, pack.wt["transition"], "cut it: the order of the sentences already says so")
    if pack.sup:
        for s, t in sents:
            m = pack.sup.search(t)
            if m and not re.search(r"\d", t[:m.start()] + t[m.end():]):
                hit("superlative", m.group(0).lower(), m.group(0), s + m.start(), pack.wt["superlative"],
                    "prove it in the same sentence (a number, an award, a named client) or drop it", "claim")
    words = _words(text, pack.script)
    if pack.th.get("em_dash", True):
        dashes = [m.start() for m in re.finditer(r"—|(?<=\s)–(?=\s)", text)]
        allowed = max(1, words // pack.th["em_dash_words_per"])
        if len(dashes) > allowed:
            hit("em-dash", "em-dash", f"{len(dashes)} dashes in {words} words", dashes[0], min(5, (len(dashes) - allowed) * pack.wt["em_dash"]),
                "use a full stop, a comma or a colon")
    bangs = [m.start() for m in re.finditer(r"[!！]", text)]
    allowed = max(1, words // pack.th["exclaim_words_per"])
    if len(bangs) > allowed:
        hit("exclaim", "exclaim", f"{len(bangs)} exclamation marks", bangs[0], min(3, (len(bangs) - allowed) * pack.wt["exclaim"]), "let the facts carry the energy")
    emo = [m for m in re.finditer("|".join(map(re.escape, COMMON["emoji"])), text)]
    for m in emo[:5]:
        hit("emoji", m.group(0), m.group(0), m.start(), pack.wt["emoji"], "no decorative emoji in site copy")
    if pack.triad:
        tri = list(pack.triad.finditer(text))
        if len(tri) >= pack.th["triads_min"]:
            for m in tri:
                hit("triad", "triad", m.group(0), m.start(), pack.wt["triad"], "list what is true, not three of everything")
    unit = "chars" if pack.script == "cjk" else "words"
    lens = [len(re.sub(r"\s", "", t)) if pack.script == "cjk" else len(t.split()) for _, t in sents]
    prose = [n for n in lens if n >= 3]
    if len(prose) >= pack.th["rhythm_min_sentences"]:
        mean = statistics.mean(prose)
        cv = statistics.pstdev(prose) / mean if mean else 1
        short = pack.th["short_chars" if pack.script == "cjk" else "short_words"]
        if cv < pack.th["rhythm_cv"]:
            hit("rhythm", "flat-rhythm", f"{len(prose)} sentences, all ~{round(mean)} {unit}", sents[0][0], pack.wt["rhythm"],
                "vary the length: a few short sentences, one longer one")
        elif min(prose) >= short:
            hit("rhythm", "no-short-sentence", f"no sentence under {short} {unit}", sents[0][0], pack.wt["rhythm"] / 3, "add a short sentence")
    points = sum(h["w"] for h in hits)
    density = points * 100 / max(words, pack.th["floor_words"])
    verdict = "slop" if density >= pack.th["slop"] else "review" if density >= pack.th["review"] else "clean"
    if verdict == "clean" and any(h["w"] >= pack.wt["strong"] for h in hits):
        verdict = "review"                                  # one strong tell is always worth a look
    if any(h.get("kind") == "leak" for h in hits):
        verdict = "slop"                                    # a chatbot's voice on a page is never right
    hits.sort(key=lambda h: (-h["w"], h["at"]))
    return {"lang": pack.lang, "words": words, "points": round(points, 1), "score": min(100, round(density * 5)), "verdict": verdict, "hits": hits}


def check_text(text: str, lang: str | None = None, root=None, candidates=None) -> dict:
    lang = lang or detect(text, candidates)
    return {**analyze(text, load(lang, root)), "lang": lang}


# ------------------------------------------------------------------ extraction: where the words are

COPY_SKIP_KEYS = {"href", "url", "src", "image", "icon", "link", "slug", "id", "route", "email", "phone", "tel", "social", "logo", "price", "color"}
EXCLUDE = re.compile(r"(^|/)(node_modules|\.next|dist|build|out|coverage|\.git|\.deckhand|dh-tryon|public|docs|scripts|tests?|__tests__|e2e|"
                     r"prisma|migrations|supabase|\.github|vendor|fixtures|components/ui)(/|$)|"
                     r"(^|/)(README|CHANGELOG|LICEN[CS]E|NOTICE|THIRD_PARTY_NOTICES|CONTRIBUTING|AGENTS|CLAUDE|PENDING|HANDOFF|SECURITY)[^/]*$|"
                     r"\.(test|spec|stories|d)\.[cm]?[jt]sx?$", re.I)
CONTENT_JSON = re.compile(r"(^|/)(messages|locales?|i18n|lang|translations|content|copy)(/|\.)", re.I)
CONTENT_JS = re.compile(r"(^|/)(content|copy|site|constants|messages|locales?|i18n|data)(/|[^/]*\.[cm]?[jt]s$)", re.I)
MARKUP = (".tsx", ".jsx", ".astro", ".vue", ".svelte")


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _prose(s: str, min_words: int = 2) -> bool:
    letters = len(re.findall(r"[^\W\d_]", s))
    cjk = len(re.findall(r"[぀-ヿ一-鿿가-힯]", s))
    if cjk >= 4:
        return True
    return letters >= 4 and len(s.split()) >= min_words and letters / max(1, len(s)) > 0.55


def _blank(text: str, rx) -> str:
    return rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


CODE_COMMENTS = re.compile(r"/\*[\s\S]*?\*/|(?<![:\"'\w])//[^\n]*")
CODEISH = re.compile(r"&&|\|\||=>|===|!==|\);|\bconst\b|\breturn\b|\bfunction\b|\bimport\b")
LITERAL = re.compile(r"(?<![\w$])(['\"`])((?:\\.|(?!\1)[^\\\n])*)\1")


def _classish(s: str) -> bool:
    toks = s.split()
    return bool(toks) and sum(1 for t in toks if re.search(r"[-:/\[\]]", t) or re.fullmatch(r"[a-z0-9]+", t) and len(t) <= 3) / len(toks) > 0.5 and s == s.lower()


def markup_fragments(text: str) -> list:
    """(line, text) of the words a JSX/Vue/Svelte/Astro file shows: text between tags, then quoted strings of prose."""
    text = _blank(text, CODE_COMMENTS)
    out, spans = [], []
    for m in re.finditer(r">([^<>{}]+)<", text):
        s = re.sub(r"\s+", " ", m.group(1)).strip()
        if s and _prose(s, 1) and not CODEISH.search(s):
            out.append((_line(text, m.start(1)), s))
            spans.append(m.span(1))
    for a, b in spans:
        text = text[:a] + re.sub(r"[^\n]", " ", text[a:b]) + text[b:]
    out += literal_fragments(text)
    return sorted(out)


def literal_fragments(text: str) -> list:
    out = []
    lines = text.splitlines()
    for m in LITERAL.finditer(text):
        s = m.group(2)
        ln = _line(text, m.start())
        src = lines[ln - 1] if ln - 1 < len(lines) else ""
        if ("${" in s or "{" in s or not _prose(s) or _classish(s) or re.match(r"^(https?:|/|\./|@|#|mailto:)", s)
                or re.search(r"\b(import|require|className|class|href|src|key|type)\b\s*[=(:]?\s*$", src[:src.find(m.group(0))] if m.group(0) in src else "")):
            continue
        out.append((ln, s.replace("\\n", " ").replace("\\'", "'").replace('\\"', '"')))
    return out


def md_fragments(text: str) -> list:
    out, buf, start, fence = [], [], 0, False
    for i, raw in enumerate(text.splitlines(), 1):
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence or re.match(r"^\s*(import|export)\s", raw) or raw.strip() in ("---", "+++"):
            continue
        line = re.sub(r"`[^`]*`", " ", raw)
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"^\s*(#{1,6}|[-*+>]|\d+\.)\s+", "", line)
        line = re.sub(r"^\s*[\w-]+:\s+", "", line) if i < 40 and re.match(r"^\s*[\w-]+:\s+\S", raw) else line
        line = re.sub(r"[*_]{1,3}", "", line).strip()
        if line and re.match(r"^\s*(#{1,6}\s|[\w-]+:\s+\S|[-*+]\s)", raw):  # a heading, a front-matter value, a list item: its own fragment
            if buf:
                out.append((start, " ".join(buf)))
            out.append((i, line))
            buf = []
            continue
        if not line:
            if buf:
                out.append((start, " ".join(buf)))
            buf = []
            continue
        if not buf:
            start = i
        buf.append(line)
    if buf:
        out.append((start, " ".join(buf)))
    return [(ln, s) for ln, s in out if _prose(s, 1)]


def json_fragments(obj, prefix: str = "") -> list:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() not in COPY_SKIP_KEYS:
                out += json_fragments(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += json_fragments(v, f"{prefix}[{i}]")
    elif isinstance(obj, str) and _prose(obj, 1) and not re.match(r"^(https?:|/|#|mailto:|tel:)", obj):
        out.append((prefix, obj))
    return out


class _Blocks:
    """Visible text of a rendered page, one fragment per block (p, li, h1…), scripts/styles/code skipped."""
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "nav", "td", "th",
             "blockquote", "figcaption", "button", "label", "dt", "dd", "main", "aside", "form", "ul", "ol", "br", "summary", "title"}
    SKIP = {"script", "style", "noscript", "template", "svg", "code", "pre"}

    def __init__(self):
        from html.parser import HTMLParser
        outer = self

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                outer._tag(tag, True, dict(attrs))

            def handle_endtag(self, tag):
                outer._tag(tag, False, {})

            def handle_data(self, data):
                if not outer.skip:
                    outer.buf.append(data)
        self.parser = P(convert_charrefs=True)
        self.out, self.buf, self.skip = [], [], 0

    def _flush(self, tag="block"):
        s = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if s and _prose(s, 1):
            self.out.append((tag, s))
        self.buf = []

    def _tag(self, tag, start, attrs):
        if tag in self.SKIP:
            self.skip += 1 if start else -1 if self.skip else 0
            return
        if tag == "meta" and (attrs.get("name") or attrs.get("property") or "").lower() in ("description", "og:description"):
            if _prose(attrs.get("content") or "", 1):
                self.out.append(("meta", attrs["content"]))
        if tag in self.BLOCK:
            self._flush(tag)

    def feed(self, html: str) -> list:
        try:
            self.parser.feed(html or "")
        except Exception:  # noqa: BLE001 — a broken page still gets read as far as it parses
            pass
        self._flush()
        seen, out = set(), []
        for tag, s in self.out:
            if s not in seen:
                seen.add(s)
                out.append((tag, s))
        return out


def html_fragments(html: str) -> list:
    return _Blocks().feed(html)


def _unit(where: str, frags: list, pack: Pack, file: str | None = None) -> dict:
    """Fragments → one analysed unit; each hit points back at its fragment (a line of a file, a key of copy.json)."""
    text, starts = "", []
    for label, s in frags:
        starts.append((len(text), label))
        text += s + "\n"
    r = analyze(text, pack)
    for h in r["hits"]:
        label = next((lb for st, lb in reversed(starts) if st <= h["at"]), None)
        h["line" if isinstance(label, int) else "key"] = label
        del h["at"]
    return {"where": where, **({"file": file} if file else {}), **r}


# ------------------------------------------------------------------ project, files, pages

def _langs(root) -> list:
    b = (read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}) if root else {}
    langs = b.get("languages") or []
    return [lang_code(x) for x in (langs if isinstance(langs, list) else str(langs).split(","))]


def _pick(text: str, lang: str | None, cands: list, rel: str = "") -> str:
    return lang or _path_lang(rel) or detect(text, cands)


def file_units(root, rel: str, text: str, lang=None, cands=(), packs=None) -> list:
    rel = rel.replace("\\", "/")
    low = rel.lower()
    if low.endswith(MARKUP):
        frags = markup_fragments(text)
    elif low.endswith((".md", ".mdx", ".txt")):
        frags = md_fragments(text)
    elif low.endswith(".html"):
        frags = html_fragments(text)
    elif low.endswith(".json"):
        try:
            frags = json_fragments(json.loads(text))
        except ValueError:
            return []
        frags = [(_line(text, max(0, text.find(json.dumps(s, ensure_ascii=False)[1:-1]))), s) for _, s in frags]
    elif low.endswith((".ts", ".js", ".mjs", ".cjs")):
        frags = literal_fragments(_blank(text, CODE_COMMENTS))
    else:
        return []
    lines = text.splitlines()
    frags = [(ln, s) for ln, s in frags if not (isinstance(ln, int) and 0 < ln <= len(lines) and OK_MARK in lines[ln - 1])]
    if not frags:
        return []
    joined = " ".join(s for _, s in frags)
    lg = _pick(joined, lang, list(cands), rel)
    packs = packs if packs is not None else {}
    if lg not in packs:
        packs[lg] = load(lg, root)
    return [_unit(rel, frags, packs[lg], file=rel)]


def copy_units(root, path: Path, lang=None, cands=(), packs=None) -> list:
    """copy.json: one unit per section (hero, pricing…) — the words the model wrote for this site."""
    data = read_json(path, None)
    if not isinstance(data, dict):
        return []
    rel = str(path.relative_to(root)).replace("\\", "/") if root and str(path).startswith(str(root)) else str(path)
    packs = packs if packs is not None else {}
    out = []
    for key, val in data.items():
        frags = json_fragments(val, key)
        if not frags:
            continue
        lg = _pick(" ".join(s for _, s in frags), lang, list(cands))
        if lg not in packs:
            packs[lg] = load(lg, root)
        out.append(_unit(f"{rel} → {key}", frags, packs[lg], file=rel))
    return out


def project_units(root, lang=None) -> list:
    root = Path(root)
    cands, conf, packs = _langs(root), project_conf(root), {}
    ignore = conf.get("ignore", [])
    units = []
    copy = root / ".deckhand" / "copy.json"
    if copy.exists():
        units += copy_units(root, copy, lang, cands, packs)
    for p in git_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        low = rel.lower()
        if EXCLUDE.search(rel) or any(fnmatch.fnmatch(rel, g) for g in ignore) or not p.is_file():
            continue
        wanted = low.endswith(MARKUP + (".md", ".mdx", ".html")) or (low.endswith(".json") and CONTENT_JSON.search(rel)) or (
            low.endswith((".ts", ".js", ".mjs")) and CONTENT_JS.search(rel))
        if not wanted or p.stat().st_size > 400_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        units += file_units(root, rel, text, lang, cands, packs)
    return units


def url_units(base: str, paths=("/",), lang=None, root=None, get=None) -> list:
    """Rendered pages of any site (the owner's, a base, a competitor's): what a visitor reads, one unit per page."""
    if get is None:
        from .seo import fetch as get
    base = base.rstrip("/")
    cands = _langs(root) if root else []
    packs, out = {}, []
    todo, seen = list(paths), set()
    while todo and len(seen) < COMMON["max_pages"]:
        path = todo.pop(0)
        if path in seen:
            continue
        seen.add(path)
        st, _, html = get(base + path)
        if not st or st >= 400 or not html:
            continue
        frags = html_fragments(html)
        if path == "/" and len(paths) == 1:                 # the home page names the rest of the site
            todo += sorted({h.split("#")[0].split("?")[0] for h in re.findall(r'href="(/[^"/][^"]*|/)"', html)} - seen)
        if not frags:
            continue
        lg = _pick(" ".join(s for _, s in frags), lang, cands)
        if lg not in packs:
            packs[lg] = load(lg, root)
        out.append(_unit(path, frags, packs[lg]))
    return out


def summarize(units: list, top: int = 10) -> dict:
    by = {v: sum(1 for u in units if u["verdict"] == v) for v in ("clean", "review", "slop")}
    worst = sorted(units, key=lambda u: (-u["score"], u["where"]))
    verdict = "slop" if by["slop"] else "review" if by["review"] else "clean"
    return {"verdict": verdict, "units": len(units), "by_verdict": by,
            "worst": [{**{k: u[k] for k in ("where", "lang", "words", "score", "verdict")}, "hits": u["hits"][:8]} for u in worst[:top] if u["verdict"] != "clean"]}


def render_md(rep: dict) -> str:
    md = ["# Copy check (AI slop)", "", f"{rep['verdict'].upper()} — {rep['units']} texts: {rep['by_verdict']['slop']} slop, "
          f"{rep['by_verdict']['review']} to review, {rep['by_verdict']['clean']} clean · {rep.get('at', '')}", ""]
    for u in rep["worst"]:
        md += [f"## {u['where']} — {u['verdict']} ({u['score']}/100, {u['lang']}, {u['words']} words)", ""]
        for h in u["hits"]:
            loc = f"line {h['line']}" if h.get("line") else h.get("key") or ""
            md.append(f"- `{h['match']}` ({h['rule']}{', ' + loc if loc else ''}){' → ' + h['fix'] if h.get('fix') else ''}")
        md.append("")
    md += ["Real customer quotes: add `dh:slop-ok` on their line. Brand words: `dh slop allow \"word\"`.", ""]
    return "\n".join(md)


def check(root=None, paths=(), text: str | None = None, url: str | None = None, lang: str | None = None, write: bool = True) -> dict:
    from .util import now
    if text is not None:
        r = check_text(text, lang, root, _langs(root) if root else None)
        return {"verdict": r["verdict"], "text": r}
    if url:
        units = url_units(url, lang=lang, root=root)
    elif paths:
        units, packs = [], {}
        for p in map(Path, paths):
            files = [f for f in sorted(p.rglob("*")) if f.is_file() and not EXCLUDE.search(str(f.relative_to(p)).replace("\\", "/"))] if p.is_dir() else [p]
            for f in files:
                if f.name == "copy.json":
                    units += copy_units(f.parent, f, lang, _langs(root) if root else (), packs)
                else:
                    try:
                        units += file_units(root, str(f), f.read_text(encoding="utf-8"), lang, _langs(root) if root else (), packs)
                    except (UnicodeDecodeError, OSError):
                        continue
    else:
        if not root:
            raise DhError("USAGE", "dh slop check [PATH…] | --text \"…\" | --url URL   (or run it in a project)")
        units = project_units(root, lang)
    rep = {**summarize(units), "at": now()}
    if write and root and not paths and (Path(root) / ".deckhand").is_dir():
        write_json(Path(root) / ".deckhand" / "slop-report.json", rep)
        (Path(root) / ".deckhand" / "SLOP.md").write_text(render_md(rep), encoding="utf-8")
        rep["report"] = ".deckhand/SLOP.md"
    return rep


# ------------------------------------------------------------------ writers, owners, contributors

def brief(lang: str, root=None) -> dict:
    """What not to write, before writing — a few lines, not the pack (token discipline)."""
    p = load(lang, root)
    d = p.data
    th = p.th
    return {"lang": lang, "pack": d.get("name"), "maturity": d.get("maturity", "seed"),
            "avoid_words": [w.split("|")[0] for w in (d.get("words") or {}).get("strong", [])],
            "use_sparingly": [w.split("|")[0] for w in (d.get("words") or {}).get("buzz", [])],
            "avoid_patterns": [x.get("example", x["id"]) for x in d.get("phrases", [])],
            "rules": [f"at most one sentence opening with {', '.join(d.get('transitions', [])[:4]) or 'a stock connector'}… per text",
                      "a superlative only with its proof in the same sentence (a number, an award, a named client)",
                      f"at most one em dash per {th['em_dash_words_per']} words; one exclamation mark per {th['exclaim_words_per']}",
                      "no decorative emoji; no three-of-everything lists",
                      "vary sentence length: some short, one long; concrete nouns, prices, places, hours over adjectives"],
            "then": "dh slop check"}


def lint(data: dict) -> dict:
    """A pack is data anyone may send: every rule compiles, is safe to run, and proves itself on the pack's own examples."""
    errors, warns = [], []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not re.fullmatch(r"[a-z]{2,3}", str(data.get("lang", ""))):
        errors.append("lang must be an ISO 639 code (fr, es, de…)")
    if data.get("script", "latin") not in SCRIPTS:
        errors.append(f"script must be one of {', '.join(SCRIPTS)}")
    words = (data.get("words") or {})
    seen = set()
    for tier in ("strong", "buzz"):
        for w in words.get(tier, []):
            if not isinstance(w, str) or not w.strip() or re.search(r"[\\()\[\]{}*+?^$]", w):
                errors.append(f"words.{tier}: {w!r} is not a plain word (alternative forms: a|b|c)")
            elif w.lower() in seen:
                errors.append(f"words.{tier}: {w!r} listed twice")
            seen.add(str(w).lower())
    ids = set()
    for p in data.get("phrases", []):
        pid = p.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", pid):
            errors.append(f"phrase id {pid!r}: lowercase-dashed")
        if pid in ids:
            errors.append(f"phrase {pid}: duplicate id")
        ids.add(pid)
        if p.get("kind") not in PHRASE_KINDS:
            errors.append(f"phrase {pid}: kind must be one of {', '.join(PHRASE_KINDS)}")
        rx = p.get("rx", "")
        if len(rx) > 400 or NESTED_QUANT.search(rx) or re.search(r"\(\?[<=!P]|\\[1-9]", rx):
            errors.append(f"phrase {pid}: rx too long, nested quantifier, lookaround or backreference (keep it plain)")
            continue
        try:
            c = re.compile(rx, re.I)
        except re.error as e:
            errors.append(f"phrase {pid}: rx does not compile ({e})")
            continue
        if not p.get("example"):
            errors.append(f"phrase {pid}: needs an example sentence it matches")
        elif not c.search(p["example"]):
            errors.append(f"phrase {pid}: does not match its own example {p['example']!r}")
        if not isinstance(p.get("w", 3), (int, float)) or not 0 < p.get("w", 3) <= 5:
            errors.append(f"phrase {pid}: w between 0 and 5")
    ex = data.get("examples") or {}
    if len(ex.get("slop", [])) < 2 or len(ex.get("clean", [])) < 2:
        errors.append("examples: at least 2 slop and 2 clean texts (they are the pack's test)")
    if not errors:
        pack = Pack(data)
        for t in ex.get("slop", []):
            r = analyze(t, pack)
            if r["verdict"] != "slop":
                errors.append(f"examples.slop scores {r['verdict']} ({r['score']}): {t[:70]!r}")
        for t in ex.get("clean", []):
            r = analyze(t, pack)
            if r["verdict"] != "clean":
                errors.append(f"examples.clean scores {r['verdict']} ({', '.join(h['match'] for h in r['hits'][:3])}): {t[:70]!r}")
        if data.get("script", "latin") != "cjk" and not data.get("stopwords"):
            warns.append("no stopwords: the language is never auto-detected (only --lang or brief.languages)")
    return {"ok": not errors, "errors": errors, "warnings": warns, "lang": data.get("lang"),
            "counts": {"strong": len(words.get("strong", [])), "buzz": len(words.get("buzz", [])), "phrases": len(data.get("phrases", []))}}


def langs() -> dict:
    out = []
    for lang, p in shipped().items():
        d = read_json(p, {}) or {}
        ov = read_json(overlay_path(lang), None)
        out.append({"lang": lang, "name": d.get("name"), "maturity": d.get("maturity", "seed"), "script": d.get("script", "latin"),
                    "strong": len((d.get("words") or {}).get("strong", [])), "buzz": len((d.get("words") or {}).get("buzz", [])),
                    "phrases": len(d.get("phrases", [])), **({"yours": str(overlay_path(lang))} if ov else {})})
    return {"packs": out, "any_other_language": "language-free features only (punctuation, emoji, rhythm) until a pack exists — data/slop/README.md"}


def add(term: str, lang: str, phrase: bool = False, buzz: bool = False, fix: str = "") -> dict:
    """The owner's own find → ~/.deckhand/slop/<lang>.json, applied from the next check on; `dh slop export` shares it."""
    term = term.strip()
    if not term:
        raise DhError("USAGE", "dh slop add \"word or phrase\" --lang fr [--buzz] [--fix \"plainer word\"]")
    p = overlay_path(lang)
    ov = read_json(p, None) or {"schema": SCHEMA, "lang": lang, "words": {"strong": [], "buzz": []}, "phrases": [], "fixes": {}, "allow": []}
    if phrase or " " in term:
        pid = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")[:40] or "phrase"
        rx = re.sub(r"(\\ )+", r"\\s+", re.escape(term.lower()))
        if not any(x["id"] == pid for x in ov["phrases"]):
            ov["phrases"].append({"id": pid, "kind": "filler", "rx": rx, "w": 2 if buzz else 3, "example": term, **({"fix": fix} if fix else {})})
    else:
        tier = "buzz" if buzz else "strong"
        if term not in ov["words"][tier]:
            ov["words"][tier].append(term)
        if fix:
            ov.setdefault("fixes", {})[term] = fix
    write_json(p, ov)
    return {"added": term, "lang": lang, "file": str(p), "share": f"dh slop export --lang {lang}"}


def allow(root, term: str) -> dict:
    p = Path(root) / ".deckhand" / "slop.json"
    conf = read_json(p, None)
    conf = conf if isinstance(conf, dict) else {"allow": [], "ignore": []}
    if not isinstance(conf.get("allow"), list):
        conf["allow"] = []
    if term not in conf["allow"]:
        conf["allow"].append(term)
    write_json(p, conf)
    return {"allowed": term, "file": ".deckhand/slop.json", "why": "a brand, product or trade word is not slop on this site"}


def export(lang: str) -> dict:
    ov = read_json(overlay_path(lang), None)
    if not ov:
        raise DhError("NOTHING_TO_EXPORT", f"no finds of yours for {lang} yet (dh slop add \"…\" --lang {lang})")
    merged = _merge(raw_pack(lang), ov)
    lt = lint(merged)
    if not lt["ok"]:
        raise DhError("PACK_INVALID", "your additions break the pack's own test — fix them first", errors=lt["errors"][:10])
    out = home() / "slop" / "outbox" / f"{lang}-{today()}.json"
    write_json(out, {k: v for k, v in ov.items() if k != "allow"})
    return {"bundle": str(out), "submit": ["fork github.com/takimdigital/deckhand-skill",
                                          f"merge the bundle into skills/deckhand/data/slop/{lang}.json (add a slop example that uses your words)",
                                          f"python3 skills/deckhand/dh.py slop lint skills/deckhand/data/slop/{lang}.json",
                                          "open a pull request — the maintainer reviews it"],
            "note": "nothing was sent anywhere; your site-specific allow list stays out of the bundle"}
