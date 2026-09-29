# 30 — BUILD (four ways in, one running app)

**Objective:** a project folder with its own history that runs locally and implements the plan.
**Output:** `dh dev start` answers; `dh phase done build` green. **Gate G2:** the owner opens the URL and says go.

## Entry by path
| path | command | notes |
|---|---|---|
| pool / mine | `dh clone <template> --to <dir>` | shallow clone at the measured commit, fresh history, `NOTICE`, `.env` from the example with LOCAL secrets generated (never vendor keys), deps installed. The planning folder itself is fine: Deckhand's own files (.deckhand, AGENTS.md, PENDING.md) step aside and come back |
| existing | `dh adopt <folder\|git-url>` | history kept; stack detected; nothing rewritten |
| scratch | `dh scaffold --to <dir>` then `dh compose --sections hero,features,pricing,faq,cta,footer --copy .deckhand/copy.json` | create-next-app + UI base (tokens, `cn`, Button); compose assembles licensed blocks filled with the plan's copy — no code generation |
| built another way | `dh base record --kind scratch\|existing --note "how"` | a generator, a hand-written app: the base is stated in the open (never through a private function) |

### copy.json (scratch path) — the only input the model writes: words, never code
```json
{ "hero":     { "eyebrow": "…", "heading": "…", "text": ["…"], "actions": [{ "label": "…", "href": "/order" }],
                "image": { "src": "/hero.jpg", "alt": "…" } },
  "features": { "heading": "…", "text": ["subtitle"], "items": [{ "title": "…", "text": "…" }] },
  "pricing":  { "heading": "…", "items": [{ "title": "…", "price": "€9", "text": "…", "bullets": ["…"],
                "action": { "label": "…", "href": "…" } }] },
  "faq":      { "heading": "…", "items": [{ "title": "question", "text": "answer" }] },
  "footer":   { "text": ["…"], "columns": [{ "title": "…", "links": [{ "label": "…", "href": "/x" }] }],
                "social": ["https://instagram.com/…"] } }
```
Every owner word comes from the plan (never invented); missing facts → `PENDING.md`. Footer columns default
to the sitemap's `nav` (page titles as labels). A section that must keep the design's form says
`"form": true`, and its WP must then wire it with success and error states. Compose scores up to 8 designs per
section (owner words carried, demo left, design family) and reports `dropped` / `demo_copy`: rewrite those
words, never delete the report.

## Adding a base someone found (vetted, never on trust)
`dh pool vet owner/repo` measures it through the GitHub API (no clone, no code run) and judges it against
written criteria. Refused (any one): a licence outside the permissive family (`data/licenses.json`), a
`package.json` licence that contradicts it, archived or no push in 3 years, not a runnable web app (build +
dev/start), committed secrets, paid/private packages. Warnings: a paid tier in the README, stale, few
stars, huge monorepo, rented services to swap, try-on-incompatible framework. `dh pool add owner/repo
[--mine]` adds it only when accepted; a refusal prints the reasons and what would be accepted.
Component registries follow the same policy: `tryon registry vet|add --index <registry.json> --repo owner/name`.

## Swap rented services (pool/existing bases)
`dh swap scan` → `.deckhand/swap-map.json`. Replace ONE vendor at a time, keeping the base's call-site
interfaces (an adapter module), then `dh swap check` (vendor SDK absent + target present). Targets:
clerk/auth0/next-auth → **better-auth** · neon/planetscale/supabase-db → **postgres container** · resend/
sendgrid → **SMTP + failover router** (`templates/ops/mail-router`) · S3/uploadthing/blob → **RustFS/MinIO
(S3 API)** · sentry → logs or GlitchTip · posthog/plausible → **Umami** or none · algolia → **Meilisearch** ·
pusher → **SSE/socket.io** · stripe/paddle/lemonsqueezy → **KEEP** (a processor, not a lock-in).
Swap BEFORE the first build when the base validates env at build time. A swap bigger than a day is a scope
decision for the owner, never a silent half-swap. Smoke the swapped path (sign-up → session → protected page;
migrate → write → read), not the home page.

## Services the app needs (database, queue, mail catcher)
Declare them once: `dh dev port --from 5700` (a bind-tested free port — Windows reserves random ranges), then
`dh dev add db --cmd "npx pglite-server --db=.pglite --port=5772" --port 5772 --env-file .env`. From then on
`dh dev start` starts the services first (a live one is reused, a dead one restarted), then the app;
`dh dev stop` stops all; `dh dev status` and RESUME show what is down. Never keep a database alive by hand in a
terminal: a pause or a restart kills it silently. A dev script that pins its port (`next dev -p 3010`) is kept as is.

## Implementing the plan
- Solo: build WP by WP in `.deckhand/work/index.json` order (WP-00 shell first).
- Parallel (`references/team.md`): you build WP-00 (schema, migrations, seed, auth, layout, shared UI), prove it
  (`npx tsc --noEmit`, `dh dev start`), then dispatch every builder in ONE batch, each with exactly one
  `.deckhand/work/AGENT-n.md`. Coordination only through `dh bb post|read|flag|wait`. Before `phase done` you
  re-run tsc and the route matrix yourself — the builders' summaries are self-reports.
- Every page from the plan exists; every action reaches its declared target; every call shows its success
  and error state. Forms validate server-side. Seed data is realistic but marked as sample.
- Run commands through `dh run -- …` (known failures print their fix immediately).

## Run it
`dh dev start` (detached; `.deckhand/dev.log`; waits until it answers) → the G2 message: the URL, the logins per role
(a table), what you tested (route matrix, screens), what you found and fixed, ONE question. `dh phase done build` →
**G2** → `dh gate pass G2 --quote "<their words>"`. A check you satisfied some other way than the documented one is
said so in that message.

## Traps
Read `dh learn preflight --phase build` output — it is printed by `dh next` and is the current list.
