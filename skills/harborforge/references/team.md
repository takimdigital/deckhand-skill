# Team — sub-agents that share files, not context

Parallel builders are a gated mode, not a default: only when the work splits into ≥ 2 truly independent parts AND the
shared foundation is frozen. Otherwise one agent does it. The rails are Deckhand's own — nothing to write:

| rail | command |
|---|---|
| the protocol | `.deckhand/work/CONVENTIONS.md` (written by `dh plan split --agents N`): frozen files, who owns which routes, hard rules, reporting |
| one package per builder | `.deckhand/work/AGENT-n.md`: its routes, its work packages, what it consumes, how it reports — its whole context |
| the board (shared memory) | `dh bb post --wp A1 --kind progress\|done\|blocker\|question\|contract\|decision --msg '…'` · `dh bb read --wp A1` |
| handoff flags | `dh bb flag A1-done` · `dh bb wait A1-done --max 170` (exit 1 = timeout: proceed and post a note — never loop) |
| ports, scratch | the dev server is yours (the orchestrator's); a builder that needs its own server: `dh dev port --from 3100`. Scratch: `.deckhand/work/tmp/A1/` |

Rails check before the first dispatch: `dh bb flag probe && dh bb wait probe --max 5` (ok) and `dh bb wait never --max 3`
(TIMEOUT). Harness syntax for dispatching, steering and waiting: `references/harness.md`.

## Build round (the common case)

1. **You build WP-00 first**: schema, migrations, seed, auth and roles, layout, navigation, `components/ui`, `lib`.
   `npx tsc --noEmit` clean, `dh dev start` answering. Then it is frozen: CONVENTIONS.md lists it.
2. **Dispatch every builder in ONE batch.** Each task is self-contained: the absolute project path, "read
   CONVENTIONS.md, then your AGENT-n.md", the host path law (Windows: `D:/…` for native tools), the dev URL, the
   return shape (`{status, routes, evidence, left}` — Hermes `output_schema`). Children inherit neither your context
   nor your memory.
3. **Size a package to fit one child** (≈ 25 tool calls, ≈ 20 min). A package that has to be killed was cut too big.
   A killed child leaves files: list what the package owes, compare with the disk, dispatch a replacement that names
   ONLY the missing artifacts and reads what the dead child left. Re-dispatching the same brief repeats the kill.
4. **Steer early, on facts that will recur** (a wrong path, a missing install): the steer rides the child's next tool
   result. A child that finished first returns it as missed — check its output against the current files yourself.
5. **Integration holds**: a consumer waits on another builder's flag only at the point it needs the result, bounded.
6. **After the wave**: servers started by children can die with them — `curl` the ports and restart what died.
   A whole batch dying at once (API retry, billing) is infrastructure, not the roles: harvest their files and board
   lines, then re-dispatch pointing at them.

## Trust only what you re-ran

- Children's summaries are self-reports. Before `dh phase done build`: `npx tsc --noEmit`, the route matrix per role
  (signed in), the acceptance rows — yourself. `git status --porcelain`: any write outside a builder's routes is a
  finding, not a detail.
- Batch results can mislabel slots: reconcile against the disk (files, flags, board) before re-dispatching anything.
- A check you rely on must fail on a known-bad input and pass on a known-good one; calibrate an instrument (a viewport
  width, a probe) before it contradicts a child.
- Test data: every row a builder creates is named `TEST-<agent>-…` and deleted before `done`.

## Panels (on quality demand, not by default)

When the owner wants more rigour on a plan, a design or an audit ("not yet — more experts"), escalate from one reviewer to
a shared-document panel, max 5 lenses + you, 3 rounds: **Round 1** each lens alone, appending to its own section;
**Round 2** every lens reads all the others and must disagree with at least 2, citing `file:line`; **Round 3** each
votes Aye/Nay on your synthesis items with one line of reason. Lenses: MINIMALIST (what to remove), VERIFICATIONIST
(which claim is untested), AGENT PSYCHOLOGIST (where an AI will shortcut or misread), PIPELINE ENGINEER (do the data
flows compose), PRAGMATIST (what breaks in production), SKEPTIC (the what-ifs: back navigation, empty states, the
search that scrolls away). For a plan: Round 1 per page (intent, first look, placement, conversion, SEO), Round 2 every
user path through the pages end to end. You merge, then tell the owner the full plan in plain words.

## Frictions become fixes — after, never during

Nothing under test is edited mid-run (it invalidates the run). Each role notes frictions as
`F-NN | file:line | "exact quote" | what goes wrong | H/M/L`. After the run: `dh autopsy --workflow` turns what
happened into proposals; each friction becomes one change at the strongest rung (eliminate → pre-flight → reorder →
gate → pitfall), in the owner's workflow — or, for Deckhand itself, in the maintainer report.
