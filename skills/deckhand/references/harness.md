# Harness syntax — the same Deckhand, each agent's own tools

`dh` detects the harness from its environment (`HERMES_AGENT`/`HERMES_SESSION_ID` → hermes, `CLAUDECODE` → claude-code,
`CODEX_*` → codex, `CURSOR_*` → cursor, `GEMINI_CLI` → gemini-cli, `OPENCODE`/`OPENCODE_SESSION` → opencode, else
unknown) and `dh next` returns the lines the current phase needs (`harness`). The lines are DATA (`data/harness.json`,
one row per harness): a harness that does not override a line gets `unknown`'s, so every harness gets every line and a
named one gets its own syntax. Nothing harness-specific is hard-coded in `dhlib` (a test enforces it). This file is the
full table; load it only when a step needs a tool you have not used yet.

Everything below `dh` is harness-neutral: one JSON per command, state in files, the run log in `.deckhand/runs.jsonl`.
What differs is how you start long processes, wait, delegate, keep a checklist and find the transcript.

## Hermes (Windows + git-bash, as on the owner's machine)

| need | syntax |
|---|---|
| a server/watcher | `dh dev start` detaches by itself. Your own: `terminal(command="…", background=true, notify=["Ready in"])` → `session_id`, then `process_manage(action="wait", session_id=…, timeout=170)` · `poll` · `log` · `kill` · `list`. **Never `nohup … &`** (exit -1). |
| time limits | `terminal` 180 s by default (`TERMINAL_TIMEOUT`), 600 s foreground max: longer is promoted to a background process with a notification — do not re-run it. `process_manage wait` is clamped to `TERMINAL_TIMEOUT`. `dh bb wait` defaults to 170 s for that reason. |
| Python cells | `execute_code(code=…)`: 5 min, ≤ 50 tool calls per cell. Its kernel state is **lost** on timeout, interrupt, `sys.exit()` or 30 min idle — never keep state there; write files. Inside a cell: `from hermes_tools import terminal, read_file, write_file` (a bare `terminal` is a NameError). |
| sub-agents | `delegate_task(tasks=[{goal, context, output_schema}, …])` — 1..10 per call, all builders of a round in ONE call. `action="steer"` + `subagent_id` + `message` (lands on the child's next tool result: steer early; a finished child returns `missed_steer`), `action="stop"`. Children's summaries are self-reports: re-prove them. |
| task text | **No `{x}` and no `<x>` anywhere in any task** — one such marker refuses the whole batch (JSX written tag-style counts). Workflow and package text rendered by `dh` never contains them. Give every absolute path; children inherit nothing. |
| files | `write_file` refuses to overwrite a file this task has not fully read (or that changed since): read it first or use `patch`. Two children must never share a scratch file: `.deckhand/work/tmp/<agent>/`. |
| pages | `browser_navigate` refuses localhost and private addresses: check pages with `curl -s` (cookie jar in your scratch folder); visual QA = a screenshot file (headless Chrome) + `vision_analyze(image_url="D:/…/shot.png", question="…", region=[x1,y1,x2,y2])`. |
| checklist | `todo_list(todos=[{id, content, status}], merge=true)` ← `dh workflow todo` (its items already carry id, content, status); tick with `dh workflow step ID done`. One item in_progress at a time. |
| bots that watch the site | `dh ops add [bot] --runner hermes` (the default inside Hermes): writes the bot into `$HERMES_HOME/scripts` and returns the exact `cronjob(action="create", no_agent=true, script=…)` call. Show the owner, then make it: **zero model tokens per tick**, the script's stdout is the alert, empty stdout sends nothing. Test with `cronjob(action="run", job_id=…)`. Secrets are read from the Deckhand vault by name at run time (cron scripts do not inherit provider credentials). |
| project context | Hermes loads ONE project file, first match wins: `.hermes.md` → `AGENTS.md` → `CLAUDE.md`. `dh init` writes its resume block into AGENTS.md, and into `.hermes.md` when the owner has one, so a Hermes session always starts from `dh resume`. |
| profiles | each profile has its own `$HERMES_HOME` (skills, `state.db`, scripts, cron). Resolve paths from `$HERMES_HOME`, never `~/.hermes`. |
| one reference | `skill_view(name="deckhand", file_path="references/30-build.md")` |
| lost context | after compaction or a restart: `dh resume` first (the compaction summary may be wrong, and it copies secrets verbatim — a key pasted in chat is in it). `session_search` recovers compressed tool calls. |
| transcript | `dh autopsy --latest` (or `--workflow`) inside Hermes reads this session from `%LOCALAPPDATA%\hermes\state.db` (`~/.hermes/state.db`), read-only, with its compression lineage and sub-agent batches. Outside: `dh autopsy --workflow <state.db> --session <id>`, or `hermes sessions export out.jsonl --session-id <id>` (or `--format trace`) then `dh autopsy out.jsonl`. Sub-agent logs: `cache/delegation/live/<delegation>/task-N.log`. |
| Windows | `py`, not `python3`. Native tools (py, node, curl) need `D:/…` paths — `/d/…` only works inside bash. `/tmp` differs between bash and native tools: scratch under the project. git-bash exports `HOSTNAME=<machine>`: Deckhand pins `127.0.0.1` for servers it starts. Reserved port ranges are random: `dh dev port --from N`. Board posts in single quotes (`--msg '…'`): `$` expands in double quotes. |
| install | the skill lives in `$HERMES_HOME/skills/<category>/deckhand` (each profile has its own); `install.ps1` / `install.sh` update the copy of every profile in place. |

## Claude Code

| need | syntax |
|---|---|
| a server/watcher | Bash `run_in_background: true`; wait with Monitor (an until-loop), never `sleep`. |
| sub-agents | the Agent tool, one per `AGENT-n.md`, launched in one message. |
| checklist | TodoWrite ← `dh workflow todo` (its items already carry content / status / activeForm). |
| cold start | `dh resume --install-hook claude` — every session in a deckhand project starts from RESUME. |
| transcript | `dh autopsy --latest` reads `~/.claude/projects/<project>/*.jsonl`. |

## Codex · Cursor · OpenCode · Gemini CLI · others

Long processes in a background terminal (`dh dev start` detaches anyway). No sub-agents? Build the `AGENT-n.md`
packages one after the other in this session, or open one session per package — the board and the flags work the same
across sessions. The checklist is `dh workflow todo --format md`. For the autopsy: `.deckhand/runs.jsonl` is always read
(run risky commands through `dh run -- …`); a chat export as JSONL (`{"role", "content"}` per line) adds the
questions and answers.
