You are a model with no memory of this repo. This file is the map. Open a source file only to change it, or when a
table here points you at one. Lookup tables are grep-friendly: `^#### tryon/lib/engine.mjs`, `^- NO_CANDIDATES`,
`^- dh pool`. `sym@path:line` means symbol `sym` is defined at that line. Line numbers are exact for the fingerprint
above. After editing code, run `python3 scripts/llm_context.py` again.

## BOOT
WHAT  Deckhand v2 is an agent skill (MIT, repo takimdigital/deckhand-skill; one skill folder [[skills/deckhand/SKILL.md]]).
      It lets an AI agent in any harness (Claude Code, Codex, Cursor, Hermes, OpenCode, Gemini CLI) take a non-technical owner
      from an idea to a live, owned web business: define → research → plan → build → brand → try-on → review → deploy →
      operate. It runs on their own $5 VPS with Coolify, or on a $0 Oracle track.
WHY   Cheap in tokens and verifiable. Scripts do every deterministic step. The model writes only words (copy,
      research, plans) and app-specific logic. Every "done" is a command's output.
HOW   Two engines plus data plus docs:
      - dh — Python 3.9+ stdlib, [[dhlib]] via [[dh.py]]. The control plane: phase state machine, gates, checks,
        build, brand, verify, deploy, learning, reuse. Entry: `python3 skills/deckhand/dh.py <cmd>` (`py` on Windows).
      - tryon — Node 18+, zero deps, [[tryon]]. Live component swap/tune/theme on the owner's running dev site, and
        `compose` for scratch pages. Entry: `node skills/deckhand/tryon/cli.mjs <cmd>`, or `dh tryon <cmd>`.
      - [[data]]: policy and catalogs. [[references]]: one short page per phase, loaded one at a time.
        [[templates]]: files copied into projects. [[ops/scripts]]: Coolify/Hostinger/backup clients, ported from v1 and
        live-proven.
PATHS A path starting with dhlib/ tryon/ data/ references/ templates/ ops/ tests/ dh.py SKILL.md is under skills/deckhand/.
      Every other path is from the repo root (scripts/ docs/ .github/ README.md AGENTS.md …).
      "<project>" = the owner's app folder; "~/.deckhand" = the owner's home state (DECKHAND_HOME overrides).
YOU ARE EITHER
  (a) USING the skill for an owner → in a project already under way, `dh resume` first (where it stands, the owner's
      decisions, what waits on the owner). Then run `dh next` and do exactly what it prints: one instruction, one
      reference to read, the lessons that apply. The owner-facing rules are [[skills/deckhand/SKILL.md]] (register, invariants,
      command surface).
  (b) WORKING ON this repo → the DEV section. Tests are offline. Every behaviour change ships with a test. Regenerate this file
      (a stale file fails CI).

