# 00 — User checklist: the only things we ask the user for

**First: `dh profile doctor`** (the owner's profile + vault) — items it answers are already collected; ask only what it leaves open.

Load when: a deployment engagement starts ("host my app", "I have a VPS", "deploy this project").
This file is the complete ask-list. Collect items 1–4 once (plus any §5 keys the app needs), then run
`10-bootstrap-vps.md` → `20-domain-dns-ssl.md` → `30-deploy-app.md`. After that, every request flows
through `40-change-pipeline.md` and `50-ops-monitoring.md`.

Prerequisites: none — this is the entry point.

## 1. What we ask for (and nothing else)

- [ ] **VPS host + IP** — or the access needed to create one (§2/§3) — *free-preview alternative: §3b, no purchase needed*
- [ ] **SSH access method** — ONE of the two paths below
- [ ] **Domain name + registrar** — Hostinger / Namecheap / GoDaddy / Cloudflare / OVH / Google
- [ ] **GitHub account** — where the repo lives; private or public both fine
- [ ] *(optional but recommended)* **provider API token** — unlocks DNS / firewall / snapshot automation
- [ ] **Business keys** — only the §5 rows the app actually needs (agent asks per use case)

VPS minimum: **Ubuntu 24.04 LTS**, KVM / full-virtualised, root SSH allowed. Coolify's floor is
2 vCPU / 2 GB RAM / 30 GB disk — order **2 vCPU / 4 GB** to leave build headroom.

## 2. Hostinger path (preferred — near-zero user work)

1. Create the VPS in hPanel: **KVM**, **Ubuntu 24.04 LTS**, ≥ 2 vCPU / 4 GB RAM.
2. hPanel → **Account → API** → create an API token (read/write for VPS + DNS) → paste it to the agent once.
3. Give the agent the **VPS id** (from hPanel → VPS) and the **IP**.

The agent does the rest via `https://developers.hostinger.com`: SSH-key register + attach, firewall
create/rules/activate/sync, DNS records, snapshots, metrics, restarts — see `10-bootstrap-vps.md`
Steps 1a/3/7 and `20-domain-dns-ssl.md`. The token is stored with `dh vault set HOSTINGER_API_TOKEN`
(this project's vault, or `--machine` for every project; chmod 600), never in a repo.

## 3. Generic path (any other provider)

1. Create a VPS: **Ubuntu 24.04 LTS**, ≥ 2 vCPU / 4 GB RAM, root SSH enabled.
2. The agent prints ONE line with its real public key substituted for `<AGENT_PUBKEY>`:
   open the provider's **browser console** (VNC / web terminal) and paste it once, as a single command:

   ```bash
   mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "<AGENT_PUBKEY>" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
   ```

3. Nothing else. The agent verifies key auth (`10-bootstrap-vps.md` Step 2) and proceeds.

## 3b. Free preview track — offered, never forced (refs 11/21)

Offer ONCE at deploy time: *"Free preview first ($0, on a free server + free domain) — or your own
VPS + real domain now?"* If the user already provided a VPS + domain, skip this section entirely.

If chosen, the user's complete job is:

1. **Oracle Cloud signup** — https://signup.oraclecloud.com: email + phone + card ($1 authorization
   hold; credit/credit-like debit only — prepaid/virtual/single-use cards are rejected). Home region
   is PERMANENT — decide it deliberately with the agent. *(recommended)* upgrade to Pay-As-You-Go for
   capacity ($0 while inside Always Free limits; $100 hold at upgrade, reversed).
2. **Create the instance** (agent guides field-by-field): Ubuntu 24.04, VM.Standard.A1.Flex ≤2 OCPU /
   12 GB, public IPv4, paste the agent's `~/.vps-ops/ssh/id_ed25519.pub` into **Add SSH keys → Paste
   public keys**, and paste `templates/ops/oci-cloud-init.yaml` into **Show advanced options → Management →
   Initialization script**. On "out of host capacity": retry, change AD, or use the PAYG upgrade.
3. **Security List** (one-time, agent dictates exact values): add ingress TCP 80 and 443 from
   0.0.0.0/0. Never open 8000 (the dashboard is reached via the agent's SSH tunnel).
4. **Free domain** (optional — skip if a real domain exists): `.pp.ua` at https://nic.ua — account +
   confirmed email + a linked card (1 UAH pre-auth, refunded — the main failure point), real legal
   name/address in the profile, then Telegram-bot (@ppuabot) phone activation within 5 days. Steps in
   `references/ops/21-free-domain-cloudflare.md`.
5. **Cloudflare account** (free) — add the domain as a zone, change the 2 nameservers at nic.ua.
6. Keep the account reachable: **log in to Oracle at least monthly** (30-day-idle accounts can be
   deemed abandoned); yearly `.pp.ua` renewal also re-activates by phone.

Everything else is unchanged: the two approvals in §4 and the keys in §5 still apply; the agent does
all server work and DNS record creation (or dictates exact clicks).

## 4. Two one-time browser approvals (agent guides, click-by-click)

**A. Coolify admin account + API access** — right after the agent installs Coolify (`10-bootstrap-vps.md` Step 5):

1. Open the dashboard **through the agent's SSH tunnel** — the agent starts `ssh -N -L 8000:127.0.0.1:8000 …` on your machine and you open `http://localhost:8000` (the dashboard is loopback-bound by the agent right after install, ref 10 Step 3b — it is NOT reachable at `http://<ip>:8000`). Then create the first **admin account** on the registration page.
2. **Settings → Configuration → Advanced** → enable **API access** (and **MCP** if you want the
   optional MCP convenience layer).
3. **Keys & Tokens → API Tokens** → create a token named `vps-ops` with scopes
   `read`, `read:sensitive`, `write`, `deploy` → copy it and paste it to the agent once.
   (`write` is required to create projects/apps/databases — without it, Coolify answers
   `Missing required permissions: write`.)
4. *(optional, recommended)* enable **2FA** on this account.

**B. GitHub App install** — only for **private repos**, prompted during `30-deploy-app.md`: the
agent creates the GitHub App in Coolify, you click **Install** on GitHub and pick the repo. One click.

That is the entire set for Track P. On Track F (§3b) the signups/activations listed there are added —
still nothing that runs on the server.

## 5. Business keys matrix — the agent asks only for the rows your app needs

| Service | What to create | Where the key is | Used for |
|---|---|---|---|
| Stripe | Secret key + webhook signing secret | dashboard.stripe.com → Developers → API keys / Webhooks | payments, webhook verification |
| Transactional email — the free chain (ref 70) | Free accounts at Resend + Mailgun + Brevo → one API key each | provider dashboard → API keys | signup verify, password reset, receipts — agent wires DNS + env + failover |
| Offsite backups — Backblaze B2 (primary, ref 55) | Free account → enable B2 → copy the master key ONCE (no card; skip Caps & Alerts — card-gated) | provider dashboard | offsite backups — agent then creates bucket + scoped key via API |
| Offsite backups — Tigris (default second target, ref 55) | Free account (no card) → create bucket + access keys | tigrisdata.com | second offsite target; 5 GB, zero egress, official MCP |
| Offsite backups — Cloudflare R2 (optional; REQUIRES a card to activate) | only if a card is acceptable: enable R2 → one token | dash.cloudflare.com → R2 | richer second target for users fine with a card |
| Cloudflare API token — DNS + brand mailboxes (refs 20/21) | Create ONE token with `Zone → Zone → Read` + `Zone → DNS → Edit` + `Zone → Email Routing → Edit` (all zones in the account) → `dh vault set CLOUDFLARE_API_TOKEN` | dash.cloudflare.com → My Profile → API Tokens → Create Token | DNS records, brand mailboxes (`support@`), future zone work — one token covers every phase by design; a scope a later phase needs is provisioned in the same ask, so the pipeline never bounces back |
| SMTP | host, port, user, pass | your mail provider's SMTP settings | apps that only speak SMTP |
| OAuth (GitHub / Google) | OAuth app → client id + secret (redirect URI = app domain) | provider developer console | social login |
| Analytics (Plausible / Umami / PostHog) | site id / project API key | provider dashboard | product analytics |
| Anything else | whatever the app's `.env.example` declares | — | the app's own config |

Login-email apps: the email row is the ONLY human step — create the three free accounts in one sitting
(email signup, no card), then hand the keys over ONE of two ways (offer, default first): paste to the
agent — it vaults them (`dh vault set NAME` → this project's vault, chmod 600) and sets the Coolify env, values never echoed
again; or ask for the click-by-click Coolify guide. Which key per provider: ref 70 §2. DNS records,
env wiring, and the failover router are agent work (refs 70 + 80).

Offsite backups (every project — ref 55): **first ask the destination question once: cloud dual (default)
/ cloud + a home copy / home only** (ref 55 §0b — an offer, never forced). Then the human steps are
Backblaze (account + enable B2 + copy the master key) and Tigris (account + access keys only — **the
agent creates the bucket via API** so the storage class is right; a console-created GLACIER bucket
serves 0-byte reads). Both **card-free**. R2 only if the user accepts a card. Ask for all of it in ONE
message; buckets, scoped keys, schedules, drills — agent work.

**Pending ledger (every project — the project's `PENDING.md`):** whenever a human action is needed —
keys to paste, a click to make, a password to escrow/rotate, an account to create — record it in
`~/.deckhand/pending.md` (id · what · WHY · HOW · WHERE · asked date · status · nag) in the same message where
you ask. `WHERE` = the exact file path / URL / menu chain — the user must not have to search. Close items with a date once done/confirmed. **Every report back to the user ends with the
open list** (short, with ages). Never silently drop an item — that is the one failure this exists to prevent.

Rule: the agent reads `.env.example` in the repo and asks for exactly those values — nothing more.
Secrets go only into the deckhand vault (`dh vault set`) and Coolify env vars, never into a repo, commit, or chat echo.

## 6. What the user will NEVER have to do

- Open a local SSH session or run server commands — the one exception is the single public-key paste in §3 (browser console).
- Operate the Coolify dashboard (beyond the two approvals above).
- Deploy, redeploy, restart, or roll back by hand.
- Edit DNS records by hand or manage TLS certificates.
- Do routine ops: logs, metrics, backups, updates, disk cleanup — all agent-driven.

## 7. DNS records (non-Hostinger registrar) — copy-paste block

```text
@        A   <IP>      # apex / root
www      A   <IP>      # www alias
coolify  A   <IP>      # Coolify instance → HTTPS + MCP
*        A   <IP>      # optional — Coolify PR previews
```

| Registrar | One-line path to add an A record |
|---|---|
| Namecheap | Domain List → Manage → **Advanced DNS** → Add New Record → **A Record**, Host `@`/`www`, Value `<IP>` |
| GoDaddy | My Products → Domains → **DNS** → Add → **A**, Name `@`/`www`, Value `<IP>` |
| Cloudflare | DNS → Records → Add record → **A**, Name `@`/`www` (or `coolify`), IPv4 `<IP>`; keep **DNS only** (grey cloud) while certs are issued |
| OVH | Web Cloud → Domains → your domain → **DNS zone** → Add an entry → **A**, sub-domain `@`/`www`, target `<IP>` |
| Google / Squarespace Domains | DNS → Custom records → **A**, host `@`/`www`, data `<IP>` |

Ask the agent for the block with your real IP substituted. TTL 14400 is fine. Cloudflare proxying
(orange cloud) can interfere with Let's Encrypt's HTTP-01 challenge — stay DNS-only during bootstrap.
[verify at live drill]

## 8. One-paste hand-off

```text
VPS:      <IP>   (provider: Hostinger, vmId <id>  |  or: <provider>, key installed per §3)
Domain:   <domain>   (registrar: <name>)
GitHub:   <user>/<repo>  (private | public)
Keys:     none yet  |  attached .env values for the services in §5
```

Next: `10-bootstrap-vps.md` → `20-domain-dns-ssl.md` → `30-deploy-app.md`.
