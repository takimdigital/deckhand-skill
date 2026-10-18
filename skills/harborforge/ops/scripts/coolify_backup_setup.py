#!/usr/bin/env python3
"""coolify_backup_setup.py — Coolify S3 storages + DB backup schedules (ref 55 §0/§1). LIVE-VERIFIED.

Reads:  ~/.vps-ops/secrets/env.sh            (COOLIFY_TOKEN, COOLIFY_URL — single-quoted!)
        ~/.vps-ops/secrets/backup.env.sh     (Tigris key pair, optional TIGRIS_BUCKET)
        ~/.vps-ops/secrets/b2-scoped.env.sh  (B2 scoped key — run ops/scripts/b2_setup.py first)
Usage:  python3 coolify_backup_setup.py <db_uuid> [--schedules]
Exit: 0 = every storage/schedule leg succeeded · 1 = any leg failed — check it (live-hit 2026-09-21:
this script exited 0 no matter what).
"""
import json, os, re, sys, urllib.request, urllib.error

BASE = os.environ.get("COOLIFY_URL", "http://127.0.0.1:8000")   # tunnel it: ssh -N -L 8000:127.0.0.1:8000


def load(path):
    env = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"export (\w+)=['\"]?(.*?)['\"]?$", line.rstrip())
        if m:
            env[m.group(1)] = m.group(2)
    return env


E = load(os.path.expanduser("~/.vps-ops/secrets/env.sh"))
E.update(load(os.path.expanduser("~/.vps-ops/secrets/backup.env.sh")))
E.update(load(os.path.expanduser("~/.vps-ops/secrets/b2-scoped.env.sh")))
TOK = E["COOLIFY_TOKEN"]


def call(method, path, payload=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:400]}


def ensure_storage(name, endpoint, bucket, region, key, secret):
    existing = call("GET", "/api/v1/s3-storages")
    if isinstance(existing, list):
        for s in existing:
            if s.get("name") == name:
                print(f"storage exists: {name} ({s['uuid']})")
                return s["uuid"]
    r = call("POST", "/api/v1/s3-storages",
             {"name": name, "endpoint": endpoint, "bucket": bucket,
              "region": region, "key": key, "secret": secret})
    if "uuid" not in r:
        print(f"storage FAILED: {name}: {json.dumps(r)[:300]}")
        return None
    print(f"storage created: {name} ({r['uuid']})")
    return r["uuid"]


def main():
    db = sys.argv[1]
    ok = True
    b2_host = E.get("B2_HOST", "https://s3.us-east-005.backblazeb2.com")
    b2_region = E.get("B2_REGION", "us-east-005")
    b2 = ensure_storage("b2-backups", b2_host,
                        E["B2_BUCKET"], b2_region, E["B2_APP_KEY_ID"], E["B2_APP_KEY"])
    tg = ensure_storage("tigris-backups", "https://t3.storage.dev", E["TIGRIS_BUCKET"], "auto",
                        E["TIGRIS_ACCESS_KEY_ID"], E["TIGRIS_SECRET_ACCESS_KEY"])
    for label, uuid in (("B2", b2), ("Tigris", tg)):
        if not uuid:
            ok = False
            continue
        v = call("POST", f"/api/v1/s3-storages/{uuid}/validate")
        print(f"validate {label}: {json.dumps(v)[:200]}")
        if isinstance(v, dict) and "_http" in v:
            ok = False
    if "--schedules" not in sys.argv:
        print("SETUP OK" if ok else "SETUP FAILED — fix before trusting schedules")
        return 0 if ok else 1
    # one schedule PER target; backup_now:true proves the first dump immediately.
    # NOTE: the executions endpoint can stay empty for on-demand runs — LIST THE BUCKET for proof.
    for label, uuid, freq, now in (("B2", b2, "0 2 * * *", True), ("Tigris", tg, "15 2 * * *", True)):
        if not uuid:
            continue
        r = call("POST", f"/api/v1/databases/{db}/backups",
                 {"frequency": freq, "enabled": True, "save_s3": True,
                  "s3_storage_uuid": uuid, "backup_now": now,
                  "database_backup_retention_amount_s3": 3,
                  "missing_backup_notification_days": 2})
        print(f"schedule {label}: {json.dumps(r)[:250]}")
        if isinstance(r, dict) and "_http" in r:
            ok = False
    print("SETUP OK" if ok else "SETUP FAILED — fix before trusting schedules")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
