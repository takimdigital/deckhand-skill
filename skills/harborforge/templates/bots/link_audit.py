#!/usr/bin/env python3
"""link_audit.py — weekly crawl: broken internal links, pages without <title>/meta description,
missing robots.txt / sitemap.xml. Env: SITE_URLS (first = start), MAX_PAGES (150). stdlib only."""
from __future__ import annotations

import os, re, sys, urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import send  # noqa: E402


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.links, self.title, self.desc, self._t = set(), "", False, False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"): self.links.add(a["href"])
        if tag == "title": self._t = True
        if tag == "meta" and (a.get("name") or "").lower() == "description" and a.get("content"): self.desc = True
    def handle_endtag(self, tag):
        if tag == "title": self._t = False
    def handle_data(self, d):
        if self._t: self.title += d


def fetch(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "deckhand-link-audit/2"}), timeout=20) as r:
            ctype = r.headers.get("content-type", "")
            return r.status, (r.read(800_000).decode("utf-8", "replace") if "html" in ctype else "")
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", 0) or 0, ""


def main() -> int:
    start = os.environ.get("SITE_URLS", "").split(",")[0].strip()
    if not start:
        print("SITE_URLS is required"); return 2
    host = urlparse(start).netloc
    seen, queue, issues = set(), [start], []
    for extra in ("/robots.txt", "/sitemap.xml"):
        code, _ = fetch(urljoin(start, extra))
        if code != 200:
            issues.append(f"{extra} missing ({code})")
    while queue and len(seen) < int(os.environ.get("MAX_PAGES", "150")):
        u = queue.pop(0).split("#")[0]
        if u in seen: continue
        seen.add(u)
        code, html = fetch(u)
        if code >= 400 or code == 0:
            issues.append(f"{u} -> {code}"); continue
        p = Page()
        try: p.feed(html)
        except Exception: pass  # noqa: BLE001
        if html and not p.title.strip(): issues.append(f"{u}: no <title>")
        if html and not p.desc: issues.append(f"{u}: no meta description")
        for l in p.links:
            nu = urljoin(u, l)
            if urlparse(nu).netloc == host and not re.search(r"\.(pdf|jpg|png|svg|zip)$", nu): queue.append(nu)
    print(f"crawled {len(seen)} pages, {len(issues)} issues")
    for i in issues: print(" -", i)
    send("link-audit", ("\n".join(f"• {i}" for i in issues[:40]) or f"✅ {len(seen)} pages, no issues"), "Weekly link + SEO audit")
    return 1 if any("->" in i for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
