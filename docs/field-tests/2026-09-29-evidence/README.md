# Evidence for the 2026-09-29 field test

All raw output for this run is quoted **inline** in `../2026-09-29-report.md`, inside the
"Expected / Actual" code blocks of each finding. That is deliberate.

The machine-readable captures (per-suite failure lists, command JSON, doctor output,
project trees) are **not** committed here, because on this machine every absolute path
contains a user segment and several captures came from runs that resolved paths outside
the throwaway folders. The field-test rules forbid personal paths in the repo, and a
folder of raw logs is the easiest way to break that by accident.

Where a claim rests on a measurement rather than a quote, the report says what was
measured and how to re-run it (see the "Steps" block of each finding — every one is
copy-pasteable from a fresh folder with `DECKHAND_HOME` set).

Finding-to-evidence map:

| Finding | Evidence form |
|---|---|
| F1 | 3 full suite runs (baseline ×2, UTF-8 ×1) with the failure name lists |
| F2, F3 | the `profile doctor` JSON + an env-presence check |
| F4 | two `workflow query` JSONs (before/after `brief set`) |
| F5 | Tier B `registry check` stdout (counts object) |
| F6 | three `gate pass G1` outputs (no quote / change / hold) + a positive control |
| F7 | the `scaffold --to app` JSON, directory listing, timestamps |
| F8 | `dh next` output + the `PermissionError` traceback |
| F9 | 11 route probes across 2 projects + the `phase done build` JSON |
| F10 | `NOTICE` before/after + `git ls-files` |
| F11 | two `dh init` JSONs + the `profile.json` scope field |
| F12 | the recorded workflow replay: `DF1` ok, `DF2` `CHECK_FAILED` |
| F13 | the composed file line, `demo-copy.json` ledger checks, `rebrand check` output |
| F14 | `plan init` JSON + `research.json` existence check |
| F15 | `dh next` harness object with `GEMINI_CLI=1` / `OPENCODE=1` |
| F16 | `dh compose` slots output + the component directory listing |
| F17 | `app/layout.tsx` before/after `seo apply` |
| F18 | `dh verify` JSON for the `product-kit` row |
| F19 | `dh resume --check` drift claim |
| F20 | `run.json` `forced` field + `resume --check` output |
| F21 | `tryon try` / `inspect` JSON on a self-closing usage |
| F22 | a real plan phase (sitemap + copy + `plan lint` iteration 1) |
| F23 | the `run.json` written outside the throwaway project |

Re-run the suites with the same interpreter and `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`
set to reproduce F1's split.
