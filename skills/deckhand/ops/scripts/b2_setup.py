#!/usr/bin/env python3
"""b2_setup.py — B2 bucket + lifecycle + scoped app key via the B2 Native API. LIVE-VERIFIED 2026-09-20.

Usage:  python3 b2_setup.py <bucket-name> <key-name> [region]  (region default: $B2_REGION or us-east-005)
Reads the master key from ~/.vps-ops/secrets/backup.env.sh (B2_MASTER_KEY_ID/_KEY).
Idempotent-ish: existing bucket is reused (lifecycle re-applied); a fresh scoped key is minted.
Writes scoped creds to ~/.vps-ops/secrets/b2-scoped.env.sh (prints NOTHING secret to stdout).

v4 API note: b2_create_key takes `bucketIds` (a LIST) — the old `bucketId` returns 400.
"""
import base64, json, os, re, sys, urllib.request, urllib.error

VAULT = os.path.expanduser("~/.vps-ops/secrets/backup.env.sh")
OUT = os.path.expanduser("~/.vps-ops/secrets/b2-scoped.env.sh")


def load(path):
    env = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"export (\w+)=['\"]?(.*?)['\"]?$", line.rstrip())
        if m:
            env[m.group(1)] = m.group(2)
    return env


def api(url, token=None, payload=None, basic=None, raw_token=None):
    headers = {}
    if raw_token:
        headers["Authorization"] = raw_token
    elif token:
        headers["Authorization"] = token
    if basic:
        headers["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=45).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return {"_http": e.code, **json.loads(body)}
        except Exception:
            return {"_http": e.code, "_body": body[:400]}


def main():
    bucket_name, key_name = sys.argv[1], sys.argv[2]
    region = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("B2_REGION", "us-east-005")
    env = load(VAULT)
    kid, key = env["B2_MASTER_KEY_ID"], env["B2_MASTER_KEY"]

    a = api("https://api.backblazeb2.com/b2api/v4/b2_authorize_account", basic=f"{kid}:{key}")
    if "authorizationToken" not in a:
        print("AUTH FAILED:", json.dumps(a)[:300]); sys.exit(1)
    tok, api_url, acct = a["authorizationToken"], a["apiInfo"]["storageApi"]["apiUrl"], a["accountId"]
    print(f"authorized ok · account {acct[:6]}… · api {api_url}")

    buckets = api(f"{api_url}/b2api/v4/b2_list_buckets", raw_token=tok, payload={"accountId": acct})
    bid = next((b["bucketId"] for b in buckets.get("buckets", []) if b["bucketName"] == bucket_name), None)
    # "keep only the last version": hidden (deleted/overwritten) versions are removed after 1 day —
    # restic's S3 backend hides deletions, so without this the bucket grows silently.
    lc = [{"fileNamePrefix": "", "daysFromUploadingToHiding": None, "daysFromHidingToDeleting": 1}]
    if bid:
        print(f"bucket exists: {bucket_name} ({bid}) — re-applying lifecycle")
        r = api(f"{api_url}/b2api/v4/b2_update_bucket", raw_token=tok,
                payload={"accountId": acct, "bucketId": bid, "lifecycleRules": lc})
        print("lifecycle:", "ok" if r.get("bucketId") else json.dumps(r)[:200])
    else:
        r = api(f"{api_url}/b2api/v4/b2_create_bucket", raw_token=tok,
                payload={"accountId": acct, "bucketName": bucket_name,
                         "bucketType": "allPrivate", "lifecycleRules": lc})
        if "bucketId" not in r:
            print("CREATE FAILED:", json.dumps(r)[:300]); sys.exit(1)
        bid = r["bucketId"]
        print(f"bucket created: {bucket_name} ({bid}) · lifecycle keep-last-version, hide→delete 1d")

    k = api(f"{api_url}/b2api/v4/b2_create_key", raw_token=tok,
            payload={"accountId": acct, "keyName": key_name,
                     "capabilities": ["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"],
                     "bucketIds": [bid]})
    if "applicationKeyId" not in k:
        print("KEY FAILED:", json.dumps(k)[:300]); sys.exit(1)

    with open(OUT, "w", newline="\n", encoding="utf-8") as f:   # LF only — CRLF env files break restic/S3 tooling
        f.write("# B2 scoped app key — vault copy. NEVER commit, NEVER echo.\n")
        f.write(f"export B2_APP_KEY_ID='{k['applicationKeyId']}'\n")
        f.write(f"export B2_APP_KEY='{k['applicationKey']}'\n")
        f.write(f"export B2_BUCKET='{bucket_name}'\n")
        f.write(f"export B2_BUCKET_ID='{bid}'\n")
        f.write(f"export B2_HOST='https://s3.{region}.backblazeb2.com'\n")
        f.write(f"export B2_REGION='{region}'\n")
    try:
        os.chmod(OUT, 0o600)                                    # owner-only on POSIX; on Windows: icacls inheritance:r
    except OSError:
        pass
    print(f"scoped key minted ({k['applicationKeyId'][:8]}…) → {OUT}  [lock it down: chmod 600 / icacls inheritance:r]")


if __name__ == "__main__":
    main()
