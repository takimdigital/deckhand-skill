# 60 — REVIEW (one command, evidence rows)

**Objective:** nothing reaches production that would embarrass, leak or break. **Output:** `dh verify`
green on every blocking row; `.deckhand/VERIFY.md`. **Gate G4:** the owner says go live.

## Rows
| row | blocking | fails when |
|---|---|---|
| typecheck | yes | `tsc --noEmit` reports errors |
| lint | no | the project's lint script fails |
| build | yes | the production build fails |
| prod-clean | yes | a try-on stamp is in the build output |
| tryon-closed | yes | a session is still open |
| secrets | yes | a credential-shaped value (policy: `data/secrets.json`) or a committed `.env` is in the repo — `.deckhand/` included |
| env-ignored | yes | `.env` is not gitignored |
| logs-ignored | yes | deckhand's run logs and local state (`.deckhand/runs.jsonl`, `failures.jsonl`, `*.log`, `autopsy/`, `tryon/`, `RESUME.md`, `notes.jsonl`, `profile.json`, `vault.env`, `profile.md`, `layout.json`) are not gitignored — any `dh` command adds the block; commit `.gitignore` |
| swaps | yes | a vendor SDK marked for replacement is still installed/imported |
| honesty | yes | template names, demo companies/people, lorem ipsum, fake logos, try-on leftovers (a product's fictional demo company in its seed is a warning, not a blocker) |
| product-kit | yes (products) | `brief.deliverable=product` and the buyer's kit is incomplete: README, LICENSE, CUSTOMIZE.md, a seed script and a reset/wipe script |
| routes | yes | a planned public route or a home-page link answers ≥ 400 — checked on the production build (served on a free port and stopped after; `--url` checks a live site instead) |
| a11y-basics | no | `<img>` without alt, `<html>` without lang |
| deps-audit | no | high/critical npm advisories |
| seo | yes (launch-breakers only) | the site blocks crawlers, a public page is noindex, a page has no real title, a preview is indexable, live canonicals point elsewhere — the rest is scored in `.deckhand/SEO.md` (`references/45-seo.md`) |

## Procedure
`$T clean` (try-on) → `dh verify` (it builds, then serves the build itself for the route check) → fix every red blocking row at its root
(never by weakening the check) → re-run → `dh phase done review` → show VERIFY.md → G4
(`dh gate pass G4 --quote "<their words>"`; for a product, G4 means "package it").
Security floor before G4: auth routes rate-limited or provider-protected; admin routes server-checked;
uploads size/type-limited; CSP/headers from the framework defaults at least; no debug endpoints.
