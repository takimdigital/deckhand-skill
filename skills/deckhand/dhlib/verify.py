"""REVIEW: one command, evidence rows, a red row blocks the deploy gate.

Rows: typecheck · lint (advisory) · build · prod-clean (no try-on stamp in the build) · tryon-closed · tryon-unwired ·
secrets · leaks/honesty (incl. AI-slop copy) · routes (every planned static route + every internal link on the home page
answers < 400 — on the production build, served on a free port for the check) · copy-slop on rendered pages (advisory) · a11y basics (advisory) · dependency audit (advisory).
Writes .deckhand/verify.json + .deckhand/VERIFY.md.
"""
from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .util import RUNTIME_STATE, SECRET_RX, git_files, is_text, now, package_json, pm_run, read_json, run, write_json
from . import brand as BRAND
from . import build as BUILD


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("/") and not href.startswith("//"):
                self.links.add(href.split("#")[0].split("?")[0] or "/")


def _get(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deckhand-verify/2"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", None) or 0, ""


def product_kit(root: Path, scripts: dict) -> list:
    """What a boilerplate sold to other businesses must carry (brief.deliverable=product)."""
    miss = []
    full = lambda p: p.is_file() and bool(p.read_text(encoding="utf-8", errors="replace").strip())  # noqa: E731 — an empty file is not a kit
    if not full(root / "README.md"):
        miss.append("README.md (what it is, the stack, the quick start)")
    if not any(full(p) for p in root.iterdir() if p.name.upper().startswith(("LICENSE", "LICENCE"))):
        miss.append("LICENSE (the terms the buyer gets)")
    if not (full(root / "CUSTOMIZE.md") or (root / "docs").is_dir() and any(full(p) for p in (root / "docs").glob("*custom*"))):
        miss.append("CUSTOMIZE.md (rebrand, the buyer's own facts, where each setting lives)")
    names = " ".join(k for k, v in scripts.items() if str(v or "").strip())          # a script that runs nothing is none
    if not re.search(r"seed", names):
        miss.append("a seed script (package.json) that loads the demo company")
    if not re.search(r"reset|wipe|clean", names):
        miss.append("a reset/wipe script (package.json) that removes the demo company for the buyer")
    return miss


def tryon_hooked(root: Path) -> list:
    """`tryon setup` wires next/vite config to .deckhand/tryon/runtime, which git never carries."""
    out = []
    for p in list(root.glob("next.config.*")) + list(root.glob("vite.config.*")):
        try:
            code = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "deckhand-tryon" in code or ".deckhand/tryon/runtime" in code:
            out.append(p.name)
    return out


