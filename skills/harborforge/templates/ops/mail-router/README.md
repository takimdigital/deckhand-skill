# mail-router — multi-provider email failover (drop-in)

One `sendEmail()` that survives free-tier limits: sequential failover Resend → Mailgun → Brevo,
invisible to the end user, with owner alerts when a provider throttles. Full rationale: vps-ops ref `70-auth-and-email.md`.

## Install (agent, ~10 min)

1. `send.ts` → `lib/email/send.ts`; point its `sql` import at the app's Postgres client.
2. Apply `schema.sql` (psql, or port to Drizzle migrations).
3. Add the `.env.example` rows to Coolify env, with real keys + the app's domain.
4. Wire the auth framework's email hooks (snippet below). Any other product mail calls the same `sendEmail()`.
5. DNS: create the per-provider sending subdomains first (ref 70 §3) — sends fail verification until then.
6. Smoke: signup → verify mail → reset mail → `SELECT provider, outcome, count(*) FROM email_attempt GROUP BY 1,2;`

## Better Auth wiring

```ts
import { sendEmail } from "@/lib/email/send";

emailVerification: { sendVerificationEmail: async ({ user, url }) => {
  void sendEmail({ to: user.email, subject: "Verify your email",
    html: `<a href="${url}">Verify</a>`, text: url }, { key: `verify/${user.id}/${Date.now()}` });
} },
emailAndPassword: { sendResetPassword: async ({ user, url }) => {
  void sendEmail({ to: user.email, subject: "Reset your password",
    html: `<a href="${url}">Reset</a>`, text: url }, { key: `reset/${user.id}/${Date.now()}` });
} },
```

## Rules (from ref 70 — don't relax)

- Fail over ONLY on throttle/auth/transport errors; 400/422/bad-recipient = terminal (never burn the next provider's quota).
- Postgres is the quota authority (redeploy-safe); caps live in env at ~5% under the real free cap.
- Every body URL must match `APP_URL` (kills link-rewriting bugs at build time).
- Weekly canary: from a cron/route, send a self-addressed mail through each provider *directly* (bypassing the chain) — catches a silently-dead provider.
- Alerts: greppable `EMAIL_ALERT` log line + optional webhook + owner email via the next healthy provider; 6 h cooldown per (provider, reason).
- Verify from the outside: provider APIs can read back your own sends (e.g. Resend `GET /emails` with a full-access key) — an agent can complete a reset loop end-to-end without any inbox.
