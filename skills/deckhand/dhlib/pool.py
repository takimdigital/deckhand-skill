"""The boilerplate pool — query it, never read it whole.

Public rows: data/pool.json (+ data/pool/<slug>.json measured details). Personal rows:
~/.deckhand/pool.json (the owner's harvested bases, ranked first). Every row is MEASURED from the live
repository (`dh pool add owner/repo`: GitHub API + raw files, no clone, no code execution).
The ranking is a pure function of (brief, rows): same input, same order, reasons attached.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

from .util import DATA, DhError, home, now, read_json, write_json
from . import profile as PROFILE
from . import vet as VET

OK_LICENSES = set(json.loads((DATA / "licenses.json").read_text(encoding="utf-8"))["accepted"])  # one policy: data/licenses.json
OWNER_LICENSES = {"owner"}          # the owner's own harvested bases
SECURITY_RISKS = {"injected-payload"}   # a risk no score outweighs: the checkout itself runs someone else's code
# copyleft / source-available texts, checked before the permissive ones (a Commons Clause LICENSE also quotes MIT)
REFUSED_TEXTS = (("Commons-Clause", r"Commons Clause"), ("AGPL-3.0", r"GNU AFFERO"), ("LGPL-3.0", r"GNU LESSER"),
                 ("GPL-3.0", r"GNU GENERAL PUBLIC"), ("SSPL-1.0", r"Server Side Public License"), ("BUSL-1.1", r"Business Source License"),
                 ("Elastic-2.0", r"Elastic License"), ("PolyForm", r"PolyForm"))
FEATURE_WORDS = ["accounts", "payments", "billing", "admin", "i18n", "jobs", "search", "notifications", "uploads", "booking",
                 "blog", "docs", "dashboard", "teams", "api", "email", "analytics", "cms", "ecommerce", "marketplace"]
VENDOR_PKGS = {
    "@clerk/nextjs": "clerk", "@clerk/clerk-react": "clerk", "@neondatabase/serverless": "neon", "resend": "resend",
    "@sentry/nextjs": "sentry", "@vercel/analytics": "vercel-analytics", "@vercel/blob": "vercel-blob", "@vercel/postgres": "vercel-postgres",
    "@upstash/redis": "upstash", "@supabase/supabase-js": "supabase", "firebase": "firebase", "@aws-sdk/client-s3": "aws-s3",
    "stripe": "stripe", "@lemonsqueezy/lemonsqueezy.js": "lemonsqueezy", "posthog-js": "posthog", "@planetscale/database": "planetscale",
    "uploadthing": "uploadthing", "@auth0/nextjs-auth0": "auth0", "openai": "openai", "@anthropic-ai/sdk": "anthropic", "plausible-tracker": "plausible",
}


def personal_path() -> Path:
    return home() / "pool.json"


def rows(include_personal: bool = True) -> list:
    pub = (read_json(DATA / "pool.json", {}) or {}).get("templates", [])
    mine = (read_json(personal_path(), {}) or {}).get("templates", []) if include_personal else []
    return [{**r, "source": "mine"} for r in mine] + [{**r, "source": r.get("source", "public")} for r in pub]


def _days_since(date: str):
    try:
        return (time.time() - time.mktime(time.strptime(date[:10], "%Y-%m-%d"))) / 86400
    except Exception:
        return None


def score(row: dict, brief: dict) -> tuple:
    reasons, blockers = [], []
    if row.get("license") not in OK_LICENSES and not (row.get("source") == "mine" and row.get("license") in OWNER_LICENSES):
        blockers.append(f"licence {row.get('license')} (permissive licences only: {', '.join(sorted(OK_LICENSES))})")
    if row.get("archived"):
        blockers.append("archived upstream")
    bad = sorted(SECURITY_RISKS & set(row.get("risks") or []))
    if bad:
        blockers.append(f"security: {', '.join(bad)} (see data/pool/{row.get('name')}.json)")
    lane = brief.get("lane") or "web"
    if (row.get("lane") or "web") != lane:
        blockers.append(f"lane {row.get('lane')} (asked {lane})")
    s = 0
    shape = brief.get("shape")
    if shape and row.get("shape") == shape:
        s += 40
        reasons.append(f"+40 shape {shape}")
    want = set(brief.get("features") or [])
    have = set(row.get("features") or [])
    hit = sorted(want & have)
    if hit:
        pts = min(30, 10 * len(hit))
        s += pts
        reasons.append(f"+{pts} features {', '.join(hit)}")
    miss = sorted(want - have)
    if miss:
        reasons.append("not in template: " + ", ".join(miss))
    langs = [l for l in brief.get("languages") or [] if l != "en"]
    st = row.get("stack") or {}
    if langs:
        if st.get("i18n"):
            s += 6
            reasons.append("+6 i18n ready")
        if set(langs) & {"ar", "he", "fa", "ur"} and st.get("rtl"):
            s += 6
            reasons.append("+6 RTL")
    if row.get("canonical") or (st.get("framework") == "next" and st.get("db") == "postgres"):
        s += 15
        reasons.append("+15 canonical stack (Next.js + Postgres)")
    stars = row.get("stars") or 0
    if stars >= 1000:
        s += 5
        reasons.append(f"+5 {stars}★")
    elif stars < 10 and row.get("source") != "mine":
        s -= 10
        reasons.append(f"-10 unproven ({stars}★)")
    vend = row.get("vendors") or []
    if vend:
        pen = min(10, 2 * len(vend))
        s -= pen
        reasons.append(f"-{pen} swap cost: {', '.join(vend)}")
    burden = {"heavy": 10, "medium": 5}.get(row.get("swap_burden") or "", 0)
    if burden:
        s -= burden
        reasons.append(f"-{burden} {row.get('swap_burden')} swap burden")
    age = _days_since(row.get("pushed_at") or "")
    if age and age > 365:
        s -= 20
        reasons.append("-20 stale (>1y since last push)")
    if row.get("source") == "mine":
        s += 50
        reasons.append("+50 your own proven base")
    return s, reasons, blockers


def query(brief: dict, top: int = 3) -> dict:
    out, blocked = [], []
    for r in rows():
        s, reasons, blockers = score(r, brief)
        item = {"name": r["name"], "repo": r.get("repo") or r.get("path"), "source": r["source"], "score": s,
                "stack": r.get("stack"), "stars": r.get("stars"), "license": r.get("license"), "reasons": reasons,
                "weak_for": r.get("weak_for")}
        (blocked if blockers else out).append({**item, **({"blockers": blockers} if blockers else {})})
    out.sort(key=lambda x: (-x["score"], x["name"]))
    return {"brief": {k: brief.get(k) for k in ("shape", "features", "languages", "lane")}, "top": out[:top],
            "considered": len(out), "blocked": len(blocked), "gap": not out or out[0]["score"] <= 0}


def show(name: str) -> dict:
    r = next((x for x in rows() if x["name"] == name), None)
    if not r:
        raise DhError("NO_SUCH_TEMPLATE", name)
    if r.get("details"):
        r = {**r, "details_data": read_json(DATA / r["details"])}
    return r


# ------------------------------------------------------------------ measuring (remote only)
def _gh(url: str):
    tok = PROFILE.secret("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "deckhand-pool/2"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _raw(repo: str, branch: str, path: str):
    try:
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def detect_stack(pkg: dict, tree: list) -> dict:
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    has = lambda *n: any(x in deps for x in n)  # noqa: E731
    paths = set(tree)
    fw = "next" if has("next") else "remix" if has("@remix-run/react", "@react-router/dev") else "astro" if has("astro") else \
        "sveltekit" if has("@sveltejs/kit") else "nuxt" if has("nuxt") else "vite" if has("vite") else "wasp" if any(p.endswith(".wasp") for p in paths) else "unknown"
    db = "postgres" if has("pg", "postgres", "@neondatabase/serverless", "@vercel/postgres") or any("postgres" in p for p in paths) else \
        "sqlite" if has("better-sqlite3", "@libsql/client") else "mysql" if has("mysql2") else "mongodb" if has("mongoose", "mongodb") else None
    orm = "prisma" if has("prisma", "@prisma/client") else "drizzle" if has("drizzle-orm") else "kysely" if has("kysely") else None
    auth = "better-auth" if has("better-auth") else "clerk" if has("@clerk/nextjs") else "next-auth" if has("next-auth", "@auth/core") else \
        "lucia" if has("lucia") else "supabase" if has("@supabase/supabase-js") else None
    ui = [u for u, d in (("shadcn", "class-variance-authority"), ("tailwind", "tailwindcss"), ("mui", "@mui/material"), ("chakra", "@chakra-ui/react")) if d in deps]
    i18n = "next-intl" if has("next-intl") else "i18next" if has("i18next", "react-i18next") else None
    return {"framework": fw, "db": db, "orm": orm, "auth": auth, "ui": ui, "i18n": i18n,
            "docker": any(p.endswith("Dockerfile") or p.endswith("docker-compose.yml") or p.endswith("compose.yml") for p in paths),
            "package_manager": "pnpm" if "pnpm-lock.yaml" in paths else "bun" if ("bun.lockb" in paths or "bun.lock" in paths) else "yarn" if "yarn.lock" in paths else "npm",
            "lang": "typescript" if "tsconfig.json" in paths else "javascript"}


def detect_features(pkg: dict, tree: list, text: str) -> list:
    deps = " ".join({**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}.keys())
    blob = (deps + " " + " ".join(tree) + " " + text).lower()
    rules = {"accounts": r"(auth|login|sign-?in|clerk|lucia)", "payments": r"(stripe|lemonsqueezy|paddle|checkout)",
             "billing": r"(billing|subscription)", "admin": r"(/admin|admin/)", "i18n": r"(next-intl|i18next|/locales?/|messages/)",
             "jobs": r"(bullmq|inngest|trigger\.dev|cron|queue)", "search": r"(meilisearch|algolia|typesense|search)",
             "notifications": r"(notification|novu|web-push)", "uploads": r"(upload|s3|r2|minio)", "blog": r"(/blog|contentlayer|mdx)",
             "docs": r"(/docs|fumadocs|nextra)", "dashboard": r"(dashboard)", "teams": r"(team|organization|workspace)",
             "email": r"(resend|nodemailer|react-email|@react-email)", "analytics": r"(posthog|plausible|umami|analytics)"}
    return sorted(k for k, rx in rules.items() if re.search(rx, blob))


def measure(repo: str) -> dict:
    repo = re.sub(r"^https?://github\.com/", "", repo.strip()).strip("/").removesuffix(".git")
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise DhError("BAD_REPO", "expected owner/name or a github.com URL")
    meta = _gh(f"https://api.github.com/repos/{repo}")
    lic = (meta.get("license") or {}).get("spdx_id")
    branch = meta.get("default_branch") or "main"
    tree = [t["path"] for t in _gh(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1").get("tree", []) if t.get("type") == "blob"][:20000]
    pkg_text = _raw(repo, branch, "package.json")
    try:
        pkg = json.loads(pkg_text or "{}")
    except ValueError:
        pkg = {}
    readme = (_raw(repo, branch, "README.md") or "")[:20000]
    head = _gh(f"https://api.github.com/repos/{repo}/commits/{branch}")
    stack = detect_stack(pkg, tree)
    text = (meta.get("description") or "") + " " + " ".join(meta.get("topics") or []) + " " + readme
    shape = None
    for s, rx in (("marketplace", r"marketplace|two-sided|listings"), ("booking", r"booking|appointment|reservation|calendar"),
                  ("catalogue", r"e-?commerce|store|shop|catalog"), ("saas", r"saas|subscription|boilerplate|starter"),
                  ("leadgen", r"landing page|marketing site|portfolio|agency"), ("internal", r"admin dashboard|internal tool|crm")):
        if re.search(rx, text, re.I):
            shape = s
            break
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    vendors = sorted({v for k, v in VENDOR_PKGS.items() if k in deps} - {"stripe"})
    return {
        "name": repo.split("/")[1].lower(), "repo": repo, "url": f"https://github.com/{repo}", "license": lic,
        "stars": meta.get("stargazers_count"), "pushed_at": (meta.get("pushed_at") or "")[:10], "archived": bool(meta.get("archived")),
        "branch": branch, "commit": head.get("sha"), "lane": "mobile" if stack["framework"] == "unknown" and "expo" in deps else "web",
        "shape": shape, "stack": stack, "canonical": stack["framework"] == "next" and stack["db"] == "postgres",
        "features": detect_features(pkg, tree, text), "locales": [], "vendors": vendors,
        "swap_burden": "none" if not vendors else "light" if len(vendors) <= 2 else "medium" if len(vendors) <= 4 else "heavy",
        "risks": [r for r, c in (("no-tests", not any(re.search(r"(vitest|jest|playwright)", k) for k in deps)),
                                  ("no-docker", not stack["docker"])) if c],
        "measured": "github-api", "measured_at": now(),
        "evidence": VET.evidence(pkg, tree, readme, bool(pkg_text)),
    }


def vet(repo: str, mine: bool = False) -> dict:
    """Measure + judge, write nothing (`dh pool vet`)."""
    row = measure(repo)
    return {"row": {k: v for k, v in row.items() if k != "evidence"}, **VET.verdict(row, mine=mine)}


def add(repo: str, mine: bool = False, shape: str | None = None, features: list | None = None, row: dict | None = None) -> dict:
    row = row or measure(repo)
    if shape:
        row["shape"] = shape
        row["shape_source"] = "owner"
    if features:
        row["features"] = sorted(set(row["features"]) | set(features))
    v = VET.verdict(row, mine=mine)
    if v["verdict"] != "accepted":
        raise DhError("REFUSED", f"{row.get('repo')} does not meet the pool criteria: " + "; ".join(f["detail"] for f in v["fails"]),
                      fails=v["fails"], warnings=v["warnings"], acceptable=v["acceptable"])
    row = {k: val for k, val in row.items() if k != "evidence"}
    row["vetted"] = {"at": now(), "warnings": [w["id"] for w in v["warnings"]]}
    target = personal_path() if mine else DATA / "pool.json"
    doc = read_json(target, {"version": 2, "templates": []}) or {"version": 2, "templates": []}
    doc["templates"] = [r for r in doc.get("templates", []) if r.get("repo") != row["repo"]] + [row]
    doc["count"] = len(doc["templates"])
    write_json(target, doc)
    return {"added": True, "to": str(target), "row": row, "verdict": "accepted", "warnings": v["warnings"]}


def add_local(path: Path, meta: dict) -> dict:
    """Register a harvested base (a folder or a private repo) in the personal pool."""
    doc = read_json(personal_path(), {"version": 2, "templates": []}) or {"version": 2, "templates": []}
    doc["templates"] = [r for r in doc.get("templates", []) if r.get("name") != meta["name"]] + [meta]
    doc["count"] = len(doc["templates"])
    write_json(personal_path(), doc)
    return {"registered": meta["name"], "pool": str(personal_path())}


def measure_local(path: Path) -> dict:
    """The owner's own project folder, measured on disk (D13: their real 'mine' sources were local folders).
    Their own code: licence 'owner' unless a LICENSE file says otherwise; never leaves the machine."""
    path = Path(path).resolve()
    if not path.is_dir():
        raise DhError("NO_SUCH_PATH", str(path))
    pkg = read_json(path / "package.json", {}) or {}
    from .util import git_files
    tree = [str(f.relative_to(path)).replace("\\", "/") for f in git_files(path)][:20000]
    readme = ""
    for n in ("README.md", "readme.md", "README"):
        if (path / n).exists():
            readme = (path / n).read_text(encoding="utf-8", errors="replace")[:20000]
            break
    lic = "owner"
    lf = next((f for f in path.iterdir() if f.name.upper().startswith(("LICENSE", "LICENCE"))), None)
    if lf:
        head = lf.read_text(encoding="utf-8", errors="replace")[:4000]
        lic = next((spdx for spdx, rx in REFUSED_TEXTS + (("MIT", r"MIT License|Permission is hereby granted, free of charge"), ("Apache-2.0", r"Apache License"),
                                         ("ISC", r"ISC License"), ("BSD-3-Clause", r"BSD 3-Clause|Redistribution and use")) if re.search(rx, head, re.I)), "owner")
    stack = detect_stack(pkg, tree)
    text = (pkg.get("description") or "") + " " + readme
    return {"name": re.sub(r"[^a-z0-9-]+", "-", path.name.lower()).strip("-"), "path": str(path), "source": "mine", "license": lic,
            "lane": "web", "shape": None, "stack": stack, "canonical": stack["framework"] == "next" and stack["db"] == "postgres",
            "features": detect_features(pkg, tree, text), "vendors": sorted({v for k, v in VENDOR_PKGS.items() if k in {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}} - {"stripe"}),
            "description": (pkg.get("description") or (readme.strip().splitlines()[0] if readme.strip() else ""))[:200],
            "stars": None, "pushed_at": now()[:10], "measured": "local", "measured_at": now()}

