"""SEO: be found on Google and in AI answers — detected, added, proved, and the owner's part tracked.

  dh seo audit [--url U]   every rule of data/seo.json against the source (tryon seo inspect), the rendered
                           pages (the URL given, else the running dev server) and, for a live https URL, the
                           host itself (redirects, HTTPS, preview indexing). Writes .deckhand/seo.json + SEO.md,
                           and refreshes the "Detected by dh seo" block of PENDING.md: every owner fact and
                           owner-only action still missing (Search Console, Bing, Business Profile, reviews,
                           address, hours, social profiles…), with WHY / HOW / WHERE and the date first asked.
  dh seo apply             builds the plan from the brief's CONFIRMED facts (nothing invented) + the plan's
                           pages + the model's words (.deckhand/copy.json → seo.pages: title, description per
                           route) and lets the engine add or improve robots, sitemap, metadata, canonicals,
                           Open Graph, JSON-LD, 404, llms.txt, IndexNow — never overwriting the owner's words.
  dh seo undo [--force]    byte-exact restore of the last apply (refused if a file was edited since).
  dh seo ping              IndexNow: tells Bing (the index behind ChatGPT search and Copilot), Yandex, Seznam
                           and Naver that the site's URLs changed (`dh deploy ship` does it on production).
Policy by path (data/seo.json policy_by_path): scratch + existing = applied by default; pool + mine =
detected, then strongly recommended before going live (DECISION NEEDED at G4).
Nobody can promise position #1. What this guarantees is that nothing within our control is missing, and that
the owner always knows exactly which of their facts or actions are still open.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .util import DATA, TRYON, DhError, now, read_json, today, write_json

POLICY = json.loads((DATA / "seo.json").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in POLICY["rules"]}
WEIGHT = {"block": 10, "high": 5, "medium": 3, "low": 1}
LIMITS = POLICY["limits"]
PREVIEW_RX = re.compile(r"(^http://)|(\.(sslip|nip)\.io)(:\d+)?(/|$)|(://(localhost|127\.0\.0\.1))", re.I)
LOCAL_RX = re.compile(r"://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?(/|$)", re.I)
# a REMOTE preview (sslip/nip, plain http on a real host) is meant to be noindex; a local production build is not
REMOTE_PREVIEW = lambda u: bool(u) and bool(PREVIEW_RX.search(u)) and not LOCAL_RX.search(u)  # noqa: E731
# rules only a rendered page can prove (they are not scored on a source-only audit); NOT_CHECKED = manual checklist
RENDERED = {"C01", "C02", "C05", "C07", "C08", "M01", "M02", "M03", "M04", "M08", "M09", "M12", "T01", "T02", "T03", "T04", "T05",
            "T06", "T07", "S02", "S03", "S04", "S05", "S06", "S07", "L01", "L04", "O02", "O04", "I01", "P02", "A01", "A05", "A06", "E04"}
NOT_CHECKED = {"S08", "L02"}


# ------------------------------------------------------------------ facts

def _get(d: dict, dotted: str):
    cur = d
    for p in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _list(v) -> list:
    if not v:
        return []
    if isinstance(v, dict):
        return [x for x in v.values() if x]
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [x for x in v if x]


def brief_of(root: Path) -> dict:
    return read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}


def is_local(brief: dict) -> bool:
    return (brief.get("shape") in POLICY["local_shapes"] or bool(_get(brief, "seo.locations"))
            or any(_get(brief, f"seo.local.{k}") for k in ("address", "phone", "hours", "category")))


def site_url(root: Path, brief: dict) -> str | None:
    d = (brief.get("domain") or "").strip()
    if d:
        return (d if d.startswith("http") else "https://" + d).rstrip("/")
    dep = read_json(Path(root) / ".deckhand" / "deploy.json", {}) or {}
    u = (dep.get("url") or "").rstrip("/")
    return u if u and not PREVIEW_RX.search(u) else None


def ctx_of(root: Path, url: str | None = None) -> dict:
    root = Path(root)
    brief = brief_of(root)
    run = read_json(root / ".deckhand" / "run.json", {}) or {}
    langs = _list(brief.get("languages")) or ["en"]
    live = bool(url and url.startswith("https://") and not PREVIEW_RX.search(url))
    return {"brief": brief, "path": run.get("path") or "existing", "local": is_local(brief), "multilingual": len(langs) > 1,
            "languages": langs, "catalogue": brief.get("shape") == "catalogue", "live": live, "url": url,
            "site": site_url(root, brief), "sitemap": read_json(root / ".deckhand" / "sitemap.json", {}) or {}}


def _applies(item: dict, ctx: dict, framework: str | None = None) -> bool:
    a = item.get("applies", "always")
    return {"always": True, "local": ctx["local"], "multilingual": ctx["multilingual"], "catalogue": ctx["catalogue"],
            "live": ctx["live"] or bool(ctx["site"]), "next": framework == "next"}.get(a, True)


def owner_gaps(ctx: dict) -> list:
    """Owner facts and owner-only actions still open (they go to PENDING.md)."""
    b = ctx["brief"]
    out = []
    for f in POLICY["facts"]:
        if not _applies(f, ctx):
            continue
        v = _get(b, f["key"]) if f["key"] != "domain" else b.get("domain")
        if not v and f["key"] == "seo.local.address" and _get(b, "seo.local.service_area"):
            v = True
        if not v:
            out.append({"key": f["key"], "kind": "fact", "required": f.get("required", False), "label": f["label"], "why": f["why"], "how": f["how"]})
    done = {"search_console": ("verified",), "bing": ("verified",), "gbp": ("claimed", "verified"), "places": ("done",), "reviews": ("yes", "done")}
    for a in POLICY["actions"]:
        if not _applies(a, ctx):            # Search Console / Bing need the domain first; local actions can start now
            continue
        state = str(_get(b, f"seo.{a['key']}") or _get(b, f"seo.{a['key']}_asked") or "").lower()
        if state not in done.get(a["key"], ("done",)):
            out.append({"key": a["key"], "kind": "action", "required": a["key"] in ("search_console", "bing", "gbp"), "label": a["label"], "why": a["why"], "how": a["how"]})
    return out


# ------------------------------------------------------------------ plan (what `dh seo apply` hands the engine)

def schema_type(brief: dict) -> str:
    if not is_local(brief):
        return "Organization"
    cat = str(_get(brief, "seo.local.category") or brief.get("business") or "").lower()
    for k, t in POLICY["schema_types"].items():
        if k in cat:
            return t
    return "LocalBusiness"


def _address(s: str) -> dict:
    """'12 Rue X, 69001 Lyon, FR' -> PostalAddress (street · postal code + city · country); unparsed parts stay whole."""
    parts = [p.strip() for p in str(s).split(",") if p.strip()]
    a = {"@type": "PostalAddress"}
    if parts:
        a["streetAddress"] = parts[0]
    if len(parts) > 1:
        m = re.match(r"^(\d[\w -]{2,9})\s+(.+)$", parts[1]) or re.match(r"^(.+?)\s+(\d[\w -]{2,9})$", parts[1])
        if m and m.group(1)[0].isdigit():
            a["postalCode"], a["addressLocality"] = m.group(1).strip(), m.group(2).strip()
        elif m:
            a["addressLocality"], a["postalCode"] = m.group(1).strip(), m.group(2).strip()
        else:
            a["addressLocality"] = parts[1]
    if len(parts) > 2:
        a["addressCountry"] = parts[-1]
    return a


def jsonld(brief: dict, url: str) -> dict:
    """The business as structured data — only facts present in the brief (the owner's), never invented."""
    brand = brief.get("brand") or {}
    name = brand.get("name") or brief.get("name") or ""
    t = schema_type(brief)
    biz = {"@type": t, "@id": f"{url}/#business", "name": name, "url": f"{url}/"}
    desc = brand.get("tagline") or brief.get("business")
    if desc:
        biz["description"] = desc
    logo = brand.get("logo")
    if logo:
        biz["logo"] = logo if logo.startswith("http") else url + "/" + logo.lstrip("/")
    photos = _list(_get(brief, "seo.photos"))
    if photos or logo:
        biz["image"] = [p if p.startswith("http") else url + "/" + p.lstrip("/") for p in photos] or biz.get("logo")
    loc = _get(brief, "seo.local") or {}
    if loc.get("phone"):
        biz["telephone"] = loc["phone"]
    if loc.get("email"):
        biz["email"] = loc["email"]
    if isinstance(loc.get("address"), dict):
        a = loc["address"]
        biz["address"] = {"@type": "PostalAddress", **{k2: a[k1] for k1, k2 in (("street", "streetAddress"), ("city", "addressLocality"), ("region", "addressRegion"),
                                                                             ("postal", "postalCode"), ("country", "addressCountry")) if a.get(k1)}}
    elif loc.get("address") and loc["address"] != "service-area":
        biz["address"] = _address(loc["address"])
    if loc.get("geo") and isinstance(loc["geo"], dict) and loc["geo"].get("lat"):
        biz["geo"] = {"@type": "GeoCoordinates", "latitude": loc["geo"]["lat"], "longitude": loc["geo"]["lng"]}
    if loc.get("hours"):
        biz["openingHours"] = _list(loc["hours"])
    if loc.get("price_range"):
        biz["priceRange"] = loc["price_range"]
    areas = _list(_get(brief, "seo.locations"))
    if areas:
        biz["areaServed"] = areas if len(areas) > 1 else areas[0]
    same = _list(brand.get("social")) + _list(_get(brief, "seo.profiles"))
    if same:
        biz["sameAs"] = same
    founder = _get(brief, "seo.founder")
    if founder:
        biz["founder"] = {"@type": "Person", "name": str(founder).split("—")[0].split(" - ")[0].strip()}
    if _get(brief, "seo.founded"):
        biz["foundingDate"] = str(_get(brief, "seo.founded"))
    site = {"@type": "WebSite", "@id": f"{url}/#website", "name": name, "url": f"{url}/", "publisher": {"@id": f"{url}/#business"},
            "inLanguage": (_list(brief.get("languages")) or ["en"])[0]}
    return {"@context": "https://schema.org", "@graph": [biz, site]}


def public_pages(ctx: dict) -> list:
    pages = [p for p in ctx["sitemap"].get("pages", []) if (p.get("auth") or "public") == "public" and "[" not in p.get("route", "[")]
    return pages or [{"route": "/", "title": ""}]


def llms_text(brief: dict, url: str, pages: list, words: dict) -> str:
    brand = brief.get("brand") or {}
    name = brand.get("name") or brief.get("name") or ""
    lines = [f"# {name}", "", f"> {brand.get('tagline') or brief.get('business') or ''}".rstrip(), ""]
    facts = []
    loc = _get(brief, "seo.local") or {}
    if _list(_get(brief, "seo.locations")):
        facts.append("Serves: " + ", ".join(_list(_get(brief, "seo.locations"))))
    for k, label in (("address", "Address"), ("phone", "Phone"), ("email", "Email"), ("hours", "Hours"), ("price_range", "Prices")):
        if loc.get(k) and loc.get(k) != "service-area":
            facts.append(f"{label}: {', '.join(_list(loc[k])) if k == 'hours' else loc[k]}")
    if facts:
        lines += [f"- {f}" for f in facts] + [""]
    lines += ["## Pages", ""]
    for p in pages:
        w = words.get(p["route"], {})
        title = w.get("title") or p.get("title") or p["route"]
        lines.append(f"- [{title}]({url}{p['route'] if p['route'] != '/' else '/'})" + (f": {w['description']}" if w.get("description") else ""))
    return "\n".join(lines) + "\n"


def plan(root: Path) -> dict:
    root = Path(root)
    ctx = ctx_of(root)
    b = ctx["brief"]
    brand = b.get("brand") or {}
    name = brand.get("name") or b.get("name")
    if not name:
        raise DhError("NO_BRAND", "brand.name missing (dh brief set brand.name=\"…\")")
    url = ctx["site"] or "http://localhost:3000"
    copy = read_json(root / ".deckhand" / "copy.json", {}) or {}
    words = (copy.get("seo") or {}).get("pages") or {}
    pages = public_pages(ctx)
    auth = [p["route"] for p in ctx["sitemap"].get("pages", []) if (p.get("auth") or "public") != "public" and "[" not in p.get("route", "")]
    key = _get(b, "seo.indexnow_key")
    if not key:
        key = secrets.token_hex(16)
        b.setdefault("seo", {})["indexnow_key"] = key
        write_json(root / ".deckhand" / "brief.json", b)
    primary = brand.get("primary") or ""
    langs = ctx["languages"]
    locale = {"en": "en_US", "fr": "fr_FR", "es": "es_ES", "de": "de_DE", "it": "it_IT", "pt": "pt_PT", "nl": "nl_NL", "ar": "ar_AR"}.get(langs[0], f"{langs[0]}_{langs[0].upper()}")
    return {
        "site": {"name": name, "url": url, "url_known": bool(ctx["site"]), "description": _get(copy, "seo.description") or brand.get("tagline") or b.get("business") or "",
                 "tagline": brand.get("tagline") or "", "locale": locale, "languages": langs,
                 "themeColor": primary if re.match(r"^#[0-9a-f]{6}$", primary, re.I) else "#111111", "background": "#ffffff"},
        "jsonld": jsonld(b, url),
        "pages": [{"route": p["route"], "title": (words.get(p["route"]) or {}).get("title") or (p.get("title") if p["route"] != "/" else None),
                   "description": (words.get(p["route"]) or {}).get("description"), "noindex": bool(p.get("noindex"))} for p in pages],
        "robots": {"ai": _get(b, "seo.ai_crawlers") or "allow", "disallow": auth, "training": POLICY["ai_crawlers"]["training"]},
        "llms": llms_text(b, url, pages, words),
        "indexnow": key,
        "verification": {k: v for k, v in (("google", _get(b, "seo.google_verification")), ("bing", _get(b, "seo.bing_verification"))) if v},
        "genericTitles": POLICY["generic_titles"], "genericDescriptions": POLICY["generic_descriptions"],
    }


# ------------------------------------------------------------------ engine (node, AST)

def _node(root: Path, *args) -> dict:
    node = shutil.which("node")
    if not node:
        raise DhError("NO_NODE", "the SEO engine needs Node.js 18+")
    r = subprocess.run([node, str(TRYON / "cli.mjs"), "seo", *args, "--project", str(root)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise DhError("SEO_ENGINE", (r.stderr or r.stdout)[-600:])
    if not out.get("ok"):
        raise DhError(out.get("code") or "SEO_ENGINE", out.get("message") or "seo engine failed")
    return out


def inspect(root: Path) -> dict:
    try:
        return _node(root, "inspect")
    except DhError as e:
        return {"router": None, "files": {}, "pages": [], "notes": [f"source not inspected: {e.message}"]}


def apply(root: Path) -> dict:
    root = Path(root)
    p = plan(root)
    pf = root / ".deckhand" / "seo-plan.json"
    write_json(pf, p)
    res = _node(root, "apply", "--plan", str(pf))
    rep = audit(root)
    return {**{k: res[k] for k in ("router", "written", "changes") if k in res}, "undo": res.get("undo"),
            "score": rep["score"], "blockers": rep["blockers"], "owner_open": len(rep["owner"]),
            "site_url": p["site"]["url"] + ("" if p["site"]["url_known"] else " (placeholder — `dh brief set domain=…`, then apply again)"),
            "next": "write any missing per-page titles/descriptions in .deckhand/copy.json → seo.pages, apply again; the owner's part is in PENDING.md"}


def undo(root: Path, force: bool = False) -> dict:
    return _node(Path(root), "undo", *(["--force"] if force else []))


# ------------------------------------------------------------------ rendered HTML

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self.lang = None, {}, [], None
        self.headings, self.imgs, self.anchors, self.jsonld, self.text = [], [], [], [], []
        self._in, self._a, self._skip, self.nosnippet = None, None, 0, False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title" and self.title is None:
            self._in, self.title = "title", ""
        elif tag == "meta":
            k = (a.get("name") or a.get("property") or "").lower()
            if k:
                self.meta.setdefault(k, a.get("content", ""))
        elif tag == "link":
            self.links.append(a)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "a":
            self._a = {"href": a.get("href", ""), "text": ""}
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in = "ld"
            self.jsonld.append("")
        elif tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if "data-nosnippet" in a:
            self.nosnippet = True

    def handle_endtag(self, tag):
        if tag == "title" and self._in == "title":
            self._in = None
        elif tag == "script" and self._in == "ld":
            self._in = None
        elif tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._a is not None:
            self.anchors.append(self._a)
            self._a = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "ld":
            self.jsonld[-1] += data
        elif not self._skip:
            self.text.append(data)
            if self._a is not None:
                self._a["text"] += data


def parse_html(html: str) -> _Page:
    p = _Page()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001 — a broken page still gets the checks it can
        pass
    p.words = len(re.findall(r"\w+", " ".join(p.text)))
    p.visible = re.sub(r"\s+", " ", " ".join(p.text)).strip()
    return p


def fetch(url: str, timeout: int = 20, follow: bool = True):
    """(status, headers, body) — never raises; 0 = unreachable."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(*([] if follow else [NoRedirect()]))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; deckhand-seo/2; +https://github.com/takimdigital/deckhand-skill)"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, ""
    except Exception:  # noqa: BLE001
        return 0, {}, ""


# ------------------------------------------------------------------ audit

def _finding(rule: str, detail: str = "", where: str = "") -> dict:
    r = RULES[rule]
    return {"rule": rule, "severity": r["severity"], "area": r["area"], "title": r["title"], "detail": detail, "where": where,
            "fix": r["fix"], "auto": r["auto"]}


def _norm(u: str) -> str:
    u = u.split("#")[0].split("?")[0]
    return u[:-1] if u.endswith("/") and u.count("/") > 3 else u


def _robots_rules(txt: str) -> dict:
    """{agent-lower: [(allow|disallow, path)]} + sitemaps."""
    groups, cur, sitemaps, last_ua = {}, [], [], False
    for raw in txt.splitlines():
        line = raw.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not last_ua:
                cur = []
            cur.append(v.lower())
            groups.setdefault(v.lower(), [])
            last_ua = True
        elif k in ("allow", "disallow"):
            for ua in cur:
                groups.setdefault(ua, []).append((k, v))
            last_ua = False
        elif k == "sitemap":
            sitemaps.append(v)
    return {"groups": groups, "sitemaps": sitemaps}


def _blocked(rules: dict, agent: str) -> bool:
    g = rules["groups"].get(agent.lower())
    if g is None:
        g = rules["groups"].get("*", [])
    return any(k == "disallow" and v == "/" for k, v in g) and not any(k == "allow" and v == "/" for k, v in g)


def check_page(route: str, status: int, headers: dict, html: str, ctx: dict) -> tuple:
    """Findings for one rendered page + its facts (for the site-wide checks)."""
    p = parse_html(html)
    f = []
    robots = (p.meta.get("robots", "") + "," + headers.get("x-robots-tag", "")).lower()
    preview = REMOTE_PREVIEW(ctx.get("url"))
    if "noindex" in robots and not preview:
        f.append(_finding("C02", robots.strip(", "), route))
    if preview and "noindex" not in robots:
        f.append(_finding("C07", f"{ctx['url']} serves {route} without noindex", route))
    title = (p.title or "").strip()
    if not title or title in POLICY["generic_titles"]:
        f.append(_finding("M01", f'title "{title}"' if title else "no <title>", route))
    elif not (LIMITS["title"][0] <= len(title) <= LIMITS["title"][1]):
        f.append(_finding("M02", f"{len(title)} characters: \"{title}\"", route))
    desc = p.meta.get("description", "").strip()
    if not desc or desc in POLICY["generic_descriptions"]:
        f.append(_finding("M03", "missing" if not desc else f'template text "{desc}"', route))
    elif not (LIMITS["description"][0] <= len(desc) <= LIMITS["description"][1]):
        f.append(_finding("M03", f"{len(desc)} characters", route))
    canon = next((l.get("href") for l in p.links if l.get("rel", "").lower() == "canonical"), None)
    if not canon:
        f.append(_finding("M04", "no canonical", route))
    elif not canon.startswith("http"):
        f.append(_finding("M04", f"relative canonical {canon}", route))
    else:
        path = urllib.parse.urlparse(canon).path or "/"
        if _norm(path) != _norm(route) and not (path in ("", "/") and route == "/"):
            f.append(_finding("M04", f"points to {canon} (another page gets the credit)", route))
        chost = urllib.parse.urlparse(canon).netloc
        if ctx["live"] and (LOCAL_RX.search(canon) or chost != urllib.parse.urlparse(ctx["url"]).netloc):
            f.append(_finding("M12", f"canonical {canon} on the live site {ctx['url']}", route))
        elif ctx.get("site") and chost != urllib.parse.urlparse(ctx["site"]).netloc:
            f.append(_finding("M04", f"canonical host {chost} is not the production domain", route))
    lang = (p.lang or "").split("-")[0].lower()
    if not lang:
        f.append(_finding("M07", "<html> without lang", route))
    elif ctx["languages"] and lang not in ctx["languages"]:
        f.append(_finding("M07", f'lang="{p.lang}" but the site is {", ".join(ctx["languages"])}', route))
    if "viewport" not in p.meta:
        f.append(_finding("M08", "", route))
    if "keywords" in p.meta:
        f.append(_finding("M09", "", route))
    h1 = p.headings.count(1)
    if h1 != 1:
        f.append(_finding("T01", f"{h1} <h1>", route))
    for a, b in zip(p.headings, p.headings[1:]):
        if b > a + 1:
            f.append(_finding("T02", f"h{a} → h{b}", route))
            break
    no_alt = [i.get("src", "")[-60:] for i in p.imgs if "alt" not in i and i.get("aria-hidden") != "true" and i.get("role") != "presentation"]
    if no_alt:
        f.append(_finding("T03", f"{len(no_alt)} without alt: {', '.join(no_alt[:3])}", route))
    long_alt = [i.get("alt") for i in p.imgs if len(i.get("alt", "")) > LIMITS["alt_max"]]
    if long_alt:
        f.append(_finding("T03", f"{len(long_alt)} alt texts over {LIMITS['alt_max']} characters", route))
    no_size = [i.get("src", "")[-60:] for i in p.imgs if not (i.get("width") and i.get("height")) and "fill" not in (i.get("data-nimg") or "")]
    if no_size:
        f.append(_finding("P02", f"{len(no_size)} images: {', '.join(no_size[:3])}", route))
    generic = sorted({a["text"].strip().lower() for a in p.anchors if a["text"].strip().lower() in POLICY["generic_link_text"]})
    if generic:
        f.append(_finding("T06", ", ".join(f'"{g}"' for g in generic), route))
    if not p.meta.get("og:title") or not p.meta.get("og:image"):
        f.append(_finding("O01", "missing " + ", ".join(k for k in ("og:title", "og:image") if not p.meta.get(k)), route))
    if "twitter:card" not in p.meta:
        f.append(_finding("O02", "", route))
    if "nosnippet" in robots or "max-snippet:0" in robots or p.nosnippet:
        f.append(_finding("A06", "", route))
    if ctx["multilingual"]:
        alts = [l for l in p.links if l.get("rel", "").lower() == "alternate" and l.get("hreflang")]
        langs = {l["hreflang"].lower().split("-")[0] for l in alts}
        if not alts or "x-default" not in {l["hreflang"].lower() for l in alts} or not set(ctx["languages"]) <= langs:
            f.append(_finding("I01", f"hreflang found: {sorted(l['hreflang'] for l in alts) or 'none'}", route))
    graph = []
    for raw in p.jsonld:
        try:
            d = json.loads(raw)
        except ValueError:
            f.append(_finding("S02", "a JSON-LD block is not valid JSON", route))
            continue
        items = d.get("@graph", [d]) if isinstance(d, dict) else d
        graph += [x for x in items if isinstance(x, dict)]
    if route == "/" and not p.words and html:
        f.append(_finding("C10", "the server HTML of the home page has no text", route))
    return f, {"route": route, "status": status, "title": title, "desc": desc, "words": p.words, "text": p.visible[:4000],
               "h1": [], "graph": graph, "links": [a["href"] for a in p.anchors], "lang": p.lang}


def check_graph(graph: list, ctx: dict) -> list:
    f = []
    types = {str(t) for x in graph for t in ([x.get("@type")] if not isinstance(x.get("@type"), list) else x["@type"])}
    biz = [x for x in graph if x.get("@type") not in ("WebSite", "WebPage", "BreadcrumbList", "FAQPage", "HowTo", "Product", "ItemList")]
    if not biz:
        f.append(_finding("S01", "no Organization/LocalBusiness entity on the home page", "JSON-LD (home)"))
    for b in biz:
        missing = [k for k in ("name", "url") if not b.get(k)] + ([k for k in ("address", "telephone") if not b.get(k)] if ctx["local"] else [])
        if missing:
            f.append(_finding("S02", f"{b.get('@type')}: missing {', '.join(missing)}", "JSON-LD (home)"))
        if not b.get("logo"):
            f.append(_finding("S04", "", "JSON-LD (home)"))
        if not b.get("sameAs"):
            f.append(_finding("S05", "", "JSON-LD (home)"))
        if b.get("aggregateRating") or b.get("review"):
            f.append(_finding("S06", f"{b.get('@type')} carries {'aggregateRating' if b.get('aggregateRating') else 'review'}", "JSON-LD (home)"))
        if ctx["local"] and not b.get("openingHours") and not b.get("openingHoursSpecification"):
            f.append(_finding("L04", "no opening hours in the structured data", "JSON-LD (home)"))
    if "WebSite" not in types:
        f.append(_finding("S03", "", "JSON-LD (home)"))
    if types & {"FAQPage", "HowTo"}:
        f.append(_finding("S07", ", ".join(sorted(types & {"FAQPage", "HowTo"})), "JSON-LD (home)"))
    return f


def check_source(insp: dict, ctx: dict) -> list:
    f = []
    files = insp.get("files") or {}
    router = insp.get("router")
    if router:
        if not files.get("robots"):
            f.append(_finding("C03", "", "source"))
        if not files.get("sitemap"):
            f.append(_finding("C04", "", "source"))
        if not files.get("llms"):
            f.append(_finding("A02", "", "public/llms.txt"))
        if not files.get("indexnow"):
            f.append(_finding("A04", "", "public/<key>.txt"))
        if not insp.get("jsonLd"):
            f.append(_finding("S01", "no JSON-LD in the source", "source"))
    if router == "app":
        if not files.get("notFound"):
            f.append(_finding("C06", "no app/not-found", "source"))
        lay = insp.get("layout") or {}
        meta = lay.get("metadata") or {}
        static_pages = [p for p in insp.get("pages", []) if not p.get("dynamic")]
        if meta.get("canonical") and len(static_pages) > 1:
            f.append(_finding("M05", "", lay.get("file", "")))
        if lay and not lay.get("generateMetadata") and "metadataBase" not in (meta.get("keys") or []):
            f.append(_finding("M06", "", lay.get("file", "")))
        if lay and not lay.get("lang"):
            f.append(_finding("M07", "<html> without lang", lay.get("file", "")))
        if not files.get("ogImage") and "openGraph" not in (meta.get("keys") or []):
            f.append(_finding("O01", "no opengraph-image and no openGraph metadata", "source"))
        planned = {p["route"] for p in public_pages(ctx)}
        for p in insp.get("pages", []):
            if p.get("client") and (p["route"] in planned or not ctx["sitemap"]):
                f.append(_finding("M10", "", p["file"]))
            if p.get("dynamic") and not p.get("generateMetadata"):
                f.append(_finding("M11", "", p["file"]))
    if router == "static" and (insp.get("index") or {}).get("spa"):
        f.append(_finding("C10", "a client-rendered single-page app: the server HTML is an empty <div id=\"root\">", insp["index"]["file"]))
    return f


def check_plan(ctx: dict) -> list:
    f = []
    pages = ctx["sitemap"].get("pages", [])
    if not pages:
        return f
    text = " ".join(f"{p.get('route', '')} {p.get('title', '')} {p.get('id', '')}".lower() for p in pages)
    if not re.search(r"about|a-propos|qui-sommes|histoire|story|team|equipe|nous", text) or not re.search(r"contact", text):
        f.append(_finding("E01", "the plan has no " + " / ".join(x for x, rx in (("About", r"about|a-propos|qui-sommes|histoire|story|team|equipe|nous"), ("Contact", r"contact")) if not re.search(rx, text)) + " page", ".deckhand/sitemap.json"))
    if not re.search(r"privacy|privacite|confidentialit|legal|mentions|impressum|terms|cgv|cgu|datenschutz", text):
        f.append(_finding("E02", "", ".deckhand/sitemap.json"))
    return f


def check_images(root: Path) -> list:
    heavy = []
    pub = Path(root) / "public"
    if pub.is_dir():
        for p in pub.rglob("*"):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif") and p.stat().st_size > LIMITS["image_kb_warn"] * 1024:
                heavy.append(f"{p.relative_to(root)} ({p.stat().st_size // 1024} KB)")
    return [_finding("P01", ", ".join(heavy[:5]) + (f" (+{len(heavy) - 5})" if len(heavy) > 5 else ""), "public/")] if heavy else []


def check_site(base: str, ctx: dict, get=fetch) -> tuple:
    """robots.txt, sitemap.xml, soft 404 (+ live-only: HTTPS, one host, preview indexing)."""
    f = []
    st, _, robots = get(base + "/robots.txt")
    rules = _robots_rules(robots) if st == 200 else {"groups": {}, "sitemaps": []}
    if st != 200:
        f.append(_finding("C03", f"/robots.txt answered {st}", "/robots.txt"))
    else:
        if _blocked(rules, "*") or _blocked(rules, "googlebot"):
            f.append(_finding("C01", "Disallow: / for every crawler", "/robots.txt"))
        if not rules["sitemaps"] and not REMOTE_PREVIEW(ctx.get("url")):
            f.append(_finding("C04", "robots.txt has no Sitemap: line", "/robots.txt"))
        blocked_ai = [b for b in POLICY["ai_crawlers"]["retrieval"] if _blocked(rules, b)]
        if blocked_ai:
            f.append(_finding("A01", ", ".join(blocked_ai), "/robots.txt"))
    st, _, sm = get(base + "/sitemap.xml")
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm) if st == 200 else []
    if st != 200:
        f.append(_finding("C04", f"/sitemap.xml answered {st}", "/sitemap.xml"))
    elif not REMOTE_PREVIEW(ctx.get("url")):
        paths = {_norm(urllib.parse.urlparse(u).path or "/") for u in locs}
        planned = {_norm(p["route"]) for p in public_pages(ctx)}
        missing = sorted(planned - paths) if ctx["sitemap"] else []
        private = sorted(_norm(p["route"]) for p in ctx["sitemap"].get("pages", []) if (p.get("auth") or "public") != "public" and _norm(p["route"]) in paths)
        hosts = {urllib.parse.urlparse(u).netloc for u in locs}
        wrong = sorted(h for h in hosts if ctx.get("site") and h != urllib.parse.urlparse(ctx["site"]).netloc)
        if missing or private or wrong:
            f.append(_finding("C05", "; ".join(x for x in (f"missing {', '.join(missing)}" if missing else "", f"lists signed-in pages {', '.join(private)}" if private else "",
                                                               f"host {', '.join(wrong)} is not the production domain" if wrong else "") if x), "/sitemap.xml"))
    probe = "/" + "dh-seo-404-" + hashlib.sha1(base.encode()).hexdigest()[:8]
    st, _, _ = get(base + probe)
    if st == 200:
        f.append(_finding("C06", f"{probe} answered 200", probe))
    if ctx["live"]:
        host = urllib.parse.urlparse(base).netloc
        st, h, _ = get("http://" + host + "/", follow=False)
        if st and not (300 <= st < 400 and h.get("location", "").startswith("https://")):
            f.append(_finding("C08", f"http://{host}/ answered {st} instead of redirecting to https", "http://"))
        other = host[4:] if host.startswith("www.") else "www." + host
        st, h, _ = get("https://" + other + "/", follow=False)
        if st == 200:
            f.append(_finding("C08", f"https://{other}/ serves the site too (redirect it to https://{host}/)", other))
    elif base.startswith("http://") and not re.search(r"://(localhost|127\.0\.0\.1)", base) and ctx.get("site"):
        f.append(_finding("E04", base, base))
    return f, locs


def audit(root: Path, url: str | None = None, get=fetch, write: bool = True) -> dict:
    """Every applicable rule, deterministic; `url` = rendered pages (verify passes the served production build)."""
    root = Path(root)
    base = (url or (read_json(root / ".deckhand" / "dev.json", {}) or {}).get("url") or "").rstrip("/") or None
    ctx = ctx_of(root, url)
    insp = inspect(root)
    findings = check_source(insp, ctx) + check_plan(ctx) + check_images(root)
    pages = []
    if base:
        site_f, _locs = check_site(base, ctx, get)
        findings += site_f
        routes = [p["route"] for p in public_pages(ctx)]
        seen_titles, seen_desc = {}, {}
        home = None
        for r in routes[:60]:
            st, h, html = get(base + r)
            if st >= 400 or st == 0:
                continue
            pf, facts = check_page(r, st, h, html, {**ctx, "url": url or base})
            findings += pf
            pages.append(facts)
            if facts["title"]:
                seen_titles.setdefault(facts["title"], []).append(r)
            if facts["desc"]:
                seen_desc.setdefault(facts["desc"], []).append(r)
            if r == "/":
                home = facts
        for t, rs in seen_titles.items():
            if len(rs) > 1:
                findings.append(_finding("M02", f'"{t}" on {", ".join(rs)}', ", ".join(rs)))
        for d, rs in seen_desc.items():
            if len(rs) > 1:
                findings.append(_finding("M03", f"the same description on {', '.join(rs)}", ", ".join(rs)))
        if home:
            findings += check_graph(home["graph"], ctx)
            findings += check_home(home, ctx)
            if ctx["local"]:
                findings += check_nap(pages, ctx)
    # one finding per rule+where+detail; a rule that does not apply to this business is dropped
    fw = insp.get("framework")
    uniq, out = set(), []
    for x in findings:
        k = (x["rule"], x["where"], x["detail"])
        if k in uniq or not _applies(RULES[x["rule"]], ctx, fw):
            continue
        uniq.add(k)
        out.append(x)
    out.sort(key=lambda x: (list(WEIGHT).index(x["severity"]), x["rule"], x["where"]))
    failed = {x["rule"] for x in out}
    applicable = [r for r in POLICY["rules"] if _applies(r, ctx, fw) and r["id"] not in NOT_CHECKED and (base or r["id"] not in RENDERED)]
    total = sum(WEIGHT[r["severity"]] for r in applicable) or 1
    lost = sum(WEIGHT[RULES[r]["severity"]] for r in failed if r in RULES)
    measured = bool(base) or bool(insp.get("router"))
    report = {
        "at": now(), "score": max(0, round(100 * (1 - lost / total))) if measured else None, "rendered": bool(base), "path": ctx["path"],
        "policy": POLICY["policy_by_path"].get(ctx["path"], "apply"), "site": ctx["site"],
        "blockers": [x for x in out if x["severity"] == "block"], "findings": out,
        "auto_fixable": sorted({x["rule"] for x in out if x["auto"]}),
        "owner": owner_gaps(ctx), "router": insp.get("router"), "notes": insp.get("notes", []),
    }
    if write:
        write_json(root / ".deckhand" / "seo.json", report)
        (root / ".deckhand" / "SEO.md").write_text(render(report), encoding="utf-8")
        sync_pending(root, report)
    return report


def check_home(home: dict, ctx: dict) -> list:
    f = []
    b = ctx["brief"]
    if home["words"] < LIMITS["min_words_home"]:
        f.append(_finding("T04", f"{home['words']} words", "/"))
    kws = _list(_get(b, "seo.keywords"))
    city = (_list(_get(b, "seo.locations")) or [None])[0]
    hay = (home["title"] + " " + home["text"][:1500]).lower()
    missing = [k for k in kws[:1] if not all(w in hay for w in re.findall(r"\w{3,}", k.lower()))]
    if ctx["local"] and city and city.lower() not in hay:
        missing.append(city)
    if missing:
        f.append(_finding("T05", "not in the home title/first paragraph: " + ", ".join(missing), "/"))
    brand = ((b.get("brand") or {}).get("name") or b.get("name") or "").lower()
    lead = home["text"][:600].lower()
    if brand and (brand not in lead or (ctx["local"] and city and city.lower() not in lead)):
        f.append(_finding("A05", "the first lines do not state who, what and where", "/"))
    social = _list((b.get("brand") or {}).get("social"))
    hosts = {urllib.parse.urlparse(u).netloc.replace("www.", "") for u in social}
    if hosts and not any(urllib.parse.urlparse(h).netloc.replace("www.", "") in hosts for h in home["links"]):
        f.append(_finding("O04", ", ".join(sorted(hosts)), "/"))
    planned = {p["route"] for p in public_pages(ctx)} - {"/"}
    linked = {_norm(urllib.parse.urlparse(h).path or "/") for h in home["links"] if h.startswith("/") or (ctx.get("site") and h.startswith(ctx["site"]))}
    unlinked = sorted(r for r in planned if _norm(r) not in linked)
    if unlinked:
        f.append(_finding("T07", ", ".join(unlinked[:8]), "/"))
    return f


def check_nap(pages: list, ctx: dict) -> list:
    loc = _get(ctx["brief"], "seo.local") or {}
    text = " ".join(p["text"] for p in pages).lower()
    digits = re.sub(r"\D", "", text)
    missing = []
    phone = re.sub(r"\D", "", str(loc.get("phone") or ""))
    if phone and phone[-9:] not in digits:
        missing.append("phone")
    addr = str(loc.get("address") or "")
    if addr and addr != "service-area" and not all(tok.lower() in text for tok in re.findall(r"\w{4,}", addr.split(",")[0])[:2]):
        missing.append("address")
    if not loc.get("phone") and not loc.get("address"):
        return [_finding("L01", "no name/address/phone known yet (PENDING.md)", "all pages")]
    return [_finding("L01", "not found on any page: " + ", ".join(missing), "footer / contact")] if missing else []


def render(rep: dict) -> str:
    L = [f"# SEO report — {rep['score'] if rep['score'] is not None else 'not measured yet'}/100", "", f"_{rep['at']} · path {rep['path']} ({'applied by default' if rep['policy'] == 'apply' else 'strongly recommended before launch'}) · "
         + ("rendered pages checked" if rep["rendered"] else "source only — run `dh verify` or `dh seo audit --url …` for the rendered pages") + "_", ""]
    if rep["blockers"]:
        L += ["## Launch-breakers", ""] + [f"- **{x['rule']}** {x['title']} — {x['detail']} ({x['where']}) → {x['fix']}" for x in rep["blockers"]] + [""]
    rest = [x for x in rep["findings"] if x["severity"] != "block"]
    if rest:
        L += ["## To fix", "", "| sev | rule | where | what | fix | auto |", "|---|---|---|---|---|---|"]
        L += [f"| {x['severity']} | {x['rule']} | {x['where']} | {x['title']}{': ' + x['detail'] if x['detail'] else ''} | {x['fix']} | {'`dh seo apply`' if x['auto'] else 'agent/owner'} |" for x in rest]
        L.append("")
    if rep["owner"]:
        L += ["## Needed from the owner (also in PENDING.md)", ""] + [f"- {o['label']} — {o['why']} HOW: {o['how']}" for o in rep["owner"]] + [""]
    L += ["Nobody can promise position #1. This report guarantees nothing within our control is missing.", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ PENDING.md

BEGIN = "<!-- dh:seo:begin — regenerated by `dh seo audit`; a line you move above this block is kept by hand -->"
END = "<!-- dh:seo:end -->"


def sync_pending(root: Path, rep: dict) -> dict:
    """The owner's open SEO facts/actions as PENDING lines; first-asked dates survive every refresh."""
    p = Path(root) / "PENDING.md"
    text = p.read_text(encoding="utf-8") if p.exists() else "# PENDING\n\n## Open\n\n## Done\n"
    asked = dict(re.findall(r"P-SEO-([\w.]+) .*? asked (\d{4}-\d{2}-\d{2})", text))
    score = f"{rep['score']}/100" if rep["score"] is not None else "not measured yet (no app to inspect — `dh seo audit` after the build)"
    lines = [f"- FYI · SEO readiness {score} · {len(rep['blockers'])} launch-breakers · "
             f"{len([x for x in rep['findings'] if x['auto']])} fixes the agent makes with `dh seo apply` · details: .deckhand/SEO.md"]
    product = (read_json(Path(root) / ".deckhand" / "brief.json", {}) or {}).get("deliverable") == "product"
    if product and rep["owner"]:
        lines.append("- FYI · a product: these facts belong to each buyer — the app's settings must let the buyer enter them "
                     "(and CUSTOMIZE.md says where): " + ", ".join(o["label"] for o in rep["owner"]))
    for o in ([] if product else rep["owner"]):
        tag = "ACTION NEEDED" if o["kind"] == "action" or o["required"] else "RECOMMENDED"
        lines.append(f"- [ ] P-SEO-{o['key']} · {tag} — {o['label']} · WHY: {o['why']} · HOW: {o['how']} · asked {asked.get(o['key'], today())}")
    block = "\n".join(["## Detected by `dh seo` — to be found on Google and in AI answers", BEGIN, *lines, END])
    if BEGIN in text:
        text = re.sub(r"## Detected by `dh seo`[^\n]*\n" + re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    elif "## Done" in text:
        text = text.replace("## Done", block + "\n\n## Done", 1)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    p.write_text(text, encoding="utf-8")
    return {"open": 0 if product else len(rep["owner"])}


def pending_summary(root: Path) -> dict:
    """Open PENDING.md lines with their age — `dh next` returns them so every report ends with them."""
    p = Path(root) / "PENDING.md"
    if not p.exists():
        return {"open": 0, "items": []}
    items = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("- [ ]"):
            m = re.search(r"asked (\d{4}-\d{2}-\d{2})", line)
            age = None
            if m:
                import datetime as _dt
                age = (_dt.date.fromisoformat(today()) - _dt.date.fromisoformat(m.group(1))).days
            label = re.sub(r"\s·\s(WHY|HOW|WHERE):.*$", "", line[6:]).strip()
            items.append({"item": label[:160], "age_days": age})
    return {"open": len(items), "items": items[:12], "say": "end the report with these open items (age in days) — the owner's part is never only in chat"}


# ------------------------------------------------------------------ IndexNow

def ping(root: Path, urls: list | None = None, post=None) -> dict:
    root = Path(root)
    b = brief_of(root)
    key = _get(b, "seo.indexnow_key")
    site = site_url(root, b)
    if not key or not site:
        return {"pinged": False, "why": "no IndexNow key (dh seo apply) or no production domain (dh brief set domain=…)"}
    if not urls:
        st, _, sm = fetch(site + "/sitemap.xml")
        urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm) if st == 200 else [site + "/"]
    body = json.dumps({"host": urllib.parse.urlparse(site).netloc, "key": key, "keyLocation": f"{site}/{key}.txt", "urlList": urls[:10000]}).encode()
    if post:
        return post(body)
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "deckhand-seo/2"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"pinged": True, "status": r.status, "urls": len(urls)}
    except urllib.error.HTTPError as e:
        return {"pinged": False, "status": e.code, "why": {403: "key file not reachable yet (deploy first)", 422: "URLs not on the key's host"}.get(e.code, "")}
    except Exception as e:  # noqa: BLE001
        return {"pinged": False, "why": str(e)[:160]}
