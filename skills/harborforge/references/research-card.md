# Research card — every research agent reads this; nothing else about searching
Job: evidence for ONE focus. Start: `dh research brief --focus F --agent ID` → questions (TARGET · PRIMARY ·
DONE_WHEN · FRESH), budget, pages already read, vocabulary so far. Write ONLY `.deckhand/research/agents/ID.json`.

## Before a search
- Search for DONE_WHEN, nothing more. In the audience's language and market, not yours.
- `dh research seen URL` before opening a page: read by another agent → use its note, never reopen.

## Loop: query → read snippets → diagnose → ONE change → query
Open a page only when its snippet says it is the TARGET or PRIMARY. After opening:
`dh research add URL --by ID --kind pricing --note "dense facts, numbers, dates"`.
| results look like | do |
|---|---|
| off-topic / wrong meaning | add the entity that disambiguates (city, trade, product); quote a rare phrase |
| generic overviews | add the rarest constraint; name the source type (pricing page, regulator, trade body) |
| 0–2 results | drop operators, then quotes, then the least-needed word |
| right topic, other words | take the words the results use (titles, headings) and search with those |
| pages about the source | search the source itself (its name, title, date) and open it |
| old | add the year; check the page's own date |
| 2 searches, nothing new | change the approach (entity type, source type, region, reading) — never reword |
Never: reword a failed query (same words ± 1 is the same query) · stack every constraint in one query ·
operators not seen working (drop `site:` / quotes if results look unfiltered) · open every result.

## Vocabulary — harvested, never invented
Copy terms verbatim from real pages: competitor sites, trade bodies, job ads, reviews, result titles.
`kind`: customer (what buyers write) · trade (what professionals say) · search (what ranking pages use).
A term you "know" but did not see on a page is not vocabulary.
`{"term":"end of tenancy clean","kind":"customer","url":"…","quote":"…book an end of tenancy clean…"}`

## Claims — one fact each, in your file's claims[]
`{"id":"C-ID-07","focus":"pricing","claim":"…","label":"VERIFIED","url":"…","quote":"…","date":"2026-05","by":"ID"}`
- VERIFIED: the fact is in the quoted text of a PRIMARY page you opened.
- SECONDARY: found only on a page about the source.
- INFERRED: derived from other claims → `"from":["C-ID-03","C-ID-05"]`, no url.
- NOT_FOUND: searched, not found → `"tried":"angles used"`, no url.
Quote verbatim (≤ 300 chars); `…` may join two parts of one page. `dh research verify` fetches every url and
fails any quote that is not on its page. Never round a label up. Prices, rules, availability: FRESH — search.

## Stop and return
DONE_WHEN met → stop searching; re-read your quotes. Budget spent, or 2 changes of approach found nothing →
NOT_FOUND with `tried`. Return to ORCH: claim ids, terms added, open gaps — dense notes, no prose.
