#!/usr/bin/env python3
"""tigris_bucket.py — create a Tigris bucket the SAFE way and PROVE it serves reads.

Why: a console-created bucket can be GLACIER class — it lists objects (HEAD shows the
right size) but every GET >~1 KB returns HTTP 200 with 0 bytes to every client
(rclone "unexpected EOF", python IncompleteRead). API-created buckets default to
STANDARD. `verify` proves readability with a 512 KB round-trip. LIVE-VERIFIED 2026-09-20.

Usage:
  TIGRIS_ACCESS_KEY_ID=tid_… TIGRIS_SECRET_ACCESS_KEY=tsec_… python3 tigris_bucket.py ls
  ... create <bucket>
  ... verify <bucket>        # 512 KB put → get → compare → delete
"""
import hashlib, hmac, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

HOST, REGION = "t3.storage.dev", "auto"
AK = os.environ.get("TIGRIS_ACCESS_KEY_ID", "")
SK = os.environ.get("TIGRIS_SECRET_ACCESS_KEY", "")


def _req(method, uri, query="", payload=b""):
    now = datetime.now(timezone.utc)
    amz, ds = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    ph = hashlib.sha256(payload).hexdigest()
    ch = f"host:{HOST}\nx-amz-content-sha256:{ph}\nx-amz-date:{amz}\n"
    sh = "host;x-amz-content-sha256;x-amz-date"
    cr = f"{method}\n{uri}\n{query}\n{ch}\n{sh}\n{ph}"
    scope = f"{ds}/{REGION}/s3/aws4_request"
    sts = f"AWS4-HMAC-SHA256\n{amz}\n{scope}\n{hashlib.sha256(cr.encode()).hexdigest()}"
    def sg(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()
    k = sg(("AWS4" + SK).encode(), ds)
    for p in (REGION, "s3", "aws4_request"):
        k = sg(k, p)
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, SignedHeaders={sh}, Signature={sig}"
    url = f"https://{HOST}{uri}" + (f"?{query}" if query else "")
    return urllib.request.Request(url, method=method,
                                  data=payload if method in ("PUT", "POST") else None,
                                  headers={"x-amz-date": amz, "x-amz-content-sha256": ph,
                                           "Authorization": auth})


def call(req):
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]


def main():
    if not AK or not SK:
        print("set TIGRIS_ACCESS_KEY_ID / TIGRIS_SECRET_ACCESS_KEY"); sys.exit(1)
    action = sys.argv[1] if len(sys.argv) > 1 else "ls"
    if action == "ls":
        code, body = call(_req("GET", "/"))
        print("HTTP", code)
        import re
        print(*re.findall(rb"<Name>([^<]+)</Name>", body), sep="\n")
    elif action == "create":
        bucket = sys.argv[2]
        code, body = call(_req("PUT", f"/{bucket}"))
        print(f"create {bucket}: HTTP {code}", body[:200] if code not in (200, 201) else "ok (default STANDARD class)")
    elif action == "verify":
        bucket = sys.argv[2]
        blob = os.urandom(512 * 1024)
        key = "classcheck-512k.bin"
        code, _ = call(_req("PUT", f"/{bucket}/{key}", payload=blob))
        if code not in (200, 201):
            print(f"PUT failed: HTTP {code} — bucket class may be GLACIER; recreate STANDARD"); sys.exit(1)
        code, got = call(_req("GET", f"/{bucket}/{key}"))
        ok = code == 200 and len(got) == len(blob) and hashlib.sha256(got).digest() == hashlib.sha256(blob).digest()
        print(f"GET: HTTP {code}, {len(got)}/{len(blob)} bytes, sha match: {ok}")
        call(_req("DELETE", f"/{bucket}/{key}"))
        sys.exit(0 if ok else 1)
    else:
        print("usage: tigris_bucket.py ls | create <bucket> | verify <bucket>")


if __name__ == "__main__":
    main()
