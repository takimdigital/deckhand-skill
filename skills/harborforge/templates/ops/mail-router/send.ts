// lib/email/send.ts — the ONLY send path in the app (auth + product mail).
// Multi-provider failover across free tiers. HTTP APIs only — no vendor SDKs.
// Postgres is the quota authority. Chain order + caps come from env (vps-ops ref 70).
// Template: copy to lib/email/send.ts · point the sql import at your client · run schema.sql.
//
// Env is read lazily, NOT at module scope: `next build` imports route/action
// modules in CI where none of the mail vars exist, and a top-level
// `new URL(process.env.APP_URL!)` would break the build. Lazy reads turn a
// missing config into a clear runtime error instead.
import { sql } from "./db"; // your Postgres client (tagged-template SQL)

type Mail = { to: string; subject: string; html: string; text: string; from?: string };
type Adapter = { id: string; cap: number; from: string; send(m: Mail, key: string): Promise<void> };

const appOrigin = () => {
  const url = process.env.APP_URL || process.env.BASE_URL;
  if (!url) throw new Error("email: APP_URL (or BASE_URL) is not set");
  return new URL(url).origin;
};
const timeoutMs = () => Number(process.env.EMAIL_TIMEOUT_MS ?? 8000);

// ---------- adapters (~12 lines each; a 4th provider = one adapter + one env row) ----------
const parseFrom = (s: string) => { const m = s.match(/^(.*)<(.+)>$/); return m ? { name: m[1].trim(), email: m[2].trim() } : { name: "", email: s.trim() }; };
async function postJson(url: string, headers: Record<string, string>, body: unknown, key: string) {
  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": key, ...headers },
    body: JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs()) });
  if (!res.ok) throw Object.assign(new Error(`http ${res.status}`), { status: res.status, body: await res.text() });
}
const ADAPTERS: Record<string, Adapter["send"]> = {
  resend: (m, key) => postJson("https://api.resend.com/emails", { authorization: `Bearer ${process.env.RESEND_API_KEY}` },
    { from: m.from, to: [m.to], subject: m.subject, html: m.html, text: m.text }, key),
  mailgun: async (m, key) => {
    const form = new URLSearchParams({ from: m.from!, to: m.to, subject: m.subject, text: m.text, html: m.html, "o:tracking": "no" });
    const res = await fetch(`https://api.mailgun.net/v3/${process.env.MAILGUN_DOMAIN}/messages`, { method: "POST",
      headers: { authorization: "Basic " + Buffer.from(`api:${process.env.MAILGUN_API_KEY}`).toString("base64"), "Idempotency-Key": key },
      body: form, signal: AbortSignal.timeout(timeoutMs()) });
    if (!res.ok) throw Object.assign(new Error(`http ${res.status}`), { status: res.status, body: await res.text() });
  },
  brevo: (m, key) => { const f = parseFrom(m.from!); return postJson("https://api.brevo.com/v3/smtp/email", { "api-key": process.env.BREVO_API_KEY! },
    { sender: f.name ? f : { email: f.email }, to: [{ email: m.to }], subject: m.subject, htmlContent: m.html, textContent: m.text }, key); },
};

const chain = (): Adapter[] => (process.env.EMAIL_CHAIN ?? "resend,mailgun,brevo").split(",").map((id) => ({
  id, cap: Number(process.env[`${id.toUpperCase()}_DAILY_CAP`] ?? 0), from: process.env[`${id.toUpperCase()}_FROM`] ?? "", send: ADAPTERS[id] }));

const log = (k: string, p: string, o: string, e: string) =>
  sql`INSERT INTO email_attempt (message_key, provider, outcome, error) VALUES (${k}, ${p}, ${o}, ${e.slice(0, 500)})`;

