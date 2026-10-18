# 20 — Domain, DNS & SSL: records → Hostinger API (or manual) → Coolify domain → Let's Encrypt

Load when: bootstrap (`10-bootstrap-vps.md`) is green and the domain must go live.
After this file: `30-deploy-app.md` (attach the same domain to the app), then `40-change-pipeline.md`.

> Rehearsal tip (live-verified): to test a fresh VPS **before DNS exists**, set the app's domain to
> the plain server IP (`http://<server-ip>`) — Traefik matches on Host and serves it with no DNS at all;
> smoke with `py ops/scripts/coolify_api.py smoke http://<server-ip>`.

Prerequisites: the vault loaded into the shell — the `shell` line `dh vault list` prints (`$HOSTINGER_API_TOKEN`, `$COOLIFY_URL`,
`$COOLIFY_TOKEN` — see `10-bootstrap-vps.md` Steps 1a/5); VPS IP known; SSH + Coolify health verified.

> **Free-preview track:** the domain is `name.pp.ua` at nic.ua, DNS hosted at Cloudflare (free).
> Run `21-free-domain-cloudflare.md` for registration + the NS swap + the A records, then use the
> "Coolify side" section below (Cloudflare = the manual-registrar route there; records stay
> **DNS-only** during cert issuance).

Hard rules: **never PUT a DNS change without validating it first** (validate → apply → re-read) ·
keep the pre-change zone backup · we own only A records for `@`, `www`, `coolify` (+ `*` if wanted) —
everything else in the zone is untouched.

## Record plan

| Name | Type | Value | Purpose |
|---|---|---|---|
| `@` | A | `<IP>` | apex / root site |
| `www` | A | `<IP>` | www alias |
| `coolify` | A | `<IP>` | Coolify instance (HTTPS + MCP) |
| `*` | A | `<IP>` | *optional* — Coolify PR previews |

