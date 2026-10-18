# 12 — Provider price sheet (Oracle out? pick from here)

Load when: choosing a server provider, or the user asks "which VPS and how much?". Quote this sheet —
never re-research prices per user — but re-verify the ONE number you are about to promise at checkout
(promos/currencies move monthly). Prices read from the providers' own pages 2026-09-18; USD ≈ EUR × 1.148.

## Decision order

1. **Oracle Always Free** (ref 11) — the only true free-tier VPS that meets Coolify's floor
   (2 OCPU / 12 GB Arm). Try first; the gate is the card, not the country.
2. **Contabo — default cheap pick.** Monthly billing available (no lock-in needed), best RAM-per-dollar,
   EU + US/Singapore DCs; weaker CPU sharing and slower support. Good for 1 app *and* for ~4 apps.
3. **Hostinger — fine, watch the renewal.** Cheap only while prepaid (24-month term); renewal roughly
   doubles. Pick when the user wants ONE provider for host + VPS (then migration disappears).
4. **Hetzner — cheapest real performance, but EU-only in practice.** Its US locations cost noticeably
   more, so quote Hetzner only with a matching location. (Users comparing a US Hetzner price against
   Contabo will otherwise see Hetzner as "expensive" — it is not, in the EU.)

## Sheet (2026-09-18)

| Provider / plan | vCPU / RAM / disk | Price | Notes |
|---|---|---|---|
| Oracle A1 Always Free | 2 / 12 GB / 200 GB total | **$0** | Arm · capacity lottery · card gate · idle-reclaim |
| **Contabo Cloud VPS Core 4** | 4 / 8 GB / 100 GB SSD | **€5.50/mo incl. VAT** (≈$6.3; net ≈$5) | 24-mo contract = cheapest; monthly available; setup fee may apply on short terms |
| Contabo Cloud VPS Core 6 | 6 / 12 GB / 200 GB | €7.50/mo incl. VAT | enough for ~4 small apps |
| **Contabo Cloud VPS Core 8** | 8 / 24 GB / 300 GB | €14.00/mo incl. VAT | the ~4-app sweet spot |
| Contabo Cloud VPS Core 12 | 12 / 48 GB / 400 GB | €25.00/mo incl. VAT | headroom for 8+ apps |
| Hostinger KVM 1 | 1 / 4 GB / 50 GB | $6.49/mo promo → renews $11.99 | 24-mo prepay; weekly backups included |
| Hostinger KVM 2 | 2 / 8 GB / 100 GB | $8.99/mo promo → renews $14.99 (CAD page: 11.96 → 20.99) | |
| Hostinger KVM 4 | 4 / 16 GB / 200 GB | $12.99/mo promo → renews $28.99 | |
| Hostinger KVM 8 | 8 / 32 GB / 400 GB | $25.99/mo promo → renews $49.99 | |
| Hetzner CAX11 (Arm) | 2 / 4 GB / 40 GB | ≈€4.49/mo (EU) | US locations priced higher |
| Hetzner CX22 | 2 / 4 GB / 40 GB | ≈€4.99/mo (EU) | re-check the US figure before quoting |
| Hetzner CX42 | 8 / 16 GB / 160 GB | ≈€16–17/mo (EU) | best CPU/I-O per dollar; Ashburn US = lowest latency to Canada |

(Render/Koyeb/fly/AWS/Azure free tiers: see ref 11 — none is Coolify-grade.)

## Contabo — live drill notes (Cloud VPS 4 "2026", 2026-09-18)

- Order email contains: panel login (`my.contabo.com`), customer ID, **IP**, `root`, "password as
  chosen during order", VNC pointer, IPv6 /64. Ubuntu 24.04, "Hub Europe" DC.
- **No cloud firewall** — ports are open as soon as something listens; nothing to configure there.
- SSH: password auth ON initially (VNC in the panel as fallback). Key-install without bothering the
  user: one ssh run with `SSH_ASKPASS=<helper> SSH_ASKPASS_REQUIRE=force` +
  `-o PreferredAuthentications=password -o PubkeyAuthentication=no` → install the pubkey → verify with
  BatchMode → delete the helper → harden to key-only (exactly how this drill ran).
- Whole stack (Coolify 4.3.23 + Proxy + Postgres + Next.js app + build) fits comfortably on
  4 vCPU / 8 GB — ~2.5 GB RAM used in steady state.
- 24-month contracts are the cheapest; warn the user about auto-renew/cancellation windows.

## Sizing rules of thumb

- **Coolify floor**: ≥2 vCPU / 2 GB RAM / 30 GB disk → order **4 GB+**, and **12 GB+ for ~4 apps**.
- Budget per app ≈0.5–1 GB RAM + ≈0.2 GB per Postgres; builds spike memory → serialize deploys under ~8 GB.
- Contabo/Hetzner/Contabo-like providers have **no cloud firewall to open** (unlike Oracle): the runbook
  is plain `10-bootstrap-vps.md` (Ubuntu 24.04 → key → Coolify). Oracle keeps the ref-11 variant.
- Contabo orders with a **24-month contract** are the cheapest but auto-renew — note the cancellation
  window to the user instead of letting it surprise them.

## Provenance

contabo.com/en/vps (VAT-incl. EUR list, 2026-09-18) · hostinger.com/vps-hosting (USD promos + renewal
strings, 2026-09-18) · Hetzner: EU figures from this session's research + user-reported US price
(`CPX12 $14`, US region). Re-verify before promising; update this file when you do.