// Link integrity: every URL in the body must be ours — providers must never rewrite auth links.
function assertLinks(m: Mail) {
  const origin = appOrigin();
  const urls = [...`${m.html} ${m.text}`.matchAll(/https?:\/\/[^\s"'<>)\]]+/g)].map((x) => x[0]);
  if (!urls.length) throw new Error("email: body has no link");
  for (const u of urls) if (new URL(u).origin !== origin) throw new Error(`email: foreign link ${u}`);
}

// Atomic per-provider / per-UTC-day quota claim; no row back ⇒ provider exhausted today → next in chain.
const claim = async (p: Adapter) => (await sql`INSERT INTO email_quota (provider, utc_day, sent)
  VALUES (${p.id}, ${new Date().toISOString().slice(0, 10)}, 1)
  ON CONFLICT (provider, utc_day) DO UPDATE SET sent = email_quota.sent + 1
  WHERE email_quota.sent < ${p.cap} RETURNING sent`).length === 1;

// Throttle/quota (failover + alert) vs message-level (terminal — never burn the next provider's quota).
const degraded = (s: number, b: string) => s === 429 || s === 402 || (s === 403 && /quota|limit|credit/i.test(b)) ||
  /daily_quota_exceeded|monthly_quota_exceeded|not_enough_credits|limit exceeded|throttl/i.test(b);
const permanent = (s: number, b: string) => s === 400 || s === 422 || /invalid[_ ](to|recipient|email)|no such user|suppress/i.test(b);

export async function sendEmail(mail: Mail, ctx: { key: string }): Promise<{ provider: string }> {
  assertLinks(mail);
  let lastErr: unknown;
  for (const p of chain()) {
    if (!p.send) continue;
    if (!(await claim(p))) { void alert(p, "local daily cap reached"); continue; }
    try {
      await p.send({ ...mail, from: p.from }, ctx.key); // adapters forward Idempotency-Key: ctx.key
      await log(ctx.key, p.id, "sent", "");
      return { provider: p.id };
    } catch (e) {
      const err = e as { status?: number; body?: string; message?: string };
      lastErr = e;
      const s = err.status ?? 0;
      const body = String(err.body ?? err.message);
      await log(ctx.key, p.id, permanent(s, body) ? "permanent" : "fail", body);
      if (permanent(s, body)) throw e; // bad recipient: terminal, never retry on the next provider
      void alert(p, degraded(s, body) ? "throttled/quota" : `transport ${s || "timeout"}`);
    }
  }
  throw lastErr ?? new Error("email: chain exhausted"); // caller falls back to its normal retry UX
}

// Edge-triggered: one alert per (provider, reason) per 6 h; owner mail goes via the NEXT healthy provider.
async function alert(p: Adapter, reason: string) {
  try {
    const first = (await sql`INSERT INTO email_alert_state (provider, reason, at) VALUES (${p.id}, ${reason}, now())
      ON CONFLICT (provider, reason) DO UPDATE SET at = now()
      WHERE email_alert_state.at < now() - interval '6 hours' RETURNING at`).length > 0;
    console.warn(`EMAIL_ALERT provider=${p.id} reason=${reason}`); // greppable line, always
    const webhook = process.env.ALERT_WEBHOOK_URL;
    if (webhook) void fetch(webhook, { method: "POST", body: JSON.stringify({ provider: p.id, reason }) }).catch(() => {});
    if (!first) return; // inside cooldown
    const owner = process.env.OWNER_ALERT_EMAIL;
    if (!owner) return;
    const c = chain();
    const failedAt = c.findIndex((x) => x.id === p.id); // start AFTER the failed provider, by id
    for (const q of c.slice(failedAt + 1)) {
      if (!q.send) continue;
      try {
        await q.send({
          to: owner,
          subject: `[mail] ${p.id}: ${reason} — fallback active`,
          text: `Provider "${p.id}" stopped accepting mail (${reason}).\nMessages continue through the next provider in the chain automatically — no action needed.\nIf this repeats often, review the chain order/caps.\n${new Date().toISOString()}`,
          html: `<p>Provider <strong>${p.id}</strong> stopped accepting mail (${reason}).</p><p>Messages continue through the next provider in the chain automatically — <strong>no action needed</strong>.</p><p>If this repeats often, review the chain order/caps.</p><p>${new Date().toISOString()}</p>`,
          from: q.from
        }, `alert/${p.id}/${Date.now()}`);
        return;
      } catch { /* try the next one */ }
    }
    console.error("EMAIL_ALERT no healthy provider left"); // last resort: log + /api/health
  } catch { /* alerts must never break sends */ }
}
