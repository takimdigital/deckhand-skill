# {{ID}} — {{TITLE}}

**Bounded context:** `{{CONTEXT}}` · **Agent:** {{AGENT}} (0 = the orchestrator, before dispatch) · **Status:** open

Builders start from their `AGENT-n.md` and `CONVENTIONS.md`; this file is the detail of one package.

## Objective
Implement this context end to end so every page below renders, every action reaches its declared
target, and every call has a visible success AND error state. Nothing outside this scope.

## Owned surface (write only here)
{{PAGES}}

## Interaction contract (each line is a test)
{{ACTIONS}}

## APIs owned
{{API}}

**Entities:** {{ENTITIES}}

## Consumes (other packages' interfaces — link to them, never edit them)
{{CONSUMES}}

## Constraints
- MUST NOT edit files owned by another package; shared UI goes through WP-00 (post a `contract` first).
- MUST follow `.deckhand/work/CONVENTIONS.md` (frozen files, the dev server is the orchestrator's, scratch and test-data rules).
- MUST read the blackboard before starting and after every 30 minutes of work:
  `dh bb read --wp {{ID}}` — decisions and contracts there are binding.
- MUST post every cross-package decision: `dh bb post --wp {{ID}} --kind contract --msg "…"`.
- MUST NOT invent business facts (prices, reviews, addresses): missing facts go to PENDING.md.
- Idempotent migrations only; no destructive DB changes without a `decision` on the blackboard.

## Acceptance (definition of done)
- {{DONE}}
- `dh verify` green, and every route this package owns answers 200 in its `routes` row (no dead link).
- `dh bb post --wp {{ID}} --kind done --msg "<one line: what shipped, what is left>"`

## Stop condition
Done, or blocked: post `--kind blocker` with the exact missing input and stop. Do not wait in a loop.
