# 21 — Preview domains: .pp.ua (free) or an owned domain → Cloudflare DNS-only

Load when: Track F needs a domain and the user won't pay ~$10/yr yet. If they CAN pay, recommend a
real domain instead — it removes every caveat in this file (card gate, public WHOIS, annual phone
re-activation, mail reputation). This is the $0 route. Next: A records → `30-deploy-app.md`.

Already own a domain? Skip the registration part entirely and use §D — the Cloudflare flow is identical.

Chain (as designed): `[business.pp.ua @ nic.ua] → [Cloudflare, DNS-only] → [server IP] → [Coolify
Let's Encrypt]`. The Let's Encrypt mechanics are unchanged from `20-domain-dns-ssl.md`.

## .pp.ua facts (verified 2026-09-18)

- Registration AND renewal are free (0.00 UAH) — but gated and chore-heavy:
  - **Card gate**: nic.ua executes a free order only if the account email is confirmed AND a payment
    card is linked (1 UAH pre-auth, refunded — an anti-bot measure). Google Pay / Apple Pay NOT
    accepted. Many non-Ukrainian cards fail this pre-auth → **single point of failure; say so up front**.
  - **Real identity**: WHOIS is public, cannot be hidden; the registry requires the real legal name +
    complete address — fake/incomplete data gets the domain serverHold-blocked.
  - **Activation**: SMS is sent only ONCE; the reliable route is Telegram **@ppuabot** (the Telegram
    account must be on the SAME phone number as the registrant record), then the form at
    https://apu.drs.ua/en/ (domain + phone + code) **within 5 days** or the request is rejected.
  - **Renewal**: yearly, and it re-triggers phone activation; lapse → 28-day priority window → paid
    restoration. Calendar reminder ~3 months before expiry. (Sources conflict on the window: 4 months
    vs 60 days — treat 90 days as safe.)
  - **Policy risk**: registry rules list "direct advertising of products and services" as a blocking
    ground and allow blocking without notice → use it as an UNPUBLISHED staging hostname only,
    `noindex` from day one, never as the public brand.
  - Reputation: zone-level .pp.ua is currently clean on major blacklists, but sibling subdomains are
    abused — do NOT send email from it (see §Email below).
- Custom nameservers ARE explicitly allowed (no limits) — Cloudflare works.
- Cloudflare accepts `name.pp.ua` as a zone: pp.ua is on the Public Suffix List, and Cloudflare's
  rule is "apex must be one level below a valid PSL suffix" — `name.pp.ua` qualifies on the FREE plan.

## A. User steps (browser — complete list, guided click-by-click)

1. Create the account at https://nic.ua → confirm the account email.
2. Link a payment card (Account → Payment cards): number/expiry/CVV + 3-D Secure; 1 UAH pre-auth
   (refunded). After 2 failed attempts an anti-fraud cool-off (up to a day) kicks in.
