# 60 — Migrate: free preview → paid host (Coolify → Coolify)

Load when: the user says "move me to the real server/domain" — leaving the free preview (refs 11/21)
or any server-to-server move. OPTIONAL by design: the free track's happy path ends at 40/50; this ref
runs only on request. Core requirement: the OLD stack keeps serving until the NEW one passes smoke.

Reality (verified 2026-09-18): Coolify has NO application export/import. Official flow = recreate the
app on the destination (on a temporary domain), verify, move state, then switch traffic. And:
*"DNS rollback changes routing; it does not merge data"* — never send traffic back to a DB that
missed writes.

## What moves

| Artifact | Where it lives | How it moves |
|---|---|---|
| Git repo | GitHub | nothing — the new box deploys from the same repo |
| App env vars | Coolify → app → Environment Variables | API export + bulk import (below); `is_shown_once` values must be re-entered by hand |
| Postgres data | Coolify DB container | `pg_dump -Fc` → `pg_restore` (or dashboard "Import Backup") |
| Persistent volumes | mounts on the old server | storage-mount backup `.tar.gz`; the dashboard cannot restore it — extract into the destination manually |
| DNS | Cloudflare | A-record swap (lower TTL first) or new domain + 301 alias |
| TLS | auto | re-issued by the new box (optionally pre-issue via DNS-01 — no cert gap) |
| Integrations | Stripe / OAuth / email | repoint webhooks + redirect URIs; email unchanged if the domain is unchanged |

## New box, before the switch (T-14 → T-1)

1. Bootstrap the paid host: `10-bootstrap-vps.md` Steps 0–8 (firewall + 80/443 open + Coolify + token).
2. Recreate the app — dashboard or API: same repo/branch, same build pack (Nixpacks/Dockerfile), ports,
   healthcheck. Set a TEMPORARY domain (e.g. `new.coolify.<domain>`) so it is testable pre-DNS-move.
3. Env vars:
   ```bash
   curl -sS -H "Authorization: Bearer $NEW_TOKEN" "$NEW/api/v1/applications/<uuid>/envs" > envs.json
   # values REDACTED unless the token has read:sensitive — otherwise re-enter from the old source
   curl -sS -X PATCH "$NEW/api/v1/applications/<uuid>/envs/bulk" \
     -H "Authorization: Bearer $NEW_TOKEN" -H "Content-Type: application/json" -d @envs.json
   ```
4. Postgres on the new box, pre-sync restore (old keeps serving):
   ```bash
   # Coolify DB users are per-container (ref 55 §5) — print the pair first, then use it:
   ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$OLD_IP 'docker exec <old-db-container> printenv POSTGRES_USER POSTGRES_DB'
   ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$OLD_IP 'docker exec <old-db-container> pg_dump -U <db-user> --format=custom --no-acl --no-owner <db> > /tmp/pre.dump'
   scp -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$OLD_IP:/tmp/pre.dump .    # then push to the new box and:
   ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$NEW_IP 'docker exec -i <new-db-container> pg_restore -U <db-user> -d <db> --clean --if-exists --no-acl --no-owner < /tmp/pre.dump'
   ```
   Dashboard alternative: new DB → Configuration → **Import Backup** (file on the server; there is no
   restore API endpoint). Default DB image is now **PostgreSQL 18** [verify at live drill].
5. Cross-architecture (arm64 → x86_64 is the common case here): dumps are portable, the app is rebuilt
   from source — NEVER copy `node_modules`, images, or volumes across arches. Test native deps on the
   new box while the old one serves (empty-DB deploy + one page render): `sharp`, `bcrypt`, etc.
6. Pre-create the Stripe endpoint for the new URL; snapshot both boxes; record the OLD DB integrity
   baseline (row counts + schema fingerprint + sequences) — the compare-target for T-0.

## T-0 switch (user-visible downtime = the freeze only, ~5–15 min)

Pre: lower the app A-record TTL (Cloudflare DNS-only: 60 s min; proxied records are pinned to 300 s)
≥ one old-TTL before the window. Coolify has NO per-app maintenance mode — the freeze is
`POST /applications/<uuid>/stop`.

1. Freeze: stop the OLD app.
2. Final dump on OLD (`pg_dump --format=custom`, same commands as above).
3. Restore into NEW (`--clean --if-exists`) → **integrity gate**: identical SQL on both containers —
   per-table row counts, schema fingerprint, sequences — exit non-zero on any diff; ABORT on mismatch.
4. DNS: same-domain → swap the A record to `$NEW_IP` (Cloudflare dashboard 2 clicks, or
   `PATCH https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records/$REC_ID`).
   New-domain scenario → nothing to swap here.
5. Start NEW + `py ops/scripts/coolify_api.py smoke https://<domain> --expect 200` + ONE real write
   through the UI (sign-up or a record save).
6. TLS check: `curl -sSI https://<domain> | head -1` → `HTTP/2 200`.
7. Unfreeze/announce; watch logs + Stripe deliveries for 30–60 min.

## Rollback matrix

| When | Action | Data risk |
|---|---|---|
| Before DNS swap | start the old app again; delete the new stack if desired | none |
| After swap, writes still frozen | swap DNS back, start old app | none — old DB untouched |
| After the new box accepted writes | DNS back is NOT safe; reconcile (dump new over old, both stopped) or fix forward on the new box | REAL — written data on the new box |

## Post-migration (same day)

- **Stripe**: new endpoint for the new URL (16 max; a NEW endpoint issues a NEW `whsec_…` → put it in
  the new env). Disable the old endpoint only after the first successful delivery; failed deliveries
  retry up to 3 days, so a short overlap is safer — watch for duplicates.
- **OAuth apps**: add the new domain's redirect URI alongside the old; remove old after verification.
- **Free domain**: keep as a permanent 301 — Cloudflare **Single Redirect** rule (10 free rules/zone;
  requires a proxied record) → new domain.
- **Old Oracle box**: keep 14–30 days as staging/rollback, then **terminate instance + delete boot
  volume** (do not rely on idle-reclamation as cleanup). Archive the final dump + `.vps-ops.json`.
- Update `<project>/.vps-ops.json` → new UUIDs + domain; keep the old values under `history`.

## Fallbacks (unverified — rehearse before trusting)

Coolify's newer API ships move endpoints (OpenAPI spec): `POST /applications/{uuid}/migrate`
(`destination_uuid`, `migrate_volumes`), `POST /applications/{uuid}/clone`, and
`GET /servers/{uuid}/export` → `POST /servers/import` → `POST /servers/{uuid}/migrate` (needs
root/read:sensitive). Behaviour with Coolify-managed DBs is undocumented — for one micro-SaaS prefer
plain recreation; treat these as `[verify at live drill]`.

## Provenance

coolify.io/docs: migrate-between-instances · databases/restore · databases/backups · instance-restore ·
proxy/traefik/dns-challenge · storage-mount backups · discussion #2949 (no maintenance mode) ·
Cloudflare DNS TTL/proxy docs · Stripe webhooks docs · Let's Encrypt rate limits (updated 2026-08-05) ·
shipped Coolify OpenAPI spec · verified 2026-09-18; full research in `D:\OCI-research` (local archive).