def run_verify(root: Path, url: str | None = None, skip: tuple = (), allow: tuple = ()) -> dict:
    root = Path(root)
    rows = []

    def row(check, ok, detail, blocking=True, evidence=None):
        rows.append({"check": check, "ok": bool(ok), "blocking": blocking, "detail": detail, **({"evidence": evidence} if evidence else {})})

    pkg = package_json(root)
    scripts = pkg.get("scripts") or {}
    if "typecheck" not in skip and (root / "tsconfig.json").exists():
        r = run(["npx", "--no-install", "tsc", "--noEmit", "-p", "."], cwd=root, timeout=900)
        errs = len(re.findall(r"error TS\d+", r["out"] + r["err"]))
        row("typecheck", r["code"] == 0, f"{errs} TypeScript errors" if r["code"] else "tsc --noEmit clean", evidence=(r["out"] or r["err"])[-800:] if r["code"] else None)
    if "lint" not in skip and "lint" in scripts:
        r = run(pm_run(root, "lint"), cwd=root, timeout=900)
        row("lint", r["code"] == 0, "lint clean" if r["code"] == 0 else "lint reported problems", blocking=False, evidence=(r["out"] or r["err"])[-600:] if r["code"] else None)
    built = False
    if "build" not in skip and "build" in scripts:
        r = run(pm_run(root, "build"), cwd=root, timeout=1800)
        built = r["code"] == 0
        row("build", r["code"] == 0, "production build ok" if r["code"] == 0 else "build failed", evidence=(r["err"] or r["out"])[-1200:] if r["code"] else None)
        out_dirs = [root / d for d in (".next", "dist", "build", "out") if (root / d).is_dir()]
        stamped = []
        for d in out_dirs:
            for p in d.rglob("*"):
                if p.is_file() and "/dev/" not in str(p).replace("\\", "/") and p.suffix in (".js", ".html", ".json") and p.stat().st_size < 5_000_000:
                    try:
                        if 'data-dh="' in p.read_text(encoding="utf-8", errors="ignore"):
                            stamped.append(str(p.relative_to(root)))
                    except Exception:
                        pass
        row("prod-clean", not stamped, "no try-on stamp in the production output" if not stamped else f"{len(stamped)} built files carry dev stamps", evidence="\n".join(stamped[:10]) or None)
    sess = root / ".deckhand" / "tryon" / "sessions"
    open_ = [p.stem for p in sess.glob("*.json") if '"state": "open"' in p.read_text(encoding="utf-8")] if sess.exists() else []
    staged = list(root.glob("**/dh-tryon/*"))
    row("tryon-closed", not open_ and not [s for s in staged if "node_modules" not in s.parts],
        "no open try-on session" if not open_ else f"open sessions: {', '.join(open_)} (keep or discard)")
    hooked = tryon_hooked(root)
    row("tryon-unwired", not hooked, "the build config does not load try-on" if not hooked else
        f"{', '.join(hooked)} loads try-on from .deckhand/ (gitignored): a deploy from git fails — `tryon clean` before release")
    leaked = []
    tracked_env = []
    for p in git_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if re.search(r"(^|/)\.env($|\.local$|\.production$)", rel):
            tracked_env.append(rel)
        if not p.is_file() or not is_text(p) or rel.startswith(".deckhand/tryon/"):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if SECRET_RX.search(line):
                    leaked.append(f"{rel}:{i}")
        except Exception:
            pass
    gi = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else ""
    env_committed = [e for e in tracked_env if run(["git", "ls-files", "--error-unmatch", e], cwd=root)["code"] == 0]
    row("secrets", not leaked and not env_committed,
        "no credential-shaped value in the repo" if not leaked and not env_committed else f"{len(leaked)} secret-shaped values, {len(env_committed)} committed .env files",
        evidence="\n".join(leaked[:10] + env_committed) or None)
    if ".env" not in gi:
        row("env-ignored", False, ".env is not in .gitignore", blocking=True)
    # deckhand's own run logs hold command output: they must never reach the owner's git history
    if (root / ".git").exists():
        loose = [show for probe, show in RUNTIME_STATE.items() if run(["git", "check-ignore", "-q", probe], cwd=root)["code"] == 1]
        row("logs-ignored", not loose, "deckhand's run logs and local state are gitignored" if not loose
            else f"not gitignored (command output, notes, project vault): {', '.join(loose)} — any dh command adds the block (then commit .gitignore)",
            blocking=True)
    from . import swap as SWAP
    sw = SWAP.check(root)
    if sw.get("rows"):
        row("swaps", sw["ok"], "every rented service replaced or kept by decision" if sw["ok"] else "vendor SDKs still present",
            evidence="\n".join(f"{r['vendor']}: {r['detail']}" for r in sw["rows"] if not r["ok"]) or None)
    brief = read_json(root / ".deckhand" / "brief.json", {}) or {}
    if brief.get("deliverable") == "product" and "product-kit" not in skip:
        kit = product_kit(root, scripts)
        row("product-kit", not kit, "the buyer's kit is complete (README, LICENSE, CUSTOMIZE, seed + reset scripts)" if not kit
            else "missing for the buyer: " + "; ".join(kit), evidence="\n".join(kit) or None)
    b = BRAND.check(root, allow=allow)
    row("honesty", b["ok"], f"{b['blocking']} blocking findings, {b['warnings']} warnings (template names, demo content, fake logos, placeholders)",
        evidence="\n".join(f"{f['severity']} {f['file']}:{f['line']} {f['kind']}: {f['text']}" for f in b["findings"][:15]) or None)
    # routes are proved on what ships: the production build, served here on a free port and stopped after.
    # An explicit --url wins; the dev server is the fallback when there is no build or start script.
    prod, base, where = None, url, "the given URL"
    if not base and built and "start" in scripts and "routes" not in skip:
        log = root / ".deckhand" / "verify-serve.log"
        prod, purl, pst = BUILD.serve(root, "start", BUILD._free_port(4100), log, wait=120, keep_pinned=False)   # bind-tested, never a reserved range
        if pst and pst < 500:
            base, where = purl, f"the production build, {purl}"
        else:
            row("prod-serve", False, "the production build did not start (`start` script)",
                evidence=log.read_text(encoding="utf-8", errors="replace")[-800:] or None)
    if not base:
        base, where = (read_json(root / ".deckhand" / "dev.json", {}) or {}).get("url"), "the dev server"
    try:
        if base and "routes" not in skip:
            base = base.rstrip("/")
            sm = read_json(root / ".deckhand" / "sitemap.json", {}) or {}
            routes = {p["route"] for p in sm.get("pages", []) if "[" not in p.get("route", "[") and (p.get("auth") or "public") == "public"}
            st, html = _get(base + "/")
            parser = _Links()
            try:
                parser.feed(html)
            except Exception:
                pass
            routes |= parser.links | {"/"}
            bad = []
            for r_ in sorted(routes)[:80]:
                code, _ = _get(base + r_)
                if not code or code >= 400:
                    bad.append(f"{r_} -> {code}")
            row("routes", not bad, (f"{len(routes)} routes answer" if not bad else f"{len(bad)} of {len(routes)} routes fail") + f" (on {where})",
                evidence="\n".join(bad[:20]) or None)
            if "seo" not in skip:
                from . import seo as SEO
                s_ = SEO.audit(root, url=base)
                row("seo", not s_["blockers"], f"SEO {s_['score']}/100 on {where} — {len(s_['blockers'])} launch-breakers, "
                    f"{len([x for x in s_['findings'] if x['severity'] == 'high'])} high · {len(s_['owner'])} owner items in PENDING.md (.deckhand/SEO.md)",
                    evidence="\n".join(f"{x['rule']} {x['where']}: {x['title']} {x['detail']}".strip() for x in (s_["blockers"] or s_["findings"])[:10]) or None)
            if "slop" not in skip:
                from . import slop as SLOP
                sr = SLOP.summarize(SLOP.url_units(base, paths=sorted(routes)[:30], root=root))
                row("copy-slop", sr["verdict"] != "slop", f"rendered copy on {where}: {sr['by_verdict']['slop']} pages read as AI slop, "
                    f"{sr['by_verdict']['review']} to review, {sr['by_verdict']['clean']} clean (dh slop check --url)", blocking=False,
                    evidence="\n".join(f"{u['where']} {u['verdict']} {u['score']}/100: " + ", ".join(h["match"] for h in u["hits"][:5]) for u in sr["worst"][:8]) or None)
        else:
            row("routes", False, "not checked: no build to serve and no running URL (dh dev start, or --url)", blocking=False)
    finally:
        if prod:
            try:
                BUILD.kill_tree(prod.pid)
                prod.wait(timeout=15)
            except Exception:  # noqa: BLE001
                pass
    a11y = []
    for p in git_files(root):
        if p.suffix in (".tsx", ".jsx") and "node_modules" not in p.parts:
            t = p.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"<(img|Image)\b(?![^>]*\balt=)[^>]*>", t):
                a11y.append(f"{p.relative_to(root)}: <{m.group(1)}> without alt")
    layout = next((p for p in (root / "app" / "layout.tsx", root / "src" / "app" / "layout.tsx") if p.exists()), None)
    if layout and not re.search(r"<html[^>]*\blang=", layout.read_text(encoding="utf-8")):
        a11y.append(f"{layout.relative_to(root)}: <html> without lang")
    row("a11y-basics", not a11y, "alt text + html lang present" if not a11y else f"{len(a11y)} issues", blocking=False, evidence="\n".join(a11y[:10]) or None)
    if "audit" not in skip and (root / "package-lock.json").exists():
        r = run(["npm", "audit", "--audit-level=high", "--json"], cwd=root, timeout=300)
        m = re.search(r'"high"\s*:\s*(\d+).*?"critical"\s*:\s*(\d+)', r["out"], re.S)
        hi = (int(m.group(1)) + int(m.group(2))) if m else 0
        row("deps-audit", hi == 0, f"{hi} high/critical advisories" if hi else "no high/critical advisories", blocking=False)
    ok = all(r["ok"] for r in rows if r["blocking"])
    head = run(["git", "rev-parse", "HEAD"], cwd=root)["out"].strip() if (root / ".git").exists() else ""
    report = {"ok": ok, "at": now(), **({"commit": head} if head else {}), "rows": rows}   # `dh resume --check`: still this code?
    write_json(root / ".deckhand" / "verify.json", report)
    md = ["# Verify report", "", f"{'PASS' if ok else 'FAIL'} — {now()}", "", "| check | result | detail |", "|---|---|---|"]
    for r in rows:
        md.append(f"| {r['check']} | {'ok' if r['ok'] else ('FAIL' if r['blocking'] else 'warn')} | {r['detail']} |")
    (root / ".deckhand" / "VERIFY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report
