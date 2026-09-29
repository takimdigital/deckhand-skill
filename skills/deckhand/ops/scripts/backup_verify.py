#!/usr/bin/env python3
"""backup_verify.py — the honest proof for Coolify backups (ref 55 §3): LIST THE BUCKETS.

B2 via the Native API (scoped key), Tigris via S3 SigV4 ListObjectsV2 (region auto).
A "success" execution is a claim; the object is the proof (and the executions endpoint
itself can be empty for on-demand runs in v4.3.23).

Usage:  python3 backup_verify.py <db_uuid> <tigris_bucket> [--wait 150]
Reads the vault: ~/.vps-ops/secrets/{env.sh,backup.env.sh,b2-scoped.env.sh}
Exit: 0 = every leg produced evidence · 1 = a leg failed or came back empty (a green exit here is
earned by objects in the buckets, never by the script merely finishing — live-hit 2026-09-21).
"""
import base64, hashlib, hmac, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = os.environ.get("COOLIFY_URL", "http://127.0.0.1:8000")


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
        return {"_http": e.code, "_body": e.read().decode()[:300]}


def b2_list():
    try:
        a = urllib.request.Request("https://api.backblazeb2.com/b2api/v4/b2_authorize_account",
            headers={"Authorization": "Basic " + base64.b64encode(
                f"{E['B2_APP_KEY_ID']}:{E['B2_APP_KEY']}".encode()).decode()})
        a = json.loads(urllib.request.urlopen(a, timeout=45).read())
        req = urllib.request.Request(f"{a['apiInfo']['storageApi']['apiUrl']}/b2api/v4/b2_list_file_names",
            data=json.dumps({"bucketId": E["B2_BUCKET_ID"], "maxFileCount": 100}).encode(),
            headers={"Authorization": a["authorizationToken"]})
        out = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return [f["fileName"] for f in out.get("files", [])]
    except Exception as e:
        print("B2 list FAILED:", str(e)[:200])
        return None


def tigris_list(bucket):
    host, region = "t3.storage.dev", "auto"
    qs = "list-type=2"
    now = datetime.now(timezone.utc)
    amz, ds = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    ph = hashlib.sha256(b"").hexdigest()
    ch = f"host:{host}\nx-amz-content-sha256:{ph}\nx-amz-date:{amz}\n"
    sh = "host;x-amz-content-sha256;x-amz-date"
    cr = f"GET\n/{bucket}\n{qs}\n{ch}\n{sh}\n{ph}"
    scope = f"{ds}/{region}/s3/aws4_request"
    sts = f"AWS4-HMAC-SHA256\n{amz}\n{scope}\n{hashlib.sha256(cr.encode()).hexdigest()}"
    def sg(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()
    k = sg(("AWS4" + E["TIGRIS_SECRET_ACCESS_KEY"]).encode(), ds)
    for p in (region, "s3", "aws4_request"):
        k = sg(k, p)
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={E['TIGRIS_ACCESS_KEY_ID']}/{scope}, "
            f"SignedHeaders={sh}, Signature={sig}")
    req = urllib.request.Request(f"https://{host}/{bucket}?{qs}",
        headers={"x-amz-date": amz, "x-amz-content-sha256": ph, "Authorization": auth})
    try:
        x = urllib.request.urlopen(req, timeout=60).read().decode()
    except urllib.error.HTTPError as e:
        print(f"Tigris list FAILED: HTTP {e.code}: {e.read().decode()[:200]}")
        return None
    return re.findall(r"<Key>([^<]+)</Key>", x)


def main():
    db, tg_bucket = sys.argv[1], sys.argv[2]
    wait_s = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 0
    deadline = time.time() + wait_s
    ok = True
    while True:
        backups = call("GET", f"/api/v1/databases/{db}/backups")
        if not isinstance(backups, list):
            print("backups:", json.dumps(backups)[:250]); ok = False; break
        if not backups:
            print("FAIL: no backup schedule exists for this database — nothing is scheduled (create the schedules, ref 55 §1)")
            ok = False
            break
        done = True
        for b in backups:
            ex = call("GET", f"/api/v1/databases/{db}/backups/{b['uuid']}/executions")
            ex = ex if isinstance(ex, list) else []
            last = ex[0] if ex else None
            if last is not None and last.get("status") in ("failed", "cancelled"):
                print(f"FAIL: newest execution for backup {b['uuid'][:12]}… is `{last.get('status')}` — the schedule ran and broke")
                ok = False
            if last is None or last.get("status") in ("running", "queued"):
                done = False
            print(f"backup {b['uuid'][:12]}… freq={b.get('frequency')} "
                  f"→ last: {last.get('status') if last else 'none (executions can be empty — bucket is the proof)'}")
        if done or time.time() > deadline:
            break
        time.sleep(10)
    print("--- B2 bucket:", E["B2_BUCKET"])
    b2_names = b2_list()
    if not b2_names:
        print("FAIL: B2 bucket listing empty or unreadable — a schedule is unproven until an object exists")
        ok = False
    else:
        for n in b2_names:
            print("  ", n)
    print("--- Tigris bucket:", tg_bucket)
    tg_names = tigris_list(tg_bucket)
    if not tg_names:
        print("FAIL: Tigris bucket listing empty or unreadable — a schedule is unproven until an object exists")
        ok = False
    else:
        for n in tg_names:
            print("  ", n)
    print("VERIFY OK" if ok else "VERIFY FAILED — backups unproven")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
