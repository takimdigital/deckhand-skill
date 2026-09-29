# AGENTS.md — Deckhand

**Cold start (no memory of this repo)? Read `LLM_CONTEXT.md` first**: the curated sections in full, then use the
rest as lookup tables. It maps every file, command, function (with line numbers), error code, state file and test,
and it is regenerated from the code, so it is never stale.

This repository is an agent skill. If your harness does not load `SKILL.md` folders automatically:

1. Read `skills/deckhand/SKILL.md` (the operating specification, ~200 lines).
2. Run `python3 skills/deckhand/dh.py next` (`py` on Windows) and do what it prints — it names the single
   reference file to load for the current phase. In a project that is already under way, run `dh resume` first
   (where it stands, the owner's decisions, the exact next command).

Working ON this repository (not with it):
- Tests: `python3 -m unittest discover -s skills/deckhand/tests` · `python3 -m pytest skills/deckhand/ops/tests -q`
  · `node --test skills/deckhand/tryon/test/*.test.mjs` (offline; registry responses are fixtures)
  · `node --test playground/playground.test.mjs`. `playground/` is a saved, source-only try-on test site (see its README):
    `node playground/playground.mjs restore` then `start` instead of building a site from scratch.
- Stdlib-only Python, zero-dependency Node (the only vendored code is `tryon/vendor/babel-parser.cjs`, MIT).
- Every behaviour change ships with a test; a fix that lives only in prose is not a fix.
- `python3 scripts/version_check.py` before tagging; `python3 scripts/leak_sweep.py` before publishing.
- After any change: `python3 scripts/llm_context.py` (CI fails on a stale `LLM_CONTEXT.md`). Once per clone,
  `git config core.hooksPath .githooks` does it on every commit. Architecture, flows and traps live in
  `scripts/llm_context.core.md`: update it when you change how something works (its `[[path#symbol]]` anchors are
  checked). Never hand-edit or hand-merge `LLM_CONTEXT.md`: regenerate it.
