"""REBRAND: the owner's identity in, the template's out — deterministic, then PROVED by a leak check.

apply: package name, metadata title/description, site config names, template display names in
source/docs, the primary colour token, a monogram icon when there is no logo. LICENSE / NOTICE /
THIRD_PARTY_NOTICES are never touched (they are the legal condition of reuse).
check: the honesty + leak gate — template names, demo companies, lorem ipsum, example contacts,
placeholder images, demo-copy markers, third-party brand logos presented as social proof; words an AI
try-on draft wrote (labelled for the owner) are a warning until confirmed or rewritten; copy that reads as AI slop
(dhlib/slop.py: a text scored slop blocks, one to review warns — `--allow ai-slop` skips it).
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import DhError, git_files, is_text, read_json, slugify
from . import state as STATE

NEVER = re.compile(r"(^|/)(LICENSE|LICENCE|NOTICE|THIRD_PARTY_NOTICES)(\.[a-z]+)?$|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?)$|(^|/)\.deckhand/", re.I)
DEMO_NAMES = [r"\bAcme( Inc\.?| Corp\.?)?\b", r"\blorem ipsum\b", r"\bdolor sit amet\b", r"\bJohn Doe\b", r"\bJane Doe\b",
              r"\byour company\b", r"\bCompany Name\b", r"\bYour Brand\b", r"\bexample@example\.com\b", r"\bhello@example\.com\b",
              r"\b\+1 ?\(?555\)?", r"\b123 Main St"]
BRAND_LOGO_FILES = re.compile(r"(^|/)(vercel|spotify|supabase|hulu|bolt|beacon|firebase|claude(-ai)?|openai|gemini|slack|figma|linear|twilio|clerk|nvidia|netflix|cisco|stripe|github|lemon-squeezy|laravel|lilly|nike|column|replit|trustpilot|g2|google)\.(tsx|jsx|svg)$", re.I)


def _template_names(root: Path) -> list:
    s = STATE.load(root, required=False) or {}
    base = s.get("base") or {}
    names = set()
    if base.get("kind") == "template":
        n = base.get("name") or ""
        names |= {n, n.replace("-", " "), n.replace("-", "")}
        if base.get("repo"):
            owner, repo = base["repo"].split("/")
            names |= {repo, repo.replace("-", " "), base["repo"]}
    extra = (read_json(root / ".deckhand" / "brief.json", {}) or {}).get("template_names") or []
    names |= set(extra)
    return sorted({x for x in names if len(x) >= 4}, key=len, reverse=True)


def _iter_text(root: Path):
    for p in git_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if NEVER.search(rel) or not p.is_file() or not is_text(p):
            continue
        try:
            yield rel, p, p.read_text(encoding="utf-8")
        except Exception:
            continue


def scan(root: Path) -> dict:
    root = Path(root)
    names = _template_names(root)
    hits = []
    pkg = read_json(root / "package.json", {}) or {}
    for rel, p, text in _iter_text(root):
        for i, line in enumerate(text.splitlines(), 1):
            for n in names:
                if re.search(re.escape(n), line, re.I):
                    hits.append({"file": rel, "line": i, "kind": "template-name", "text": line.strip()[:140]})
                    break
            if re.search(r"(title|siteName|name)\s*[:=]\s*['\"]", line) and re.search(r"(layout|site|config|metadata|seo)", rel, re.I):
                hits.append({"file": rel, "line": i, "kind": "identity-field", "text": line.strip()[:140]})
    logos = [str(p.relative_to(root)) for p in root.glob("public/*") if re.search(r"(logo|favicon|og|opengraph|icon)", p.name, re.I)]
    return {"package_name": pkg.get("name"), "template_names": names, "identity": hits[:200], "assets": logos}


def _hex_ok(c: str) -> bool:
    return bool(re.match(r"^(#[0-9a-fA-F]{3,8}|oklch\(.+\)|rgb\(.+\)|hsl\(.+\))$", c or ""))


def apply(root: Path, brand: dict | None = None, dry: bool = False) -> dict:
    root = Path(root)
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    brand = {**(brief.get("brand") or {}), **(brand or {})}
    name = brand.get("name") or brief.get("name")
    if not name:
        raise DhError("NO_BRAND", "brand.name missing (dh brief set brand.name=\"…\")")
    tagline = brand.get("tagline") or brief.get("business") or ""
    changes = []
    # 1. package.json name
    pj = root / "package.json"
    if pj.exists():
        t = pj.read_text(encoding="utf-8")
        new = re.sub(r'("name"\s*:\s*")[^"]*(")', lambda m: m.group(1) + slugify(name) + m.group(2), t, count=1)
        if new != t:
            changes.append({"file": "package.json", "what": "name"})
            if not dry:
                pj.write_text(new, encoding="utf-8")
    # 2. template display names + metadata/site-config fields
    names = _template_names(root)
    for rel, p, text in _iter_text(root):
        new = text
        for n in names:
            new = re.sub(re.escape(n), name, new, flags=re.I)
        if re.search(r"(layout|site|config|metadata|seo|manifest)", rel, re.I):
            new = re.sub(r"(\btitle\s*:\s*)(['\"])(?!%s)[^'\"]*\2" % re.escape(name), lambda m: f"{m.group(1)}{m.group(2)}{name}{m.group(2)}", new, count=1)
            if tagline:
                new = re.sub(r"(\bdescription\s*:\s*)(['\"])[^'\"]*\2", lambda m: f"{m.group(1)}{m.group(2)}{tagline.replace(m.group(2), '')}{m.group(2)}", new, count=1)
        if new != text:
            changes.append({"file": rel, "what": "identity"})
            if not dry:
                p.write_text(new, encoding="utf-8")
    # 3. primary colour
    color = brand.get("primary")
    if color:
        if not _hex_ok(color):
            raise DhError("BAD_COLOR", f"brand.primary {color!r}: use #hex, rgb(), hsl() or oklch()")
        for css in [root / c for c in ("app/globals.css", "src/app/globals.css", "styles/globals.css", "src/index.css")] :
            if css.exists():
                t = css.read_text(encoding="utf-8")
                new, n = re.subn(r"(:root\s*\{[^}]*?--primary\s*:\s*)[^;]+;", lambda m: m.group(1) + color + ";", t, count=1)
                if n and new != t:
                    changes.append({"file": str(css.relative_to(root)), "what": "--primary"})
                    if not dry:
                        css.write_text(new, encoding="utf-8")
                break
    # 4. monogram icon when there is no logo
    appdir = next((root / d for d in ("app", "src/app") if (root / d).is_dir()), None)
    if appdir and not brand.get("logo") and not any((appdir / f).exists() for f in ("icon.svg", "icon.png", "favicon.ico")):
        letter = re.sub(r"[^A-Za-z0-9]", "", name)[:1].upper() or "•"
        fill = color if color and color.startswith("#") else "#111111"
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{fill}"/><text x="32" y="43" font-family="system-ui,sans-serif" font-size="34" font-weight="700" text-anchor="middle" fill="#fff">{letter}</text></svg>\n'
        changes.append({"file": str((appdir / "icon.svg").relative_to(root)), "what": "monogram icon"})
        if not dry:
            (appdir / "icon.svg").write_text(svg, encoding="utf-8")
    return {"brand": name, "changes": changes, "dry": dry, "next": "dh rebrand check"}


# a product (a boilerplate sold to many businesses) ships a fictional demo company — in its seed, nowhere else
DEMO_PATHS = r"(^|/)(db/seed|seeds?/|seed\.|demo/|demo-data|fixtures/|sample-data)"


def check(root: Path, allow: tuple = ()) -> dict:
    """Findings with severity: block (fails the gate) | warn."""
    root = Path(root)
    names = _template_names(root)
    findings = []
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    product = brief.get("deliverable") == "product"
    demo_rx = re.compile(DEMO_PATHS + "".join(f"|{re.escape(x)}" for x in ((brief.get("demo") or {}).get("paths") or [])))

    def add(rel, i, kind, text, sev="block"):
        if kind in allow:
            return
        if product and kind in ("demo-content", "lorem") and demo_rx.search(rel):
            sev, text = "warn", "demo data of a product (the buyer's reset script wipes it): " + text.strip()
        findings.append({"file": rel, "line": i, "kind": kind, "text": text.strip()[:140], "severity": sev})
    for rel, p, text in _iter_text(root):
        is_doc = rel.lower().endswith((".md", ".mdx")) or rel.startswith("docs/")
        for i, line in enumerate(text.splitlines(), 1):
            for n in names:
                if re.search(r"(?<![\w/.-])" + re.escape(n) + r"(?![\w-])", line, re.I):
                    add(rel, i, "template-name", line, "warn" if is_doc else "block")
                    break
            for rx in DEMO_NAMES:
                if re.search(rx, line, re.I) and not rel.endswith((".env.example",)):
                    add(rel, i, "demo-content", line, "warn" if is_doc else "block")
                    break
            if "deckhand-placeholder.svg" in line:
                add(rel, i, "placeholder-image", line, "warn")
            if "data-dh-demo" in line or "dh-tryon" in line and not rel.startswith(".deckhand"):
                add(rel, i, "tryon-leftover", line)
        lorem = len(re.findall(r"\b(lorem|ipsum|dolor|amet|consectetur|adipiscing|mollitia|rerum|quisquam|voluptate|dolore|cumque|illo|esse|aliquam|tempor|incididunt)\b", text, re.I))
        if lorem >= 3 and not is_doc:
            add(rel, 1, "lorem", f"{lorem} lorem-ipsum words in this file (placeholder Latin shipped as content)")
        if BRAND_LOGO_FILES.search(rel) and re.search(r"components/(sections|ui-kit)/", rel):
            add(rel, 1, "third-party-logo", "a registry demo logo shipped as social proof — replace with real clients or remove", "block")
    # the design's demo copy that try-on/compose could not replace with the owner's words
    ledger = read_json(root / ".deckhand" / "demo-copy.json", {}) or {}
    norm = lambda t: re.sub(r"\s+", " ", t).strip()  # noqa: E731
    cache = {}
    for e in ledger.get("entries", []):
        fp = root / e["file"]
        if not fp.exists() or "demo-copy" in allow:
            continue
        if e["file"] not in cache:
            cache[e["file"]] = norm(fp.read_text(encoding="utf-8", errors="ignore"))
        if norm(e["text"]) in cache[e["file"]]:
            if e.get("ai"):
                # an AI draft the owner saw labelled and kept: its own words are flagged for review, not blocked
                add(e["file"], 1, "ai-copy", f"AI-written text on the page: \"{e['text'][:80]}\" — owner confirms or rewrites", "warn")
            else:
                add(e["file"], 1, "demo-copy", f"design demo text still on the page: \"{e['text'][:80]}\" — rewrite for the owner or delete")
    # copy that reads as written by a model (dhlib/slop.py): a text scored slop blocks, one to review warns
    if "ai-slop" not in allow:
        from . import slop as SLOP
        for u in SLOP.project_units(root):
            if u["verdict"] == "clean":
                continue
            for h in u["hits"][:8]:
                add(u["file"], h.get("line") or 1, "ai-slop", f"{u['verdict']} {u['score']}/100 · {h['rule']} \"{h['match']}\""
                    + (f" [{h['key']}]" if h.get("key") else "") + (f" → {h['fix']}" if h.get("fix") else ""), "block" if u["verdict"] == "slop" else "warn")
    blocking = [f for f in findings if f["severity"] == "block"]
    return {"ok": not blocking, "blocking": len(blocking), "warnings": len(findings) - len(blocking), "findings": findings[:300]}
