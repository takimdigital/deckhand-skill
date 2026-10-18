# 80 — OPERATE (the business keeps running; the pack keeps learning)

## Change requests (any time after deploy)
`OPS.md` / `.deckhand/deploy.json` present ⇒ this is a live app: edit → `dh verify` → commit (conventional
message) → `dh deploy ship` → report with the smoke evidence. Content/design changes may use try-on first.
Never edit production directly; never "quick fix" on the server.
Weeks later, in a new session or another AI: `dh resume` first (and `dh resume --check` before shipping: it says
whether the last verify and the live commit still match the code).

## Bots and crons
`dh ops suggest` ranks bots for this business (shape, features, deployed?). Install the top ones the owner
approves: `dh ops add <id> --runner github` (free Actions cron, state cached) or `--runner cron` (on the VPS).
Generic bots are real scripts (`watchdog`: uptime, TLS expiry, container health, backup age, disk;
`link-audit`: 404s + SEO basics; `backup-proof`; `deps-audit`). App bots (`weekly-kpi`, `lead-digest`,
`abandoned-signup`, `payment-failed`, `booking-reminder`, `review-request`, `low-stock`) ship as a spec +
skeleton: implement against THIS app's tables with a read-only DB user, idempotent, one message.
A schedule is live only after it fired once through its own trigger (the output prints the command).

## The learning loop (autopsy — deterministic, evidence only)
- Risky commands run through `dh run -- …`: every run (and every `dh` call) lands in `.deckhand/runs.jsonl`;
  a known signature prints its proven fix at once; `dh run --fix -- …` replays a recipe made only of safe,
  repeatable steps (installs, cache clears, codegen) and retries once.
- After a session (or a hard one): `dh autopsy [transcript.jsonl | --latest]` → `.deckhand/autopsy/<id>.md`.
  No model reads the log: failures (including those a `| tail` hid), their retries, **the recipe that
  actually fixed each one** (the edits and state-changing commands between the last failed attempt and the
  success), the owner (skill · environment · project), the fix-ladder rung the evidence supports, recurring
  signatures, blind retries, tool errors, and the workflows that finished a phase. Same session → same bytes.
- `dh autopsy … --apply` writes: lessons with recipes (global ledger — every future project gets them in
  `dh next` and `dh run`), skill-fix proposals in `~/.deckhand/autopsy/proposals/` (repro + the fix that
  worked + whether a regression test exists), and playbooks (a phase's working steps; after two sessions
  `dh next` shows them as `worked_before`). It never edits the skill: a person or a reviewed PR applies a
  proposal, with its regression test, and bumps `CHANGELOG.md`.
- `dh learn from-failure` / `dh learn promote` remain for a single fix recorded by hand.
- Sources: a Claude Code transcript, Hermes' own store (`state.db`, read-only — inside Hermes `--latest` is this
  session; else `--session ID`), a `hermes sessions export` file, any chat JSONL (`{"role","content"}`), and always
  `.deckhand/runs.jsonl`.

## Workflows — the path, improved by every run
- `dh autopsy --workflow` (any moment, not only at the end): the timeline (active time, pauses, gates and who passed
  them — the owner's words or an agent's note), every question put to the owner with the answer and what it changed
  (LATE: asked after define; DIRECTION-CHANGE: it re-opened work; LOST: the harness dropped the owner's message),
  deviations from the pinned workflow, what each failure cost (minutes, attempts, the step it hit), the sub-agent
  batches, how the AI talked to the owner (counts), then **proposals**, each with its reason and evidence. A long
  session? Give sub-agents one `--part` each (timeline, questions, deviations, errors, delegation, guidance, proposals).
- Show the owner the proposals block; they choose: `dh workflow save --from-autopsy W-… --proposals P1,P3` (their own
  pool, `~/.deckhand/workflows/`, never shared) · `--public` (a bundle for a community pull request, reviewed by the
  Deckhand maintainer) · nothing. The saved workflow gets the next version, this run as proof, and a changelog line.
- No workflow was pinned? `dh workflow new --from-run` turns this run into a draft for the next similar project
  (a plumbing kit after the cleaning one). Proof levels are computed: draft → proven (a complete green run) →
  trusted (3 green runs on 2 harnesses or systems, reviewed).
- The autopsy never edits the skill; Deckhand's own issues go to `.deckhand/autopsy/W-….maintainer.md`.

## Reuse — the owner's own library of bases (on their GitHub)
Owner likes the result → `dh harvest --name <base> --push`:
1. the tracked files are copied (no `.env`, no `.deckhand/` state), the brand is neutralised to the base's
   name, a manifest records pages, sections, stack and what proved it (last `dh verify`, live smoke);
2. a secret scan must be clean — or nothing leaves the machine (`SECRETS_IN_BASE` lists file:line);
3. a PRIVATE repo `<login>/deckhand-base-<name>` receives it; the library index `<login>/deckhand-library`
   (`library.json` + a readable README table) gets its row. Token: `dh vault set GITHUB_TOKEN` (fine-grained,
   Administration + Contents: read and write) — handed to git via the environment, never stored in a remote.
On any machine / harness: `dh pool sync` pulls the index → `dh pool query` ranks the owner's bases first →
`dh clone <base> --to <dir>` starts from it (private clone, fresh history, local secrets generated).
Without `--push` the base stays local (`~/.deckhand/bases/`), registered the same way.
Kept sections can also be saved one by one from the try-on panel (**Save to my library**).
