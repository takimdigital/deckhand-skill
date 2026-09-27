# 10 — Bootstrap: SSH key → key attach → firewall → Coolify → token → hardening → snapshot

Load when: the user's VPS + access method (+ provider API token) are known — i.e. after
`00-user-checklist.md` §1–§3. Next refs: `20-domain-dns-ssl.md` → `30-deploy-app.md`.

> **Oracle Cloud (free-preview track):** do `11-oracle-free-tier.md` FIRST (root login + in-VM
> firewall + cloud-init), then run Steps 0 → 2 → 4 → 5 → 6 here; **skip Step 3** (firewall = OCI
> Security List + ref 11 — that pair IS Track F's dashboard lock: never open 8000 there + the tunnel, ref 11 Steps 1/4) and **Step 7** (Hostinger-only). **Never run UFW on Oracle images.**
Runs from the agent machine (git-bash on Windows; `py` = Python launcher). `ops/scripts/hostinger_api.py`
and `ops/scripts/coolify_api.py` are stdlib-only — the contract; raw curl equivalents shown for every
step. Secrets live only in the deckhand vault — stored with `dh vault set NAME` (`--machine` for a server every project uses; chmod 600 —
cosmetic on Windows git-bash; enforce for real with `icacls <file> /inheritance:r /grant:r "%USERNAME%:F"`). The scripts
read the vault themselves (this project's, then the machine's); for the raw curl lines load it into the shell with
the `shell` line `dh vault list` prints (`set -a; . <machine vault>; . <this project's>; set +a`; values are
single-quoted, so this never executes or splits one). SSH keys stay in `~/.vps-ops/ssh/` and v1's
`~/.vps-ops/secrets/env.sh` is still read as a fallback, so servers set up with v1 keep working.

> **Optional — the Coolify CLI** (MIT, `coollabsio/coolify-cli`): some refs show `coolify …` commands for convenience; nothing requires it — every step also has a stdlib script/curl path. Install only if you want those commands: Linux/macOS `curl -fsSL https://raw.githubusercontent.com/coollabsio/coolify-cli/main/scripts/install.sh | bash` · Windows PowerShell `irm https://raw.githubusercontent.com/coollabsio/coolify-cli/main/scripts/install.ps1 | iex` (user-local: prefix `$env:COOLIFY_USER_INSTALL=1; `) · or `go install github.com/coollabsio/coolify-cli/coolify@latest`.

Hard rules: firewall BEFORE the Coolify install · hardening only AFTER key auth is proven (Step 2) ·
never close port 22 (Coolify manages over SSH) · never touch Coolify's installer-created keys.

## Step 0 — keygen on the agent machine

```bash
mkdir -p ~/.vps-ops/ssh && chmod 700 ~/.vps-ops ~/.vps-ops/ssh
[ -f ~/.vps-ops/ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -C "vps-ops" -f ~/.vps-ops/ssh/id_ed25519
chmod 600 ~/.vps-ops/ssh/id_ed25519
```

Expected: `~/.vps-ops/ssh/id_ed25519` (+ `.pub`) exists; re-running never overwrites (idempotent).
Passphrase-less **by design** (agent is non-interactive; Coolify requires passphrase-less keys). Windows
note: on perms errors (`UNPROTECTED PRIVATE KEY`), `chmod 600`, use git-bash's `/usr/bin/ssh`, and/or `-o IdentitiesOnly=yes`.

## Step 1a — Hostinger: register + attach the key via API

Store the provider token once: the owner runs `dh vault set HOSTINGER_API_TOKEN` (hidden prompt) — or, if they pasted it in chat, `printf '%s\n' '<token>' | dh vault set HOSTINGER_API_TOKEN` — then load the vault with the `shell` line `dh vault list` prints.

```bash
PUB="$(cat ~/.vps-ops/ssh/id_ed25519.pub)"

# 1) register the key → response carries the key id
curl -sS -X POST https://developers.hostinger.com/api/vps/v1/public-keys \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
  -d "{\"name\":\"vps-ops\",\"key\":\"$PUB\"}"
# → {"id": <keyId>, ...}        ← capture <keyId>

# 2) attach it to the VM
curl -sS -X POST https://developers.hostinger.com/api/vps/v1/public-keys/attach/<vmId> \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"ids":[<keyId>]}'
# → ActionResource {"id": <actionId>, ...}   (async — track via GET .../actions/<actionId>)

# 3) verify
curl -sS https://developers.hostinger.com/api/vps/v1/virtual-machines/<vmId>/public-keys \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"
```

Expected: step 3 lists `vps-ops` with our pubkey material.
Script equivalent (idempotent — reuses an existing key by material, then attaches):
`py ops/scripts/hostinger_api.py sshkey ensure --vm <vmId> --name vps-ops --key-file ~/.vps-ops/ssh/id_ed25519.pub`

## Step 1b — generic: one-paste key install

Hand the user the §3 one-liner from `00-user-checklist.md` with `<AGENT_PUBKEY>` replaced by
`cat ~/.vps-ops/ssh/id_ed25519.pub` (single command into their provider's browser console). Then Step 2.

## Step 2 — verify SSH (gate: do not continue until this passes)

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP 'uname -srm; id -u'
```

Expected:
```text
Linux 6.8.0-xx-generic x86_64
0
```
`BatchMode=yes` makes a password prompt impossible — success proves key auth. `Linux …` + `0` = root. **Every ssh from the agent machine carries `-o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts"`** (this gate stores the key there on first contact) — dropping it makes later calls fail with `Host key verification failed` (MSYS trap in Step 3b).

## Step 3 — firewall BEFORE install

### Hostinger (preferred — provider-level, installs nothing on the box)

```bash
# 3.1 create the firewall
curl -sS -X POST https://developers.hostinger.com/api/vps/v1/firewall \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"vps-ops"}'
# → {"id": <fwId>, ...}

# 3.2 one accept rule per port — ALL fields required; port is a STRING
for P in 22 80 443 8000 6001 6002; do
  curl -sS -X POST "https://developers.hostinger.com/api/vps/v1/firewall/<fwId>/rules" \
    -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H "Content-Type: application/json" \
    -d "{\"protocol\":\"TCP\",\"port\":\"$P\",\"source\":\"any\",\"source_detail\":\"any\"}"
done

# 3.3 activate the firewall on the VM
curl -sS -X POST "https://developers.hostinger.com/api/vps/v1/firewall/<fwId>/activate/<vmId>" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"
# → ActionResource

# 3.4 sync — activated VMs lose sync after rule changes; pushes the current rules
curl -sS -X POST "https://developers.hostinger.com/api/vps/v1/firewall/<fwId>/sync" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"
```

⚠️ A Hostinger firewall **drops all incoming by default** — the accept rules for 22, 80, 443, 8000,
6001, 6002 are mandatory, and every later rule change needs another `…/sync`. 8000/6001/6002 are needed only
DURING BOOTSTRAP (health checks before Step 3b locks the dashboard at the Docker level) — once the tunnel
works you can delete those three from the firewall and `…/sync`; 22/80/443 stay.
Protocol enum: `TCP|UDP|ICMP|GRE|any|ESP|AH|ICMPv6|SSH|HTTP|HTTPS|MySQL|PostgreSQL`; port range form `"1024:2048"`.
Script equivalent (idempotent: find-or-create → ensure rules → activate → sync): `py ops/scripts/hostinger_api.py firewall ensure --vm <vmId> --ports 22,80,443,8000,6001,6002 --name vps-ops`

### Generic (ufw — non-Hostinger providers only)

```bash
ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP \
  'ufw allow OpenSSH && ufw allow 80,443,8000,6001,6002/tcp && ufw --force enable && ufw status'
```

Expected: `Status: active` + rules for 22/tcp (OpenSSH), 80, 443, 8000, 6001, 6002.
Never remove the port-22 rule — Coolify manages the server over SSH.

## Step 3b — lock the dashboard: the docker-aware way (live-verified 2026-09-19)

> ⏩ **Ordering:** run this step AFTER Step 4 (install) — it edits
> `/data/coolify/source/docker-compose.prod.yml`, which the installer creates. The section
> order below is reference order; **execution order is 3 → 4 → 3b → 5** (and re-run 3b after
> every Coolify update).

Do NOT rely on host firewalls for Coolify's own published ports.
**Reason: Docker's userland proxy** — traffic to published ports (8000/6001/6002) bypasses host iptables entirely —
DOCKER-USER **and** INPUT DROP rules were live-tested and stayed at **0 packets** while the ports
remained fully reachable from the internet. Providers WITH a cloud firewall (Oracle) still block
them at the network layer; providers without one (Contabo, most bare VPS) are fully exposed.

The reliable lock = bind them to loopback inside Coolify's own compose:

```bash
ssh -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP '
  cd /data/coolify/source
  cp -n docker-compose.prod.yml docker-compose.prod.yml.bak-vpsops
  sed -i "s|\"${APP_PORT:-8000}:8080\"|\"127.0.0.1:${APP_PORT:-8000}:8080\"|; \
          s|\"${SOKETI_PORT:-6001}:6001\"|\"127.0.0.1:${SOKETI_PORT:-6001}:6001\"|; \
          s|\"6002:6002\"|\"127.0.0.1:6002:6002\"|" docker-compose.prod.yml
  docker compose --project-name source -f docker-compose.yml -f docker-compose.prod.yml up -d'
```

Verify (all three): `ss -ltnp | grep -E ':(8000|6001|6002)'` → **127.0.0.1** binds · a curl from
outside must time out (`curl -m 6 http://$VPS_IP:8000/api/health` → exit 28, code 000) ·
`curl -s http://127.0.0.1:8000/api/health` on the box → 200.

Dashboard access from then on = **SSH tunnel only** (run in background from the agent machine):

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8000:127.0.0.1:8000 \
  -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes \
  -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP
```

**MSYS ssh trap — every agent-side ssh, not just tunnels (live-verified 2026-09-20/21).** On Windows/git-bash, MSYS ssh resolves `$HOME` to
`/home/<user>` — often absent/unwritable — so any ssh without a durable `known_hosts` dies
with `Host key verification failed` (silently in background; live-hit again 2026-09-21 by an unattended scheduled check). Create the vault
known_hosts once — `ssh-keyscan -t ed25519 $VPS_IP | tr -d '\r' > ~/.vps-ops/ssh/known_hosts`
(verify the fingerprint before trusting!) — and carry `-o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes` on **every** ssh this skill runs from the agent machine: bootstrap gates, ops/deploy commands, backup/watchdog status pulls. Belt (when `/home` is writable): `mkdir -p /home/$USER && ln -s "$HOME/.ssh" /home/$USER/.ssh`. If the DEFAULT `~/.ssh/known_hosts` is ever poisoned for a host (bad/duplicate row or a changed host key), repair it with the sanctioned path — `ssh-keygen -R <ip> -f "$HOME/.ssh/known_hosts"`, then re-add the current line from the vault copy (`ssh-keygen -F <ip> -f "$HOME/.vps-ops/ssh/known_hosts"`, append the match to the default file) — never a raw in-place text edit: the harness guard blocks edits on `~/.ssh/known_hosts` and the file stays broken (live: an attempted in-place fix was guard-blocked and the default file stayed stale until the next repair). **Dead-tunnel
symptom:** every `coolify_api.py` call fails with `10061 / actively refused` — that is the tunnel,
not Coolify; run `py ops/scripts/coolify_api.py tunnel` (health-checks and auto-starts it; `deploy` preflights it too - set `VPS_SSH_HOST`/`VPS_SSH_KEY` once in the vault env), or restart it manually (background) and `curl -s http://127.0.0.1:8000/api/health` before deploying.

Windows note (live-verified): forwarding 6001/6002 can die with `bind [127.0.0.1]:6002: Permission
denied` (Windows reserved port ranges) and `ExitOnForwardFailure` then kills the whole tunnel —
**forward 8000 only**; the dashboard is fully usable (live log panels may need a refresh).

⚠️ Coolify upgrades re-download both compose files from its CDN (`upgrade.sh`) — the loopback
binds are LOST on upgrade. Leave a re-apply note on the box (`/root/vps-ops-notes.txt`) and re-run
Step 3b after every Coolify update.

## Step 4 — install Coolify + verify

```bash
ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes \
  -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP \
  'curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash'
curl -s -o /dev/null -w '%{http_code}\n' http://$VPS_IP:8000/api/health
ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP 'docker ps --format "{{.Names}}"'
```

Expected: install finishes (several minutes); health → `200`; container list = `coolify`, `coolify-db`,
`coolify-redis`, `coolify-realtime`, `coolify-proxy`, `coolify-sentinel` (validated live: Ubuntu 24.04 + Coolify 4.3.21).

→ Now run **Step 3b** (dashboard lock) before continuing to Step 5.

> Rehearsal note (WSL2 only): Docker's own install script refuses WSL ("we recommend Docker Desktop") and
> the Coolify installer aborts along with it. Pre-install Docker first:
> `apt-get install -y docker.io docker-compose-v2` → the installer then detects Docker and skips its step.
> On a real VPS (non-WSL kernel) the standard path works untouched.

## Step 5 — token handoff + storage

Guide the user through `00-user-checklist.md` §4A (one browser session). Then store it in the vault (each `dh vault set`
adds or replaces ONE name — nothing else in the vault is touched; Windows: use a `C:/…` path for `VPS_SSH_KEY`):

```bash
dh profile set coolify.url=http://127.0.0.1:8000
printf '%s\n' '<token>' | dh vault set COOLIFY_TOKEN        # or the owner runs `dh vault set COOLIFY_TOKEN` (hidden prompt)
printf '%s\n' 'http://127.0.0.1:8000' | dh vault set COOLIFY_URL
printf '%s\n' "root@$VPS_IP" | dh vault set VPS_SSH_HOST
printf '%s\n' "$HOME/.vps-ops/ssh/id_ed25519" | dh vault set VPS_SSH_KEY
set -a; . ~/.deckhand/vault.env; [ -f .deckhand/vault.env ] && . .deckhand/vault.env; set +a   # = the `shell` line of dh vault list
curl -sS -H "Authorization: Bearer $COOLIFY_TOKEN" "$COOLIFY_URL/api/v1/applications"
```

Expected: `[]` (fresh install) or a JSON array — via the tunnel: COOLIFY_URL is the tunnel's local end (`http://127.0.0.1:8000`); after Step 3b the public IP's :8000 is closed, so a public-IP URL here can never answer. `401` → API access still disabled or token wrong (§4A).
Script check: `py ops/scripts/coolify_api.py health` → `coolify health: 200`. Never echo the token into
chat, logs, or a repo file. The token contains `|` (Sanctum format `1|…`): `dh vault set` stores it
**single-quoted** (`COOLIFY_TOKEN='1|…'`); unquoted, the shell splits it and every call answers `Unauthenticated.`
(live-verified). `coolify_api.py` reads flags > `$COOLIFY_URL`/`$COOLIFY_TOKEN` > the deckhand vault + profile > v1's
`~/.vps-ops/config.json` / `secrets/env.sh`.

## Step 6 — harden (only after Step 2 proved key auth)

```bash
ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -i ~/.vps-ops/ssh/id_ed25519 root@$VPS_IP '
  printf "%s\n" "PermitRootLogin prohibit-password" "PasswordAuthentication no" \
    > /etc/ssh/sshd_config.d/99-vps-ops.conf && sshd -t && systemctl restart ssh && echo HARDENED'
ssh -o BatchMode=yes -o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no root@$VPS_IP
```

Expected: first command prints `HARDENED`; re-running Step 2 still succeeds; the password attempt fails
with `Permission denied (publickey)`. Keep Coolify's localhost keys untouched; recover via hPanel if Step 2 breaks.

## Step 7 — golden snapshot (Hostinger)

```bash
curl -sS -X POST "https://developers.hostinger.com/api/vps/v1/virtual-machines/<vmId>/snapshot" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"        # no body → ActionResource
curl -sS "https://developers.hostinger.com/api/vps/v1/virtual-machines/<vmId>/actions/<actionId>" \
  -H "Authorization: Bearer $HOSTINGER_API_TOKEN"
# → "state": "success"    (states: success | error | delayed | sent | created)
```

Script equivalents: `py ops/scripts/hostinger_api.py snapshot create <vmId>` · `py ops/scripts/hostinger_api.py actions <vmId> <actionId>`.
Record the timestamp — the known-good baseline for restores. Generic providers: their snapshot UI/API, or skip.

## Step 8 — Coolify instance domain (recommended: unlocks HTTPS + MCP)

1. Add `coolify A <IP>` DNS (`20-domain-dns-ssl.md`).
2. Coolify Settings → set the **instance domain** (`https://coolify.<domain>`) → wait for the cert.
3. Verify: `curl -s -o /dev/null -w '%{http_code}\n' https://coolify.<domain>/api/health` → `200`.
Until this step MCP is unusable (it needs a public HTTPS URL); REST over `http://<ip>:8000` remains the working contract.

## Harness MCP wiring (optional convenience layer)

Hermes — `~/.hermes/config.yaml`:
```yaml
mcp_servers:
  coolify:
    url: "https://coolify.<domain>/mcp"
    headers:
      Authorization: "Bearer <token>"
```
Claude Code:
```bash
claude mcp add --transport http coolify https://coolify.<domain>/mcp --header "Authorization: Bearer <token>"
```
Hostinger's remote MCP (`https://mcp.hostinger.com`) is OAuth-based — fine in Claude Code/Cursor; for Hermes use `ops/scripts/hostinger_api.py` with `$HOSTINGER_API_TOKEN`.

## Failure remedies

| Symptom | Likely cause | Fix |
|---|---|---|
| `Permission denied (publickey)` Step 2 (Hostinger) | key not attached / wrong id | re-run attach with the right `<keyId>`; re-check `GET …/{vmId}/public-keys` |
| `Permission denied (publickey)` Step 2 (generic) | paste never landed | re-paste the §3 one-liner in the provider console; check file perms 600 |
| `UNPROTECTED PRIVATE KEY` / bad permissions | Windows perms on the key file | `chmod 600`; use git-bash `/usr/bin/ssh`; add `-o IdentitiesOnly=yes` |
| `Host key verification failed` (bare ssh from an MSYS harness) | ssh read `/home/<user>/.ssh/known_hosts` (absent) instead of `$HOME/…` | add `-o UserKnownHostsFile="$HOME/.vps-ops/ssh/known_hosts" -o StrictHostKeyChecking=yes` (canonical form — trap in Step 3b) |
| `Host key verification failed` after a VPS rebuild | stale entry for `$VPS_IP` in the vault known_hosts | `ssh-keygen -R $VPS_IP -f ~/.vps-ops/ssh/known_hosts`, retry Step 2 |
| `:8000/api/health` not 200, or unreachable | install still running; AFTER Step 3b the port is loopback-only BY DESIGN (a timeout from the internet is the lock working) | wait 2–3 min; `docker ps`; from the agent machine run the tunnel (`py ops/scripts/coolify_api.py tunnel`) then `curl http://127.0.0.1:8000/api/health` — never re-open 8000 publicly |
| Token curl → `401` | API access off / token scopes wrong | `00-user-checklist.md` §4A, recreate the token |
| `config error: …` from a script | token/URL not stored | `dh vault set COOLIFY_TOKEN` + `dh profile set coolify.url=…` (curl lines: the `shell` line `dh vault list` prints) |
| SSH lost after firewall change | rule for 22 missing | add TCP/22 + `…/sync`; recover via provider console |
