# 50 — Operate: status, logs, metrics, cleanup, backups, updates, incidents

**Purpose:** day-2 operations — answer "is it up?", read logs, watch the server, reclaim disk, keep backups and updates current, and work incidents from one table.
**Use when:** the user asks "is the site up / what's wrong / when did it last deploy?", or on the monthly maintenance pass.
**Prerequisites:** `30-deploy-app.md` done and `<project>/.vps-ops.json` present; `COOLIFY_TOKEN` (ref 10) and `HOSTINGER_API_TOKEN` (ref 00) available.
**Companion refs:** `40-change-pipeline.md` (fix-forward + rollback) · `10-bootstrap-vps.md` (SSH key, host, Coolify) · `20-domain-dns-ssl.md` (DNS/SSL).

## 1. Status at ask-time

```bash
py ops/scripts/coolify_api.py status      # all apps: name, status, last deployment (status + time)
py ops/scripts/coolify_api.py apps        # same inventory, uuid + status only
py ops/scripts/coolify_api.py health      # Coolify API reachable? (GET /health, no auth)
coolify app list --format json        # full JSON inventory — REST equivalent: GET /applications
```

Expected `status` line: `<app-name>  running  last:success 2026-09-17T18:04:12`. Report exactly what it prints — `last:-` means no deployment recorded yet.
Fast reachability: `py ops/scripts/coolify_api.py smoke https://<domain> --expect 200` (exit 0 pass · 4 fail).

## 2. Logs

```bash
py ops/scripts/coolify_api.py logs <APP_UUID> --lines 200 --timestamps
coolify app logs <APP_UUID> --lines 200 --show-timestamps
curl -sS "$COOLIFY_URL/api/v1/applications/<APP_UUID>/logs?lines=200&show_timestamps=false" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"
```

Build (deployment) logs live on the deployment object — `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 5`, then its `logs` field. Runtime crashes live in app logs. Quote the last ~30 relevant lines in a report, not the whole dump.

## 3. Server health (Hostinger)

```bash
py ops/scripts/hostinger_api.py vm get <vmId>              # specs + state
py ops/scripts/hostinger_api.py vm metrics <vmId> --days 7 # 7-day window for CPU/RAM/disk/traffic
```

The metrics endpoint requires **both** `date_from` and `date_to` (ISO) — `--days N` builds that window for you. Raw form:

```bash
curl -sS "https://developers.hostinger.com/api/vps/v1/virtual-machines/<vmId>/metrics?date_from=2026-09-10T00:00:00Z&date_to=2026-09-17T00:00:00Z" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"
```

Response fields `cpu_usage`, `ram_usage`, `disk_space`, `outgoing_traffic`, `incoming_traffic`, `uptime` — each `{"unit":"...","usage":{"<epoch>": value}}`. Report the peak and trend per field; exact unit scales `[verify at live drill]`.

## 4. Disk reclamation (Coolify)

```bash
curl -sS "$COOLIFY_URL/api/v1/servers/<SERVER_UUID>/docker-cleanup" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"                                    # what can be reclaimed
curl -sS -X POST "$COOLIFY_URL/api/v1/servers/<SERVER_UUID>/docker-cleanup/run" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"                                    # run the cleanup
```

GET reports reclaimable stopped containers / dangling images / build cache; the POST starts it. Run before disk-pressure incidents and after large deploys. Response field names live-verified 2026-09-17: GET returns `{"docker_cleanup_frequency","docker_cleanup_threshold","force_docker_cleanup","delete_unused_volumes","delete_unused_networks","disable_application_image_retention"}`; POST `…/docker-cleanup/run` → `{"message":"Manual cleanup job started…"}`.

## 5. Backups — local dump + restore recipe (**offsite dual-target is the default: ref 55**)

```bash
coolify database backup create <DB_UUID> --frequency "0 2 * * *" --enabled --retention-days-locally 7
```

Take the backup uuid from the output, then trigger one **immediately** and confirm it actually ran:

```bash
coolify database backup trigger <DB_UUID> <BACKUP_UUID>
coolify database backup executions <DB_UUID> <BACKUP_UUID>     # expect a successful execution, not just "scheduled"
```

