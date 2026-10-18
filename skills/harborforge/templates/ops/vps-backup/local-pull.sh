#!/usr/bin/env bash
# Deckhand home pull (vps-ops ref 55 §7) — runs on the USER'S machine, NOT the VPS.
# v3 (2026-09-20): fast-fail local-S3 probe + one probe per run + per-step DONE lines
# with elapsed seconds. Why: a stopped Docker Desktop made the reachability probe
# retry for MINUTES, which (a) blew an agent-tool timeout mid-run and (b) looked like
# a remote (tigris) hang in the start-only log. Both fixed here.
# Mirrors the offsite buckets into local folders AND/OR a local RustFS S3:
#   restic -r <DEST>/<provider>/coolify -p <pass> snapshots   (repos included — no server needed)
# Env file (chmod 600, LF only):
#   CLOUD_REMOTES="b2:my-bucket tigris:my-offsite-bucket"
#   DEST=C:/Users/<you>/deckhand-backups
#   LOCAL_S3_REMOTE=rustfs:<bucket>                        # optional local RustFS target
#   ALERT_URL=https://<app-domain>/api/mail-alert?secret=… # optional; the route appends a link
# Schedule: Windows Task Scheduler / cron / an agent cronjob — and give the run a
# GENEROUS timeout if an agent drives it (steps are logged, so watch the log, not the clock).
set -euo pipefail
ENVF="${DECKHAND_ENV:-$HOME/.vps-ops/secrets/home-pull.env.sh}"
source "$ENVF"
DEST="${DEST:-$HOME/deckhand-backups}"; mkdir -p "$DEST"
LOG="$DEST/local-pull.log"; touch "$LOG"
log(){ echo "$(date -Is) $*" | tee -a "$LOG"; }
alert(){ [ -n "${ALERT_URL:-}" ] || return 0
  code=$(curl -sS -m 20 -o "$DEST/alert.out" -w '%{http_code}' "$ALERT_URL" -H 'Content-Type: application/json' \
    -d "{\"subject\":\"home backup FAILED ($(hostname))\",\"text\":\"$(tail -n 30 "$LOG" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' ')\"}") || code=000
  [ "$code" = 200 ] || log "ALERT DELIVERY http=$code"
}
trap 'alert' ERR

# Network bounds. The probe gets a SHORT leash: an unreachable local Docker must
# fail in ~5-15s, never minutes (that was the bug).
SYNC_BOUNDS="--contimeout 15s --timeout 300s --retries 2 --low-level-retries 3"
PROBE_BOUNDS="--contimeout 5s --timeout 10s --retries 1 --low-level-retries 1"

# preflight: S3 signing dies >15 min clock skew — warn BEFORE the first sync
date_hdr=$(curl -sI -m 10 https://t3.storage.dev 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ate: //p' | head -1)
dateskew=$(date -u -d "$date_hdr" +%s 2>/dev/null || echo "")
if [ -n "$dateskew" ]; then
  skew=$(( $(date -u +%s) - dateskew ))
  if [ "${skew#-}" -gt 900 ]; then
    log "WARNING: PC clock skew ${skew}s (>15 min) — S3 signing will fail until fixed (Windows: run fix-clock.cmd elevated / 'w32tm /resync /force')"
  fi
fi

# ONE probe for the local S3 target (fast-fail) — not one per provider.
s3_ok=0
if [ -n "${LOCAL_S3_REMOTE:-}" ]; then
  if rclone lsd "$LOCAL_S3_REMOTE" $PROBE_BOUNDS >/dev/null 2>&1; then
    s3_ok=1; log "local S3 '$LOCAL_S3_REMOTE' reachable"
  else
    log "local S3 target '$LOCAL_S3_REMOTE' unreachable (Docker Desktop off / RustFS stopped?) — skipped, folder copies still made"
  fi
fi

T0=$(date +%s)
for r in $CLOUD_REMOTES; do
  prov=$(echo "$r" | cut -d: -f1)
  log "sync $r -> folder"
  t0=$(date +%s)
  rclone sync "$r" "$DEST/$prov" --transfers 4 --checkers 8 $SYNC_BOUNDS
  log "done $r -> folder ($(( $(date +%s) - t0 ))s)"
  if [ "$s3_ok" = 1 ]; then
    log "sync $r -> $LOCAL_S3_REMOTE/$prov (local S3)"
    t0=$(date +%s)
    rclone sync "$r" "$LOCAL_S3_REMOTE/$prov" --transfers 4 --checkers 8 $SYNC_BOUNDS
    log "done $r -> $LOCAL_S3_REMOTE/$prov ($(( $(date +%s) - t0 ))s)"
  fi
done
log "pull OK (total $(( $(date +%s) - T0 ))s)"