TTL: 14400 (Coolify's default) unless the registrar forces lower.

## Hostinger route (exact API flow)

### 1. Read first — this is also the backup

```bash
curl -sS "https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" \
  | tee ~/.vps-ops/dns-backup-$(date +%F-%H%M%S).json
```

Script equivalent: `py ops/scripts/hostinger_api.py dns get <domain> --save ~/.vps-ops/dns-backup-<timestamp>.json` — a NEW name every read (never overwrite: a same-day re-read would save the already-changed zone over the pre-change rollback reference).
Expected: the full current zone JSON — keep the copy; it is the rollback reference.

### 2. Write `proposed.json` — A records only

```json
{
  "overwrite": true,
  "zone": [
    {"name": "@",       "type": "A", "ttl": 14400, "records": [{"content": "<IP>"}]},
    {"name": "www",     "type": "A", "ttl": 14400, "records": [{"content": "<IP>"}]},
    {"name": "coolify", "type": "A", "ttl": 14400, "records": [{"content": "<IP>"}]}
  ]
}
```

⚠️ `overwrite:true` here is intentional and recommended: it deletes+recreates exactly the name+type
pairs in the payload and **leaves every other record (TXT/MX/CNAME/…) untouched**. `overwrite:false`
only appends / updates TTL and can duplicate records — do not use it.

### 3. Validate (dry run) — must be 200 before the PUT

```bash
curl -sS -X POST "https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN/validate" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
  -d @proposed.json
```

Expected: HTTP 200 = valid. A 422 = the body is wrong — read the raw error body and fix exactly the
field it names; do not retry blindly.

### 4. Apply

```bash
curl -sS -X PUT "https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
  -d @proposed.json
```

### 5. Re-read to verify (never trust the write)

```bash
curl -sS "https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" | grep -A3 '"name": "@"'
```

Script equivalent for steps 2–5 (idempotent merge + diff summary):
`py ops/scripts/hostinger_api.py dns set-a <domain> --ip <IP> --names @,www,coolify --ttl 14400`.

### Rollback — DNS snapshots

```bash
curl -sS "https://developers.hostinger.com/api/dns/v1/snapshots/$DOMAIN" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"                       # list snapshots
curl -sS -X POST "https://developers.hostinger.com/api/dns/v1/snapshots/$DOMAIN/<snapshotId>/restore" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"                       # restore
```

Fallback: PUT the old A values back from `dns-backup-<date>.json` using the desired-state body.
`GET /api/dns/v1/snapshots/{domain}` contents not yet exercised live. [verify at live drill]

## Manual registrar route

Registrar is not Hostinger (or the API route is refused): hand the user the §7 table from
`00-user-checklist.md` and let them add `@`, `www`, `coolify` (+ optional `*`) A records to the VPS
IP. Continue with the propagation check below — identical from here on.

## Propagation check (do this BEFORE touching Coolify / SSL)

```bash
dig +short <domain> @1.1.1.1        # expect: a single line — <IP>
nslookup <domain> 1.1.1.1           # Windows — "Address:" line must be <IP>
```

Expected: the output equals the VPS IP exactly. Stale value or empty → wait out the TTL and re-check;
do not attach the domain in Coolify while DNS is wrong (the ACME challenge will fail and rate-limit).

## Coolify side — attach the domain to the app

```bash
curl -sS -X PATCH "$COOLIFY_URL/api/v1/applications/<uuid>" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"domains":"<domain>,www.<domain>"}'
```

`domains` is a **comma-separated string** — multiple hostnames in one value (attach BOTH the apex and `www` — the plan's two app records; certs are per hostname):
`{"domains":"<domain>,www.<domain>"}`. UI equivalent: App → Configuration → Domains.
Coolify issues the Let's Encrypt certificate automatically once DNS resolves to the VPS and port 80
is reachable (ref 10 Step 3 put 80 in the firewall). Record the domain in `<project>/.vps-ops.json`
(see `30-deploy-app.md`). If a scheme is shown in the UI value, mirror it. [verify at live drill]

## Let's Encrypt verification

```bash
curl -sSI https://<domain> | head -1
# expect: HTTP/2 200

echo | openssl s_client -connect <domain>:443 -servername <domain> 2>/dev/null \
  | openssl x509 -noout -issuer -dates
# expect: issuer string contains "Let's Encrypt"; notBefore/notAfter bracket today
# [verify at live drill] — this one-liner has not been executed end-to-end yet

py ops/scripts/coolify_api.py smoke https://<domain> --expect 200 --contains "<a string only your app returns>"   # a bare 200 can't tell your app from a default page
# expect: OK 200 https://<domain>     (exit code 4 = check failed)
```

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Cert "pending" / not issued after attach | `dig +short <domain> @1.1.1.1` == IP? `curl -sSI http://<domain>` answers? | fix DNS first, then redeploy the app; Coolify retries ACME on the next deployment |
| `curl: (60) SSL certificate problem` / wrong cert served | DNS still points elsewhere, or a proxy sits in front | re-check `dig`; disable Cloudflare proxy (DNS-only) during issuance; redeploy |
| Issuance fails, port 80 blocked | firewall has a TCP/80 rule? `…/firewall/<fwId>/sync` run? | add the rule + sync (`10-bootstrap-vps.md` Step 3), redeploy |
| `www` fails while apex works (or vice versa) | both A records present? both hostnames in the `domains` string? | add the missing A record (record plan) and include both hostnames in `domains`; certs are per hostname |
| Stale / duplicate A records | re-GET the zone, look for extra A entries | PUT the desired-state body again (`overwrite:true`, A only) — it rewrites exactly those names |
| DNS correct but app 404s / 502s | app deployed and healthy? `py ops/scripts/coolify_api.py status` | deploy the app (`30-deploy-app.md`); inspect logs |

## Next

`30-deploy-app.md` — create the app in Coolify, sync envs, attach this domain, first deploy + smoke.
