"""VET: nothing enters the pool on trust — every base is measured, then judged against written criteria.

A found repo (by the owner, by the agent, by anyone) goes through `dh pool vet owner/repo` (report only) or
`dh pool add owner/repo` (report, then added only if accepted). The verdict is a pure function of the
measured evidence: same repo state -> same verdict, with every reason written out, and — when refused —
what WOULD be accepted, so the owner knows what to look for instead.

Hard criteria (any fail = refused):
  licence      a permissive licence (data/licenses.json: MIT, Apache-2.0, BSD-2/3, ISC, 0BSD, Unlicense)
  consistent   package.json "license" does not contradict it (UNLICENSED, "SEE LICENSE IN", a copyleft id)
  alive        not archived; pushed within the last 3 years
  runnable     a web app: package.json with a build script and a dev or start script, a known framework
  clean        no committed secrets (.env, keys, service-account files)
  free         no paid/private packages (Tailwind Plus, MUI X Pro, AG Grid Enterprise, Font Awesome Pro …)
Soft criteria (warnings, and ranking penalties in `dh pool query`):
  paid tier mentioned in the README · stale (>1 year) · few stars · huge monorepo · rented services to swap ·
  an old Node engine · a framework try-on cannot use (Astro/Svelte/Nuxt)
"""
from __future__ import annotations

import json
import re
import time

from .util import DATA, SECRET_FILE_RX

POLICY = json.loads((DATA / "licenses.json").read_text(encoding="utf-8"))
ACCEPTED = POLICY["accepted"]
REFUSED = POLICY["refused"]
TRYON_FRAMEWORKS = {"next", "vite", "remix"}
WEB_FRAMEWORKS = TRYON_FRAMEWORKS | {"astro", "sveltekit", "nuxt"}


def acceptable_text() -> str:
    return ("Accepted: a permissive licence (" + ", ".join(ACCEPTED) + ") · a runnable web app (package.json with build + dev/start, "
            "Next.js / Vite / Remix preferred) · not archived, pushed within 3 years · no committed secrets · no paid or private packages.")


def _days(date: str):
    try:
        return (time.time() - time.mktime(time.strptime(date[:10], "%Y-%m-%d"))) / 86400
    except Exception:
        return None


def _refused_expr(expr: str) -> bool:
    """An SPDX expression naming a refused licence anywhere: AGPL-3.0-only, GPL-3.0-or-later, (MIT AND Commons-Clause)."""
    if "COMMONS" in expr.upper():
        return True
    for tok in re.findall(r"[A-Za-z0-9.+-]+", expr):
        base = re.sub(r"(-only|-or-later|\+)$", "", tok, flags=re.I)
        if base in REFUSED and base not in ("NONE", "OTHER", "NOASSERTION"):
            return True
    return False


