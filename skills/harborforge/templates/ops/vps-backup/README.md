# vps-backup — the deep layer (restic → B2 + Tigris) — LIVE-VERIFIED 2026-09-20

One script, two offsite repos, weekly verified drill, plus a home-copy pull. Full rationale: ref `55-offsite-backups.md`.

## Install (agent, on the VPS)

1. `apt-get install -y jq` · restic: **upstream static binary** (apt lags) — `curl -fsSL -o /tmp/r.bz2 https://github.com/restic/restic/releases/latest/download/restic_<ver>_linux_amd64.bz2` (get `<ver>` from the releases API) → `bunzip2` (needs `bzip2` pkg) → `/usr/local/bin/restic`. rclone 1.75+ likewise if used for home/koofr paths.
2. Copy `coolify-backup.sh` → `/opt/backup/`, `chmod 700`. Keep it **LF** — Git on Windows can materialize CRLF and a CRLF script dies on the VPS (the repo pins `*.sh` to LF via `.gitattributes`); after any hand-copy, `bash -n /opt/backup/coolify-backup.sh` must pass. Create `/opt/backup/state`.
3. Create `/etc/backup/env` (root, 600, **LF line endings** — CRLF makes restic hang on a mangled repo path). The values drop straight out of the vault — either naming works (the script normalizes; live-hit 2026-09-21: the first backup died on the raw mismatch before this):
   - `B2_HOST` / `B2_BUCKET` / `B2_KEY_ID` / `B2_SECRET` / `B2_REGION` ← `~/.vps-ops/secrets/b2-scoped.env.sh` (`B2_APP_KEY_ID` / `B2_APP_KEY` aliases accepted; a `https://` prefix on the host is fine)
   - `TG_HOST` / `TG_BUCKET` / `TG_KEY_ID` / `TG_SECRET` ← `~/.vps-ops/secrets/backup.env.sh` (`TIGRIS_BUCKET` / `TIGRIS_ACCESS_KEY_ID` / `TIGRIS_SECRET_ACCESS_KEY` aliases accepted)
   - plus `ALERT_URL`, the `VOLUMES` allowlist, `DB_CONTAINERS` (names = the plain uuids), `SANITY_DB`/`SANITY_SQL`.
4. Create the two repos ONCE (`restic init` with per-repo env — see the wrappers in the script) — then **escrow both passwords in the owner's password manager**. Lost password = lost backups, forever.
5. Run a first manual round-trip: `coolify-backup.sh backup && coolify-backup.sh verify` — only after BOTH pass, enable timers.
6. systemd (preferred over cron):

```ini
# /etc/systemd/system/coolify-backup.service
[Unit]
Description=Coolify offsite backup
[Service]
Type=oneshot
ExecStart=/opt/backup/coolify-backup.sh backup

# /etc/systemd/system/coolify-backup.timer
[Unit]
Description=Nightly Coolify offsite backup
[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
[Install]
WantedBy=timers.target
```

**First-fire proof (required before “backups live”):** after enabling the timers, fire both units by
hand — `systemctl start coolify-backup.service && systemctl start coolify-verify.service` — and require
`rc=0` + `status.json` ok + a fresh snapshot on EACH repo + the verify PASS email. The units run with
no `$HOME` and a minimal env: a manual script run proves only the script; **only the units prove the
schedule** (live-hit 2026-09-21: the first scheduled nightly died while every manual drill passed).

Weekly verify = a second pair (`coolify-verify.service` → `ExecStart=/opt/backup/coolify-backup.sh verify`, `coolify-verify.timer` → `OnCalendar=Sun *-*-* 04:30:00`).
Enable: `systemctl daemon-reload && systemctl enable --now coolify-backup.timer coolify-verify.timer`.

## Drill findings baked into this template (2026-09-20)

- **Coolify DB users are per-container** (`coolify-db` → `coolify`; app DBs → the app name) — the script auto-detects via `printenv`; never assume `postgres`.
- **Executions endpoint can be empty** for on-demand Coolify dumps — list the bucket; the object is the proof. Re-triggering via `PATCH {backup_now:true}` is unreliable — DELETE + re-POST the config.
- **Wrong bucket class = 0-byte reads**: a GLACIER-class bucket lists objects (HEAD size correct) but every GET >~1 KB returns HTTP 200 + 0 bytes to every client (rclone `unexpected EOF`, python `IncompleteRead`). Create buckets via API (default STANDARD) — never accept a console default without verifying with a 512 KB round-trip (`ops/scripts/tigris_bucket.py` does exactly that).
- **restic has no per-repo credentials** — inject `AWS_ACCESS_KEY_ID/SECRET` + `AWS_DEFAULT_REGION` per invocation (Tigris `auto`, B2 the bucket region).
- **The mail router rejects link-less bodies** — the alert route must append the app URL.

