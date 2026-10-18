# 10 — RESEARCH (evidence, not opinions)

**Objective:** know what wins in THIS niche before a page is planned. **Output:** `.deckhand/research.json`
(template: `templates/research.json`), `dh phase done research` green. Owner declined → `dh phase skip research --reason "…"`.

## Specification
- **competitors (≥3, target 3–5):** real businesses serving the same audience in the same market/language.
  Per competitor: `name, url, positioning` (their one-line promise), `pricing` (shape + anchor price),
  `strengths[]` (what converts: e.g. instant quote, same-day slots, trust badges), `gaps[]` (what they miss —
  the owner's opening). Every entry has a URL you actually opened.
- **audience:** `primary` segment, `pains[]`, `jobs_to_be_done[]`, the `language` they search in.
- **conversion.plays[]:** the 1–3 moves the top performers make that the median does not (the pattern:
  90% of cleaners publish a contact form; the winners ship an instant quote calculator). `first_screen[]`:
  what must be visible without scrolling. `trust[]`: proof types that fit (reviews, guarantees, certifications —
  the OWNER must supply real ones → PENDING). `objections[]` + the answer each needs on the page.
- **discovery:** keywords in the audience's language, local-SEO relevance, the page types that rank.
- **features:** `now[]` (day one, ≤7), `later[]`, `not[]` (deliberately excluded, with reason).
- **unproven[]:** what could not be verified. Say it; never fill it.

- **claims[]:** every fact behind the fields above, one per claim, with a label (VERIFIED · SECONDARY · INFERRED ·
  NOT_FOUND), the url and a verbatim quote from that page. Format and labels: `references/research-card.md`.
- **vocabulary[]:** ≥ 3 terms (target 8) copied from real pages, never from memory: `term, kind (customer |
  trade | search), url, quote` — the quote contains the term. The plan, the copy and the SEO words use them.

## Procedure
1. One brief per focus: `dh research brief --focus competitors|pricing|audience|conversion|discovery|local-rules|vocabulary
   --agent ID`. It names the card (`references/research-card.md` — the only search guidance to read), the questions
   pre-filled from the brief, the budget and what other agents already read.
2. Solo: work the focuses one after another as agent `A1`. Parallel: one agent per focus, at most 5 at once; each
   writes ONLY `.deckhand/research/agents/ID.json` and registers every page it opens (`dh research add URL --by ID
   --note "the dense facts found there"` — a note like "opened" is refused), so no page is read twice (`dh research
   seen URL` first). Queries use `brief.category` (3–5 words), never the whole business pitch.
3. Fill the summary fields (competitors, audience, conversion, discovery, features) from the claims.
4. `dh research verify` merges the agents' files, fetches every cited page and checks each quote is on it.
   A mismatch is fixed (copy the real sentence) or relabelled; a page that blocks robots or draws itself with
   JavaScript is reported as unchecked, not failed.
5. `dh phase done research` — also requires ≥ 3 vocabulary terms and a verify run after the last edit.
Measure a change to this process: `dh research score NEW_LOG --baseline OLD_LOG` (searches, page reads, repeated
queries, duplicate reads, tokens, and tokens per proven claim).

## Rules
- MUST NOT copy competitor copy, contact them, sign up, or scrape behind logins.
- A claim without a URL is deleted, not softened — or labelled NOT_FOUND with what was tried.
- The research feeds the plan: every `conversion.plays[]` item becomes a section or feature in the sitemap,
  or is listed under `features.later` with a reason.
