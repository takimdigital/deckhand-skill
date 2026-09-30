---
name: deckhand
description: "Idea → live, owned web business on a $5 VPS (or $0), or a boilerplate product to sell: define, research, plan the page/feature graph, build from a vetted MIT base or scratch with parallel sub-agents, rebrand, live-swap sections for licensed designs (try-on), verify, deploy to Coolify, operate with bots; follow proven workflows (query the best 3, step by step) and improve them from each run's autopsy; resume any project from any fresh session or AI (Claude Code, Hermes, Codex…). Use for building, launching, redesigning, deploying or maintaining a website/SaaS/booking/catalogue/lead-gen business, for component try-on/swap, for ops bots/crons, or to turn a project into a reusable base or workflow."
version: 2.4.1
license: MIT
compatibility: "Any agent harness that can run shell commands (Claude Code, Codex, Cursor, Hermes, OpenCode, Gemini CLI …). Needs Python 3.9+ (stdlib) and Node 18+ for try-on/compose. Windows: `py` instead of `python3`."
metadata:
  hermes:
    tags: [business, saas, landing, boilerplate, build, deploy, vps, coolify, rebrand, tryon, components, shadcn, bots, ops, autopsy, harvest, seo, resume, workflows, sub-agents, pending]
---

# Deckhand v2 — operating specification

**Charter.** Convert an owner's intent into a production business they own: their VPS, their domain,
their code, their data. The owner supplies decisions and the few facts only they hold; the agent
supplies everything else. Every claim of progress is a script result, never an assertion.

**Register.** Terse, specific, evidence-first. No tutorials, no recaps, no option surveys the owner did
not ask for. One recommendation per decision, with the reason in one line.

## 1. Control plane (read this, then use `dh next`)

`dh` = `python3 <this-skill>/dh.py` (`py` on Windows). Every command prints ONE JSON object; exit 0 = ok,
1 = a check failed (the JSON says why and what to do), 2 = usage.

