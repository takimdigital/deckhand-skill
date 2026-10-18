# 30 — Deploy an app (repo → Coolify app → envs → Postgres → HTTPS → smoke)

> Ported from the proven `vps-ops` runbooks. Commands run from the deckhand skill folder (`py` on Windows, `python3` elsewhere); `~/.vps-ops/` remains the server-credentials home these scripts read. `dh deploy …` wraps the common path.

**Purpose:** turn a Deckhand project into a running, HTTPS, auto-deploying app on the Coolify VPS.
**Use when:** first deployment of a project — "deploy / host / go live / put this on my VPS".
**Prerequisites:** `10-bootstrap-vps.md` done (Coolify live, token stored with `dh vault set COOLIFY_TOKEN`, `coolify` CLI context optional) · `20-domain-dns-ssl.md` A-record step done for `<domain>` **before** §5.
**Companion refs:** `40-change-pipeline.md` (every later change) · `50-ops-monitoring.md` (status/backups/incidents) · `00-user-checklist.md` (one-time browser approvals).

Run from git-bash. `py ops/scripts/...` paths are relative to the skill root. REST fallbacks need the vault in the shell: the `shell` line `dh vault list` prints (`$COOLIFY_URL`, `$COOLIFY_TOKEN`) — never echo the token.

## 0. Prerequisites on the repo

```bash
gh repo create <name> --private --source=. --push    # GitHub repo, pushed
```

If `gh` is missing/not authed → hand the user the `00-user-checklist.md` browser step, then continue from the push URL.
The app must be built by Deckhand (any path): a `Dockerfile` **or** a nixpacks-detectable app, listening on **port 3000**, with `.env.example` listing every variable.

Deploy-blocking repo traps (live-verified 2026-09-19 — check these BEFORE the first build):

- **Pin the package manager to the lockfile era.** No `packageManager` in package.json → Nixpacks
  pulls a current pnpm whose install can hard-fail. Pin it (e.g. `"packageManager": "pnpm@10.29.3"`
  for a lockfileVersion 9.0 repo) — corepack then uses the exact same version as CI.
- **A `pnpm-workspace.yaml` must be VALID** — either a real workspace (`packages:` non-empty) or the
  file must not exist. A placeholder file without `packages` fails with
  `ERROR packages field missing or empty` (this blocked the first build; fix = delete the file +
  add the pin).
- **Runtime CLIs live in `dependencies`, not `devDependencies`**, when the first-run steps use them
  (e.g. `drizzle-kit` for container-side migrations). `tsx` needs no entry — `npx -y tsx` fetches it
  on demand.
- **The `packageManager` pin is repo-wide — check the repo's own CI workflow too.** Pinning pnpm in
  package.json while a GitHub Actions job ALSO passes `version:` to `pnpm/action-setup` fails that job in
  seconds: `Multiple versions of pnpm specified` / `ERR_PNPM_BAD_PM_VERSION` (live-verified). One source of
  truth: keep the pin, delete `version:` from the action (it reads `packageManager` itself) — and once the
  pin lands, watch the run (`gh run list` → `gh run watch <id>`): CI is where competing pins surface.
  While touching the workflow, bump actions off Node-20-era majors (`checkout@v5`, `setup-node@v5`,
  `pnpm/action-setup@v6`) — the runner still executes them, but GitHub flags them on every run. When on
  those majors, keep the canonical step order **checkout → pnpm/action-setup → setup-node**:
  `setup-node@v5` auto-caches the pnpm store and must find `pnpm` on PATH — reversed, the job dies with
  `Unable to locate executable file: pnpm` (live-verified).

## 1. Pin the UUIDs (once per deploy)

```bash
coolify server list  --format json     # the localhost server → <S>
coolify project list --format json     # pick a project → <P>
```

REST: `GET /servers` (a `localhost` server exists right after install) · `GET /projects`. Create a project if none fits:

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/projects" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"<project-name>","description":"<one line>"}'      # → {"uuid":"<P>"}
```

## 2. Create the application

### 2a. Public repo (fastest)

```bash
coolify app create public --server-uuid <S> --project-uuid <P> --environment-name production \
  --git-repository https://github.com/<u>/<r> --git-branch main --build-pack nixpacks \
  --ports-exposes 3000 --format json