3. Make the registrant phone reachable for SMS/Telegram; install Telegram on that EXACT number.
4. Register the domain: nic.ua → .pp.ua search → free order.
5. Fill the owner profile with the real legal name + full address.
6. Activate: Telegram @ppuabot (/start → send phone number → activate) → https://apu.drs.ua/en/.
7. Create a Cloudflare account (https://dash.cloudflare.com/sign-up) → verify email.
8. Cloudflare → "Onboard a domain" → `name.pp.ua` → Free plan → copy the 2 assigned nameservers.
9. nic.ua → Domains → (gear) → **NS-servers** → dropdown "Custom name servers" → Change → paste one
   NS per line → Save. Wait for Cloudflare to flip to **Active** (4–24 h).

## B. Agent steps

1. After the zone is Active, create the records — DNS-only (grey cloud) is MANDATORY for Coolify's
   HTTP-01 certs. User clicks, or use the API with the token from the vault (`dh vault set CLOUDFLARE_API_TOKEN`,
   then the `shell` line `dh vault list` prints → `$CLOUDFLARE_API_TOKEN`). **Create that token with the FULL pipeline scope set in one go:**
   `Zone → Zone → Read` + `Zone → DNS → Edit` + **`Zone → Email Routing → Edit`** — the last is what
   brand mailboxes (`support@`) need later; without it every future mail phase bounces back to the
   user (live-seen). Missing a scope later? **EDIT the same token** (dash.cloudflare.com → My
   Profile → API Tokens → Edit → add the permission) — no new token, no new paste:
   ```bash
   curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records" \
     -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"type":"A","name":"@","content":"'"$SERVER_IP"'","ttl":120,"proxied":false}'
   ```
   Records: `@` → server IP · `www` → server IP · optionally `coolify` → server IP (for the dashboard
   domain later). All DNS-only.

   **Probe before promising** (any phase that touches Cloudflare starts here): `GET /zones/$CF_ZONE_ID/email/routing`
   → 200 = routing usable, `Authentication error` = scope missing · `GET /zones/$CF_ZONE_ID/dns_records?per_page=1`
   → DNS read. A wall found in planning is one batched ask; a wall found mid-wiring is a stall.
2. Verify BEFORE touching Coolify: `dig +short name.pp.ua @1.1.1.1` → the server IP exactly.
3. Continue in `20-domain-dns-ssl.md` from "Coolify side" (attach the domain — Cloudflare = the
   manual-registrar route there), then `30-deploy-app.md`. Certs issue over HTTP-01 (ports 80/443
   open per refs 11/10).

## C. Email reality on a preview domain

App email (sign-in codes, receipts) must NOT send from `.pp.ua` (deliverability + policy). For the
preview: keep email in a test/console mode, or verify a sending subdomain with a free provider
(Resend free = 3,000/mo, 100/day; Postmark trial = 100). Decide before `30-deploy-app.md` (it needs
the app's env values). Switch to the real domain at migration (`60`).

## D. Already own a domain? (any registrar — NameSilo, Namecheap, GoDaddy, …)

Skip registration entirely — you still get everything Cloudflare gives us:

1. Cloudflare → **Add a site** → your domain → **Free** plan → it scans existing DNS.
   ⚠️ BEFORE swapping NS: if the domain has **email (MX) or other live services**, recreate those
   records inside the Cloudflare zone first — after the swap, the old DNS stops answering.
   (A parked domain with no MX/TXT: nothing to preserve.)
2. At the registrar, switch to the 2 Cloudflare nameservers (disable DNSSEC first if enabled):
   - **NameSilo**: Domain Manager → the domain → **Nameservers** → *Custom nameservers* → paste both → Submit
   - **Namecheap**: Domain List → Manage → **Nameservers** → *Custom DNS*
   - **GoDaddy**: My Products → DNS → **Nameservers** → Change → *Custom*
3. Wait for the zone to go **Active** (minutes–hours), then continue at §B (A records, DNS-only).

## Alternatives (ranked, 2026)

| Option | Cost | NS → Cloudflare? | Reality |
|---|---|---|---|
| .pp.ua (this ref) | $0 | yes | card gate + Telegram activation + real WHOIS + yearly re-activation |
| Real domain (any registrar) | ~$8–12/yr | yes | recommended for anything user-facing |
| 101domain (international .pp.ua reseller) | $18.99 reg / $25.99 ren | yes | skips the card gate; keeps the phone chore |
| sslip.io / nip.io | $0, no signup | no | `IP.sslip.io` works instantly with LE (HTTP-01); throwaway testing only |
| eu.org | $0 | yes | approval queue months-to-years for 2nd-level; not for a business |
| us.kg | — | — | suspended after abuse; KYC now required; not accepting |
| dynu.com / afraid.org | $0 | no | no NS delegation → cannot be a Cloudflare zone |

## Provenance

nic.ua product + KB pages (card gate, activation, NS config): nic.ua/en/domains/.pp.ua,
nic.ua/en/knowledge-base/free-order-is-not-created, …/how-to-activate-pp-ua-domain · publicsuffix.org
(pp.ua listed) · Cloudflare add-site docs ("one level below a PSL suffix") · Resend pricing · verified
2026-09-18; full research in `D:\OCI-research` (local archive, not shipped).
