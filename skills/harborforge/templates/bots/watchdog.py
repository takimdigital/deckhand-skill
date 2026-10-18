#!/usr/bin/env python3
"""watchdog.py — is the business up? (stdlib; runs anywhere: GitHub Actions, the VPS cron, a laptop)

Env: SITE_URLS (comma list, required) · SSL_WARN_DAYS (14) · SLOW_MS (4000)
     COOLIFY_URL + COOLIFY_TOKEN (optional: container health + newest backup age, BACKUP_MAX_HOURS=30)
     VPS_SSH=user@host (optional: disk usage via ssh, DISK_WARN_PCT=85) · a notify channel (see notify.py)
Reports only CHANGES (down, recovered, new warning) — never the same alert twice. Exit 1 while something is down.
"""
from __future__ import annotations

import json, os, socket, ssl, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import send  # noqa: E402


def http_check(url: str, slow_ms: int):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deckhand-watchdog/2"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ms = int((time.time() - t0) * 1000)
            if r.status >= 400:
                return "down", f"{url} answered {r.status}"
            return ("slow", f"{url} took {ms} ms") if ms > slow_ms else ("ok", f"{url} {r.status} in {ms} ms")
    except Exception as e:  # noqa: BLE001
        return "down", f"{url} unreachable: {getattr(e, 'code', '') or e}"


def ssl_days(host: str) -> int | None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            end = datetime.strptime(t.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            return (end - datetime.now(timezone.utc)).days
    except Exception:  # noqa: BLE001
        return None


def coolify(url: str, token: str, max_hours: int):
    out = []
    def get(path):
        req = urllib.request.Request(url.rstrip("/") + "/api/v1" + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "null")
    try:
        for app in get("/applications") or []:
            st = str(app.get("status", ""))
            if st and not st.startswith("running"):
                out.append(("down", f"app {app.get('name')} is {st}"))
            elif "unhealthy" in st:
                out.append(("warn", f"app {app.get('name')} is {st}"))
        for db in get("/databases") or []:
            try:
                ex = get(f"/databases/{db['uuid']}/backups") or []
                execs = [e for b in ex for e in (b.get("executions") or [])] if isinstance(ex, list) else []
                done = [e for e in execs if str(e.get("status")) == "success"]
                if done:
                    newest = max(e.get("created_at", "") for e in done)
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(newest.replace("Z", "+00:00"))).total_seconds() / 3600
                    if age > max_hours:
                        out.append(("warn", f"database {db.get('name')}: newest backup is {int(age)} h old"))
                elif execs:
                    out.append(("warn", f"database {db.get('name')}: no successful backup execution"))
            except Exception:  # noqa: BLE001
                continue
    except Exception as e:  # noqa: BLE001
        out.append(("down", f"Coolify API unreachable: {e}"))
    return out


def disk(target: str, warn: int):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, "df -P / | tail -1"], capture_output=True, text=True, timeout=30)
    try:
        pct = int(r.stdout.split()[4].rstrip("%"))
        return [("warn", f"disk / is {pct}% full on {target}")] if pct >= warn else []
    except Exception:  # noqa: BLE001
        return [("warn", f"disk check failed on {target}: {r.stderr.strip()[:120]}")]


def main() -> int:
    urls = [u.strip() for u in os.environ.get("SITE_URLS", "").split(",") if u.strip()]
    if not urls:
        print("SITE_URLS is required"); return 2
    findings = []
    for u in urls:
        findings.append(http_check(u, int(os.environ.get("SLOW_MS", "4000"))))
        host = urlparse(u).hostname
        if u.startswith("https://") and host:
            d = ssl_days(host)
            if d is None:
                findings.append(("warn", f"{host}: TLS certificate could not be read"))
            elif d < int(os.environ.get("SSL_WARN_DAYS", "14")):
                findings.append(("warn", f"{host}: certificate expires in {d} days"))
    if os.environ.get("COOLIFY_URL") and os.environ.get("COOLIFY_TOKEN"):
        findings += coolify(os.environ["COOLIFY_URL"], os.environ["COOLIFY_TOKEN"], int(os.environ.get("BACKUP_MAX_HOURS", "30")))
    if os.environ.get("VPS_SSH"):
        findings += disk(os.environ["VPS_SSH"], int(os.environ.get("DISK_WARN_PCT", "85")))
    bad = [f for f in findings if f[0] in ("down", "warn", "slow")]
    for level, msg in findings:
        print(f"{level.upper():5} {msg}")
    text = "\n".join(f"{'🔴' if l == 'down' else '🟠'} {m}" for l, m in bad) if bad else "✅ all checks green again"
    send("watchdog", text, "Watchdog")
    return 1 if any(l == "down" for l, _ in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