```

Expected: JSON for the new application → copy `uuid` as `<APP_UUID>`.

REST fallback (exact schema):

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/applications/public" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" -d '{
    "project_uuid": "<P>", "server_uuid": "<S>", "environment_name": "production",
    "git_repository": "https://github.com/<u>/<r>", "git_branch": "main",
    "build_pack": "nixpacks", "ports_exposes": "3000", "name": "<app-name>"}'
```

- Required: `project_uuid`, `server_uuid`, `environment_name` (or `environment_uuid`), `git_repository`, `git_branch`, `build_pack` ∈ {`nixpacks`,`railpack`,`static`,`dockerfile`,`dockercompose`}.
- Optional: `ports_exposes` (**string**, not a number), `name`, `description`, `domains` (**comma-separated string**), `destination_uuid`.
- *(Live-verified 2026-09-17: both `nixpacks` and `dockerfile` build packs build & serve correctly — a repo-level `Dockerfile` + `"build_pack":"dockerfile"` finished in 30 s.)*

### 2b. Private repo — two routes

**GitHub App (recommended — Coolify then owns the webhook, so auto-deploy is automatic).** In the Coolify UI: Sources → GitHub App → create → GitHub opens → the user installs it on the account (**one browser click, one-time**, see `00-user-checklist.md`). Then create the app with the GitHub App attached — exact CLI flags `[verify at live drill]`; REST route is the same `POST /applications/public` body, then `PATCH /applications/<APP_UUID>` with `{"github_app_uuid":"<uuid>"}` (a pinned PATCH field). Inventory: `GET /github-apps`, `GET /github-apps/{id}/repositories`, `GET /github-apps/{id}/branches`; delete with `DELETE /github-apps/{id}` — the numeric `id`, **not** the uuid (uuid → HTTP 500, live-verified 2026-09-17). Never delete the built-in `Public GitHub` app (system-wide; Coolify refuses it with 409).

**Deploy-key route (no browser click).** Dedicated key, registered with Coolify, then create with `private_key_uuid`:

```bash
ssh-keygen -t ed25519 -N "" -C "vps-ops-deploy" -f ~/.vps-ops/ssh/deploy_<app>
# build the body via file so the PEM never lands in shell history:
py -c "import json,pathlib; p=pathlib.Path.home()/'.vps-ops/ssh/deploy_<app>'; print(json.dumps({'name':'deploy-<app>','private_key':p.read_text()}))" > "$LOCALAPPDATA/Temp/coolify-key.json"
curl -sS -X POST "$COOLIFY_URL/api/v1/security/keys" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d @"$LOCALAPPDATA/Temp/coolify-key.json"                       # → uuid = <PK_UUID>
rm "$LOCALAPPDATA/Temp/coolify-key.json"
```

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/applications/private-deploy-key" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" -d '{
    "project_uuid": "<P>", "server_uuid": "<S>", "environment_name": "production",
    "git_repository": "git@github.com:<u>/<r>.git", "git_branch": "main",
    "build_pack": "nixpacks", "ports_exposes": "3000", "private_key_uuid": "<PK_UUID>"}'
```

Then add the matching **public** key as a read-only GitHub deploy key, and wire the webhook by hand for auto-deploy (§7). ⚠ On Windows, `gh` is a native exe and cannot read MSYS paths — pass the key via `"$(cygpath -m ~/.vps-ops/ssh/deploy_<app>.pub)"` (live-verified 2026-09-17). `GET /security/keys` · `GET|DELETE /security/keys/{uuid}`.
⚠ The private key stays in `~/.vps-ops/ssh/` and in Coolify — never in chat, a repo, or a command line.

## 3. Environment variables

Build `.env.production` locally from `.env.example` + the user's business keys (`KEY=value`, one per line). It is **gitignored** and never committed.

```bash
coolify app env sync <APP_UUID> --file .env.production     # upsert; existing keys untouched; nothing is ever deleted
py ops/scripts/coolify_api.py envs <APP_UUID>                  # verify: prints the key names present
```

Without the coolify CLI: `py ops/scripts/coolify_api.py envset <APP_UUID> --file .env.production` (it prints the key
names, never the values). REST fallback (exact schema — `{"data":[{key,value,(optional) is_preview|is_literal|is_multiline|is_shown_once}]}`),
with the body in a file so no secret reaches the command line or shell history:

```bash
# envs.json: {"data":[{"key":"DATABASE_URL","value":"…"},{"key":"STRIPE_SECRET_KEY","value":"…"}]}  (gitignored, deleted after)
curl -sS -X PATCH "$COOLIFY_URL/api/v1/applications/<APP_UUID>/envs/bulk" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" -d @envs.json
```

For one-off **non-secret** values, `py ops/scripts/coolify_api.py envset <APP_UUID> KEY=VALUE` is fine — but never put a secret value on a command line (shell history); secrets go through `--file` only. *(Live-verified: the bulk PATCH answers **201**, not 200 — accept any 2xx; changes apply on the next deploy.)*

## 4. Postgres (skip if the app brings its own DB)

```bash
coolify database create postgresql --server-uuid <S> --project-uuid <P> \
  --environment-name production --format json          # exact flags: [verify at live drill]