## ARCHITECTURE
```
owner ⇄ agent (any harness) ──shell──▶ dh (dhlib/*.py)                        one JSON object per call, exit 0|1|2
                                        │ run state  <project>/.deckhand/run.json   (state machine: phases + gates G1-G4)
                                        │ checks     dhlib/checks.py (a phase is done only when its script passes)
                                        │ subprocess ─▶ node tryon/compose.mjs (dh compose) · node tryon/cli.mjs (dh tryon)
                                        │ subprocess ─▶ git · npm/pnpm/bun/yarn · ops/scripts/coolify_api.py (dh deploy)
                                        ▼
owner's browser ─▶ tryon serve (tryon/server.mjs, 127.0.0.1:3999) ─ reverse proxy + injected overlay.js ─▶ dev server
                    /__dh/api/* (token) ─▶ tryon/lib/engine|draft|tune|sitetheme ─▶ writes the project's source
                    dev server HMR re-renders; the agent is NOT in this loop (0 model calls per click)
registries (https, cached in ~/.deckhand/cache/tryon) ─▶ materialize ─▶ <components>/dh-tryon/<slug>/ (staging)
```
- Contract. dh: [[dhlib/util.py#emit]] prints one JSON object. Failures raise [[dhlib/util.py#DhError]](code, message,
  **extra), and [[dhlib/cli.py#main]] prints {ok:false, code, message, …} with exit 1. Exit 2 = argparse usage.
  tryon: `out()` in [[tryon/cli.mjs]]; failures throw [[tryon/lib/engine.mjs#TryonError]](code, message, extra).
- Project detection. dh: [[dhlib/util.py#project_root]] (--project, else the nearest .deckhand/run.json, else
  package.json). tryon: [[tryon/lib/project.mjs#detectProject]] measures framework (next|vite), aliases, ui/lib dirs,
  package manager, deps, Tailwind major, globals.css, semantic tokens, and the primitive base (radix|base|any).
- Source edits (tryon). Parse with vendored @babel/parser ([[tryon/lib/ast.cjs#parse]]). Every node carries exact offsets,
  so every edit is a string splice on the original bytes. The result is re-parsed before it is written. Every open
  session has a backup, so discard is byte-exact.
- DOM → source. [[tryon/lib/stamp.cjs#stamp]] adds `data-dh="file:line:col"` to every JSX element. This happens only in
  dev, through [[tryon/loader.cjs]] (webpack/Turbopack), [[tryon/vite.mjs]], and the next-config wrapper written by
  [[tryon/lib/setup.mjs#setup]].
- Learning. `dh …` and `dh run -- …` append to <project>/.deckhand/runs.jsonl ([[dhlib/learn.py#log_run]]).
  [[dhlib/autopsy.py#autopsy]] turns that log, or a Claude Code transcript, into lessons/playbooks/proposals.
  `dh next` and `dh run` read them back.

## STATE — every file the skill reads or writes outside its own folder
| path | written by | read by | holds |
|---|---|---|---|
| <project>/.deckhand/run.json | [[dhlib/state.py#save]] | [[dhlib/state.py#load]] | name, mode phased/auto, path pool/mine/existing/scratch, phases{status}, gates{status}, base |
| .deckhand/history.jsonl | [[dhlib/state.py#log]] | humans | init / phase_done / gate / reopen events |
| .deckhand/brief.json | [[dhlib/cli.py#cmd_brief]] | checks, pool.query, brand, sitelinks, harvest | business, shape, languages, audience, brand{name,tagline,primary,logo,social} ([[templates/brief.json]]) |
| .deckhand/research.json | the agent (summary) · [[dhlib/research.py#merge]] (claims[], vocabulary[]) | [[dhlib/checks.py#research]], [[dhlib/research.py#verify]] | 3 competitors with URL, strengths and gaps; audience; conversion plays; features.now; claims {id, label, url, quote}; vocabulary {term, kind, url, quote} ([[templates/research.json]]) |
| .deckhand/research/agents/ID.json · sources.jsonl · verify.json · cache/ (gitignored) | each research agent (its own file only) · [[dhlib/research.py#add_source]] · [[dhlib/research.py#verify]] · [[dhlib/research.py#page_text]] | merge · `dh research seen` · checks.research ([[dhlib/research.py#verified_now]]) | claims + terms per agent · pages read with notes (append-only) · quote results + research_sha · fetched page text |
| .deckhand/sitemap.json | the agent, after [[dhlib/plan.py#init]] | [[dhlib/plan.py#lint]], render, split, sitelinks, verify routes | pages, actions with typed targets, nav, forms, features, entities ([[templates/sitemap.json]]) |
| .deckhand/PLAN.md · work/WP-*.md · work/AGENT-n.md · work/CONVENTIONS.md · blackboard.jsonl · work/state/<flag> | [[dhlib/plan.py#render]] · [[dhlib/plan.py#split]] · [[dhlib/plan.py#bb_post]] · [[dhlib/plan.py#bb_flag]] | owner · sub-agents ([[dhlib/plan.py#bb_wait]]) | the plan for G1; one WP per bounded context; exactly N agent packages grouped by owned route prefixes ([[dhlib/plan.py#_groups]]) + the shared rules; progress/contract/done/blocker posts; handoff flags |
| .deckhand/services.json | [[dhlib/build.py#service_add]] (`dh dev add`) | [[dhlib/build.py#dev_start]] (services first), dev_status, [[dhlib/resume.py#_services]] | services the app needs {name, cmd, port or ready regex, env_file} — committed config |
| .deckhand/suggest.json (gitignored) | [[dhlib/suggest.py#dismiss]] (`dh suggest dismiss ID --days N`) | [[dhlib/suggest.py#compute]] | {dismissed: {id: until date}} — a quieted suggestion comes back after the date |
| .deckhand/workflow.json | [[dhlib/workflow.py#use]] (a copy of the pinned workflow) | [[dhlib/workflow.py#progress]], observe, todo, autopsy | the workflow this run follows; run.json `workflow` = {id, version, source, sha, params, done[], skipped[], deviations[]} — a changed file is refused (sha) |
| .deckhand/copy.json | the agent | [[tryon/compose.mjs]] | section copy (schema in compose.mjs header; footer.columns/social, navbar.links) |
| .deckhand/slop.json · SLOP.md · slop-report.json | [[dhlib/slop.py#allow]] (`dh slop allow`; `ignore` globs by hand) · [[dhlib/slop.py#check]] (a project scan) | [[dhlib/slop.py#load]] (allow list), [[dhlib/slop.py#project_units]] (ignore) · owner | brand/trade words never flagged on this site · the last copy report: verdict, worst texts with hits and fixes |
| ~/.deckhand/slop/<lang>.json · slop/outbox/ | [[dhlib/slop.py#add]] (`dh slop add`) · [[dhlib/slop.py#export]] | [[dhlib/slop.py#load]] (merged over the shipped pack) | the owner's own cliché finds, applied at once · a bundle to contribute by PR (allow list left out) |
| .deckhand/dev.json · dev.log · svc-<name>.log | [[dhlib/build.py#dev_start]] | checks.build, verify, dev_status | url, pid, services{name: pid, up, log} · the dev server log · each service's log |
| .deckhand/swap-map.json | [[dhlib/swap.py#scan]] | [[dhlib/swap.py#check]] | vendor SDKs found → owned target |
| .deckhand/demo-copy.json | [[tryon/lib/engine.mjs#recordDemoCopy]] | [[dhlib/brand.py#check]] | demo words a kept design still shows (block), or AI-written words to confirm (ai:true → warn) |
| .deckhand/seo.json · SEO.md · seo-plan.json | [[dhlib/seo.py#audit]] · [[dhlib/seo.py#apply]] | owner, `dh next` (G4 summary), verify row `seo` | score, launch-breakers, findings by rule, owner gaps · the plan handed to the engine |
| PENDING.md "Detected by `dh seo`" block | [[dhlib/seo.py#sync_pending]] (every audit) | owner, [[dhlib/seo.py#pending_summary]] → `dh next` | open owner facts/actions (P-SEO-<key>), first-asked dates kept |
| <project>/lib/seo.ts · app/robots.ts · sitemap.ts · manifest.ts · opengraph-image.tsx · not-found.tsx · components/seo/json-ld.tsx | [[tryon/lib/seo.mjs#seoApply]] (marker `dh:seo`) | the app | business facts + JSON-LD · crawl rules · public routes · share image · real 404 |
| .deckhand/tryon/seo/last.json | [[tryon/lib/seo.mjs#seoApply]] | [[tryon/lib/seo.mjs#seoUndo]] | the files before the last SEO apply (byte-exact undo) |
| .deckhand/verify.json · VERIFY.md | [[dhlib/verify.py#run_verify]] | checks.review, handoff, harvest, [[dhlib/resume.py#check]] | rows {check, ok, blocking, detail}, commit (HEAD it proved) |
| .deckhand/deploy.json | [[dhlib/deploy.py#target]] · ship | checks.deploy, handoff, ops | app_uuid, url, last{commit,result}, smoke |
| .deckhand/RESUME.md (gitignored) | [[dhlib/resume.py#write]] after EVERY dh command ([[dhlib/cli.py#_refresh]]), success or failure | a cold agent (`dh resume`, the SessionStart hook) | where the project stands, rendered from its files by [[dhlib/resume.py#gather]] → [[dhlib/resume.py#render]]: switch verdict, stage, exact next commands, done+proof, gates, in progress, decisions, PENDING, recent; ≤ [[dhlib/resume.py#BUDGET]] chars |
| .deckhand/notes.jsonl (gitignored) | [[dhlib/resume.py#note]] (`dh note decision\|doing\|next`) | [[dhlib/resume.py#gather]], [[dhlib/resume.py#safety_facts]] | {at, ts, kind, text (redacted), phase}: what otherwise lives only in the chat |
| .deckhand/profile.json · vault.env · profile.md (gitignored; the project's layer, or the same three files in the folder it is bound to) | [[dhlib/profile.py#set_scope]] (`dh init --for client`; clone/adopt/scaffold carry scope, the choice and a copy of the layer to an app folder: [[dhlib/profile.py#carry]]; scope always stays in .deckhand/profile.json) · [[dhlib/profile.py#set_fields]] / [[dhlib/profile.py#vault_set]] (default unless the project is bound to `machine`; `--here`) · [[dhlib/profile.py#_move_layer]] (a re-bind carries them) | [[dhlib/profile.py#load]] (machine merged under project) · [[dhlib/profile.py#secret]] · [[dhlib/profile.py#layer_dir]] · [[dhlib/pending.py#profile_md]] · the ops scripts' `project_layer` | scope me/client + project facts · that project's secrets (a client's keys never leave its project) |
| .deckhand/layout.json (gitignored) | [[dhlib/profile.py#_write_binding]]: the first project write (`here`, chosen_by default, + `ask_once`) or `dh profile where --set here\|machine\|FOLDER` ([[dhlib/profile.py#bind]]) | [[dhlib/profile.py#binding]] (checked: corrupt, folder missing/unwritable, made for another root → not ok) → [[dhlib/profile.py#layer_dir]], [[dhlib/profile.py#_route]], RESUME "Settings and keys", handoff | {version, root, location here\|machine\|folder, dir, profile_path, vault_path, profile_md_path, writes, chosen_by, bound_at}: where THIS project's settings and keys are written |
| <project>/AGENTS.md (marked block) · CLAUDE.md (`@AGENTS.md` when new; the same block when the owner has one) | [[dhlib/resume.py#agent_entry]] (dh init, every build path) | any harness at session start | "run `dh resume` first" between `deckhand:begin`/`deckhand:end`; the owner's text is kept |
| ~/.claude/settings.json hooks.SessionStart | [[dhlib/resume.py#install_hook]] (`dh resume --install-hook claude`, `install.sh --claude-hook`) | Claude Code | `dh resume --hook` on startup/resume/clear/compact → [[dhlib/resume.py#hook]] prints the RESUME as context (nothing outside a project) |
| .deckhand/runs.jsonl · failures.jsonl | [[dhlib/learn.py#log_run]] · [[dhlib/learn.py#run_cmd]] | [[dhlib/autopsy.py#load_runs]], [[dhlib/learn.py#from_failure]] | every command {cmd, exit, out} · failed tails |
| .deckhand/lessons.jsonl | [[dhlib/learn.py#add]] (scope=project) | [[dhlib/learn.py#match]] | project-only lessons |
| .deckhand/autopsy/<A-id>.md,.json | [[dhlib/autopsy.py#autopsy]] | owner, `--apply` | the deterministic report |
| .deckhand/autopsy/<W-id>.md,.json,.maintainer.md · workflow-latest.json | [[dhlib/wfautopsy.py#run]] (`dh autopsy --workflow`) | owner (proposals + save prompt), [[dhlib/wfautopsy.py#workflow_save]], the maintainer · [[dhlib/workflow.py#progress]] (proposal count) | timeline, questions ledger, deviations, errors per step, delegation, guidance counts, proposals P1…, maintainer items |
| .deckhand/tryon/setup.json · runtime/ | [[tryon/lib/setup.mjs#setup]] | [[tryon/lib/setup.mjs#unsetup]], doctor | journal of the config patch (byte-exact undo) · copied loader/plugin |
| .deckhand/tryon/sessions/<id>.json · backups/<id>/ | [[tryon/lib/engine.mjs#open]] | show/keep/discard, checks.tryon, verify | open→kept/discarded, variants[], shaBefore/After · original file bytes |
| .deckhand/tryon/drafts/<D>.json · <D>/draft.tsx | [[tryon/lib/draft.mjs#requestDraft]] · the agent | [[tryon/lib/draft.mjs#checkDraft]], completeDraft | AI draft brief + state pending/rejected/done · the agent's component |
| .deckhand/tryon/tune/<id>.json(+.orig) | [[tryon/lib/tune.mjs#tuneOpen]] | tuneSet/Keep/Reset | dials, original file bytes and sha (FILE_CHANGED guard) |
| data/checks/<reg>.json (shipped) · ~/.deckhand/catalog/checks/<reg>.json (local) | [[tryon/lib/fitcheck.mjs#recordVerdicts]] (`tryon registry check`, `registry add`) | [[tryon/lib/catalog.mjs#loadVerdicts]] → rank | per-design fit verdicts; local wins; unreachable never recorded |
| .deckhand/tryon/flags.json · reports/tryon-flags-<sha10>.md | [[tryon/lib/flags.mjs#addFlag]] (overlay ⚑ Flag) · [[tryon/lib/flags.mjs#buildReport]] | `tryon flags`, the owner, the AI they send it to | flagged variants with everything to reproduce them · the report (the owner's text: never committed, never published) |
| .deckhand/tryon/theme/last.json | [[tryon/lib/sitetheme.mjs#themeApply]] | [[tryon/lib/sitetheme.mjs#themeUndo]] | the files before the last Site apply |
| <project>/PENDING.md · HANDOFF.md | [[dhlib/state.py#init]] (from [[templates/PENDING.md]]) · [[dhlib/handoff.py#write]] | owner | facts only the owner holds · access LOCATIONS, commands, pending |
| <project>/NOTICE · THIRD_PARTY_NOTICES.md | [[dhlib/build.py#clone]] · [[tryon/lib/engine.mjs#recordNotice]] | never rewritten | upstream + licence of the base and of every kept design |
| <project>/<components>/sections/ or ui-kit/<slug>/ · dh-tryon/ | keep · open | the app | kept designs · staging (removed on keep/discard/clean) |
| <project>/globals.css marked blocks | [[tryon/lib/theme.mjs#tokenLayer]] (deckhand:tokens) · [[tryon/lib/engine.mjs#open]] (dh:css per variant) · [[tryon/lib/sitetheme.mjs#themeCss]] (dh:theme) | the app | derived tokens · variant CSS · Site knobs |
| ~/.deckhand/profile.json · vault.env (0600) | [[dhlib/profile.py#set_fields]] · [[dhlib/profile.py#vault_set]] | [[dhlib/profile.py#secret]] (env → project vault → machine vault → v1 keyring), [[ops/scripts/coolify_api.py#resolve]] | owner facts and infrastructure (PERSON / PERSON_SECRETS always land here in a personal project; a client project's broken layer reads none of them) · secrets as `NAME='value'` (single-quoted: [[dhlib/profile.py#shell_line]] sourcing is safe), never printed |
| ~/.vps-ops/ssh/ · ~/.vps-ops/secrets/*.env.sh (v1 keyring) | the ops runbooks (SSH keys) · v1 | [[dhlib/profile.py#legacy_read]] (fallback), backup scripts | SSH keys for the servers · the backup keyring (backup.env.sh, b2-scoped.env.sh) · v1 tokens still honoured |
| <project>/.gitignore (deckhand block) | [[dhlib/util.py#ensure_gitignore]] (dh init, every build path) | git, verify `logs-ignored` | [[dhlib/util.py#GITIGNORE_LINES]]: runs, failures, *.log, dev.json, autopsy/, tryon/, RESUME.md, notes.jsonl, profile.json, vault.env, profile.md, layout.json; an older block is upgraded in place (every RESUME write calls it) |
| ~/.deckhand/pool.json · bases/<name>/ | [[dhlib/pool.py#add_local]] · [[dhlib/harvest.py#harvest]] · [[dhlib/pool.py#measure_local]] (`dh pool add D:/path --mine`) | [[dhlib/pool.py#rows]] (ranked first) | personal bases (source mine) |
| ~/.deckhand/workflows/<id>.json · outbox/ · cache/workflows/ | [[dhlib/workflow.py#save]] · [[dhlib/workflow.py#new_from_run]] · [[dhlib/workflow.py#publish_bundle]] · [[dhlib/workflow.py#sync]] | [[dhlib/workflow.py#rows]] / [[dhlib/workflow.py#load]] (mine → base → community) | the owner's workflows (never shared unless published) · community bundles to submit by PR · the community index + fetched files (sha-checked) |
| skills/deckhand/workflows/*.json · workflows/community/*.json + index.json (repo root, not installed) | the maintainer · community PRs + [[scripts/workflows_index.py]] | [[dhlib/workflow.py#rows]] | base workflows (shipped) · the community pool, read through its index from COMMUNITY_URL |
| ~/.deckhand/pending.md · profile.md | [[dhlib/pending.py#add]] / [[dhlib/pending.py#close]] (`dh pending … --machine`) · the owner (profile.md, by hand) | [[dhlib/pending.py#summary]] (→ `dh next` pending, RESUME) · [[dhlib/pending.py#profile_md]] (`dh profile show|doctor` notes_md) | the owner's cross-project human tasks (same line format as PENDING.md) · free-form facts about the owner (answered, never re-asked) |
| ~/.deckhand/lessons.jsonl · playbooks.jsonl · autopsy/proposals/E-*.md | [[dhlib/learn.py#add]] · [[dhlib/autopsy.py#apply_report]] | match/preflight · [[dhlib/guide.py#_playbook]] · a human | global lessons (+recipe, auto) · steps that finished a phase ≥2× · skill-fix proposals |
| ~/.deckhand/library/ (components/, components.index.json) | [[tryon/lib/library.mjs#saveToLibrary]] | [[tryon/lib/catalog.mjs#loadCatalog]] (r=mine, ranked first) | the owner's saved components |
| ~/.deckhand/registries.json · catalog/registry-<id>.json | [[tryon/lib/vet.mjs#addRegistry]] | [[tryon/lib/catalog.mjs#loadCatalog]] | vetted extra registries and their mapped items |
| ~/.deckhand/cache/tryon/ | [[tryon/lib/registry.mjs#getText]] | same | fetched registry files (a click never refetches) |
| GitHub <login>/deckhand-base-<name> (private) · <login>/deckhand-library | [[dhlib/harvest.py#harvest]] via [[dhlib/github.py#push]] · [[dhlib/harvest.py#library_upsert]] | [[dhlib/harvest.py#library_sync]], [[dhlib/build.py#clone]] | a harvested base · library.json + README table |

## INVARIANTS — never break these (and what enforces each)
1. Output contract: one JSON object on stdout; exit 0 ok · 1 check failed/refused · 2 usage. Nothing else on stdout
   ([[dhlib/util.py#emit]]; tryon `out`). The exceptions: `tryon serve` streams JSON lines, including
   {"event":"draft_request"}; `dh resume --hook` prints plain text (a harness injects it as context) and never fails.
2. Dependencies: Python stdlib only (3.9+). Node built-ins only (18+). The only vendored code is [[tryon/vendor]]
   (babel parser, MIT). Never use the project's own `typescript` package: TS7 has no JS API (lesson S-008).
3. Deterministic: same inputs → same bytes. This covers ranking ([[tryon/lib/catalog.mjs#rank]], [[dhlib/pool.py#score]]),
   verdicts ([[dhlib/vet.py#verdict]], [[tryon/lib/vet.mjs#vetRegistry]]), autopsy reports, tune/theme transforms and
   this file. No clocks or randomness in outputs, except ids and timestamps in state.
4. Edits are exact and reversible. Every source edit is AST-located, re-parsed before it is written, and backed up.
   Discard, tune reset, theme undo and `tryon clean` restore bytes exactly ([[tryon/lib/engine.mjs#discard]],
   [[tryon/lib/tune.mjs#tuneReset]], [[tryon/lib/sitetheme.mjs#themeUndo]], [[tryon/lib/setup.mjs#unsetup]]).
5. Dev tooling never ships. Stamps load only when NODE_ENV=development. Verify rows `prod-clean` and
   `tryon-closed` block ([[dhlib/verify.py#run_verify]]). `tryon clean` runs before review.
6. Owner facts are never invented. Unknowns go to PENDING.md. Demo copy left in a kept design blocks
   `dh rebrand check`. AI-written words are listed and warn until the owner confirms them
   ([[dhlib/brand.py#check]], [[tryon/lib/engine.mjs#demoTexts]], [[tryon/lib/engine.mjs#literalFit]]).
7. Secrets stay in the vault or env. They never appear on a command line, in a remote URL, stdout, a commit or
   HANDOFF.md. The GitHub token reaches git through GIT_CONFIG_* env ([[dhlib/github.py#git_env]]).
   One policy, [[data/secrets.json]], drives every scanner and the redaction:
   - [[dhlib/util.py#SECRET_RX]] feeds verify, harvest and vet; [[tryon/lib/library.mjs]] is strict.
   - [[dhlib/util.py#redact]] scrubs runs.jsonl, failures.jsonl and `dh run` output ([[dhlib/learn.py#scrub]]), plus
     every autopsy report, lesson and playbook. A recipe with a redacted step is never auto-replayed.
   - `harvest --push` refuses on any secret-shaped file or string ([[dhlib/harvest.py#secret_scan]], [[!SECRETS_IN_BASE]]).
   - Every project gitignores the run logs ([[dhlib/util.py#ensure_gitignore]]); verify blocks when they're not ignored.
   - Layers: [[dhlib/profile.py#use_project]] is set by [[dhlib/cli.py#main]] for every command. Where a write lands
     is [[dhlib/profile.py#_route]]: `--machine`/`--here` for one call; else the owner's own facts and infrastructure ([[dhlib/profile.py#PERSON]], [[dhlib/profile.py#PERSON_SECRETS]]:
     server, Coolify, DNS, GitHub, notifications, backups) → machine (personal project: no new project asks them again); else the project's binding (.deckhand/layout.json): none → record `here` + return `ask_once` (never
     asked again in that project); `machine` → ~/.deckhand; `here`/folder → [[dhlib/profile.py#layer_dir]]; broken →
     [[!BINDING_BROKEN]], nothing written (the pipeline's reads keep running on machine + .deckhand/). A client
     project can't bind to machine ([[!CLIENT_PROJECT]]); a folder inside the project is refused ([[!IN_PROJECT]]),
     so the gitignore guarantee holds; a re-bind moves the layer and stops on a differing value ([[!CONFLICT]]).
     Another project never reads it. The RESUME, notes, layout and project vault never leave the machine.
   Helper/CLI inputs are validated before they become CSS, class lists or paths: [[tryon/lib/sitetheme.mjs#cleanTheme]]
   ([[!BAD_THEME]]), [[tryon/lib/tune.mjs#dialsOf]] ([[!BAD_DIAL]]), safe ids ([[!BAD_ID]]).
8. One licence policy ([[data/licenses.json]]) for bases, registries and the catalog. NOTICE and
   THIRD_PARTY_NOTICES.md are never deleted or rewritten ([[dhlib/brand.py#NEVER]]). AI-generated variants carry a
   provenance header and no third-party notice.
9. Nothing enters on trust: `dh pool vet|add` ([[dhlib/vet.py#verdict]]) and `tryon registry vet|add`
   ([[tryon/lib/vet.mjs#vetRegistry]]). A refused item is refused with the reason and what would be accepted
   ([[dhlib/vet.py#acceptable_text]]).
10. Gates are hard in phased mode. [[dhlib/state.py#phase_done]] refuses out of order ([[!OUT_OF_ORDER]]) or behind an
   unpassed gate ([[!GATE_BLOCKED]]). A phase is done only when [[dhlib/checks.py#run]] says ok (or `--force REASON`,
   which is recorded).
11. The autopsy never edits the skill. It writes lessons, playbooks, and proposals for a human or a reviewed PR.
12. The agent is never in the click loop. The overlay calls the local helper; the helper calls the engine. A new
   try-on feature must not require polling the model.
13. Every behaviour change ships with a test. A fix that lives only in prose isn't a fix. After any change,
   regenerate LLM_CONTEXT.md.
14. Windows parity. Use `py`; read files with CRLF normalized; delete trees with [[dhlib/util.py#rmtree]] (read-only
   git objects); resolve launchers with [[dhlib/util.py#which]] (npm.cmd). Line endings follow [[.gitattributes]].
   CI runs Ubuntu and Windows.
15. Nothing lives only in the chat. RESUME.md is regenerated from files after every dh command; it is never a
   model recap. The switch verdict ([[dhlib/resume.py#safe]]) is computed: NO while files changed after the last note
   (dh-managed files excluded: [[dhlib/resume.py#MANAGED]]) or a failure newer than the last note has no known fix.
16. Gates pass on the owner's words. Phased `dh gate pass` needs `--quote` ([[!NEED_QUOTE]]); a quote that reads as a
   change request is refused ([[dhlib/state.py#classify_quote]], [[!CHANGE_REQUEST]]) and points at `dh reopen`. A go the
   owner holds back ("don't ship it", "wait, do not proceed", "this is not good": [[dhlib/state.py#HOLD_RX]]) is not a go
   either: with no change words it is refused as [[!HOLD]] ([[dhlib/state.py#is_hold]]: wait and ask, never reopen); a go with a change passes only when the go is explicit ("G1 ok, but…", "approved, but…":
   [[dhlib/state.py#STRONG_RX]]) — a bare "ok but add a blog page" is a change. In doubt, the gate asks again.
17. Workflows are data an AI runs: [[dhlib/workflow.py#lint]] refuses private calls, user paths, secrets, unknown dh
   commands (checked against the real parser) and, for base/community, anything off the allow-list; `use` shows every
   other command to the owner first ([[!NEEDS_ACCEPT]]); a community file must match its index sha ([[!SHA_MISMATCH]]).
   Rendered text never carries `{x}` or `<x>` (Hermes delegate_task refuses a batch that does). The workflow autopsy
   writes only its report; accepted proposals go where the owner says (mine / a public bundle), never into the skill.
18. Copy packs are data anyone may send: [[dhlib/slop.py#lint]] refuses a regex with a nested quantifier, lookaround or
   backreference (a pack can never hang a check), and a pack whose own examples disagree with its rules (slop example
   scored clean, clean example flagged, phrase missing its example). The verdict is deterministic: no model, no network.

## FLOWS (→ = then; each step names its code)
F1 RUN LOOP
- `dh init` → [[dhlib/state.py#init]] writes run.json, PENDING.md and the AGENTS.md cold-start block ([[dhlib/resume.py#agent_entry]]).
- `dh next` → [[dhlib/guide.py#next_step]] returns:
  - STEPS[phase], a list of commands ([[dhlib/guide.py#STEPS]]);
  - `read`, the one reference to load;
  - `lessons` from [[dhlib/learn.py#preflight]];
  - `worked_before` from playbooks;
  - `pool_top` during plan.
- Agent works → `dh phase done X` → [[dhlib/checks.py#run]]:
  - red → [[!CHECK_FAILED]] with `why[]`;
  - green → in phased mode a gate may block → owner says go → `dh gate pass Gn`.
- `dh reopen X` resets X and every later phase and gate.
- Order is one rule, [[dhlib/state.py#reached]]: every earlier phase done or skipped, no gate owed before it
  ([[!OUT_OF_ORDER]] / [[!GATE_BLOCKED]]). Used by `phase done|skip` and, via [[dhlib/state.py#require]], by clone/scaffold
  (build), `rebrand apply` (brand), `deploy ship` (deploy). A gate passes only once its phase is done ([[!GATE_NOT_DUE]]);
  review is never skipped ([[!NOT_SKIPPABLE]]); a skipped try-on passes G3 only in auto mode.
- Phases and their gates: [[dhlib/state.py#PHASES]]. G1 plan, G2 build, G3 tryon, G4 review.

F2 BUILD PATHS (run.json.path)
- pool/mine: `dh pool query` ([[dhlib/pool.py#query]]: [[dhlib/pool.py#score]] = shape +40, features, freshness…;
  blockers exclude) → `dh clone NAME --to DIR` ([[dhlib/build.py#clone]]):
  - licence re-checked;
  - shallow clone at the measured commit, or a private GitHub clone for mine;
  - fresh git history ([[dhlib/build.py#_fresh_git]]);
  - NOTICE written; .env seeded with LOCAL secrets only ([[dhlib/build.py#seed_env]]);
  - base recorded.
- existing: `dh adopt PATH|URL` ([[dhlib/build.py#adopt]]); history kept.
- scratch: `dh scaffold` ([[dhlib/build.py#scaffold]]: create-next-app in a sibling, moved in so `--to .` never removes
  the shell's folder; a relative `--to` is the project's; + [[templates/scaffold]] tokens/cn/Button) →
  `dh compose` (F3).
- `--to` another folder than the planning one: the app folder continues the SAME run ([[dhlib/build.py#carry_run]]:
  brief, sitemap, plan, gates, notes; logs and the settings layer stay, [[dhlib/profile.py#carry]] moves that); the
  planning folder records `moved_to`, `dh next` there says `cd`, `phase done` there is [[!MOVED]]. Only from a
  planning folder ([[dhlib/build.py#planning_folder]]: a run with no base yet): run from inside another business,
  nothing of it (keys, run) comes along.
- Then:
  - `dh swap scan|check` swaps rented vendor SDKs for owned targets ([[dhlib/swap.py#TARGETS]]; payment processors
    are kept);
  - `dh dev start` ([[dhlib/build.py#serve]]: detached process group, waits until the URL answers < 500) → owner
    tests → G2.

F3 COMPOSE (scratch landing page, no codegen)
- [[dhlib/build.py#compose]] → `node tryon/compose.mjs` reads .deckhand/copy.json → for each section:
  1. [[tryon/lib/catalog.mjs#rank]] (with a kit-coherence bonus);
  2. fetch and materialize;
  3. [[tryon/lib/transplant.mjs#parameterize]], then [[tryon/lib/transplant.mjs#bind]] with the copy;
  4. [[tryon/lib/sitelinks.mjs#fillLinks]] for footer/navbar;
  5. [[tryon/lib/engine.mjs#bake]].
- Output: components/sections/<slug>/, and the page imports them in order.
- Rules: one <h1> per page; copy with no room in the design is reported, never dropped silently.
- Then [[dhlib/build.py#compose]] reads the same copy.json with [[dhlib/slop.py#copy_units]] → `copy_check` in its output
  (verdict + worst sections) and a `next` to rewrite when it is not clean.

F4 TRY-ON SESSION WIRING
- `tryon setup` ([[tryon/lib/setup.mjs#setup]]):
  - next.config → `withDeckhandTryon(config)` ([[tryon/lib/setup.mjs#patchNextConfig]]);
  - vite → dhTryon() ([[tryon/lib/setup.mjs#patchViteConfig]]);
  - journaled. The token layer ([[tryon/lib/engine.mjs#ensureTokens]]) is added by the first open, not by setup.
- `tryon doctor`: the dev server `dh dev start` recorded (.deckhand/dev.json, any port) first
  ([[tryon/server.mjs#detectTarget]]); a Vite page renders in the browser, so its stamps are checked in the entry
  module the HTML loads, not in the HTML.
- Restart dev → `tryon serve` ([[tryon/server.mjs#startServer]]):
  - proxy rewrites Host/Origin to localhost (Next dev guard) and injects the overlay into HTML;
  - HMR websockets are passed through;
  - API gated by the per-run token; writes run one at a time.
- Overlay ([[tryon/overlay.js]]): owner clicks Try-on → picks an element (nearest data-dh stamp, breadcrumb of
  ancestors: the 5 innermost plus the sections that hold them) → chooses a slot ([[tryon/lib/slots.mjs]]) → tabs
  "Swap it | Tune it"; a "Site" button sits on the pill. A click on a button picks the control itself (not its label
  span). A typed refusal comes back as 200 {ok:false} (the owner's console stays clean); a malformed body is a 400.

F5 OPEN (swap) [[tryon/lib/engine.mjs#open]]
1. Find the element: [[tryon/lib/engine.mjs#pickElement]]. The one at file:line:col when it is what the owner clicked
   (the overlay sends a hint: tag + start of its text; [[tryon/lib/engine.mjs#fitsHint]] says no only when sure), else
   the same element found again nearest the old line ([[tryon/lib/engine.mjs#relocate]]; one unambiguous match or
   nothing). The page is older than the file after a session added/removed import lines → otherwise
   [[!ELEMENT_NOT_FOUND]] with `reload:true` (the overlay reloads and re-enters picking; it also reloads before the
   next pick after Keep/Discard). Tune uses the same lookup ([[tryon/lib/tune.mjs#tuneOpen]]). Coordinates that name
   an element already in an open try (the ones it was opened at, or inside its wrapper) → [[!SESSION_OPEN]] with
   its `id`: keep or discard first (reloading would not help).
2. [[tryon/lib/transplant.mjs#extractUnits]] gets the owner's content units: text, links, images, inputs, and
   unrolled .map lists — plus the words written beside a link (one run = a line of text, words on both sides = one
   sentence carried with the link inside), the owner's `<form>` elements (moved whole: action, handlers, fields) and
   each image's row ([[tryon/lib/transplant.mjs#ownerLogos]]: 2+ images side by side = their logo row).
3. [[tryon/lib/catalog.mjs#rank]] ranks candidates: mine first; primitive-base mismatch hidden and counted.
4. For each candidate:
   1. [[tryon/lib/materialize.mjs#fetchBundle]]: [[tryon/lib/registry.mjs]] json or gh transport, cached, https only,
      size/file caps.
   2. [[tryon/lib/materialize.mjs#writeBundle]]:
      - every file needed; the project's ui primitives reused; cn from lib/utils;
      - palette classes → tokens ([[tryon/lib/theme.mjs#normalizeClasses]]); compat fixes; a design's cva props on
        the project's reused primitives fitted to what the project's component takes
        ([[tryon/lib/materialize.mjs#fitProjectPrimitives]]: Veil's `<Card variant="outline">` vs a shadcn Card
        without variants passed dev and failed `next build` once kept).
   3. Blocks only:
      - [[tryon/lib/transplant.mjs#parameterize]]: static units → `content.x ?? demo`, demo lists → list slots;
        chrome hidden; demo brand logos hidden — or, when the owner has a logo row, the design's row becomes
        `logoRowN` (their `<img>`s, same spacing); a design form hidden — or, when the owner has a form, it becomes
        `formN` (their `<form>` whole); a prop default rendered as text (`title = "Design Systems"`,
        [[tryon/lib/transplant.mjs#defaultPropSlots]]) is a slot `@title`, passed as the prop itself
        ([[tryon/lib/transplant.mjs#contentProp]]); a state-switched label (`{on ? "A" : "B"}`) is one slot; a card
        template's constant button label is a list field `dhAction`; a featured card's extra line (its "Popular"
        badge) is optional and hides whole;
      - then [[tryon/lib/sitelinks.mjs#fillLinks]], then [[tryon/lib/transplant.mjs#bind]]. List items are built
        as JS source: a dynamic value (`{c.phone}`, an href `` `tel:${c.phone}` ``) travels as code, never through
        JSON; names bound inside the picked element (a `.map` item) never leave it;
      - fit gate ([[tryon/lib/engine.mjs#fitGate]]): a section carrying < half the owner's units is skipped as
        POOR_FIT (a lone label counts), a card or button carrying less than all of them too, and so is any design
        that has no place for the owner's form (`lost: 'form'`: a newsletter would lose its
        email field). Every word a staged design still shows of its own is marked `data-dh-demo`
        ([[tryon/lib/engine.mjs#markDemo]]; words inside a component get a marked span); Keep removes the marks
        ([[tryon/lib/engine.mjs#unmarkDemo]]). A UI primitive goes through this path when it does not render what is
        put inside it ([[tryon/lib/engine.mjs#rendersChildren]]: `{...props}` counts only on an element without
        children of its own; `'inline'` when `children` lands inside a text element — then only an owner element
        holding words is wrapped, a card's divs never go into a `<p>`); else it wraps the owner's content, and the
        design's own text-rendered prop defaults are passed empty ([[tryon/lib/transplant.mjs#defaultPropsOf]]). A
        button prop's link prop (`<a href={primaryCtaUrl}>{primaryCtaText}</a>`) takes the owner's href.
   4. Install-free candidates are checked as they are staged ([[tryon/lib/engine.mjs#checkImports]], one child
      node: every named import and `NS.x`/`<NS.X>` read must exist; a package the import itself needs and nobody
      installed counts) → BROKEN_IMPORT, and the next candidate takes the place. A candidate that needs an install is
      held: offered only when too few install-free ones exist (a running dev server may not see a new package).
      With the `radix-ui` umbrella installed, `@radix-ui/react-X` imports become `radix-ui/X`
      ([[tryon/lib/materialize.mjs#radixUmbrella]]) — nothing to install. Outside Next (Vite, CRA) `next/link` and
      `next/image` become local stand-ins written beside the design (NEXT_SHIMS in [[tryon/lib/materialize.mjs]]).
5. One batched npm install (held candidates only), then the gate again for them.
6. Sort by fit.
7. Write ONE wrapper (`data-dh-session`, variant 0 = the original, hidden). Imports are marked `// dh-tryon:<id>`.
   The result is re-parsed; the backup is saved.
8. Cycling ← → is client-side display toggling: zero writes. [[tryon/lib/engine.mjs#show]] persists the choice.
   The pool: a session holds `pool:{total,left}` ([[tryon/lib/engine.mjs#poolOf]]) and `tried` (every design offered
   or refused for good; a failed download is not remembered). More ([[tryon/lib/engine.mjs#more]], helper `more`,
   `tryon more --id S --batch N`): the variants on screen come back in their places (`first`; an AI draft from its
   own files via `aiItem`), then the next batch from the pool after them, up to [[tryon/lib/engine.mjs#MAX_VARIANTS]].
   A spent pool ([[!POOL_EMPTY]]) or a full try ([[!TOO_MANY_VARIANTS]]) touches nothing. Per-candidate staging is
   ONE function, [[tryon/lib/engine.mjs#stageCandidate]], shared with the registry fit check (F-FIT).
   Compare (overlay only, zero writes): variant 0 and the variant shown share one grid cell of the wrapper; the
   original is on top, clipped at the dragged line (`clip-path`), over the page background; `apply()` clears it
   before any display toggle (it restores the styles it saved). Flags: [[tryon/lib/flags.mjs#addFlag]] captures the
   variant, fit, usage, the owner's element from the session backup, [[tryon/lib/flags.mjs#designSlots]], the
   overlay's `autoCheck()` and the env into .deckhand/tryon/flags.json; [[tryon/lib/flags.mjs#buildReport]] writes
   ONE deterministic Markdown file named by its hash (no clock in it) with a `try --only` reproduce per flag.
9. Nothing fits → [[!NO_CANDIDATES]] or [[!NO_VARIANTS]] with `draft:{file,line,col,slot}`; the overlay offers an
   AI draft (F7). The message says why in the owner's words ([[tryon/lib/engine.mjs#noVariantsWhy]]: no room for
   your content, the closest fit, or no place for your form).
10. The page still builds: [[tryon/lib/engine.mjs#openVerified]] (helper open/more; `tryon try` with --url or
   .deckhand/dev.json). Baseline GET of the page → open → [[tryon/lib/engine.mjs#probeUntil]] reloads until the
   HTML holds THIS session's wrapper or a build error (a file watcher lags the write: the first answer can be the
   old page). An error → discard at once, [[tryon/lib/engine.mjs#culpritsOf]] (the variant folder in the trace,
   else the module it cannot load) → reopen without them (`dropped`, up to 3 tries) or [[!BUILD_BROKE]]
   `restored:true` — also when the designs left after dropping the culprits fit nothing (the message names the
   dropped ones, never a bare "no candidates"). Packages installed on the way stay and are reported (`installedKept`,
   on discard too). No dev URL known → opened with `verified:false` and a note: an `ok` never means the page was
   loaded. The 2.3.0 browser test ran `try` without one and read the footer 500 as a failed safety net.
   Vite ([[tryon/lib/engine.mjs#probeVite]]): the page's HTML never shows a variant, so the edited module is polled
   until it carries the session, then each design's entry module is requested (Vite resolves its imports then: a
   500 "Failed to resolve import" names the file; the request also warms Vite's dependency optimizer).
11. Content mapping rules learned live ([[tryon/lib/transplant.mjs#bind]]): `<summary>`/`<dt>` are headings (FAQ);
   `<figcaption>`/`<cite>` are the author line; a role only one side uses reads as text; a list item without a
   heading lends its first text to the design's heading field; clearly long demo text (a quote) takes the owner's
   longest text; one template spot, one role (the spot that shows "€290" shows "Custom" too); a price or period in a
   plain span is a field; the design's "/month" is blanked when the owner's price already says it; fixed slots take
   the owner's list items whole; a footer column's nested `links` get the owner's column links; a list field the
   owner does not fill keeps the design's words dashed (`<span data-dh-demo>`, only where the field is only ever
   text) and reported, and bakes back to the design's plain value on Keep. No plan: a design's demo menus and
   social rows are emptied ([[tryon/lib/sitelinks.mjs#fillLinks]]); the list merge then spreads the item's empty
   arrays first ([[tryon/lib/transplant.mjs#skeleton]]), so an owner column over an emptied demo array renders
   with `links: []` instead of crashing the page on `.map` (shadcnui-blocks footer-01..03 took Next down: HTTP 500). Logos inside content cards are hidden one by
   one, never the cards. From the component zoo (every common section kind, screenshotted): a figure (120+, 98%,
   24h, 7/7) is its own role `figure` and pairs with the design's figure; the owner's one short line becomes a
   headline the design would otherwise leave to demo copy; a card's title goes to the title and its longest text to
   the body ([[tryon/lib/transplant.mjs#pairCard]]), rows of a column packed one item each; a comparison table
   (rows of plain cells, equal width) goes into a design list with as many cell fields, positionally, its `<th>`
   names over the columns — a design without one gets none of the rows; the word that captions the owner's photo
   (`alt` = the name) goes to the design's captioning field; a list field also read as a value (`{t.period && …}`)
   is emptied rather than shown undashed, and a design's period never sits beside an owner's price.

F6 KEEP / DISCARD
- [[tryon/lib/engine.mjs#keep]]:
  - the wrapper collapses to the chosen variant under a clean local name;
  - the folder graduates to <components>/sections/ or ui-kit/<slug>;
  - [[tryon/lib/engine.mjs#bake]] writes the literal copy into the component (show/hide switches resolved);
  - losers and their CSS are deleted;
  - THIRD_PARTY_NOTICES entry ([[tryon/lib/engine.mjs#recordNotice]]; not for AI drafts);
  - leftover demo copy → demo-copy.json.
- Keeping variant 0 is a discard.
- [[tryon/lib/engine.mjs#discard]]: backup restore when sha matches, else a surgical unwrap. It also sweeps staging
  folders no open session shows (`swept`: left by a try that died mid-way, e.g. a killed process).
- `tryon save` → [[tryon/lib/library.mjs#saveToLibrary]]: refuses without a licence or when a credential-shaped string
  is found.

F7 AI DRAFT (labelled fallback; the agent writes once, scripts gate)
1. Overlay "AI draft", or `tryon draft` → [[tryon/lib/draft.mjs#requestDraft]] writes drafts/<D>.json. The brief holds:
   - content units, markup, hrefs, lists, images, dynamic expressions;
   - the original JSX;
   - the project's ui/utils/packages;
   - the rules and `write_to`.
   `tryon serve` also prints {"event":"draft_request"} on stdout.
2. Agent: `tryon drafts [--wait]` → writes <D>/draft.tsx (default export) → `tryon draft-done --id D`.
3. [[tryon/lib/draft.mjs#checkDraft]] gates:
   - DRAFT_EMPTY, DRAFT_FILE, DRAFT_ENTRY, DRAFT_PARSE, DRAFT_EXPORT;
   - DRAFT_IMPORT: only the project's ui/utils, installed packages, draft-local files;
   - DRAFT_SIDE_EFFECT: no fetch/env;
   - DRAFT_RAW_COLOR: tokens only;
   - DRAFT_IMAGE / DRAFT_LINK: only the owner's;
   - DRAFT_DROPPED_CONTENT: [[tryon/lib/engine.mjs#literalFit]] must carry every owner unit.
4. Gate outcome:
   - rejected → [[!DRAFT_REJECTED]] with problems; state rejected; fix and re-run;
   - passed → [[tryon/lib/draft.mjs#completeDraft]] folds any open session on the same element (discard, reopen
     with [aiItem, ...its registry items]) → engine.open with `candidates`.
5. Every AI variant is labelled everywhere:
   - `generated:true`; purple "AI-generated" badge;
   - file header "AI-generated … no licence notice applies";
   - invented words listed as ai-copy (warn).

F8 TUNE (one element; the Impeccable verbs as deterministic knobs)
- [[tryon/lib/tune.mjs#tuneOpen]] saves the original, then [[tryon/lib/tune.mjs#tuneSet]].
- Each set recomputes from the ORIGINAL: [[tryon/lib/tune.mjs#tuneElement]] → [[tryon/lib/tune.mjs#tuneClassList]] →
  [[tryon/lib/tune.mjs#tuneToken]] over the subtree's class strings. The result is written each time; HMR shows
  exactly what would be kept.
- Knobs: [[tryon/lib/tune.mjs#DIALS]]. Presets: quieter/bolder/airy/compact/clarity/softer/sharper
  ([[tryon/lib/tune.mjs#PRESETS]]).
- The pick: a Link inside `<Button asChild>` tunes the Button ([[tryon/lib/engine.mjs#styledBy]]: its classes make the
  button). On the picked control or component usage only, a knob with nothing to transform ADDS its class
  (rounded-*, shadow-*, font-*, text-*: a class on a shadcn usage wins through cn/tailwind-merge); a section never.
  A knob that still finds nothing says why and where to go instead (overlay WHY: Site → Corners…).
- Keep = stop tracking. Reset = byte-exact; after the owner edited the file ([[!FILE_CHANGED]] refuses further sets),
  Reset puts back only the class strings the knobs changed and keeps their edit (surgical, `undone`/`left`).
- From chat, no browser: [[tryon:tune]] `--file F --line N --col C --preset airy` (or `--density 1 …`) →
  `tune --id T --keep|--reset`.

F9 SITE (whole look)
- Knobs ([[tryon/lib/sitetheme.mjs#KNOBS]]): accent ([[tryon/lib/sitetheme.mjs#ACCENTS]] or any hex), neutrals,
  corners, density (Tailwind 4 --spacing), headlines (--text-*), fonts ([[tryon/lib/sitetheme.mjs#FONTS]]).
- Preview: the overlay asks [[api:theme-vars]] for the exact values ([[tryon/lib/sitetheme.mjs#themeVars]]) and sets
  them on :root.
- Apply ([[tryon/lib/sitetheme.mjs#themeApply]]):
  - writes one `dh:theme` block at the end of globals.css ([[tryon/lib/sitetheme.mjs#themeCss]]; unlayered body
    rule, headings in @layer base);
  - fonts: [[tryon/lib/sitetheme.mjs#rewriteFonts]] rewrites next/font in the root layout (AST) and adds
    --font-heading;
  - keeps the replaced files in theme/history.json (10 applies; a 2.2.x last.json still counts).
- Undo is byte-exact and walks back one apply at a time, to the original (`more` says how many are left).
- Fonts are Next-only (next/font in the root layout); a Vite project gets every other knob.
- From chat, no browser: [[tryon:theme]] (state and allowed values) · `theme --neutrals warm --corners round …` ·
  `theme --undo`.

F10 REVIEW `dh verify` → [[dhlib/verify.py#run_verify]]
- Rows: typecheck · lint (advisory) · build · prod-clean · tryon-closed · secrets · leaks/honesty
  ([[dhlib/brand.py#check]], AI-slop copy included) · routes · seo · copy-slop on the rendered routes (advisory,
  [[dhlib/slop.py#url_units]]) · a11y (advisory) · audit (advisory).
- routes: every planned static route plus every internal home-page link must answer < 400, on the production build
  served on a free port 4100+ (falls back to --url or the dev server).
- Writes verify.json and VERIFY.md. Any red blocking row → [[!VERIFY_FAILED]] → G4 can't pass.

F11 DEPLOY
- First time: runbooks [[references/ops/00-user-checklist.md]] → 10/11 (server) → 20/21 (domain) → 30 (app).
- `dh deploy target --app UUID --url U` → `dh deploy ship` ([[dhlib/deploy.py#ship]]):
  1. clean tree required ([[!DIRTY_TREE]]);
  2. git push;
  3. Coolify /deploy;
  4. [[ops/scripts/coolify_api.py#wait_for_deploy]] with expect_commit=HEAD, so a stale deployment can't pass;
  5. [[dhlib/deploy.py#smoke]] (http → NO_TLS warning; sslip/nip → PREVIEW_URL warning).
- `dh handoff` ([[dhlib/handoff.py#write]]).

F12 LEARN
- `dh run -- CMD` ([[dhlib/learn.py#run_cmd]]):
  - failure → [[dhlib/learn.py#match]] against lessons (seed [[data/lessons.seed.jsonl]] + ~/.deckhand + project) →
    prints the known fix;
  - `--fix` replays an `auto` recipe (safe commands only), then retries once.
- `dh autopsy [src|--latest] [--apply]` ([[dhlib/autopsy.py#autopsy]]):
  1. Sources: Claude JSONL ([[dhlib/autopsy.py#load_claude]]), runs.jsonl ([[dhlib/autopsy.py#load_runs]]), plain.
  2. Failure = non-zero exit, or error MARKERS in an executing command's output (pipes hide exits;
     [[dhlib/autopsy.py#is_failure]]). Designed refusals (USAGE, GATE_BLOCKED, OUT_OF_ORDER, DRAFT_REJECTED) are
     not failures.
  3. Episodes are merged by [[dhlib/autopsy.py#signature]]. The recipe = the state-changing steps between the LAST
     failed attempt and the success (verification commands excluded).
  4. Owner ([[dhlib/autopsy.py#_owner]]): skill · environment · project.
  5. Rung ([[dhlib/autopsy.py#_rung]]): eliminate > preflight > reorder > gate > pitfall.
  6. `--apply` ([[dhlib/autopsy.py#apply_report]]): lessons with recipe/auto, skill proposals E-*.md, and playbooks
     that `dh next` shows as `worked_before` (seen ≥ 2).
  7. In a dev session (cwd has skills/deckhand/SKILL.md), everything is owned by the skill and no playbooks are made.

F13 VET
- Bases: `dh pool vet|add owner/repo`:
  - [[dhlib/pool.py#measure]] reads the GitHub API and raw files; no clone, no code run;
  - [[dhlib/vet.py#evidence]] → [[dhlib/vet.py#verdict]];
  - hard criteria: licence, consistent, alive, runnable, clean, free; soft criteria are warnings and ranking
    penalties;
  - add refuses with [[!REFUSED]].
- Registries: `tryon registry vet|add` → [[tryon/lib/vet.mjs#vetRegistry]]:
  - checks: refused-list hosts, the repo licence, shadcn schema, usable items, sampled downloads with no paywall;
  - accepted → [[tryon/lib/vet.mjs#addRegistry]], items mapped by [[tryon/lib/regmap.mjs#mapShadcnItems]];
  - licence: the GitHub API, else the repo's own LICENSE file read raw ([[tryon/lib/vet.mjs#spdxOf]]; a Commons
    Clause or copyleft text is never permissive).
- F-FIT, the fit check (`tryon registry check --id X|all [--sample N] [--md] [--ship]`; `registry add` runs it on a
  sample) → [[tryon/lib/fitcheck.mjs#fitCheck]]:
  - each item is staged by [[tryon/lib/engine.mjs#stageCandidate]] (the same function a real try uses) against a
    REFERENCE owner section of its kind in a throwaway scaffold site ([[tryon/lib/fitcheck.mjs#makeSite]]; deps
    stubbed, one site per primitive base), so a verdict means what an owner would see: fits · partial (shown,
    some owner content dropped) · refused (the fit gate would skip it) · broken (it cannot be staged) · unreachable
    (download failed: not recorded) · unchecked (no reference for its slot);
  - [[tryon/lib/fitcheck.mjs#recordVerdicts]] → `data/checks/<reg>.json` (shipped, `--ship`) or
    `~/.deckhand/catalog/checks/<reg>.json` (local, wins) → [[tryon/lib/catalog.mjs#loadVerdicts]];
  - [[tryon/lib/catalog.mjs#rank]] hides a broken design (never offered unless `try --only` names it), puts a
    refused one last (−30) and a fitting one first among equals (+3);
  - gaps it found, fixed in the engine: a footer/navbar showing the plan's menu carries the owner's links that menu
    already holds ([[tryon/lib/engine.mjs#carryPlanLinks]]); `© {2026}` / `© {new Date().getFullYear()}` are
    copyright slots ([[tryon/lib/transplant.mjs#selfContained]]); a Base UI `<Button render={<Link>…</Link>} />`
    carries its action like the Radix `asChild` twin ([[tryon/lib/transplant.mjs#renderedBy]]); a primitive's part
    (`CardHeader` beside `Card`) is never stripped as site chrome; a shadcn block read raw gets its page's one
    component as the entry, `from "cn"` as the project's utils ([[tryon/lib/materialize.mjs#rawSource]]; read as a
    package it would install an unrelated npm `cn`), and a fetched primitive's own primitives in turn; footer columns
    titled by `group` (`{ group, items }`) take the plan's columns ([[tryon/lib/sitelinks.mjs#columnShape]]); a block
    importing another block's file (`@/registry/blocks/radix/navbar-04/components/logo`) or its registry's own
    primitive (`ui/marquee`) gets it from that registry's JSON beside its own; a form kept in a file beside the
    design (`<LoginForm />` from `./login-form`) is the design's form, so the owner's form takes its place;
  - refusals left on purpose: a one-quote testimonial or a logo-only integrations row cannot hold the reference's
    content (an owner with less still gets it: the gate runs again on the real section); a text effect whose words
    are a required array prop (`words`, `texts`) has no place for one heading.

F14 REUSE
- `dh harvest --name N [--push]` ([[dhlib/harvest.py#harvest]]):
  1. copy tracked files, minus [[dhlib/harvest.py#DROP]];
  2. neutralize the business to N ([[dhlib/harvest.py#_facts]]): its name in every spelling (Sunny Bakery,
     sunny-bakery, SunnyBakery…), phone however written, emails, address, domain, social profiles, owner, tagline,
     any tel: link → placeholders the rebrand check blocks on (hello@example.com, +1 555 0100, 123 Main St…); its
     data files (seed, fixtures, data/, public photos) are kept so the base builds and fingerprinted in the
     manifest (`owner_data`): the next project's `dh rebrand check` blocks (`previous-business-data`) until each
     is replaced; `.env.example` is kept;
  3. write a manifest (proven by verify and live URL);
  4. register in the personal pool.
- `--push`:
  1. [[dhlib/harvest.py#secret_scan]];
  2. [[dhlib/github.py#ensure_repo]] creates a private <login>/deckhand-base-N;
  3. push to main;
  4. [[dhlib/harvest.py#library_upsert]] updates <login>/deckhand-library (library.json + README table).
- Another machine: `dh pool sync` ([[dhlib/harvest.py#library_sync]]) → `dh clone N` (private clone on the recorded
  branch).
- Components: `tryon save` → ~/.deckhand/library (ranked first).

F15 OPERATE
- `dh ops suggest` ([[dhlib/ops.py#suggest]]: [[data/bots.json]] vs the brief and whether it's deployed) →
  `dh ops add BOT --runner github|cron` ([[dhlib/ops.py#add]]):
  - generic bots are real scripts ([[templates/bots]]: watchdog, link_audit, notify);
  - app bots are a spec plus skeleton the agent completes.
- Change pipeline: [[references/80-operate.md]].

F16 BRAND
- `dh rebrand scan|apply|check` ([[dhlib/brand.py#apply]]): package name, metadata, template names, primary colour
  token, monogram icon.
- check blocks on: template names, demo companies, lorem, example contacts, placeholder images, demo-copy markers,
  third-party logos as social proof, and copy scored slop (kind `ai-slop`, F24; review-level copy warns).

F24 COPY CHECK (AI slop) `dh slop …` → [[dhlib/slop.py]]
- One engine, one JSON pack per language ([[data/slop]]: en fr es de it pt nl pl ja ko zh; [[data/slop/_common.json]]
  weights + thresholds). [[dhlib/slop.py#load]] = shipped pack + ~/.deckhand/slop/<lang>.json + the project allow
  list + the brand name's words → [[dhlib/slop.py#Pack]] (every entry compiled once).
- Where the words are: [[dhlib/slop.py#project_units]] = .deckhand/copy.json per section ([[dhlib/slop.py#copy_units]])
  + site files (JSX/Vue/Svelte/Astro text and prose strings [[dhlib/slop.py#markup_fragments]], md/mdx, html, content
  json/ts), never README/docs/tests/components/ui ([[dhlib/slop.py#EXCLUDE]]); a line with `dh:slop-ok` is skipped.
  [[dhlib/slop.py#url_units]] = rendered pages of any URL (home + its internal links, max_pages).
- Language per text: --lang, else a locale in the path, else [[dhlib/slop.py#detect]] (script: kana/hangul/han, then
  stopwords among brief.languages). No pack → the language-free features only.
- [[dhlib/slop.py#analyze]]: phrases (a phrase inside a longer one counts once; words inside a phrase too) → words
  (strong/buzz) → transitions (from the 2nd) → superlatives without a number → em dashes, "!", emoji over a rate →
  triads (from the 3rd) → flat rhythm (≥ 8 sentences, low CV). Points per 100 words (floor 40) → clean | review | slop;
  one strong hit ⇒ ≥ review; kind leak ⇒ slop. Hits carry line (files) or key (copy.json) and the pack's fix.
- `check` raises [[!SLOP]] on slop and writes SLOP.md; `brief` = what not to write (before writing); `add`/`export` =
  the owner's finds → a community bundle; `lint` = [[dhlib/slop.py#lint]] ([[!PACK_INVALID]]).

F17 FOUND ON GOOGLE (SEO)
- Policy: [[data/seo.json]] (rules C/M/T/S/L/O/I/P/E/A, owner facts, owner actions, AI crawlers, schema types).
  By path ([[dhlib/guide.py#_seo_steps]]):
  - scratch and existing: `dh seo apply` in the brand phase;
  - pool and mine: `dh seo audit` + DECISION NEEDED, repeated at G4.
- [[dh:seo]] `apply` ([[dhlib/seo.py#apply]]):
  1. [[dhlib/seo.py#plan]] builds the plan: facts from the brief only ([[dhlib/seo.py#jsonld]]), the plan's public
     pages, the model's words from copy.json seo.pages, an IndexNow key stored in the brief.
  2. `tryon seo apply` → [[tryon/lib/seo.mjs#seoApply]] adds or improves: never replaces an owner file or title;
     removes a root-layout canonical (rule M05 is why); skips 'use client' pages and dynamic routes with a note.
- `audit` ([[dhlib/seo.py#audit]]) combines:
  - source: [[dhlib/seo.py#check_source]] via [[tryon/lib/seo.mjs#seoInspect]];
  - the plan: [[dhlib/seo.py#check_plan]];
  - images: [[dhlib/seo.py#check_images]];
  - rendered pages: [[dhlib/seo.py#check_page]], [[dhlib/seo.py#check_graph]], [[dhlib/seo.py#check_home]],
    [[dhlib/seo.py#check_nap]];
  - the host: [[dhlib/seo.py#check_site]] (live https: redirects, one host, rule M12: placeholder canonicals).
  It then applies the score, [[dhlib/seo.py#sync_pending]] and SEO.md.
- A REMOTE preview (sslip/nip/http) must be noindex (C07); a local production build must not be (C02).
- [[dhlib/verify.py#run_verify]] adds row `seo` on the served build (blocking = launch-breakers only).
- [[dhlib/deploy.py#ship]] → [[dhlib/seo.py#ping]] (IndexNow) on production.

F18 RESUME (any session, any AI)
- Every `dh` command → [[dhlib/cli.py#_refresh]] → [[dhlib/resume.py#write]] (after the command, even when it failed;
  clone/adopt/scaffold also refresh the new project). `resume`/`note` write it themselves and are not logged in runs.jsonl.
- [[dhlib/resume.py#gather]] reads run.json, history, notes, brief/research/sitemap/verify/deploy, SEO + PENDING
  ([[dhlib/seo.py#pending_summary]]), try-on sessions ([[dhlib/resume.py#_sessions]]), git status/log, and
  [[dhlib/guide.py#next_step]] (DH/TRYON shortened to `dh`/`tryon`).
- [[dh:note]] decision|doing|next → notes.jsonl (redacted with the vault values). `doing done` clears doing.
- [[dh:resume]] → {safe_to_switch, why, file, resume, session}; session = the Claude Code log size
  ([[dhlib/resume.py#session_hint]]; > 2 MB → "a fresh session will be sharper").
- `dh resume --check` → [[dhlib/resume.py#check]]: phase checks re-run (define…tryon); G1 vs brief/sitemap mtime;
  dev URL answers (info); verify.commit vs HEAD and files edited after verify; deploy last.commit vs HEAD (info);
  `--online` smoke; open try-on after tryon done. Drift → [[!DRIFT]] exit 1.
- [[dhlib/guide.py#_fresh_session]]: last history event is a gate and the verdict is YES → `dh next` returns
  `fresh_session` (the moment to offer a new session).
- Cold start: `dh init` → [[dhlib/resume.py#agent_entry]]; Claude Code → [[dhlib/resume.py#install_hook]] +
  [[dhlib/resume.py#hook]] (finds the project from the hook's stdin cwd, [[dhlib/resume.py#stdin_if_piped]] never hangs).

F20 WORKFLOWS (proven paths)
- `dh workflow query` → [[dhlib/workflow.py#query]]: facets from the brief + flags ([[dhlib/workflow.py#_facet]];
  industry → family via [[data/industries.json]], longest keyword wins) → [[dhlib/workflow.py#score]] over index rows
  only ([[dhlib/workflow.py#rows]]: mine, base, community — the community index refreshed at most daily,
  DECKHAND_OFFLINE skips it) → top 3 with reasons, missing, proof. Level from runs: [[dhlib/workflow.py#level]].
- `dh workflow use REF` → [[dhlib/workflow.py#use]] (lint, NEEDS_ACCEPT, pin sha + params, copy to workflow.json).
- Every successful dh command → [[dhlib/cli.py#_observe]] → [[dhlib/workflow.py#observe]]: the matching open step is
  ticked ([[dhlib/workflow.py#_norm]]: dh + 2 words, + a gate/phase name); a state-changing command no step names is a
  deviation (phase exits excepted); `phase done` closes ask/write/delegate steps and marks unrun steps not-run.
- [[dhlib/guide.py#next_step]] → [[dhlib/workflow.py#progress]]: `do` = the phase's open steps rendered
  ([[dhlib/workflow.py#step_line]] + [[dhlib/workflow.py#fill]]), `workflow.line` = the status line (also in RESUME).
- `dh workflow todo` ([[dhlib/workflow.py#todo]]) · `step` · `new --from-run` ([[dhlib/workflow.py#new_from_run]]:
  successful state-changing commands per phase, paths made generic, decisions as learned questions) · `publish`.

F21 WORKFLOW AUTOPSY
- Sources ([[dhlib/autopsy.py#detect]] → [[dhlib/autopsy.py#load]]): Claude Code JSONL (+ messages, timestamps),
  Hermes state.db ([[dhlib/autopsy.py#load_hermes_db]]: read-only, the session from --session / HERMES_SESSION_ID /
  latest with this cwd, its compression lineage without sub-agents, async_delegations), Hermes export
  ([[dhlib/autopsy.py#load_hermes_export]]), chat JSONL ([[dhlib/autopsy.py#load_chat]]), runs.jsonl.
  [[dhlib/autopsy.py#_hermes_rows]]: `terminal` calls → commands (exit_code), write_file/patch → edits.
- [[dhlib/wfautopsy.py#run]] → timeline (phase marks, active vs pauses > 20 min, gates with quote or PARAPHRASED) →
  [[dhlib/wfautopsy.py#questions]] (assistant asks → next owner message; kind define/gate/late; DIRECTION-CHANGE =
  a change-request answer at a gate, or a reopen/brief change/decision within 30 min; LOST) → deviations →
  [[dhlib/wfautopsy.py#errors]] (the failure engine, episodes mapped to steps, minutes) → delegation → guidance →
  [[dhlib/wfautopsy.py#proposals]] → reports (owner + maintainer), id = hash of the content, `--part` one section.
- `dh workflow save --from-autopsy W --proposals P1,P3 [--public]` → [[dhlib/wfautopsy.py#workflow_save]]: learned
  question (asked in the define round), added step, optional step, pitfall; this run as proof; version + 1; changelog.

F22 OWNER'S TASKS (pending)
- `dh pending add|decide|done|drop|wait|list` → [[dhlib/pending.py]]: project PENDING.md or `--machine`
  ~/.deckhand/pending.md; IDs from item lines only ([[dhlib/pending.py#_next_id]]); HOW + WHERE required
  ([[!NEED_HOW_WHERE]]); `when:` = a deferral (not listed until `--all`); the checkbox is the state of record.
- [[dhlib/pending.py#summary]] (project + machine, ages) → `dh next` pending → RESUME "Waiting on the owner".

F23 SUGGEST (what the owner could do next)
- [[dhlib/guide.py#next_step]] → [[dhlib/guide.py#_suggest]] (the `do` commands passed as exclude_cmds: never said twice)
  → [[dhlib/suggest.py#compute]] → [[dhlib/suggest.py#facts]] (run state, history, the run-log tail, notes-based safety,
  both pending ledgers, report dates, verify/seo/deploy, HEAD — no network) → every rule in [[dhlib/suggest.py#RULES]]
  (a failing rule is skipped) → dismissed ids hidden until their date → sorted by (-score, id) → top 3 + `more`.
  Levels: now ≥ 80 · soon 50–79 · later < 50. Guard refusals ([[dhlib/util.py#GUARD_CODES]], [[dhlib/util.py#is_guard]])
  are decisions: not failures here, not in RESUME's verdict, not autopsy episodes.
- [[dhlib/resume.py#render]] prints [[dhlib/suggest.py#lines]] under "Next (optional)" after "Waiting on the owner".
- The autopsy command follows the harness ([[dhlib/suggest.py#autopsy_cmd]]: `--latest` inside Hermes / Claude Code).

F19 RESEARCH EVIDENCE
- `dh research brief --focus F --agent ID` ([[dhlib/research.py#brief]]): questions from [[data/research.json]] filled
  from the brief (business, audience, market, language), budget, pages already read, vocabulary so far, the card
  [[references/research-card.md]].
- Agents: `dh research seen URL` → open → `dh research add URL --by ID` (append-only [[dhlib/research.py#add_source]];
  returns other agents' notes) → claims + vocabulary in research/agents/ID.json.
- `dh research verify` → [[dhlib/research.py#merge]] (single writer; DUP_ID refuses) → per item
  [[dhlib/research.py#_problems]] (label rules) → [[dhlib/research.py#page_text]] (visible text via _Text: no
  script/style; meta description and alt kept; cached) → [[dhlib/research.py#quote_in]] (normalized, `…` joins parts).
  Statuses: found · mismatch · invalid · unchecked (blocked, error, PDF, < 200 chars = JS-drawn). ok = no mismatch,
  no invalid claim, no bad term → [[!RESEARCH_UNVERIFIED]] otherwise.
- `dh research score` → [[dhlib/research.py#load_trace]] (Claude Code tool_use/tool_result + toolUseResult urls,
  usage deduped by message id, tool calls deduped by id; or generic {query, results, opened}) →
  [[dhlib/research.py#metrics]] ([[dhlib/research.py#near_repeat]]: same words ±1 or ≥ 80% shared) + outcome.

## ROUTING — "to change X, edit Y (and prove it in Z)"
| change | edit | prove in |
|---|---|---|
| a phase, its order, gate or reference | [[dhlib/state.py#PHASES]], [[dhlib/checks.py]], [[dhlib/guide.py#STEPS]], references/NN-*.md | [[skills/deckhand/tests/test_dh.py]] |
| what `dh next` prints | [[dhlib/guide.py#next_step]] | test_dh.py |
| a dh command or flag | [[dhlib/cli.py#build_parser]] + [[dhlib/cli.py#dispatch]] + the module; SKILL.md §4 table | test_dh.py |
| plan lint rules (E0–E11, W1–W4) | [[dhlib/plan.py#lint]] | test_dh.py |
| pool ranking / vetting criteria / licence policy | [[dhlib/pool.py#score]] · [[dhlib/vet.py#verdict]] · [[data/licenses.json]] | [[skills/deckhand/tests/test_vet.py]] |
| clone/adopt/scaffold/dev server | [[dhlib/build.py]] | test_dh.py |
| rebrand / honesty findings | [[dhlib/brand.py#check]] | test_dh.py |
| AI-slop copy: features, scoring, extraction, language detection | [[dhlib/slop.py]] · [[data/slop/_common.json]] | [[skills/deckhand/tests/test_slop.py]] |
| a language pack (words, phrases, examples) | data/slop/<lang>.json (guide: [[data/slop/README.md]]) | `dh slop lint` · test_slop.py (every pack passes its own examples) |
| verify rows | [[dhlib/verify.py#run_verify]] | test_dh.py (Verify) |
| deploy / smoke / Coolify client | [[dhlib/deploy.py]] · [[ops/scripts/coolify_api.py]] | [[skills/deckhand/ops/tests/test_coolify_api.py]], test_dh.py (Deploy) |
| server, DNS, backup and storage clients (used by the ops runbooks) | [[ops/scripts/hostinger_api.py]] · [[ops/scripts/coolify_backup_setup.py]] · [[ops/scripts/backup_verify.py]] · [[ops/scripts/b2_setup.py]] · [[ops/scripts/tigris_bucket.py]] · [[ops/scripts/repo_presence.py]] | [[skills/deckhand/ops/tests]] (pytest) |
| lessons, `dh run`, recipes | [[dhlib/learn.py]] · seed [[data/lessons.seed.jsonl]] | test_dh.py, test_autopsy.py |
| autopsy detection / owner / rung | [[dhlib/autopsy.py#is_failure]] · [[dhlib/autopsy.py#_owner]] · [[dhlib/autopsy.py#_rung]] · MARKERS | [[skills/deckhand/tests/test_autopsy.py]] |
| harvest / GitHub library | [[dhlib/harvest.py]] · [[dhlib/github.py]] | [[skills/deckhand/tests/test_library.py]] (mock API) |
| candidate ranking / slots | [[tryon/lib/catalog.mjs#rank]] · [[tryon/lib/slots.mjs]] | [[skills/deckhand/tryon/test/engine.test.mjs]] |
| registry fit check, verdicts, what a verdict hides | [[tryon/lib/fitcheck.mjs]] · [[tryon/lib/catalog.mjs#rank]] | [[skills/deckhand/tryon/test/fitcheck.test.mjs]] |
| fetching registry items | [[tryon/lib/registry.mjs]] (fixtures: DH_FIXTURES, record: DH_RECORD) | engine.test.mjs |
| staging files / import rewriting | [[tryon/lib/materialize.mjs]] | engine.test.mjs |
| owner content carried into designs | [[tryon/lib/transplant.mjs]] | [[skills/deckhand/tryon/test/transplant.test.mjs]], sections.test.mjs |
| footer/navbar links from the plan | [[tryon/lib/sitelinks.mjs]] | [[skills/deckhand/tryon/test/sections.test.mjs]] |
| colours → tokens | [[tryon/lib/theme.mjs]] | setup-theme-server.test.mjs |
| open/show/keep/discard/bake | [[tryon/lib/engine.mjs]] | engine.test.mjs, sections.test.mjs |
| every common section kind (notice bar, stats, logo row, team, comparison table, forms, product/blog cards, card and button primitives), demo marks, form swap, logo swap, prop-default slots (component zoo) | [[tryon/lib/transplant.mjs#bind]] · [[tryon/lib/transplant.mjs#parameterize]] · [[tryon/lib/engine.mjs#markDemo]] · [[tryon/lib/engine.mjs#rendersChildren]] | [[skills/deckhand/tryon/test/zoo.test.mjs]] + the zoo matrix (18 sections, Chromium, contact sheets) |
| content mapping (FAQ, testimonials, pricing, footer columns), navbars from Tailark heroes, Vite shims + build check, Tune additions + surgical reset, Site undo steps (live audit) | [[tryon/lib/transplant.mjs#bind]] · [[tryon/lib/regmap.mjs#navbarsFromHeroes]] · [[tryon/lib/materialize.mjs#writeBundle]] · [[tryon/lib/engine.mjs#probeVite]] · [[tryon/lib/tune.mjs#tuneReset]] · [[tryon/lib/sitetheme.mjs#themeUndo]] | [[skills/deckhand/tryon/test/live-audit.test.mjs]] + the live matrix (3 apps, Chromium) |
| stale stamps, the import gate, the page-still-builds check (field fixes) | [[tryon/lib/engine.mjs#pickElement]] · [[tryon/lib/engine.mjs#checkImports]] · [[tryon/lib/engine.mjs#openVerified]] · overlay `stale`/`reloadButton` | [[skills/deckhand/tryon/test/field.test.mjs]] (fake dev server) + browser e2e |
| AI draft gates | [[tryon/lib/draft.mjs#checkDraft]] | [[skills/deckhand/tryon/test/draft.test.mjs]] |
| Tune knobs / presets | [[tryon/lib/tune.mjs]] (+ overlay tuneUI) | [[skills/deckhand/tryon/test/tune.test.mjs]] |
| Site knobs / fonts | [[tryon/lib/sitetheme.mjs]] (+ overlay sitePanel) | tune.test.mjs |
| overlay UI | [[tryon/overlay.js]] (plain ES5-ish browser JS, no build) | browser e2e (manual, Playwright + Chromium) |
| helper routes / proxy | [[tryon/server.mjs]] | [[skills/deckhand/tryon/test/setup-theme-server.test.mjs]] |
| dev-only wiring (Next/Vite) | [[tryon/lib/setup.mjs]] · [[tryon/lib/stamp.cjs]] · [[tryon/loader.cjs]] · [[tryon/vite.mjs]] | setup-theme-server.test.mjs, stamp.test.mjs |
| registry vetting | [[tryon/lib/vet.mjs]] · [[data/registries.json]] | [[skills/deckhand/tryon/test/vet.test.mjs]] |
| the shipped catalog | [[tryon/catalog-build.mjs]] (maintainer, network; `--only id,id` rebuilds those registries and keeps every other item, a registry's `index_mirror` is read when its site is not) → [[data/components.index.json]], then `tryon registry check --id all --ship` → data/checks/ | engine.test.mjs, fitcheck.test.mjs |
| installer | [[install.sh]] · [[install.ps1]] | manual |
| owner-facing docs | [[README.md]] · [[docs/USE-CASES.md]] · [[skills/deckhand/SKILL.md]] | [[scripts/version_check.py]] (versions) |
| secret patterns / redaction / project gitignore | [[data/secrets.json]] · [[dhlib/util.py#redact]] · [[dhlib/util.py#ensure_gitignore]] | [[skills/deckhand/tests/test_security.py]], [[skills/deckhand/tryon/test/hardening.test.mjs]] |
| resume, notes, switch verdict, cold-start entry, hook, project profile/vault layer | [[dhlib/resume.py]] · [[dhlib/profile.py]] · [[dhlib/cli.py#_refresh]] | [[skills/deckhand/tests/test_resume.py]] |
| workflows: format, lint, query, pools, observe, todo, extraction, publish | [[dhlib/workflow.py]] · [[data/industries.json]] · skills/deckhand/workflows/*.json · [[scripts/workflows_index.py]] | [[skills/deckhand/tests/test_workflow.py]] |
| workflow autopsy, session loaders (Hermes, chat) | [[dhlib/wfautopsy.py]] · [[dhlib/autopsy.py#load]] | test_workflow.py |
| gate quotes, services, ports, split into N agents, product deliverable, pending ledger (field fixes) | [[dhlib/state.py#gate_pass]] · [[dhlib/build.py]] · [[dhlib/util.py#free_port]] · [[dhlib/plan.py#split]] · [[dhlib/verify.py#product_kit]] · [[dhlib/pending.py]] | [[skills/deckhand/tests/test_field.py]] |
| suggestions after PENDING (rules, scores, dismissals) | [[dhlib/suggest.py]] · [[dhlib/guide.py#_suggest]] · [[dhlib/resume.py#render]] | [[skills/deckhand/tests/test_suggest.py]] |
| harness syntax `dh next` prints | [[data/harness.json]] · [[dhlib/guide.py#harness_notes]] · [[references/harness.md]] | test_workflow.py / manual |
| research evidence: labels, quote check, sources, brief questions, scoring | [[dhlib/research.py]] · [[data/research.json]] · [[references/research-card.md]] | [[skills/deckhand/tests/test_research.py]] |
| SEO rules, owner facts, crawler lists | [[data/seo.json]] · [[dhlib/seo.py]] (checks, PENDING block, ping) · [[tryon/lib/seo.mjs]] (writes) | [[skills/deckhand/tests/test_seo.py]], [[skills/deckhand/tryon/test/seo.test.mjs]] |
| docs ↔ commands, README numbers | whatever changed (docs, SKILL.md §4, README) | [[scripts/test_repo_coherence.py]] |
| this file | code (generated part) · [[scripts/llm_context.core.md]] (curated part) · [[scripts/llm_context.py]] | [[scripts/test_llm_context.py]] |

## DEV — working on this repo
- Tests (all offline):
  - `python3 -m unittest discover -s skills/deckhand/tests`
  - `python3 -m pytest skills/deckhand/ops/tests -q`
  - `node --test skills/deckhand/tryon/test/*.test.mjs`
  - `python3 -m unittest discover -s scripts -p 'test_*.py'`
- Registry HTTP comes from [[skills/deckhand/tryon/test/fixtures/registry]] (DH_FIXTURES; re-record with DH_RECORD).
  GitHub is a local mock API plus file:// remotes (DH_GITHUB_API/DH_GITHUB_GIT).
  The fixture site is [[skills/deckhand/tryon/test/fixtures/site]].
- CI: [[.github/workflows/ci.yml]] runs every suite on Ubuntu and Windows (Windows non-blocking), plus the version
  check, plus `llm_context.py --check` off main.
  [[.github/workflows/llm-context.yml]] regenerates this file on main when it drifts.
- Hooks: `git config core.hooksPath .githooks` once per clone. [[.githooks/pre-commit]] then regenerates this file
  from the index on every commit.
- Release: [[RELEASING.md]].
  - [[scripts/version_check.py]]: README badge = SKILL.md version = CHANGELOG top.
  - [[scripts/leak_sweep.py]]: private terms list, refuses to pass without it.
  - [[docs/releases]]/vX.Y.Z.md (first line = title, ≤ 8 bullets) → push the tag (or run the workflow) →
    [[.github/workflows/release.yml]] re-runs version_check --tag and publishes the GitHub release from that file.
- Style:
  - terse docstrings/headers that state the contract (they are copied into MODULES, so write them for a model);
  - JSON-first outputs; error codes UPPER_SNAKE;
  - one reason per refusal, plus what would be accepted.
- Traps already paid for (do not re-learn them):
  - Killing by pattern (`pkill -f X`, `ps | grep X | xargs kill`) kills your own shell when X is in your command
    line (exit 144). Kill by PID.
  - Regex `(?:\s+.*\n)+` backtracks catastrophically (\s matches \n). Use `[ \t]+`.
  - Python heredoc patch scripts collide with `"""` quoting. Write the patch to a file, then run it.
  - A GITHUB_TOKEN in the env overrides the vault ([[dhlib/profile.py#secret]] reads env first). Tests must pop it.
  - [[dhlib/util.py#DhError]] takes code and message positional-only. Its extra may carry its own `code`
    (a subprocess result). The CLI prints extra first, so ok/code/message always win. `dh run` used to crash here.
  - Env-assignment redaction must stay case-sensitive (`MY_TOKEN=`). Case-insensitive, it ate `api_key=…&ok=1`
    query strings.
  - A bare repo's HEAD may be master. Push and clone explicit branches (main).
  - Empty dirs are not tracked by git (a fixture's public/). [[tryon/lib/engine.mjs#ensurePlaceholder]] creates
    public/.
  - Windows read-only .git objects make shutil.rmtree fail → [[dhlib/util.py#rmtree]].
  - Next dev blocks HMR via a proxy unless Host/Origin = localhost (S-006). Turbopack rules must not use `as` (S-005).
  - create-next-app's `body{font-family:Arial}` beats next/font variables. The dh:theme body rule is unlayered for
    that reason.
  - Next.js metadata is inherited and shallow-merged: a canonical or openGraph.url in the root layout lands on
    every page, and a page-level openGraph replaces the layout's whole object. That's why [[tryon/lib/seo.mjs]] puts
    the canonical per page and the share image in `opengraph-image`.
  - Turbopack refuses a symlinked node_modules pointing outside the project: copy it for a real build test.
  - Live registry/GitHub/Google Fonts calls may be blocked in sandboxes. Prove behaviour with fixtures and say what
    wasn't live-tested.
  - LLM_CONTEXT.md merge conflict → never hand-merge. Run `python3 scripts/llm_context.py` and commit the result.
- Not proven live yet: a full `dh deploy ship` against a real server (the Coolify client itself is live-proven from
  v1), and the $0 Oracle track. Business bots are specs plus skeletons.
