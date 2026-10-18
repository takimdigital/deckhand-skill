# 11 — Oracle Cloud Always Free: the $0 preview server (Arm)

Load when: the user chose the FREE PREVIEW track (Track F — no VPS/domain yet, or "prove it before
I pay"). This ref replaces §2/§3 of `00-user-checklist.md` and Steps 1–3/7 of `10-bootstrap-vps.md`
for Oracle; Steps 4–6 there still apply. Next: `21-free-domain-cloudflare.md` → `30-deploy-app.md`.

Positioning rules (never mix tracks): this is a PREVIEW host — disposable by design, one exit path
(`60-migrate-to-paid.md`). Say "preview" in every report; never present it as production-grade
durability. Status: researched + primary-source-verified 2026-09-18; first live run pending —
`[verify at live drill]` markers are open until exercised.

## Facts (verified 2026-09-18)

| Item | Value |
|---|---|
| Compute (Arm) | Ampere A1: 1,500 OCPU-h + 9,000 GB-h/month = **2 OCPU / 12 GB** per tenancy (halved from 4/24 in Jun 2026; over-limit instances deleted after 30 days — resize, don't rebuild) |
| Compute (AMD) | up to 2× VM.Standard.E2.1.Micro (1 GB) — CANNOT run Coolify (min 2 vCPU / 2 GB); ignore |
| Storage | 200 GB block total (boot + block), home region only; default boot volume 50 GB |
| Egress | 10 TB/month; **outbound port 25 blocked** (use Resend/Postmark APIs for email) |
| Home region | PERMANENT (cannot change); Always Free exists only there |
| Capacity | "Out of host capacity" is the normal free-tier experience |
| Idle policy | instance may be reclaimed if, over 7 days: CPU p95 <20% AND network <20% AND (A1) memory <20% |
| Signup | email + phone + card; $1 authorization hold; credit / credit-like debit only — NO prepaid/virtual/single-use cards |
| Country | Algeria is in the signup country list; the real gate is the CARD |

## What the user does (browser — the complete list, guided click-by-click)

1. **Sign up** → https://signup.oraclecloud.com — Home Region chosen DELIBERATELY (permanent):
   closest-to-users or best-capacity; no OCI region exists in Algeria — nearest are eu-marseille-1,
   eu-madrid-1, af-casablanca-1 (Casablanca Always-Free eligibility unverified). Card → $1 hold.
2. *(recommended for capacity)* **Upgrade to Pay-As-You-Go** (Billing → Upgrade): $0 charges while
   inside Always Free limits; $100 hold at upgrade (reversed). This is the reliable fix for capacity.
3. **Create the instance** — Compute → Instances → Create instance:
   - Image: **Ubuntu 24.04** (Platform images; standard, NOT Minimal on Arm)
   - Shape: **Ampere → VM.Standard.A1.Flex → 2 OCPU / 12 GB** (the max allowed)
   - Networking: public subnet + *Automatically assign public IPv4 address*; boot volume default fine
   - **Add SSH keys → Paste public keys** → the agent's `~/.vps-ops/ssh/id_ed25519.pub`
   - **Show advanced options → Management → Initialization script** → paste `templates/ops/oci-cloud-init.yaml`
4. **Security List** (one-time): add ingress **TCP 80** and **TCP 443** from `0.0.0.0/0` (exact field
   values below). Never open 8000.
5. Routinely: **log in to Oracle at least monthly** (30-day-idle accounts can be deemed abandoned).

## Agent steps

0. Hand over ONE copy-paste bundle: `cat ~/.vps-ops/ssh/id_ed25519.pub` + `cat templates/ops/oci-cloud-init.yaml`.
1. **Two firewalls — both must open** (the #1 Oracle gotcha):
   - **Layer 1 — VCN Security List** (user clicks; agent dictates): Networking → VCN → Security
     Lists → default → Add Ingress Rule: Stateless **unchecked**, Source Type **CIDR**, Source
     **0.0.0.0/0**, IP Protocol **TCP**, Source Port Range **All**, Destination Port Range **80**
     (then **443**). Leave 22 as-is.
   - **Layer 2 — in-VM iptables**: Oracle Ubuntu images REJECT everything but SSH. The cloud-init
     asset above already inserted the ACCEPTs at the TOP (`-I INPUT 1/2`) — always before the
     REJECT regardless of image version. Verify: `ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$IP 'iptables -S INPUT | head'`.
     Manual fallback:
     ```bash
     ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$IP 'iptables -I INPUT 1 -m state --state NEW -p tcp --dport 80 -j ACCEPT
       iptables -I INPUT 2 -m state --state NEW -p tcp --dport 443 -j ACCEPT
       netfilter-persistent save || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent && netfilter-persistent save)'
     ```
     **Never use UFW on Oracle images** (documented risk of an unbootable instance); Docker bypasses
     UFW anyway.
2. **Verify access** (gate): `ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$IP 'uname -m; id -u'`
   → `aarch64` + `0`. If root is refused (cloud-init skipped): login as `ubuntu`, `sudo su -`,
   write `/etc/ssh/sshd_config.d/99-vps-ops.conf` with `PermitRootLogin prohibit-password` (a drop-in —
   the main sshd_config is OVERRIDDEN by sshd_config.d on cloud images), copy the pubkey to
   `/root/.ssh/authorized_keys`, `systemctl restart ssh` (Ubuntu's unit is `ssh`, not `sshd`).
3. **Coolify install** — `10-bootstrap-vps.md` Step 4, run **as root** (the installer tags its key by
   `$USER`; a root login shell yields the correct key). Then proceed with Steps 5–6 there (token via
   tunnel → hardening).
4. **Dashboard WITHOUT opening 8000** — SSH tunnel from the agent machine (keep it running):
   ```bash
   ssh -N -o ExitOnForwardFailure=yes -L 8000:127.0.0.1:8000 \
     -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes \
     -i ~/.vps-ops/ssh/id_ed25519 root@$IP
   ```
   (Forward 8000 only — Windows kills 6001/6002 binds, `bind: Permission denied`, and `ExitOnForwardFailure` then drops the whole tunnel; ref 10's Windows note.)
   User opens http://localhost:8000 → `00-user-checklist.md` §4A (admin account + API token);
   `$COOLIFY_URL=http://localhost:8000` while the tunnel is up. Optional later: instance domain
   (`https://coolify.<domain>`) per ref 10 Step 8 → then the tunnel is only for emergencies.
5. Write `<project>/.vps-ops.json` with `"track": "free-preview"` + region; continue to ref 21 (domain)
   or straight to `30-deploy-app.md` if the user already has a domain.

## Capacity — "Out of host capacity" ladder

different Availability Domain → different Fault Domain → retry later → **upgrade to PAYG** (the
reliable fix, community-consistent 2025–26). A1 can be created in any AD except South Korea North
(Chuncheon). No official per-region table exists; treat blog claims as anecdotes.

## Arm (aarch64) notes

- 1 OCPU = 1 core (Ampere Altra); 2 cores / 12 GB ≈ a small VPS — fine for Coolify + Postgres + Next.js.
- Coolify images, Traefik, postgres, redis, Nixpacks are multi-arch (arm64 verified 2026-09-18).
- amd64-only THIRD-PARTY images fail (no qemu/binfmt by default) — add `tonistiigi/binfmt` if ever needed.
- A heavy Next.js rebuild can exhaust memory — serialize deploys; on 12 GB it fits, with headroom gone.

## Backups on the free tier

Coolify scheduled DB backups land under `/data/coolify/backups` (no API route to download them) — pull
via SSH as the offsite copy. Save Coolify's `APP_KEY` (`/data/coolify/source/.env`) off-box alongside
any instance backup. Optional free offsite: Cloudflare R2 (10 GB-mo) or Backblaze B2 (10 GB) via
Coolify's S3-compatible destination.

## Reclamation tail risk (state it honestly in every report)

CPU p95 + network + (A1) memory all <20% over 7 days → Oracle may reclaim the instance; a daily
health ping does NOT move those percentiles. Real traffic keeps it alive; migration is the real answer.

## If Oracle signup fails (card rejected, verification stall, capacity blocked)

The card gate is industry-wide: every real free-forever VM wants a credit / credit-like card, and
Oracle additionally rejects prepaid/virtual/single-use. Order of moves:

1. **Retry the signup with a different card** — credit or credit-like debit (no PIN); a
   foreign-currency (devise) or foreign-issued card is the usual fix when a local card fails.
   No VPN/proxy, one clean browser session; keep any support ticket open in parallel.
2. **Another cloud, still free-ish (card required):**
   - Google Cloud trial: **$300 / 90 days** → run a 2–4 GB VM (e2-small/medium) inside the credit;
     the forever-free e2-micro is only 1 GB (below Coolify's floor). `[verify at live drill]`
   - AWS: new accounts get **$200 credits / 6 months, then the account closes** — no perpetual EC2.
   - Azure: $200 / 30 days + 750 h B1s for 12 months only.
3. **Go paid-cheap instead** — see `12-provider-price-sheet.md` (default pick: **Contabo from
   ~€5.50/mo incl. VAT**; Hostinger if the user wants one provider for host + VPS; Hetzner EU is the
   cheapest per performance, but its US locations cost noticeably more). Starting paid directly
   DELETES the migration step (ref 60) — no capacity lottery.
4. **No card at all?** Render free (no card) sleeps after 15 min and its Postgres expires in 30 days;
   fly.io has no free tier for new orgs; Koyeb free is closed to new signups. There is **no
   card-free production-grade free VPS in 2026** — say that honestly.
5. **Capacity-only failures** (account exists, instance creation fails): the ladder in §Capacity —
   the PAYG upgrade is the fix; no need to switch providers.

## Provenance

Oracle docs: Always Free resources (limits + idle policy), troubleshooting out-of-host-capacity,
Ubuntu/OCI firewall guidance. Coolify docs: installation, Oracle Cloud KB, firewall ports.
Community region reports labeled as such. All verified 2026-09-18; full research in `D:\OCI-research`
(local archive, not shipped).