coolify database get <DB_UUID> --format json           # copy the internal connection URL
```

REST fallback (exact schema):

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/databases/postgresql" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"server_uuid":"<S>","project_uuid":"<P>","environment_name":"production",
       "postgres_user":"app","postgres_db":"app"}'   # optional: postgres_password (generated if omitted), destination_uuid
```

Required: `server_uuid`, `project_uuid`, `environment_name` (or `environment_uuid`). Inventory: `GET /databases`, `GET /databases/{uuid}`.

*(Live-verified 2026-09-17):* the POST response carries **`internal_db_url`** (password included — never echo it).
The container runs postgres `initdb` for ~2 min while the API reports **`exited:unhealthy` — that is NORMAL**; keep
polling `GET /databases/{uuid}` until `running:healthy`. Progress is visible via `GET /databases/{uuid}/logs`
(returns `{"logs": "..."}`, shows the initdb output). If it stays down, `POST /databases/{uuid}/start` exists.
Wire the URL into the app with the §3 bulk PATCH **from a file** (never on the command line), then redeploy.
If the container never materializes, or the status looks stuck (`exited:unhealthy` while docker says
otherwise): `POST /databases/{uuid}/start` builds it (live-verified, ~15 s) — then verify with
`docker ps` / `docker logs <db>` directly; Coolify's stored status field lags reality.
Strong end-to-end check: a `GET /db` route doing `SELECT 1` → `smoke <url>/db --contains db-ok` (validated).
Add the connection URL to `.env.production` as `DATABASE_URL=<url>`, re-run `coolify app env sync <APP_UUID> --file .env.production`. App and DB in the same project → Coolify hands you the internal Docker-network URL; no external access needed.

## 5. Attach the domain

Prerequisite: `<domain>` resolves to the VPS IP (`20-domain-dns-ssl.md`; `py ops/scripts/hostinger_api.py dns set-a <domain> --ip <IP> --names @,www`).

```bash
curl -sS -X PATCH "$COOLIFY_URL/api/v1/applications/<APP_UUID>" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"domains":"https://<domain>"}'
```

`domains` is a **comma-separated string** — several names: `"https://<domain>,https://www.<domain>"`. The same PATCH also accepts `name`, `build_pack`, `ports_exposes`, `git_commit_sha`, `github_app_uuid`.
Coolify issues the Let's Encrypt certificate on the next deploy (port 80 reachable first). Verify after §6: `curl -sSI https://<domain> | head -1` → `HTTP/2 200`.

## 6. First deploy + verify

```bash
coolify deploy uuid <APP_UUID>                                   # enqueue
py ops/scripts/coolify_api.py wait <APP_UUID> --timeout 900          # poll to terminal status
py ops/scripts/coolify_api.py smoke https://<domain> --expect 200 --contains "<a string only your app returns>"
```

REST deploy trigger — **query params only, no body**:

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/deploy?uuid=<APP_UUID>&force=false" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"
```

Expected:
- `wait` → `SUCCESS (1m32s, deployment <id>)`, exit **0**. Exit `3` = deployment failed → `40-change-pipeline.md` classification. Exit `5` = timeout → keep polling / read logs.
- `smoke` → `OK 200 https://<domain>`, exit **0**; exit `4` = fail. A bare 200 proves *something* answered — not that it's YOUR app: the `--contains` run (title, hero line, any string only the app returns) is the proof.

