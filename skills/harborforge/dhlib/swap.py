"""SWAP: rented services out, owned ones in — proved by absence (the SDK) and presence (the target).

scan  -> .deckhand/swap-map.json: every vendor SDK found (package.json + imports) with its target.
check -> exit 1 while a vendor SDK is still imported/installed, or a target is missing.
Payment processors are KEPT by default (a processor is a service, not a code lock-in).
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import git_files, now, package_json, read_json, write_json

TARGETS = {
    "clerk": ("auth", ["@clerk/"], "better-auth", ["better-auth"]),
    "auth0": ("auth", ["@auth0/"], "better-auth", ["better-auth"]),
    "supabase": ("db+auth", ["@supabase/"], "postgres + better-auth", ["pg", "postgres", "drizzle-orm", "@prisma/client", "better-auth"]),
    "neon": ("db", ["@neondatabase/"], "postgres (container)", ["pg", "postgres", "drizzle-orm", "@prisma/client"]),
    "planetscale": ("db", ["@planetscale/"], "postgres (container)", ["pg", "postgres", "drizzle-orm", "@prisma/client"]),
    "vercel-postgres": ("db", ["@vercel/postgres"], "postgres (container)", ["pg", "postgres", "drizzle-orm", "@prisma/client"]),
    "upstash": ("cache/queue", ["@upstash/"], "redis (container) or none", ["ioredis", "redis", "bullmq"]),
    "resend": ("email", ["resend"], "SMTP / failover mail router", ["nodemailer"]),
    "sendgrid": ("email", ["@sendgrid/"], "SMTP / failover mail router", ["nodemailer"]),
    "postmark": ("email", ["postmark"], "SMTP / failover mail router", ["nodemailer"]),
    "aws-s3": ("storage", ["@aws-sdk/client-s3"], "RustFS/MinIO (S3-compatible, keep the SDK pointed at it)", ["@aws-sdk/client-s3"]),
    "uploadthing": ("storage", ["uploadthing", "@uploadthing/"], "S3-compatible storage on the VPS", ["@aws-sdk/client-s3", "minio"]),
    "vercel-blob": ("storage", ["@vercel/blob"], "S3-compatible storage on the VPS", ["@aws-sdk/client-s3", "minio"]),
    "sentry": ("errors", ["@sentry/"], "none (logs) or GlitchTip", []),
    "posthog": ("analytics", ["posthog-js", "posthog-node"], "Umami (self-hosted) or none", []),
    "vercel-analytics": ("analytics", ["@vercel/analytics", "@vercel/speed-insights"], "Umami or none", []),
    "plausible": ("analytics", ["plausible-tracker", "next-plausible"], "Umami or none", []),
    "algolia": ("search", ["algoliasearch", "react-instantsearch"], "Meilisearch (container)", ["meilisearch"]),
    "pusher": ("realtime", ["pusher", "pusher-js"], "SSE or socket.io", ["socket.io", "eventsource"]),
    "firebase": ("backend", ["firebase", "firebase-admin"], "postgres + better-auth", ["better-auth"]),
}
KEEP = {"stripe": "payments — kept (processor)", "@lemonsqueezy/lemonsqueezy.js": "payments — kept", "@paddle/": "payments — kept"}


def _deps(root: Path) -> dict:
    pkg = package_json(root)
    return {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}


def _usages(root: Path, prefixes: list) -> list:
    hits = []
    rx = re.compile(r"""(from\s+|require\(\s*|import\(\s*)['"](%s)""" % "|".join(re.escape(p) for p in prefixes))
    for p in git_files(root):
        if p.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs") or "node_modules" in p.parts:
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(root)}:{i}")
        except Exception:
            pass
    return hits


def scan(root: Path) -> dict:
    root = Path(root)
    deps = _deps(root)
    entries = []
    for vendor, (cat, prefixes, target, tpats) in TARGETS.items():
        pk = [d for d in deps if any(d == p or d.startswith(p) for p in prefixes)]
        uses = _usages(root, prefixes)
        if pk or uses:
            entries.append({"vendor": vendor, "category": cat, "packages": pk, "usages": uses[:30], "target": target,
                            "target_patterns": tpats, "status": "todo"})
    kept = [{"package": d, "why": w} for d in deps for k, w in KEEP.items() if d == k or d.startswith(k)]
    prev = read_json(root / ".deckhand" / "swap-map.json", {}) or {}
    done = {e["vendor"]: e for e in prev.get("entries", []) if e.get("status") in ("done", "kept", "removed")}
    entries = [{**e, **({"status": done[e["vendor"]]["status"]} if e["vendor"] in done else {})} for e in entries]
    doc = {"at": now(), "entries": entries, "kept": kept}
    write_json(root / ".deckhand" / "swap-map.json", doc)
    return {"vendors": [e["vendor"] for e in entries], "kept": kept, "map": ".deckhand/swap-map.json",
            "next": "replace one vendor at a time (references/30-build.md §swap), then dh swap check"}


def check(root: Path) -> dict:
    root = Path(root)
    doc = read_json(root / ".deckhand" / "swap-map.json", None, expect=dict)
    if doc is None:
        return {"ok": True, "rows": [], "note": "no swap map (dh swap scan) — nothing to prove"}
    deps = _deps(root)
    rows = []
    for e in doc.get("entries", []):
        if e.get("status") == "kept":
            rows.append({"vendor": e["vendor"], "ok": True, "detail": "kept by decision: " + e.get("why", "")})
            continue
        prefixes = TARGETS.get(e["vendor"], (None, e.get("packages", [])))[1]
        left_pkgs = [d for d in deps if any(d == p or d.startswith(p) for p in prefixes)]
        left_uses = _usages(root, prefixes)
        tp = e.get("target_patterns") or []
        target_ok = (not tp) or any(t in deps for t in tp)
        ok = not left_pkgs and not left_uses and target_ok
        rows.append({"vendor": e["vendor"], "ok": ok, "detail": "gone, target present" if ok else
                     f"still installed: {left_pkgs}; still imported: {left_uses[:5]}; target present: {target_ok}"})
    return {"ok": all(r["ok"] for r in rows), "rows": rows}