## A home copy (ref 55 §7 — choices ② and ③)

`local-pull.sh` **v3** runs on the USER'S machine (never the VPS): it mirrors the backup buckets down (restic repos included → a full local restore works) into a folder and — when reachable — the local RustFS S3. (The "pull straight from the VPS" option is the documented manual ssh recipe in ref 55 §7.) Schedulers: plain cron / **Windows Task Scheduler** (`run-pull.cmd` template + `schtasks /Create /TN … /SC DAILY /ST 10:00`) / an **agent cronjob** (Hermes needs its gateway installed & running or scheduled fires never happen). Windows notes: native exes need `C:/…` paths; **check the PC clock** — SigV4 fails ("Timestamp … is in the future") at >15 min skew (ready-made `fix-clock.cmd`; or `w32time` + `w32tm /resync /force`, elevated). The pull also runs a clock-skew preflight and warns before signing breaks.

**Windows Task Scheduler — four silent killers (all live-hit 2026-09-20):** ① **bash path** — discover it (`where bash`); `C:\Windows\System32\bash.exe` is the WSL launcher, not MSYS, and Git's default path may not exist at all. ② **HOME** — pin it in the `-lc` string (`HOME=/c/Users/<you>`), or MSYS falls back to `/home/<user>`, the vault env file is missing → silent exit 1. ③ **PATH** — prepend `%USERPROFILE%\bin` (rclone/restic live there). ④ **conditions** — battery flags default to true (laptop on battery = `0x800710E0` refused); set both false + `StartWhenAvailable=true` (a missed run catches up after boot) + `ExecutionTimeLimit PT1H`. The `.cmd` must be **CRLF + ASCII only** (a stray `\b` escape byte in a path = "filename … syntax is incorrect"). **Always fire once (`schtasks /Run`) and require `Last Result: 0` + a fresh `pull OK` — an unverified schedule is not a backup.**

**Local S3 variant (the UI option) — verified live 2026-09-20:** drop `rustfs-local.compose.yml` (+ a `.env` with `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY`) anywhere on the machine and `docker compose up -d` → S3 API at `http://127.0.0.1:9000` (health `curl -fsS http://127.0.0.1:9000/health`), console at `http://localhost:9001` (the SPA lives at `/rustfs/console/`). Add an rclone remote (`provider=Minio`, `endpoint=http://127.0.0.1:9000`, `force_path_style=true`) and `LOCAL_S3_REMOTE=rustfs:<bucket>` to the env file — the pull mirrors each provider into it; **target down = a logged skip, never a failed run**. Docker Desktop is free for personal use (alternatives: Podman Desktop / Rancher Desktop / plain WSL2 docker).

## Provider traps

- **B2:** lifecycle “keep only the last version” (set at bucket create, `ops/scripts/b2_setup.py`) — restic's S3 backend hides deletions; hidden versions keep accruing. Card-less accounts are hard-capped — alert on `cap_exceeded`.
- **Tigris:** create buckets via API (STANDARD); deleted names sit in a ~10-min cooldown (`409 BucketInaccessible`) — pick a new name. 5 GB free — size the pruned set accordingly.
- **systemd runs have NO `$HOME`** (live-hit 2026-09-21): restic 0.19 hard-fails (`unable to open cache: unable to locate cache directory: neither $XDG_CACHE_HOME nor $HOME are defined`) — the FIRST scheduled run dies while every manual SSH test passes. The script pins `RESTIC_CACHE_DIR` itself; keep that line.
- **Failure emails tail the append-only LOG** (live-hit 2026-09-21): a step that doesn't tee its output leaves `die()`'s email showing the PREVIOUS run's tail (the failed nightly emailed the last drill's output — useless for diagnosis). Every restic step appends to `$LOG`; every run opens with a `=== run start ===` marker.

## What the harness checks (dead-man's switch)

SSH in and read `/opt/backup/state/status.json` — `{status, step, ts}`, overwritten every run (`status=ok` + the phase in `step`). Freshness comes from the artifacts themselves: `restic … snapshots --latest 1` < 26 h for the backup, and the weekly drill's own PASS/FAIL email < 8 d. Silence = failure; alert the owner through the same mail chain.
