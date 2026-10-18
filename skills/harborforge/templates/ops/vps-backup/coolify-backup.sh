#!/usr/bin/env bash
# vps-ops deep backup layer (ref 55 §5) — restic → TWO offsite S3 providers (B2 + Tigris).
# LIVE-VERIFIED 2026-09-20 (live drill): backup + prune + weekly restore drill all pass.
# 2026-09-21 hardening: RESTIC_CACHE_DIR pinned (systemd units carry NO $HOME — restic 0.19 hard-fails
#   with "unable to locate cache directory" and the FIRST automated run dies while every manual test
#   passes); all restic steps tee to $LOG so failure emails show the FAILING run, not the previous one;
#   every run opens with a "=== <mode> run start ===" marker.
# Backs up: every Coolify DB container (incl. coolify-db, logical dumps) + an explicit app-volume allowlist.
# Install on the VPS: restic (UPSTREAM static binary — apt lags), jq, docker. Secrets under /etc/backup (root, 600).
# systemd: coolify-backup.timer (03:15 daily) + coolify-verify.timer (Sun 04:30) — see README.
# ADAPT: /etc/backup/env values; PIN the volume allowlist; escrow restic-*.pass OFF this box.
#
# /etc/backup/env (root, 600 — MUST be LF line endings; CRLF breaks restic repo paths):
#   B2_HOST=s3.us-east-005.backblazeb2.com  B2_BUCKET=…  B2_KEY_ID=…  B2_SECRET=…  B2_REGION=us-east-005
#   TG_HOST=t3.storage.dev                  TG_BUCKET=…  TG_KEY_ID=…  TG_SECRET=…
# The vault's own forms are accepted as-written too (b2_setup.py / tigris_bucket.py write these):
# https:// prefixes on the hosts, B2_APP_KEY_ID/B2_APP_KEY for the key pair, TIGRIS_* / TIGRIS_BUCKET
# names — normalized below (live-hit 2026-09-21: the first backup died on the raw naming mismatch).
#   ALERT_URL=https://<app-domain>/api/mail-alert?secret=…   # guarded route -> mail chain (ref 70; route appends a link — the router rejects link-less bodies)
#   VOLUMES="postgres-data-<uuid>"                            # explicit allowlist, space-separated
#   DB_CONTAINERS="<db-uuid> coolify-db"                      # container name = uuid (ref 50 §5)
#   SANITY_DB=<db-uuid>  SANITY_SQL="select count(*) from users"   # weekly drill checks the APP db
set -euo pipefail
source /etc/backup/env
# Normalize the vault's forms — either naming works; a missing value fails later at restic with a clear repo URL:
B2_HOST="${B2_HOST:-}"; B2_HOST="${B2_HOST#https://}"; B2_HOST="${B2_HOST#http://}"; B2_HOST="${B2_HOST#s3.}"
TG_HOST="${TG_HOST:-}"; TG_HOST="${TG_HOST#https://}"; TG_HOST="${TG_HOST#http://}"
B2_KEY_ID="${B2_KEY_ID:-${B2_APP_KEY_ID:-}}"; B2_SECRET="${B2_SECRET:-${B2_APP_KEY:-}}"
TG_KEY_ID="${TG_KEY_ID:-${TIGRIS_ACCESS_KEY_ID:-}}"; TG_SECRET="${TG_SECRET:-${TIGRIS_SECRET_ACCESS_KEY:-}}"
TG_BUCKET="${TG_BUCKET:-${TIGRIS_BUCKET:-}}"
# systemd has no $HOME — pin restic's cache so the script cannot run in an env that breaks it:
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/var/cache/restic}"; mkdir -p "$RESTIC_CACHE_DIR"
B2PASS=/etc/backup/restic-b2.pass; TGPASS=/etc/backup/restic-tg.pass   # 600 root; ALSO escrow off-box
TG="s3:https://${TG_HOST}/${TG_BUCKET}/coolify"
B2="s3:s3.${B2_HOST#s3.}/${B2_BUCKET}/coolify"
STAGE=/var/tmp/coolify-backup; STATE=/opt/backup/state; LOG=/var/log/coolify-backup.log
mkdir -p "$STATE"; touch "$LOG"
log(){ echo "$(date -Is) $*" | tee -a "$LOG"; }
alert(){ [ -n "${ALERT_URL:-}" ] || return 0
  code=$(curl -sS -m 20 -o /tmp/alert.out -w '%{http_code}' "$ALERT_URL" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg s "$1" --arg b "$2" '{subject:$s,text:$b}')") || code=000
  [ "$code" = 200 ] || log "ALERT DELIVERY http=$code $(head -c 200 /tmp/alert.out 2>/dev/null)"
}
state(){ echo "{\"status\":\"$1\",\"step\":\"$2\",\"ts\":\"$(date -Is)\"}" > "$STATE/status.json"; }
die(){ state failed "$1"; alert "backup FAILED on $(hostname): $1" "$(tail -n 40 "$LOG" 2>/dev/null || true)"; exit 1; }
# per-repo restic wrappers — restic has no per-repo credentials; inject env per call
rTG(){ AWS_ACCESS_KEY_ID="$TG_KEY_ID" AWS_SECRET_ACCESS_KEY="$TG_SECRET" AWS_DEFAULT_REGION=auto \
       restic -r "$TG" -p "$TGPASS" "$@"; }
