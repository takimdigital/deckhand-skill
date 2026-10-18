# 70 — DEPLOY (proof, not hope)

**Objective:** the site is live on the owner's server and domain, with a passing smoke check, and the owner
holds a HANDOFF.md. **Output:** `dh phase done deploy`.

## First deploy (once per server/app) — runbooks in `references/ops/`
1. `00-user-checklist.md` — what only the owner can do (accounts, one key paste), batched.
2. Server: paid VPS → `10-bootstrap-vps.md` · $0 preview (Oracle Always Free) → `11-oracle-free-tier.md`
   (price sheet: `12-provider-price-sheet.md`).
3. Domain + TLS: `20-domain-dns-ssl.md` · free domain / Cloudflare → `21-free-domain-cloudflare.md`.
4. App: `30-deploy-app.md` (repo → Coolify app → env → Postgres → domain → first deploy → first-run data →
   `OPS.md`). Email: `70-auth-and-email.md`. Backups: `55-offsite-backups.md`. Uploads: `56-app-object-storage.md`.
5. Record the target: `dh deploy target --app <coolify-app-uuid> --url https://<domain>`.

## No domain yet ($0, or "just let me see it live")
A domain is optional for a preview. Coolify gives every app a generated address on `sslip.io`
(`http://<app-id>.<server-ip>.sslip.io`, shown on the app's page) when the server has no wildcard domain.
Use it as the target: `dh deploy target --app <uuid> --url http://<…>.sslip.io`. Setting the address to
`https://…` asks Traefik for a Let's Encrypt certificate; if issuance fails, keep http for the preview.
`dh deploy smoke` then carries a warning (`NO_TLS` / `PREVIEW_URL`), and HANDOFF.md labels the site
"preview". Hard rule: **no logins, payments or personal data over plain http**. Those features stay off
(or the owner adds a free or paid domain via `20-domain-dns-ssl.md` / `21-free-domain-cloudflare.md`) before G4.

## Every release
`dh deploy ship` = clean tree required → `git push` → Coolify deploy → wait for a terminal deployment of
THIS commit (a stale success is not success) → smoke (200 + brand name on the page) → `deploy.json`.
Failure → `dh deploy raw dlogs <uuid>`; rollback per `ops/40-change-pipeline.md`.

## Found on Google (after the domain is live)
`dh brief set domain=<domain>` → `dh seo apply` → `dh deploy ship` (pings IndexNow) → `dh seo audit --url https://<domain>`.
The owner's part — Search Console, Bing Webmaster Tools, Business Profile, reviews — is in PENDING.md with the exact
clicks; the agent adds the Search Console DNS record through the provider API when asked (`references/45-seo.md`).

## Handoff
`dh handoff` → HANDOFF.md (live URL, where each secret lives, everyday commands, bots, verify summary,
open PENDING items, licences). Present it; `dh phase done deploy`. Free-preview deployments are labeled
"preview" everywhere; `ops/60-migrate-to-paid.md` is the exit.