REST fallbacks (live-verified 2026-09-17): `POST /databases/{uuid}/backups` with body
`{"frequency": "0 3 * * *", "enabled": true, "database_backup_retention_days_locally": 7, "backup_now": true}`
— **`backup_now:true` triggers the first dump immediately**, no separate trigger call needed ·
`GET /databases/{uuid}/backups` · `GET /databases/{uuid}/backups/{scheduled_backup_uuid}/executions`
(execution shortly shows `status:"success"`; the dump lands in
`/data/coolify/backups/databases/<team>/<db-name>-<uuid>/pg-dump-<db>-<epoch>.dmp`).
Offsite is no longer "optional": **every project defaults to dual offsite targets (Backblaze B2 primary + Tigris — both card-free; Cloudflare R2 optional, card-gated) with 3-copy retention, schedules and verification — all in `55-offsite-backups.md`.** The local dump stays as a fast-restore cache; the offsite object is the source of truth.
VPS-level snapshot (monthly, before updates):

```bash
py ops/scripts/hostinger_api.py snapshot create <vmId>
py ops/scripts/hostinger_api.py actions <vmId>            # poll the async op until state=success
py ops/scripts/hostinger_api.py snapshot list <vmId>
```

Restore drill (live-verified 2026-09-17 — run ~yearly, or after any schema scare): dumps are **custom-format (magic `PGDMP`)** → restore with `pg_restore`, not `psql`. The database's docker container is named **exactly its uuid** (Coolify's display name `postgresql-database-<uuid>` is NOT the container name):

```bash
C=<db-uuid>          # container name = the plain uuid
DUMP=$(ls /data/coolify/backups/databases/<team>/*/pg-dump-<db>-*.dmp | head -1)
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker cp $DUMP $C:/tmp/restore-test.dmp"
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec $C psql -U <dbuser> -d postgres -c 'CREATE DATABASE restore_test;'"
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec $C pg_restore -U <dbuser> -d restore_test /tmp/restore-test.dmp"   # rc=0
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec $C psql -U <dbuser> -d restore_test -c 'SELECT 1;'"                 # must answer
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec $C rm -f /tmp/restore-test.dmp"   # then DROP DATABASE restore_test;
```

## 6. Updates

Coolify (the script backs up the DB first; log at `/data/coolify/source/upgrade-*.log`). **After ANY Coolify upgrade, re-run Step 3b** — the upgrade re-downloads both compose files and the dashboard's loopback binds are LOST (ref 10):

```bash
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP 'curl -fsSL https://cdn.coollabs.io/coolify/upgrade.sh | bash'
py ops/scripts/coolify_api.py health       # expect 200 once containers are back
coolify context version                # confirm the new version after the upgrade
```

OS packages:

```bash
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP 'apt-get update && apt-get -y upgrade'
# reboot only if the kernel changed, never mid-deploy — then wait ~60s and re-check python health
```

Cadence: monthly, agent-driven, **after** a fresh snapshot (§5). Never update while a deployment is running.

## 7. Incident playbook

| Incident | First checks | Action |
|---|---|---|
| App 502 / site down | `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 5` + app logs (§2) | `POST /applications/{uuid}/restart` (+ `/start` `/stop`); if a bad release → `40-change-pipeline.md` rollback |
| Server unreachable (SSH and `:8000` both fail) | `py ops/scripts/hostinger_api.py vm get <vmId>` | `py ops/scripts/hostinger_api.py vm restart <vmId>`; still dead → snapshot restore |
| Certificate expired / TLS error | `curl -sI https://<domain>` + ref 20 checks | redeploy the app (Let's Encrypt renews on deploy); confirm port 80 open |
| Disk full (deploys start failing, metrics `disk_space`) | §3 metrics | §4 docker-cleanup; remove stale resources; resize if structural |
| Coolify dashboard/API down | `py ops/scripts/coolify_api.py health` | re-run the §6 upgrade script; last resort `ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP 'cd /data/coolify/source && docker compose up -d'` |
| DNS wrong / not resolving | `nslookup <domain> 1.1.1.1` vs VPS IP | `py ops/scripts/hostinger_api.py dns set-a <domain> --ip <IP> --names @,www` (ref 20) |
| Deploy queue stuck after a restart | `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 3` | re-trigger `coolify deploy uuid <APP_UUID>` once; if it repeats, update Coolify (§6) |

Escalate in writing: which row, what the check returned verbatim, what action was taken. Never guess a cause.

## 8. Routine cadence

| When | Do |
|---|---|
| every ask | `py ops/scripts/coolify_api.py status` + smoke the domain |
| weekly | skim app logs (§2) for restarts; glance at metrics (§3) |
| monthly | snapshot → updates (§6) → docker-cleanup (§4) → smoke check |
| yearly | restore drill (§5) on a scratch app |