def verdict(row: dict, mine: bool = False) -> dict:
    """row = pool.measure() output (with its `evidence`). Pure: no network, no clock besides `now` for age."""
    ev = row.get("evidence") or {}
    fails, warns, passes = [], [], []

    def check(ok, cid, good, bad, hard=True):
        (passes if ok else (fails if hard else warns)).append({"id": cid, "detail": good if ok else bad})

    lic = row.get("license") or "NONE"
    check(lic in ACCEPTED, "licence", f"{lic} — {ACCEPTED.get(lic, '')}",
          f"{lic}: {REFUSED.get(lic, REFUSED['OTHER'])}")
    pl = str(ev.get("package_license") or "")
    contra = pl and (any(pl.upper().startswith(x) for x in POLICY["package_license_refused"]) or pl in REFUSED or _refused_expr(pl))
    check(not contra, "consistent", "package.json licence agrees" if pl else "package.json has no licence field (the repo licence applies)",
          f"package.json says \"{pl}\" — it contradicts the repo licence; the stricter one wins")
    check(not row.get("archived"), "alive", "maintained (not archived)", "archived upstream — no fixes will ever come")
    age = _days(row.get("pushed_at") or "")
    if age is not None:
        check(age <= 3 * 365, "alive", f"last push {int(age)} days ago", f"last push {int(age / 365)} years ago — dependencies have rotted", hard=True)
        if 365 < age <= 3 * 365:
            warns.append({"id": "stale", "detail": f"last push {int(age)} days ago — expect upgrades"})
    fw = (row.get("stack") or {}).get("framework") or "unknown"
    scripts = ev.get("scripts") or {}
    runnable = fw in WEB_FRAMEWORKS and "build" in scripts and ("dev" in scripts or "start" in scripts)
    check(runnable, "runnable", f"{fw} app with build + {'dev' if 'dev' in scripts else 'start'} scripts",
          "not a runnable web app here: " + ("no package.json" if not ev.get("has_package") else
                                              f"framework {fw}" if fw not in WEB_FRAMEWORKS else "missing build or dev/start script")
          + " (a monorepo? point at the app, or add the app folder yourself)")
    if runnable and fw not in TRYON_FRAMEWORKS:
        warns.append({"id": "tryon", "detail": f"{fw}: fine to deploy, but try-on/compose work on React (Next.js / Vite / Remix) only"})
    secrets = ev.get("secret_files") or []
    check(not secrets, "clean", "no committed secrets", "committed secret files: " + ", ".join(secrets[:5]) + " — a base must never ship credentials")
    paid = ev.get("paid_packages") or []
    check(not paid, "free", "no paid or private packages", "needs paid/private packages: " + ", ".join(paid[:5]))
    for g in (ev.get("git_deps") or [])[:3]:
        warns.append({"id": "git-dependency", "detail": f"{g} installs from git — check it is public and licensed"})
    if ev.get("paywall_hits"):
        warns.append({"id": "paid-tier", "detail": "README mentions a paid tier (" + ", ".join(ev["paywall_hits"][:3]) + ") — check the free part is complete"})
    stars = row.get("stars") or 0
    if stars < 5 and not mine:
        warns.append({"id": "traction", "detail": f"{stars}★ — unproven; measure it on a test run before building on it"})
    if (ev.get("file_count") or 0) > 15000:
        warns.append({"id": "size", "detail": f"{ev['file_count']} files — a large monorepo; clone and boot will be slow"})
    if row.get("vendors"):
        warns.append({"id": "rented-services", "detail": "to swap for owned ones: " + ", ".join(row["vendors"]) + f" ({row.get('swap_burden')})"})
    node = ev.get("node_engine")
    m = re.search(r"(\d+)", str(node or ""))
    if m and int(m.group(1)) < 18:
        warns.append({"id": "node", "detail": f"engines.node {node} — below Node 18"})
    ok = not fails
    return {"repo": row.get("repo"), "verdict": "accepted" if ok else "refused", "fails": fails, "warnings": warns, "passes": passes,
            **({} if ok else {"acceptable": acceptable_text()})}


def evidence(pkg: dict, tree: list, readme: str, has_package: bool) -> dict:
    """What verdict() needs, extracted from the files pool.measure() already downloads."""
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    lic = pkg.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    return {
        "has_package": has_package, "package_license": lic, "scripts": {k: True for k in (pkg.get("scripts") or {})},
        "node_engine": (pkg.get("engines") or {}).get("node"), "file_count": len(tree),
        "secret_files": sorted(p for p in tree if SECRET_FILE_RX.search(p) and not re.search(r"\.(example|sample|template)$", p))[:10],
        "paid_packages": sorted(d for d in deps if any(d == p or d.startswith(p) for p in POLICY["paid_packages"])),
        "git_deps": sorted(d for d, v in deps.items() if re.match(r"^(git\+|git:|github:|ssh:|https?://)", str(v))),
        "paywall_hits": sorted(set(m.group(0).lower() for m in re.finditer(POLICY["paywall_text"], readme or "", re.I)))[:5],
    }