rB2(){ AWS_ACCESS_KEY_ID="$B2_KEY_ID" AWS_SECRET_ACCESS_KEY="$B2_SECRET" AWS_DEFAULT_REGION="${B2_REGION:-us-east-005}" \
       restic -r "$B2" -p "$B2PASS" "$@"; }
exec 9>/var/lock/coolify-backup.lock; flock -w 900 9   # serialize (restic#5582 habits)

backup(){
  log "=== backup run start ==="
  rm -rf "$STAGE"; mkdir -p "$STAGE/pg" "$STAGE/volumes"; trap 'rm -rf "$STAGE"' EXIT
  for c in $DB_CONTAINERS; do
    # Coolify DB users are per-container (NOT postgres): auto-detect
    u=$(docker exec "$c" printenv POSTGRES_USER 2>/dev/null); u=${u:-${PGUSER:-postgres}}
    d=$(docker exec "$c" printenv POSTGRES_DB 2>/dev/null);   d=${d:-${DBNAME:-postgres}}
    docker exec "$c" pg_dump --format=custom --no-acl --no-owner -U "$u" "$d" > "$STAGE/pg/$c.dump" \
      || die "pg_dump $c"
  done
  for v in $VOLUMES; do
    docker run --rm -v "$v":/src:ro -v "$STAGE/volumes":/out alpine tar czf "/out/$v.tgz" -C /src . \
      || die "tar $v"
  done
  rTG backup "$STAGE" --tag daily --host coolify-vps >>"$LOG" 2>&1 || die "restic backup Tigris"
  rB2 backup "$STAGE" --tag daily --host coolify-vps >>"$LOG" 2>&1 || die "restic backup B2"
  rTG forget --keep-last 3 --prune >>"$LOG" 2>&1 || die "prune Tigris"
  rB2 forget --keep-last 3 --prune >>"$LOG" 2>&1 || die "prune B2"
  state ok backup; log "backup OK"   # success is silent; the weekly verify sends the heartbeat
}

verify(){ # weekly drill: freshness + sampled bytes on BOTH repos + functional restore from Tigris (free egress)
  log "=== verify run start ==="
  rc=0
  rTG snapshots --latest 1 --json >>"$LOG" 2>&1 || rc=1
  rB2 snapshots --latest 1 --json >>"$LOG" 2>&1 || rc=1
  rTG check --read-data-subset=10% >>"$LOG" 2>&1 || rc=1   # plain check reads NO data
  rB2 check --read-data-subset=10% >>"$LOG" 2>&1 || rc=1
  for pair in "TG" "B2"; do
    if [ "$pair" = TG ]; then t=$(rTG snapshots --latest 1 --json 2>/dev/null | jq -r '.[0].time'); else t=$(rB2 snapshots --latest 1 --json 2>/dev/null | jq -r '.[0].time'); fi
    age=$(( ($(date -u +%s) - $(date -u -d "$t" +%s)) / 3600 ))
    [ "$age" -lt 26 ] || { log "stale snapshot in $pair ($age h)"; rc=1; }
  done
  # functional restore from the free-egress repo — each dump into its own db,
  # sanity-check the APP db (SANITY_DB) with SANITY_SQL; pg_restore warnings on
  # non-sanity dbs are logged, not fatal (extensions etc.)
  rm -rf /var/tmp/drill
  rTG restore latest --target /var/tmp/drill >>"$LOG" 2>&1 || rc=1
  docker rm -f drill-pg >/dev/null 2>&1 || true
  docker run -d --name drill-pg -e POSTGRES_PASSWORD=drill postgres:16 >/dev/null || rc=1
  for i in $(seq 30); do docker exec drill-pg pg_isready -U postgres -q && break; sleep 2; done
  for f in /var/tmp/drill"$STAGE"/pg/*.dump; do
    [ -f "$f" ] || { echo "no dumps restored!" >>"$LOG"; rc=1; break; }
    name=$(basename "$f" .dump); db="d_${name:0:20}"
    docker exec drill-pg createdb -U postgres "$db" >>"$LOG" 2>&1 || rc=1
    if ! docker exec -i drill-pg pg_restore -U postgres -d "$db" --no-owner --no-acl < "$f" >>"$LOG" 2>&1; then
      [ "$name" = "${SANITY_DB:-$name}" ] && rc=1 || echo "pg_restore warnings in $name (non-fatal)" >>"$LOG"
    fi
  done
  cnt=$(docker exec drill-pg psql -U postgres -d "d_${SANITY_DB:0:20}" -tAc "${SANITY_SQL:-select 1}" 2>>"$LOG")
  echo "sanity (${SANITY_DB:0:20}): $cnt" >>"$LOG"
  [ -n "$cnt" ] || rc=1
  docker rm -f drill-pg >/dev/null; rm -rf /var/tmp/drill
  if [ $rc -eq 0 ]; then state ok verify; alert "restore drill PASS" "latest Tigris+B2 snapshots verified $(date -Is)"
  else state failed verify; alert "restore drill FAILED on $(hostname)" "$(tail -n 60 "$LOG")"; fi
  exit $rc
}
case "${1:-backup}" in backup) backup;; verify) verify;; *) echo "usage: $0 backup|verify"; exit 2;; esac
