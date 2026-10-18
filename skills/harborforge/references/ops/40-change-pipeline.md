# 40 — The change pipeline (implement → push → deploy → wait → smoke → report)

**Purpose:** the canonical loop for every change after the first deploy. This is where the project will actually live.
**Use when:** the user asks for any change to an already-deployed app ("add X", "fix Y", "ship this", "make the button green") — including when they simply hand you a project directory that contains `OPS.md`/`.vps-ops.json` (that IS a deployed app; local-only is never done).
**Prerequisites:** `30-deploy-app.md` completed; `<project>/.vps-ops.json` exists in the repo.
**Companion refs:** `30-deploy-app.md` (app/env/domain setup) · `50-ops-monitoring.md` (logs, status, incidents) · `20-domain-dns-ssl.md` (DNS/SSL failures).

## The loop

```
1. read  <project>/.vps-ops.json           → server/project/app/db uuids + domain
2. implement the change                    (inspect → change → `dh verify`)
3. commit + push to main
4. deploy: trigger it explicitly           (a loopback dashboard gets NOTHING from GitHub — §4)
5. py ops/scripts/coolify_api.py wait <APP_UUID> --timeout 900 --expect-commit $(git rev-parse --short HEAD)
6. py ops/scripts/coolify_api.py smoke https://<domain> --expect 200 --contains "<marker from this change>"
6b. release: tag + GitHub Release          (runtime changes only — §6b)
7. report — 5-line template below
   └─ failure at 5 or 6 → logs → classify → fix-forward (max 2) or rollback
```

## Step by step

**1 — Anchor.** Every session starts here; never re-derive UUIDs by hand.

```bash
cat .vps-ops.json        # {"server_uuid","project_uuid","app_uuid","db_uuid","domain","coolify_url"} — no secrets
```

**2 — Implement.** Buildout-pack protocols (inspect → change → test). The change must be green locally before any push: red tree never gets deployed.