Statuses are tolerant: `{"success","finished"}` = OK · `{"failed","cancelled"}` = FAIL · **anything else = still running**. *Live-verified on Coolify 4.3.21: terminal OK = `finished`; the deployments endpoint returns `{"count":N,"deployments":[...]}` (newest first by `created_at`), which `ops/scripts/coolify_api.py` already normalizes.*

## 6b. First-run data steps — inside the running container (live-verified)

App env vars are already inside the container (Coolify injects them), so migrations and seeds run
straight through `docker exec` — no extra wiring:

```bash
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker ps --format '{{.Names}}' | grep <APP_UUID> | head -1"   # find the container
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec <container> sh -lc 'cd /app && npx drizzle-kit migrate'"
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec <container> sh -lc 'cd /app && npx -y tsx lib/db/seed.ts'"
```

**If the app's seed ships a development owner** (a known password in the README), that is now a live
admin: delete it and create the production owner in the same session —

```bash
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec <db-container> psql -U <dbuser> -d <db> -c \"DELETE FROM users WHERE email='test@test.com';\""
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP "docker exec <container> sh -lc 'cd /app && npx -y tsx scripts/create-owner.ts <real-email>'"
```

The owner script prints the generated password **exactly once** — store it with `dh vault set APP_OWNER_PASSWORD`
and hand it to the user out-of-band. Re-run the smoke afterwards; the site is then prod-clean.

## 7. Auto-deploy on push

- **GitHub App route → automatic.** Coolify owns the webhook; a push to `main` queues a deployment. Nothing to configure.
- **Other routes (public repo / deploy key) → add a repo webhook** pointing at the Coolify webhook URL shown in the app's UI (App → Webhooks). Exact URL pattern: **`[pin at first live run if not GitHub App]`**. Without it, every change needs the explicit deploy in `40-change-pipeline.md` step 4.

## 8. Session anchor — `<project>/.vps-ops.json`

```json
{"server_uuid":"<S>","project_uuid":"<P>","app_uuid":"<APP_UUID>","db_uuid":"<DB_UUID>","domain":"<domain>","coolify_url":"http://127.0.0.1:8000","track":"paid"}
```

No secrets — safe to commit. Commit it (`git add .vps-ops.json && git commit -m "chore: vps-ops anchor" && git push`): every later session, in any harness, re-enters the pipeline from this file alone. Track F adds `"region":"<oci-region>"`; `coolify_url` is the local end of the SSH tunnel (the dashboard is loopback-only, ref 10 Step 3b).
It is machine-minimal by design — for humans/agents with zero context, pair it with the `OPS.md`
handoff (§9), which they can actually read and act on.

## 9. Handoff file — `OPS.md` (write it at deploy time, keep it current)

The anchor (§8) is machine-minimal. Every deployed app ALSO gets **`OPS.md` at the repo root** — the
single file any future session (human or agent, zero context) reads FIRST, so nobody burns tokens
re-discovering the world. Start from `templates/ops/OPS.md`, fill it, commit it with the app.

It must carry: what the app is · live URL(s) + health checks · server + SSH command + provider/panel ·
Coolify ids + dashboard access (the tunnel command) · **a secrets inventory — locations only, NEVER values** ·
domain/DNS (registrar, zone, records) · the copy-paste everyday commands (deploy a change, migrate,
DB shell, owner re-key, logs, smoke) · a "do not do these" list (app-specific landmines — e.g. re-running
an app's dev seed against prod) · what is NOT set up yet (backups, payment keys). ≤ ~150 lines; update it
the moment topology changes (domain, ids, envs, host).

Tell the user it exists — it is the cold-start door into everything else.

## Done checklist

| # | Check | Command |
|---|---|---|
| 1 | app uuid pinned + committed | `cat .vps-ops.json` |
| 2 | env keys present | `py ops/scripts/coolify_api.py envs <APP_UUID>` |
| 3 | deployment terminal SUCCESS | `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 3` |
| 4 | HTTPS answers 200 + app content | `py ops/scripts/coolify_api.py smoke https://<domain> --expect 200 --contains "<app string>"` |
| 5 | auto-deploy wired | push a trivial commit → expect a new deployment (`[verify at live drill]` on non-GitHub-App routes) |