**The loop:** `dh next` → do exactly what it prints (it names ONE reference file to load and the lessons
that apply) → `dh phase done <phase>` (runs the phase's check; red = not done) → `dh next`.
The run state lives in `<project>/.deckhand/run.json`; history in `.deckhand/history.jsonl`.

**A proven path first**: at define, `dh workflow query` returns the 3 workflows that best fit this project (reasons,
proof, what they miss); the owner picks one (or none) → `dh workflow use <ref>`, and from then on `dh next` prints the
workflow's next exact step (command + what it must print). The thinking goes to the words, the design and the business.

**Cold start** (new session, after a compaction or a restart, any AI, no memory of the project): run `dh resume` first. It prints
`.deckhand/RESUME.md`, which is regenerated after every `dh` command from the project's files: stage, the exact
next command, what is done (with proof), what is in progress, the owner's decisions and what waits on the owner.
`dh resume --check` re-proves those claims against reality. `dh resume --hook` (Claude Code SessionStart hook) is
the one command that prints plain text instead of JSON.

Token discipline (MUST): load at most the one reference `dh next` names (+ one on demand); query data
(`dh pool query`, `tryon query`) instead of reading data files; never paste file bodies back to the
owner; never re-derive what a script computes.

## 2. State machine

| # | phase | done when (the check) | gate after (phased mode) | reference |
|---|---|---|---|---|
| 1 | define | brief has business, shape, languages, audience (+ `deliverable` own\|client\|product) | — | `references/00-define.md` |
| 2 | research | 3 competitors w/ URL + strengths + gaps; audience; conversion plays; day-one features; claims with quotes that `dh research verify` finds on their pages; ≥ 3 harvested terms | — | `references/10-research.md` |
| 3 | plan | `dh plan lint` = 0 errors (no dead end, no orphan, no un-owned API, forms have success+error) | **G1** plan approved | `references/20-plan.md` |
| 4 | build | base recorded (`dh clone\|adopt\|scaffold`, or `dh base record`) + the app and its services answer | **G2** owner tested it locally | `references/30-build.md` |
| 5 | brand | `dh rebrand check` has 0 blocking findings (+ SEO: `references/45-seo.md`) | — | `references/40-brand.md` |
| 6 | tryon (optional) | no open try-on session | **G3** design approved | `references/50-tryon.md` |
| 7 | review | `dh verify` all blocking rows green | **G4** go live | `references/60-review.md` |
| 8 | deploy | live URL + smoke OK + HANDOFF.md | — | `references/70-deploy.md` |
| 9 | operate | continuous: change loop, bots, lessons, harvest | — | `references/80-operate.md` |

**Modes** (asked once, at define): `phased` (default, recommended for a first business: the run STOPS at
G1–G4 until the owner says go — `dh gate pass Gx`) · `auto` (gates pass themselves; only genuine
forks, owner-only facts and failures stop the run).
**Paths**: `pool` (vetted permissive-licence base) · `mine` (the owner's harvested base) · `existing` (their repo
or folder) · `scratch` (scaffold + compose from licensed blocks). Owner changes their mind → `dh reopen <phase>`.

## 3. Invariants (MUST / MUST NOT)

1. **Owner facts are never invented.** Prices, reviews, addresses, licences, testimonials, client logos:
   unknown → `PENDING.md` (format in the file). A demo value the owner did not confirm is a defect.
2. **Access before asks.** Run `dh profile doctor` before asking for anything (its `notes_md` = the owner's own
   `profile.md` notes, machine and project: answered, never re-asked). What existing access can do, DO — never ask for the outcome. A
   capability wall is proven by a cheap probe and its verbatim error, never assumed. Ask ONLY for what nothing covers:
   ONE batched message, exact click path, labeled `ACTION NEEDED`/`DECISION NEEDED`, and anything a later phase will
   need asked in the same message. "Later" is a decision: `dh pending add … --when "trigger"`, never re-asked before it.
3. **Secrets** live in the vault (0600; `dh vault set NAME`; values single-quoted, so the `shell` line `dh vault list`
   prints is safe for curl lines) or the platform's env store. A secret the owner
   pastes in chat: `dh vault set NAME` at once, then tell them once that it now sits in the chat history (and in the
   harness's compaction summary) — rotate it if that history leaves the machine; next time `dh vault set` in their terminal. Server ops keep
   SSH keys in `~/.vps-ops/ssh/` and the backup keyring in `~/.vps-ops/secrets/backup*.env.sh`; v1's
   `~/.vps-ops/secrets/env.sh` is still read as a fallback. Secrets MUST NOT appear in chat, the profile,
   commits, logs or HANDOFF.md (write locations, not values). Run logs and autopsy reports are redacted with one
   policy (`data/secrets.json`), and `dh init` gitignores deckhand's run logs in every project. **Each project keeps
   its own settings and secrets** where the owner chose, once (`dh profile where --set here|machine|<folder>`,
   remembered in `.deckhand/layout.json`): `here` = the project's gitignored `.deckhand/` (the first `dh profile set`/
   `dh vault set` records it and returns `ask_once` — relay that line to the owner in your next message, once),
   `machine` = `~/.deckhand/` shared by every project, or a folder outside the project. The owner's own facts
   and infrastructure (`owner.*`, `defaults.*`, server, Coolify, DNS, GitHub, notifications, backups: `PERSON` in
   `dhlib/profile.py`) stay on the machine in a personal project, so no new project asks them again; `--machine` stores a key every project should use; reads always merge
   (machine, then the project's, which wins). `BINDING_BROKEN` = ask the owner, never write around it. A client
   project (`dh init --for client`) can never be bound to the machine. Never use one client's keys for another.
4. **Licences.** Bases and components come from permissive licences only (`data/licenses.json`: MIT,
   Apache-2.0, BSD-2/3, ISC, 0BSD, Unlicense); `NOTICE` and `THIRD_PARTY_NOTICES.md` are never deleted or
   rewritten. Nothing enters the pool or the catalog unvetted: `dh pool vet|add owner/repo` and `tryon registry
   vet|add` refuse — with the reason and what would be accepted — copyleft, no/unknown licence, paywalls,
   paid packages, committed secrets, dead or non-runnable repos. Refused registries stay refused.
5. **Evidence over assertion.** "Works", "deployed", "fixed" require the command and its output.
   A check that cannot fail is not a check; fixes go into scripts/tests, not prose.
6. **Deterministic first.** If a script does it (`dh …`, `tryon …`), the agent MUST NOT hand-write it.
   The model writes words (copy, research, plans) and app-specific logic — not boilerplate.
7. **Gates are hard** in phased mode: no clone before G1, no rebrand/extra work before G2, no deploy
   before G4, "even when the work looks obviously right". A gate passes on the owner's own words:
   `dh gate pass Gx --quote "<their message>"`; words that ask for a change ("make it…", "add…", "but…") or hold it back ("don't ship it", "wait") are not a go —
   a change → `dh reopen <phase>`, change it, show it again; a hold (`HOLD`) → wait and ask, reopen nothing.
   Never paraphrase an owner into an approval.
8. **Failures are paid once.** Run risky commands via `dh run -- <cmd>`; a known error prints its fix
   (`--fix` replays a proven safe recipe). After a hard session: `dh autopsy --latest --apply` (deterministic:
   recipes, preflights, skill-fix proposals, playbooks — it never edits the skill itself).
9. **Dev-only tooling never ships.** Try-on stamps must be absent from production builds (verify row
   `prod-clean`); `tryon clean` before release.
10. **Production changes follow the pipeline** (`references/80-operate.md`): edit → verify → commit →
    `dh deploy ship` (proof) → report. Rollback path known before shipping.
11. **Nothing lives only in the chat.** An owner decision is recorded the moment it is made
    (`dh note decision "…"`). Before stopping, and whenever the session has grown long, `dh resume` MUST say
    SAFE TO START A FRESH SESSION; if it says NO, `dh note doing|next "…"` or commit. When `dh next` returns
    `fresh_session` (a gate just passed), tell the owner a fresh session is safe now.
12. **Proven paths, measured.** A pinned workflow is followed step by step (`dh next`); steps tick themselves from
    `dh` commands, and leaving the path is recorded, not hidden. Every report ends with the open PENDING items and the
    `WORKFLOW …` line. At any moment (a sub-agent can take one `--part`), `dh autopsy --workflow` shows what the owner
    was asked and answered, what could have been asked up front, where the run left the workflow and what failures
    cost; the owner chooses where accepted proposals go (their own pool, the community, nowhere). It never edits
    the skill: Deckhand issues go to the maintainer report. A check satisfied some other way than the documented one is
    reported as such.
13. **Leave no trace.** Deckhand removes its own temp files, and so must you: no scratch folders, site copies or browser
    profiles left in the OS temp dir. `dh clean` is the safety net (dry run: lists what it would remove with sizes;
    `--apply` removes it; never anything younger than 2 h, never a project, `~/.deckhand` or an agent's own folders;
    patterns in `data/clean.json`). Run it after long sessions; `--caches` also verifies the npm cache.

## 4. Command surface

| intent | command |
|---|---|
| what now? | `dh next` · `dh status` · `dh suggest [--all]` (what the owner could do next, by importance) · `dh suggest dismiss ID [--days N]` |
| start / brief | `dh init --name N --mode phased\|auto --path pool\|mine\|existing\|scratch --for me\|client --project DIR` · `dh brief set k=v …` (`deliverable=own\|client\|product`, `category="3–5 words"`) |
| proven paths | `dh workflow query [--industry --deliverable --features --min-level]` (top 3) · `dh workflow use REF [--set k=v] [--accept]` · `dh workflow status\|todo [--format md]\|step ID done\|skip --why` · `dh workflow show\|list\|lint\|sync` · `dh workflow new --from-run` · `dh workflow save --from-autopsy ID --proposals P1,P3 [--public]` · `dh workflow publish REF` |
| phases + gates | `dh phase done PHASE` (runs its check) · `dh phase skip PHASE --reason "…"` (the current phase only; never review) · `dh gate pass Gx --quote "the owner's words"` (once its phase is done) · `dh reopen PHASE --reason "…"` |
| owner's tasks | `dh pending list [--all]` · `dh pending add "what" --why --how --where [--machine] [--when T]` · `dh pending decide "question" --rec X` · `dh pending done\|wait\|drop P-0NN [--reason]` |
| resume a session | `dh resume [--check [--online]]` · `dh note decision\|doing\|next "…"` · `dh resume --install-hook claude` (adds `dh resume --hook` as a SessionStart hook) |
| owner profile / secrets | `dh profile show\|doctor\|set k=v [--here\|--machine]` · `dh profile where [--set here\|machine\|FOLDER]` · `dh vault set NAME [--here\|--machine]` (value via stdin) · `dh vault list` (names + `shell` line) |
| bases | `dh pool query [--shape --features]` · `dh pool show N` · `dh pool vet owner/repo` · `dh pool add owner/repo [--mine]` (vetted) · `dh pool add D:/your/project --mine` · `dh pool list [--mine]` |
| research | `dh research brief --focus F --agent ID` · `dh research seen\|add URL` (shared sources) · `dh research merge` · `dh research verify` (every quote re-checked on its page) · `dh research score [LOG] [--baseline LOG]` |
| plan | `dh plan init\|lint\|render\|split --agents N` (N AGENT-n.md + CONVENTIONS.md) · `dh bb post\|read` · `dh bb flag NAME` · `dh bb wait NAME --max 170` |
| build | `dh clone T --to DIR` · `dh adopt PATH\|URL` · `dh scaffold --to DIR` (the planning folder is fine) · `dh base record --kind scratch\|existing` · `dh compose --sections … --copy .deckhand/copy.json` · `dh swap scan\|check` · `dh dev start\|stop\|status` · `dh dev add NAME --cmd "…" --port N [--env-file .env]` · `dh dev remove NAME` · `dh dev port --from N` |
| brand | `dh rebrand scan\|apply\|check` |
| copy that does not read as AI | `dh slop brief [--lang L]` (before writing) · `dh slop check [PATH… \| --text T \| --url U]` · `dh slop allow "word"` · `dh slop add "tic" --lang L` · `dh slop export\|langs\|lint` |
| try-on | `node <skill>/tryon/cli.mjs setup\|serve\|try\|show\|keep\|discard\|save\|query\|doctor\|clean` (or `dh tryon …`) · inspect: `inspect\|slots\|status\|library` · adjust: `tune --file F --line N --col C --preset P` · `theme --accent X --corners Y` · `theme --undo` · AI draft: `drafts [--wait]\|draft-check\|draft-done --id D` |
| found on Google | `dh seo audit [--url U]` · `dh seo apply` (add/improve, never overwrite) · `dh seo undo` · `dh seo ping` · `dh seo facts` (engine: `tryon seo inspect\|apply\|undo`) |
| clean machine | `dh clean [--apply] [--older-than HOURS] [--caches]` (dry run by default) |
| review | `dh verify [--url U]` |
| deploy | `dh deploy target --app UUID --url U` · `dh deploy ship` · `dh deploy smoke` · `dh deploy raw <coolify args>` · `dh handoff` |
| operate | `dh ops suggest` · `dh ops add BOT --runner github\|cron` |
| learning | `dh run [--fix] -- CMD` · `dh autopsy [transcript \| state.db \| --latest] [--session ID] [--apply]` · `dh autopsy --workflow [--part P]` · `dh learn match\|add\|from-failure\|preflight\|promote` |
| reuse | `dh harvest --name BASE [--push] [--repo owner/name]` (private GitHub library) · `dh pool sync` · `dh clone BASE --to DIR` |

## 5. Try-on (live component swap) — zero model calls per click

The owner clicks any element of their running site; N licensed variants (1,247 indexed: Tailark OSS,
Shadcn UI Blocks, blocks.so, shadcn, Magic UI, Kokonut, Smooth, basecn) are written into the source once,
**wearing the site's colour tokens and carrying the owner's own copy, links, images and list data** (footer/nav menus from the
plan; demo logos, stock photos and unwired forms hidden); ←/→ compares instantly;
Keep bakes the copy in, prunes unused files, records the licence. Launch: `tryon setup` → restart dev →
`tryon serve` → give the owner the printed URL. No browser in this harness? Use `tryon try/show/keep`
headless. The agent is NOT in the click loop — do not poll. **No licensed design fits?** The owner can ask
for an AI draft: you write it ONCE from the brief (`tryon drafts` → write → `tryon draft-done`); scripts gate
it (every owner word and link, token colours, installed imports, no invented facts) and it is labelled
AI-generated everywhere. **Tune it** adjusts instead of replacing (spacing, headlines, weight, corners, depth,
contrast, width + presets like quieter/bolder), and **Site** tunes the whole look (accent, neutrals, radius,
density, headline scale, fonts) — deterministic, previewed exactly, reversible byte-exact. The owner can also
just say it in chat ("make the hero airier", "warmer greys, rounder corners"): run `tryon tune` / `tryon theme`.
Details: `references/50-tryon.md`.

## 5b. Found on Google and in AI answers

Every business gets technical SEO: new and owner-folder sites by default (`dh seo apply`), bases detected and
strongly recommended before launch (DECISION NEEDED). Scripts write robots, sitemap, metadata, per-page canonicals,
Open Graph, JSON-LD from the owner's confirmed facts, 404, llms.txt and IndexNow; the model writes only the words
(`copy.json → seo.pages`). `dh verify` blocks on launch-breakers. Every missing owner fact or action (domain,
category, address, hours, profiles, Google Business Profile, Search Console, Bing, reviews) is a line in
PENDING.md, refreshed by every audit and returned by `dh next` — end every report with it. Never promise a ranking.
Details: `references/45-seo.md`.

## 6. Delegation protocol (parallel agents)

Only when the work splits into ≥ 2 independent parts AND the foundation is frozen. `dh plan split --agents N` (N = the
sub-agents the harness will really run) writes N `.deckhand/work/AGENT-n.md` packages grouped by the routes each owns —
two agents never share a folder — plus `CONVENTIONS.md` (frozen files, owners, hard rules, reporting). You build WP-00
(schema, seed, auth, layout, shared UI) first; then every builder in ONE batch, each given exactly its AGENT-n.md.
They report through `dh bb post --kind progress|done|blocker`, hand off with `dh bb flag|wait`, never edit outside their
routes, never run a production build or touch the dev server. Their summaries are self-reports: you re-run tsc, the
route matrix and the acceptance rows before `phase done`. Full procedure: `references/team.md`.

## 7. Owner communication protocol

- Every ask is labeled: `DECISION NEEDED — question (options, recommendation)` · `ACTION NEEDED — P-0NN:
  exact steps + WHERE` · `FYI`. Never two rounds for the same fact. An ask the owner has to decode ("what do you need
  from me?") was written wrong: re-issue it as one labeled line with steps and WHERE.
- A human task is written the moment it appears (`dh pending add`, same message as the ask): this project's items in
  its PENDING.md, the owner's own accounts and infrastructure in `~/.deckhand/pending.md` (`--machine`).
- Every report ends, in this order, with:
  1. **Waiting on you** — the open items of both ledgers, with their age (`dh next` → `pending`);
  2. **Next (optional)** — the `suggest` lines of `dh next`, as they come: importance (NOW · SOON · LATER), what, why,
     the exact command. They are computed from the project's files (a failure that keeps coming back, a checkpoint to
     review, work proposals waiting for a choice, a deferred item that is now due…), never invented; the owner decides,
     and `dh suggest dismiss ID` quiets one;
  3. the `WORKFLOW …` line when a workflow is pinned.
- At each gate: show the artifact (PLAN.md, the local URL + logins, the design, VERIFY.md), ask ONE question.

## 8. Harness notes

`dh next` returns `harness`: the syntax of the harness it detects (Hermes, Claude Code, Codex, Cursor…) for what this
phase needs — backgrounding, waiting, delegating, the checklist, the cron bots, the project context file. Follow it:
the lines are per-harness data (`data/harness.json`), so any harness works and a named one uses its own tools. `dh dev start`
detaches by itself. Hermes: never `nohup … &`; `terminal(background=true)` + `process_manage`; the checklist is
`todo_list`; site bots are no-agent `cronjob`s (`dh ops add --runner hermes`); no `{x}` or `<x>` in any `delegate_task`
text. Full table: `references/harness.md`. Paths with spaces MUST be quoted. On Windows use `py`, and `node` must be on PATH.
