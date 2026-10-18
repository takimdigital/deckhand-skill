# 70 — Auth & login email (verify + reset that actually arrives)

Load when: the app must send account email (signup verification, password reset, receipts) or needs auth added.
Read after `30-deploy-app.md`. Partner file: `references/ops/80-mcp-integrations.md` (MCP catalog; DNS section).

"No email = not a business" — this ref turns a deployed shell into something users can actually sign up for.

## 1. Auth verdict (Sept 2026, primary-source verified)

Rule: new auth = **Better Auth** (MIT, package `better-auth`, ≥1.7.5). Never Lucia (deprecated Mar 2025). Avoid Auth.js for new work.

| Option | Why / why not |
|---|---|
| **Better Auth** ✔ | Email/password + verification + reset + magic-link/OTP built in; Drizzle `pg` adapter; MIT; env-only config; self-host failure strings documented. |
| Auth.js (NextAuth v5) ✘ | Still beta after ~3 years (npm `beta` tag; `latest` = v4 line); security patches only; NO built-in password reset/verification — you DIY `authorize()`. Behind a proxy it dies with `UntrustedHost` without `AUTH_TRUST_HOST`. |
| Lucia ✘ | Deprecated — docs are a learning resource only. |

Boilerplate rule: do NOT half-wire two auth systems. If the boilerplate ships auth (e.g. custom jose sessions),
pick ONE path: (a) keep it and wire email into its flows, or (b) migrate fully to Better Auth.
Migration keeps existing users via custom `password.hash/verify` config; Better Auth adds its own `user/session/account/verification` tables — never run both in parallel.

### Better Auth — deploy facts (Coolify / Traefik / Next.js)

Env: `BETTER_AUTH_SECRET` (`openssl rand -base64 32`) · `BETTER_AUTH_URL=https://<domain>` (origin ONLY — scheme required, no path) · `DATABASE_URL`.
Schema: `npx @better-auth/cli@latest generate` → Drizzle migrate. Handler: `toNextJsHandler(auth)` at `app/api/auth/[...all]/route.ts`.
Pages: `/sign-up` `/sign-in` `/forgot-password` `/reset-password?token=` `/verify-email`.

Gotchas (each doc-verified or field-seen):
1. Always set `BETTER_AUTH_URL` — without it: `Could not get origin from request...`; scheme-less: `Invalid base URL... must include http://`. Emails/redirects build wrong behind TLS termination.
2. Origin check: wrong origin → HTTP 403 `Invalid origin` (`INVALID_ORIGIN`) + log `add <url> to trustedOrigins`. Traefik forwards the original Host by default → keep `advanced.trustedProxyHeaders` **false** unless the proxy rewrites Host.
3. Cookies: Secure flag follows `NODE_ENV=production` — keep it set in the container (TLS ends at Traefik).
4. Next 16 renamed `middleware.ts` → `proxy.ts`; `nextCookies()` must be the **LAST** plugin in `plugins[]`, or Server-Action sign-in can't set cookies.
5. Coolify: set `HOSTNAME=0.0.0.0` + `PORT=3000`; `NEXT_PUBLIC_*` = build-time (change ⇒ redeploy), secrets = runtime-only.
6. Do NOT set Auth.js's names (`AUTH_SECRET`, `AUTH_URL`, `AUTH_TRUST_HOST`) — Better Auth ignores them.

## 2. Email — the free chain (zero budget, Sept 2026 verified)

Default chain (route order): **Resend → Mailgun → Brevo** — the failover router tries them in this order.

| Provider | Free quota | Why in the chain |
|---|---|---|
| **Resend** | 3,000/mo · 100/day | React Email support; official MIT MCP; receiving also possible (counts against quota). |
| **Mailgun** | 100/day · 1 domain | Official Apache-2.0 MCP; no card; plain REST + SMTP. |
| **Brevo** | 300/day (no monthly cap) | Biggest reserve. Caveat: mandatory "Sent with Brevo" sticker on free sends; 1 user. |

Substitutes / rejects (one-liners): SMTP2GO 1,000/mo · 200/day — no branding, best Brevo replacement. Mailtrap 4,000/mo · 150/day. MailerSend 500/mo (manual approval). Loops 4,000/30d (branded). Plunk 1,000/mo (AGPL-3.0). Postmark 100/mo. ZeptoMail 10k credit / 6 mo. **Not free:** Sidemail (7-day trial only), SendGrid (60-day trial only), Mandrill (paid only).

Reading inbound replies (agent): **AgentMail** — free, 3,000/mo, official MCP, no card (best). Cloudflare Email Routing — free unlimited inbound (sending needs Workers Paid $5/mo).