**2b — Checkpoints (mandatory for every multi-file or open-ended change).**
Restate the work as passes the first time you touch the repo: `Pass 1: <coherent milestone> → ship
(steps 3–6) · Pass 2: <next> → ship …`. After every milestone: run the local verify (cheapest:
`pnpm typecheck` / the app's test script — early, not at the end), **commit the checkpoint**, and move
on. Ship each wide pass end-to-end before starting the next — a "do X and also fix Y etc." request is
passes, not one hour of uncommitted edits. Why this is a hard rule: runs get interrupted (model
streams stall, sessions are stopped, machines sleep) — **an interrupted run must leave committed,
shippable work; uncommitted work is work lost**. Never go more than one milestone without a commit.

**3 — Commit + push.**

**Pre-flight when `package.json` or the lockfile changed:** deploys install with `--frozen-lockfile` and die on any drift (`ERR_PNPM_OUTDATED_LOCKFILE`) — check BEFORE the push, repair in the same push:

```bash
CI=true pnpm install --frozen-lockfile      # exit 0 = lockfile matches package.json; exit 1 + ERR_PNPM_OUTDATED_LOCKFILE = repair first
CI=true pnpm install --no-frozen-lockfile && git add pnpm-lock.yaml   # the repair (CI=true alone stays frozen — the flag is required)
```

```bash
git add -A && git commit -m "<message>" && git push origin main
git rev-parse --short HEAD        # record the short sha for the report
```

**4 — Deploy — trigger it explicitly.**

The dashboard is loopback-locked (our default), so GitHub webhooks cannot reach Coolify: **the push
alone deployed nothing.** Trigger the build, then confirm the newest deployment is YOUR commit:

```bash
py ops/scripts/coolify_api.py deploy <APP_UUID>            # in-repo script, tunnel-aware
# fallback, REST — query params only, no body:
curl -sS -X POST "$COOLIFY_URL/api/v1/deploy?uuid=<APP_UUID>&force=false" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"

py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 3   # newest entry's commit == your short sha
```

(An app wired to a GitHub App integration on a PUBLICLY reachable Coolify may auto-queue on push —
confirm via `deployments`; never assume.)

**Tunnel preflight (built in).** The dashboard is loopback-only on the VPS — every command here goes through the SSH tunnel, and `deploy` now **health-checks the tunnel and starts it automatically** when `VPS_SSH_HOST`/`VPS_SSH_KEY` are set (vault env; one-time setup — otherwise it prints the exact manual command). If any call ever returns `10061/refused`: run `py ops/scripts/coolify_api.py tunnel` — it health-checks and starts it; `tunnel OK` means go.

**5 — Wait for a terminal status.**

```bash
py ops/scripts/coolify_api.py wait <APP_UUID> --timeout 900 --expect-commit $(git rev-parse --short HEAD)
#   polls /deployments/applications/{uuid} AND binds the result to YOUR commit: a finished
#   deployment with a different commit is treated as stale (your push may not have registered
#   yet) and polling continues; SUCCESS then prints the commit it verified.
#   live-verified (Coolify 4.3.21): response wrapper {"count":N,"deployments":[...]}; terminal OK status = "finished".
#   deploy trigger returns {"deployments":[{ "message", "resource_uuid", "deployment_uuid" }]} — grab the uuid for logs/tracking.
```

**Bind the wait to YOUR commit.** `wait` polls the *newest* deployment — called too early it could see the *previous* finished build (a bare smoke 200 can't tell). Pass `--expect-commit <short-sha>` (you have it from §3) and the wait only returns for your build. Belt: `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 1` and compare its `commit`.

| exit | meaning |
|---|---|
| 0 | `SUCCESS (<Ns>, deployment <id>, commit <sha>)` — terminal OK **and** (with `--expect-commit`) the sha is yours |
| 3 | `DEPLOY FAILED (<status>)` — build failed → classification table |
| 5 | `TIMEOUT` — still running or stuck; check logs, do not assume success |

Deployment statuses are tolerant by design: `{"success","finished"}` = OK · `{"failed","cancelled"}` = FAIL · **anything else = still running**. Deployment objects carry `deployment_uuid`, `status`, `created_at`, `commit`, `commit_message`, `rollback`, `logs` — list them with `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 5`; read the newest one's log directly with `py ops/scripts/coolify_api.py dlogs <APP_UUID>` (`--grep`/`--deployment`/`--tail`).

**6 — Smoke test the live URL.**

```bash
py ops/scripts/coolify_api.py smoke https://<domain> --expect 200
py ops/scripts/coolify_api.py smoke https://<domain> --expect 200 --contains "<marker from this change>"
```

Exit `0` = pass, `4` = fail (wrong status, missing marker, or connection error). A passing smoke is the only proof the change is live.

**6b — Release (runtime changes only, once smoke is green).**

A shipped change is a *published* change — the user's repo should show it. Docs-only commits (README/OPS notes): no deploy, no release; say so in the report.

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
gh release create vX.Y.Z --latest --title "<Product> vX.Y.Z" --notes "<≤8 bullets of what the user sees>"
```

> **gh target trap:** with a second remote (a starter kept as `upstream`), `gh` resolves the repo by
> itself and can aim at upstream (404 / wrong repo). Run `gh repo set-default <owner>/<repo>` once in
> repo, or pass `-R <owner>/<repo>` — the repo-presence kit prints the set-default step for you.

- **Design gate (optional — user-facing changes):** run `dh verify` (routes, honesty, a11y rows) before this release step and carry one `Verify:` line in the receipt.

- **SemVer judged by the user's world:** patch = fixes/copy/UX polish · minor = new features/flows · major = relaunch/breaking. First release in an app's life = **v1.0.0**.
- **Before choosing the version: read the tags, not package.json.** Run `gh release list --limit 5` + `git tag --sort=-v:refname | head -5` FIRST — the next version is one step above the NEWEST existing tag. `package.json`/README drift (live-seen: releases at v1.2.0 while package.json said 1.0.0 → a numerically-older "latest" release got cut and had to be re-cut); if they disagree with the tags, fix them in the release commit. Already cut a wrong tag? `gh release delete <tag> --yes` + `git tag -d <tag>` + `git push origin :refs/tags/<tag>`, then re-cut.
- **Notes:** ≤ 8 short bullets, user-facing only — features, fixes, prices, availability — plus one line for anything the user must still do. No internal narration, no file lists, no fluff.
- Keep `package.json` `version` == newest tag; keep the README's status line current.
- **The first release also runs the one-time repo-presence pass — via the kit, never hand-built:** copy `templates/ops/repo-presence/repo.example.json`, fill the content (facts only, our style), then `py ops/scripts/repo_presence.py init repo.json --dir <project> --gh` renders README/LICENSE/package.json metadata and sets the repo description + topics. Re-run whenever the repo's face drifts. A repo the user is proud to open is part of "shipped".

**7 — Report — the 5-line receipt (plus the optional `Design:` line when the design gate ran):**

```
Change:     <short-sha> <commit subject>
Deployment: <deployment_uuid> (<duration, e.g. 1m32s>)
URL:        https://<domain>
Status:     SUCCESS
Smoke:      OK 200 https://<domain>
```

The user reads this block as the **receipt** — carry it in every shipped-pass report even when nobody
asked; it is also the answer to "did it deploy?" (a receipt, not reassurance).

## Hard rules

1. Never deploy a red tree — local tests pass first.
2. Never report "deployed" without a terminal deployment status (`wait` exit 0).
3. Never report "deployed" without a passing smoke check.
4. Max **2** fix-forward attempts, then roll back. No unbounded retry loops.
5. Secrets live only in Coolify envs (`30-deploy-app.md` §3) — never echoed, never on a command line, never committed.
6. A change that needs a new env var: sync first (`coolify app env sync <APP_UUID> --file .env.production`), then deploy.
7. **Checkpoint rule (§2b):** commit at every coherent milestone; never end a turn with more than one milestone of uncommitted edits; wide requests ship in passes. An interrupted run must leave shippable work.
8. **Release rule (§6b):** a runtime change isn't done until it's tagged + released once smoke is green; docs-only changes deploy nothing and release nothing.
9. **Masked secrets in reads:** tool output masks credential-looking strings (`Bearer …`, API keys → `***`). Never retype such a line from a read into an edit — match the surrounding text instead; after editing a credential-bearing file run `grep -n '\*\*\*' <file>` + the build. A pasted mask passes review and fails at runtime (live-seen on an email-sender auth line, caught only by `tsc`).
10. **Verify gate:** on a user-facing change run `dh verify` before the release step; a red blocking row blocks the release like a red build.
11. **Version truth = the tags:** before any release read `gh release list`; the next version sits one step above the newest existing tag; keep `package.json` + README synced in the release commit (drift live-seen: releases at v1.2.0 vs package.json 1.0.0).

## Failure classification

| Symptom | Where to look | Command / action |
|---|---|---|
| Build error (nixpacks/docker step fails) | deployment logs | `py ops/scripts/coolify_api.py dlogs <APP_UUID>` — newest deployment's log tail; `--grep ERR_PNPM` / `--deployment <id>` to pin; fallback `deployments --limit 5` → the row's `logs` field |
| Build dies fast at install (`ERR_PNPM_OUTDATED_LOCKFILE`) | lockfile drifted from package.json (a pin edited after `pnpm add`; `CI=true` installs are frozen by default) | `dlogs <APP_UUID> --grep ERR_PNPM` → repair locally: `CI=true pnpm install --no-frozen-lockfile` → commit `pnpm-lock.yaml` → push → redeploy |
| Deploy OK but the app exits/crashes at runtime | application logs | `py ops/scripts/coolify_api.py logs <APP_UUID> --lines 200 --timestamps` · `coolify app logs <APP_UUID> --lines 200 --show-timestamps` · `GET /applications/{uuid}/logs?lines=200&show_timestamps=false` |
| `wait` OK but smoke 404 / 502 / connection refused | crash-looping container (check app logs), or port/domain misconfig | `ports_exposes` must be `"3000"` (string), `domains` correct (`30-deploy-app.md` §2/§5); restart the app |
| Smoke cannot resolve the name | DNS not propagated | `20-domain-dns-ssl.md` checks; `nslookup <domain> 1.1.1.1` must equal the VPS IP |
| TLS/cert error in smoke | Let's Encrypt pending or port 80 blocked | wait 2–3 min, redeploy; then `20-domain-dns-ssl.md` |
| Missing/blank env var at runtime | envs | `py ops/scripts/coolify_api.py envs <APP_UUID>` (key names only) → re-sync from `.env.production` |

## Rollback (exact)

```bash
coolify app rollback images <APP_UUID>              # list rollback candidates (previous images/commits)
coolify app rollback run <APP_UUID> --commit <last-good-sha>
```

REST equivalent (pinned body):

```bash
curl -sS -X POST "$COOLIFY_URL/api/v1/applications/<APP_UUID>/rollback" \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"commit": "<last-good-sha>"}'
# candidates: GET /applications/{uuid}/rollback-images → copy the `tag` verbatim (FULL 40-char sha)
# ⚠ short shas FAIL here (the rollback deployment dies in the clone stage) — use the full tag; rollback
#   reuses the existing image, so it completes in seconds (live-verified 2026-09-17). Git-native alternative
#   that always works and keeps repo HEAD == deployed artifact: `git revert <bad-sha> && git push && redeploy`.
```

Then **always** re-run wait + smoke and report the rollback:

```bash
py ops/scripts/coolify_api.py wait <APP_UUID> --timeout 900
py ops/scripts/coolify_api.py smoke https://<domain> --expect 200
```

```
Change:     <bad short-sha> <commit subject> — reverted
Deployment: <deployment_uuid> (<duration>)
URL:        https://<domain>
Status:     ROLLED BACK to <last-good-sha>
Smoke:      OK 200 https://<domain>
```

Find `<last-good-sha>`: newest entry from `py ops/scripts/coolify_api.py deployments <APP_UUID> --limit 10` whose status is in `{success, finished}` (its `commit` field), or `git log --oneline`.

## Decision rule: fix-forward vs rollback

| Situation | Do |
|---|---|
| Clear one-line cause (typo, missing env var, config) | fix-forward once, re-run the loop from step 3 |
| Second failure with an unclear cause | roll back, then diagnose with logs in a follow-up change |
| Failure only in prod (works locally) | capture logs first, then roll back — do not iterate blind on prod |
