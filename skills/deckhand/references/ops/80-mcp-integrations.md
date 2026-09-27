# 80 — MCP integrations (modular catalog)

Purpose: the agent-managed service layer, ONE section per domain. **Append new domains at the bottom — never rewrite existing sections.**

Policy (never violate):
- NEVER install MCP servers globally or by default. Wire a server workspace-scoped ONLY when the current step needs it or the user explicitly asks.
- Prefer official servers; record license + exact install line here.
- Auth tokens: created by the human ONCE, stored with `dh vault set NAME` (this project's vault, or `--machine` for every project; chmod 600) and/or Coolify env — never in a repo.
- MCP is convenience, never a dependency: everything here is also plain REST, reachable by our stdlib scripts (`ops/scripts/coolify_api.py`, `ops/scripts/hostinger_api.py`; DNS = plain Cloudflare API calls, as in the bootstrap refs). Use MCP for interactive sessions; scripts for deterministic pipeline steps.

## Domain: DNS + registrar

Default DNS plane: **Cloudflare** — MCP `mcp.cloudflare.com/mcp` ("Code Mode", Apache-2.0, remote, OAuth or bearer token).
Token scopes: **Zone → DNS → Write** (record CRUD) `+ Zone → Write` (create zones). Capabilities: zone create, DNS CRUD,
registrar search/check/**register** (API beta — NO renew/transfer/contact-update via API; `auto_renew` defaults FALSE → set true at registration).

Registration fallback (when the agent must also register/renew):
- **Porkbun MCP** — official, MIT, local: `npx -y @porkbunllc/mcp-server` (96 tools: register/renew/transfer/DNS/pricing; free self-serve sandbox `pk1_sb_` keys). Human once: account (may need photo ID), email+phone verify, FIRST purchase in UI (API requires ≥1 prior registration), account credit, monthly spend limit.
- **NameSilo MCP** — official remote `mcp.namesilo.com` (50 methods incl. register/renew/transfer/DNS). Human once: account + API key from the API Manager.
- Skip: GoDaddy MCP (read-only), Dynadot (DNS-write unverified). Community Spaceship/Gandi servers = unsupported.

| Step | Agent-autonomous? | Human, once |
|---|---|---|
| Zone create · DNS record CRUD · read-back verify | Yes (CF token) | Create the CF token (Zone→DNS→Write [+Zone→Write]) |
| Point nameservers at Cloudflare | Yes where registrar has API (Porkbun/NameSilo MCP) | Else: one dashboard click at the registrar |
| Search/price a domain | Yes | — |
| Register a NEW domain (Cloudflare) | Yes after setup | Verified email + billing profile + registrant contact + agreement (dashboard) |
| Register a NEW domain (Porkbun) | After the first purchase | Account + first registration in UI + credit |
| Register (NameSilo) | Yes once key exists | Account + API key (no minimum deposit) |
| Renew | Porkbun / NameSilo yes; **Cloudflare: no API** | CF: set auto-renew at registration, or renew in dashboard |
| Transfer in | Porkbun / NameSilo yes | EPP/auth code; CF = dashboard transfer only |

## Domain: Email

Sending = ref 70's chain + router. MCPs here are for setup/management/reading:

| Service | MCP | License | Install | Note |
|---|---|---|---|---|
| Resend | official | MIT | remote `mcp.resend.com/mcp` · or `npx resend-mcp` | send + read; React Email first-party |
| Mailgun | official | Apache-2.0 | `npx @mailgun/mcp-server` (stdio) | routes + stored messages |
| Brevo | official hosted | (hosted) | `mcp.brevo.com/v1/brevo/mcp` | 27 modules; its **MCP server key** (Brevo → SMTP & API → API keys and MCP) is separate from the sending **API key** — create only when wiring this server |
| Mailtrap | official | MIT | `npx mcp-mailtrap` | testing/sandbox |
| Cloudflare | official | Apache-2.0 | `mcp.cloudflare.com/mcp` + Agentic Inbox | free inbound routing; sending needs Workers Paid $5/mo |
| AgentMail | official hosted | (hosted) | `mcp.agentmail.to/mcp` | BEST for agent READING inbound (free, no card) |

No-MCP fallback that always works: provider webhook → our own endpoint (deterministic; no installs).

## Domain: Backup & object storage

| Service | MCP | License | Install | Note |
|---|---|---|---|---|
| Backblaze B2 | official (Backblaze Labs) | MIT | `npx -y @backblaze-labs/b2-mcp` (env `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`) | 40 tools; a scoped key is enough; capability-aware |
| Tigris (card-free S3, ref 55) | official | MIT | `npx -y @tigrisdata/tigris-mcp-server run` · hosted `mcp.storage.dev` (OAuth) | 5 GB free, zero egress; Coolify partner |
| Koofr (card-free consumer option) | no MCP — use rclone | — | `rclone config create koofr koofr user=… pass="$(rclone obscure …)"` | 10 GB free; restic rclone backend |
| Filebase (fallback S3) | none official — generic S3 MCPs work (`txn2/mcp-s3`) | MIT | — | 5 GB free, `s3.filebase.io`, region `auto` |
| Cloudflare R2 | — use the Cloudflare API MCP row above (Code Mode) | Apache-2.0 | `mcp.cloudflare.com/mcp` | no R2-specific official server exists; npm `r2-mcp`-style packages are 404s — ignore them |
| RustFS (app storage, ref 56) | official | Apache-2.0 | build from `rustfs/mcp` (`cargo install rustfs-mcp`) — no prebuilt image | list/upload/get bucket tools |

## Domain: payments / analytics / other (append here)

(empty — extend per need, same table shapes as above)