**Brand mailboxes (`support@`, `infos@`) — agent-set end to end (live-verified flow):**
- **Scope first (probe, don't assume):** `GET /zones/{zone_id}/email/routing` — 200 = ready;
  `Authentication error` = the token lacks `Zone → Email Routing → Edit`. The fix is EDITING the
  existing token (My Profile → API Tokens → Edit → add the permission, ref 21) — never ask for a
  new token paste. One ask, batched, with the exact click path.
- **Then it is all agent work:** enable routing on the zone → add the owner's inbox as a
  **destination address** → create the custom-address rule `support@<domain>` → confirm receiving
  from DNS (`route1/2/3.mx.cloudflare.net` MX + SPF on the apex).
- **The flow's ONE user click:** Cloudflare mails a verification link to the destination inbox
  (first time per destination — non-designable). Batch it with other asks, ledger it
  (`ACTION NEEDED` + WHERE), and never block the phase on it — sending keeps working meanwhile.
- **Finish:** contact/help surfaces point at the brand address and product mail carries
  `Reply-To: support@<domain>` — the founder's personal inbox never appears on a live product.

**Human-once (ONE batched message):** create the free accounts (email signup, no card) and hand over one key each — then everything else is agent work.

Getting the RIGHT key (walk the user through exactly this — they will have no idea):

| Provider | Where in the dashboard | Which key + cautions |
|---|---|---|
| **Resend** | Sign up — the API key is prompted immediately (step 1; easiest). | At signup you get a **Sending-only** key — perfect for the router at runtime, but it CANNOT create or verify domains (`401 restricted_api_key`). For domain setup create a key with **Full access** (API Keys → Create; or edit the key's permission) — or add the domain in the dashboard and hand the records over. Until a domain is verified, Resend only delivers to your own signup address (`onboarding@resend.dev` = testing only — never ship it). |
| **Mailgun** | Sign in → Settings → **API security** → Create key. | Choose role **Developer** (enough to send; smallest privilege. Admin only if domain APIs need it later). Key shown once. |
| **Brevo** | Sign up → side menu **SMTP & API** → **API keys and MCP**. | Take the **API key** (`xkeysib-…`). The **MCP server key** beside it is ONLY for the optional MCP session (ref 80) — never for sending. **IPs**: the first API call from a new IP answers `401 unrecognised IP address` — AND Brevo emails the account owner a one-click **"Yes, authorize the new IP"** link (from account-alerts@t.brevo.com; legitimate — if you didn't initiate it, ignore). Both the setup machine AND the app server need authorising (manual fallback: app.brevo.com/security/authorised_ips). **Domain setup is fully API-able**: `POST /v3/senders/domains {"name":"mail2.<domain>"}` returns the records; after DNS, `PUT /v3/senders/domains/<name>/authenticate` → `authenticated:true, verified:true`. |

Hand-over — offer BOTH, default first (never say a bare "drop them into Coolify env"):
(a) *paste the keys to the agent* — it stores them in the vault (`dh vault set NAME` → this project's vault, chmod 600)
and sets the Coolify env vars; values are never echoed or committed again;
(b) *prefer to enter them yourself?* the agent gives a click-by-click guide: Coolify → the app →
**Environment Variables** → Add → exact name shown → paste value → Save.

## 3. Deliverability DNS — the part that makes mail arrive

Rule: **one sending SUBDOMAIN per provider** — `mail1.` Resend · `mail2.` Brevo · `mail3.` Mailgun,
From: `no-reply@mailN.<domain>` + `Reply-To: support@<domain>`. Why: each subdomain needs only ONE SPF include
(never risk the 10-lookup limit — RFC 7208 returns `permerror` for everyone when exceeded); provider changes touch one name; reputation isolated. Also forced by providers: Resend 403s when From isn't on a verified domain; Brevo requires the same subdomain for sender + authentication.

| Provider | Records on its subdomain (values from provider dashboard) |
|---|---|
| Resend (`mail1`) | Take the EXACT set the dashboard/API returns — live-verified shape: MX `send.mail1` → `feedback-smtp.<region>.amazonses.com` (10) · TXT `send.mail1` → `v=spf1 include:amazonses.com ~all` · TXT `resend._domainkey.mail1` (p=…) · CNAME `rsend.mail1` → `send.forge.rmta.net`. Verify via API after propagation; status flips to `verified` on its own check. |
| Brevo (`mail2`) | Exactly what `POST /v3/senders/domains` returns (live-verified): CNAME `brevo1._domainkey` + `brevo2._domainkey` → `b1/b2.<domain-with-dashes>.dkim.brevo.com` · TXT `<subdomain>` → `brevo-code:…` · TXT `_dmarc.<subdomain>` → `v=DMARC1; p=none; rua=mailto:rua@dmarc.brevo.com` (the authenticate call requires it — add it). No SPF/mx in this flow. |
| Mailgun (`mail3`) | TXT `v=spf1 include:mailgun.org ~all` · TXT `<selector>._domainkey` (p=…) · NO tracking CNAME (rewrites links — auth links must never be rewritten). Live-verified: SPF+DKIM alone flip the domain to `active` (~2 min after DNS) — the receiving MX and tracking CNAME stay off on a send-only subdomain. A Developer-role key can create and verify the domain. |

Root: `_dmarc` TXT `v=DMARC1; p=none; rua=mailto:dmarc@<domain>; adkim=r; aspf=r` → tighten to
`p=quarantine`/`reject` after 2–4 clean weeks. Verify each provider independently (bypass the chain): send to Gmail,
check `Authentication-Results` shows `dkim=pass` + `spf=pass` with that provider's domain. Keep ALL click/open tracking OFF everywhere.
Agent creates these records via the DNS API/MCP — ref 80.

Free-plan quirk (live-seen): Brevo-carried mail shows Gmail's **"Unsubscribe"** chip — Brevo attaches a
`List-Unsubscribe` header on free accounts (Resend/Mailgun sends don't). Cosmetic for auth mail since Brevo
is the overflow provider, but clicking it suppresses ONLY Brevo for that address — so keep Brevo LAST in
the chain. Toggle location in Brevo's account settings: [unverified — verify if a user asks].

## 4. Failover router — drop-in (`templates/ops/mail-router/`)

Copy `templates/ops/mail-router/` into the app: `send.ts` → `lib/email/`, run `schema.sql`, fill the env rows, wire per its README.
Rules it implements (do not deviate):
- ONE send path (`lib/email/send.ts`); chain order + caps from env; HTTP APIs, no vendor SDKs.
- Sequential failover, 8 s/attempt, first 2xx wins — the end user never sees the switch.
- Quota authority = Postgres (`email_quota`, atomic claim, UTC day) — redeploy-safe; caps set ~5% under the real cap.
- Failover ONLY on: 401 · 429 · 402 · 403-quota · 5xx · timeout/DNS error. NEVER on 400/422 /invalid-recipient /suppression — a bad address must not burn provider B.
- Idempotency: message key → `Idempotency-Key` header + `email_attempt` unique(message_key, provider) — a timeout→failover can't double-send silently.
- Alerting edge-triggered: one per (provider, reason) per 6 h; greppable `EMAIL_ALERT` line + optional webhook + owner email via the NEXT healthy provider; if none healthy — log + `/api/health` only.
- Weekly canary per provider (self-send, bypassing the chain) — catch a quietly-dead provider before it's needed.
- Read env INSIDE functions, never at module scope: Next.js imports route/action modules during `next build`, where mail envs don't exist yet — a top-level `new URL(process.env.APP_URL!)` breaks the CI build. The shipped template already reads lazily.
- Env changes need a **redeploy** (Coolify restart does not re-read env vars); a cached rebuild is ~75 s — the drain drill below is cheap to run for real.
- Live-verified 2026-09-19 on a Next.js + Postgres + Coolify deployment: full password-reset cycle end-to-end, plus the drill — drain the primary (`*_DAILY_CAP=0`) → the next provider carries it → restore → primary again — with `email_attempt` / `email_quota` / `email_alert_state` recording every hop. Agents can read their own outbound back from the provider API (e.g. Resend `GET /emails` with a full-access key) — an end-to-end reset test needs no inbox.

Auth wiring (Better Auth hooks — the framework never learns providers exist):

```ts
emailVerification: { sendVerificationEmail: async ({ user, url }) => {
  void sendEmail({ to: user.email, subject: "Verify your email", html: `<a href="${url}">Verify</a>`, text: url }, { key: `verify/${user.id}/${Date.now()}` });
} },
emailAndPassword: { sendResetPassword: async ({ user, url }) => {
  void sendEmail({ to: user.email, subject: "Reset your password", html: `<a href="${url}">Reset</a>`, text: url }, { key: `reset/${user.id}/${Date.now()}` });
} },
```

`void` = fire-and-forget (avoids timing attacks); failures live in `email_attempt` + the alert path.

## 5. Smoke test (auth + email) — part of "deployed"

1. Sign up a fresh address → verification mail arrives → link works → signed in.
2. Trigger reset → mail arrives → new password works; old sessions revoked.
3. `SELECT provider, outcome, count(*) FROM email_attempt GROUP BY 1,2;` — confirm which provider carried each mail.
4. Temporarily break provider A's key in env → next signup still delivers (live failover) → restore key.
5. Contact route: the help/contact surface points at the **brand mailbox** (not a personal address) and a
   message sent to it arrives; the founder's inbox is absent from every user-facing page.

## 6. Capacity to quote

Chain = **~480 sends/day at $0** (95 + 95 + 290 local caps). Sized by deliverability, not throughput.
Paid exit only when outgrown: change env + DNS, no code changes.
