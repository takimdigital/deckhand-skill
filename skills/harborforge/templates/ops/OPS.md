# OPS.md — <App name> (`<domain>`)

**Read this file first.** Everything a fresh session (human or agent) needs to work on this app is here or
pointed to from here. Machine-readable twin: `.vps-ops.json` (repo root). Skill: `vps-ops` (refs 30/40/50).

---

## TL;DR for an agent

1. App repo: `<repo URL>` (<visibility>) · local `<path>` · branch `<branch>`.
2. Live: **https://<domain>** — <one line: what this app is>.
3. Server: <provider + IP> — everything runs in **Coolify** (app `<APP_UUID>`).
4. SSH: `ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP>` (key-only).
5. Coolify dashboard is **loopback-only** → tunnel: `ssh -N -L 8000:127.0.0.1:8000 -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP>` → http://127.0.0.1:8000
6. Secrets: all in `~/.vps-ops/secrets/` (see inventory below). **Never commit secrets.**
7. Deploy a change: commit + push `<branch>` → redeploy via Coolify (command below) → smoke test.
8. Load skill `vps-ops` before ops work; ref 40 = change pipeline, ref 50 = logs/backups.
9. Human-pending items live in `~/.deckhand/pending.md` (project-tagged) — check it before asking the owner for anything, and record new asks there.

## What this app is

<one paragraph: product, stack, version pins, notable data/state>

## Live surfaces

| Thing | Value |
| --- | --- |
| App URLs | <apex + www> |
| SSL | <issuer, issued/expires, auto-renew by Coolify/Traefik> |
| Health checks | <3–4 URLs + expected codes> |
| Admin/owner | <email> — password location below; how to re-key (command below) |

## Server + platform

| Thing | Value |
| --- | --- |
| Provider | <provider, plan, panel URL, customer id> |
| Host | `<IP>` · <OS> · root, **SSH key-only** |
| SSH key | `~/.vps-ops/ssh/<key>` · host fingerprint `<SHA256:…>` |
| Coolify | <version> · server `<S>` · project `<P>` |
| App / DB | app `<APP_UUID>` · database `<DB_UUID>` (<user>/<db>) |
| App envs (in Coolify) | <KEY names only — never values> |
| Payments | <configured? where keys live — or "not configured" + what happens today> |
| Backups | <configured? where — or "NOT configured yet, next task"> |

## Domain + DNS

- Registrar: <…> · DNS on <host> (zone id `<…>`, proxy mode)
- Records: <A/AAAA/CNAME list → IP>
- Change DNS: <dashboard / API + where the token lives>

## Email (if the app sends mail — ref 70)

| Thing | Value |
| --- | --- |
| Chain + caps | `<EMAIL_CHAIN>` · caps in Coolify envs; sending subdomains + From per provider |
| Verify it works | <the app's mail-test/canary command> |
| Open items | <e.g. a provider whose server IP / domain isn't finished yet — say so plainly> |

## Secrets inventory — locations only, never values

| Secret | Where it lives |
| --- | --- |
| SSH private key (+ known_hosts) | `~/.vps-ops/ssh/` |
| API tokens (Coolify, DNS…) | `~/.vps-ops/secrets/env.sh` (`<VAR names>`) |
| App env file | `~/.vps-ops/secrets/<app>.env.production` |
| Owner password | `~/.vps-ops/secrets/<where>` (+ re-key command below) |
| Provider panel password | <password manager / rotate note> |

**Rotating:** <one line per secret — where to rotate it>.

## Everyday commands (copy-paste)

```bash
# load secrets (any shell that needs the API)
. ~/.vps-ops/secrets/env.sh

# find the current app container (suffix changes per deploy)
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP> \
  "docker ps --format '{{.Names}}' | grep <APP_UUID>"

# DEPLOY a change: push <branch>, then trigger the pipeline
curl -s -X POST "$COOLIFY_URL/api/v1/deploy?uuid=<APP_UUID>" \
  -H "Authorization: Bearer $COOLIFY_TOKEN"
# wait + smoke (from the vps-ops skill dir):
py <skill>/ops/scripts/coolify_api.py wait <APP_UUID> --timeout 900
py <skill>/ops/scripts/coolify_api.py smoke https://<domain>

# MIGRATIONS (only when new migrations exist)
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP> \
  "docker exec <app> sh -lc 'cd /app && npx drizzle-kit migrate'"

# DB shell
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP> \
  "docker exec -it <DB_UUID> psql -U <user> -d <db>"

# RE-KEY the owner (prints the new password exactly once — save it)
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP> \
  "docker exec <app> sh -lc 'cd /app && npx -y tsx scripts/create-owner.ts <email> --reset'"

# logs
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@<IP> "docker logs --tail 100 <app>"
```

## ⚠️ Do not do these

- <app-specific landmines — e.g. never run the dev seed against the live DB (it recreates a known-password
  owner); never open the Coolify dashboard to the public internet; never edit files inside the container>

## Provenance

<deployed when · by which skill/route · first pitfalls fixed + commit · where the fuller project status lives>
