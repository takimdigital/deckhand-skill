# 45 — SEO (be found on Google and in AI answers)

**Objective:** nothing in our control stands between the business and page one: technical SEO is complete, every
page says clearly what it is and where, the business is one consistent entity everywhere, and the owner's part
is tracked until done. **Output:** `dh seo audit` without launch-breakers; the `seo` row of `dh verify` green;
the owner's open items in `PENDING.md`. **Honesty:** nobody can promise position #1. Say so once; then remove
every reason not to rank. **A product** (`brief.deliverable=product`): the business facts belong to each buyer — the
app reads them from its settings, `dh seo audit` lists them as the buyer's (not as PENDING), and CUSTOMIZE.md says
where the buyer enters them. Still run `dh seo audit` on hand-written SEO.

## When (by path — `dh next` prints the right lines)
| path | brand phase | before G4 |
|---|---|---|
| scratch (new site) | `dh seo apply` by default | `dh verify` (row `seo`) |
| existing (their repo/folder) | `dh seo audit` → `dh seo apply` (adds or improves, never overwrites their words) | same |
| pool / mine (a base) | `dh seo audit` → **DECISION NEEDED**: show `.deckhand/SEO.md`, recommend `dh seo apply` strongly | `dh next` repeats the decision at G4 if not applied |

After the domain is chosen: `dh brief set domain=…` + `dh seo apply` again (canonicals, sitemap, structured data
on the real domain). After every production `dh deploy ship`: IndexNow is pinged automatically; run
`dh seo audit --url https://<domain>` (live checks: HTTPS, one host, preview not indexed, canonicals). Monthly
in operate: the same live audit.

## What the scripts do (never hand-write these)
`dh seo apply` (engine: `tryon/lib/seo.mjs`, AST-exact, journaled, `dh seo undo` byte-exact):
- `lib/seo.ts` — the business facts from the brief (name, domain, languages, JSON-LD): one source of truth.
- `app/robots.ts` — allow crawling, disallow `/api/` and signed-in pages, point to the sitemap. AI answer bots
  (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot, Bingbot…) always allowed; training bots follow
  `seo.ai_crawlers` (`allow` default, or `search-only`).
- `app/sitemap.ts` — the plan's public pages on the production domain (+ hreflang alternates and x-default
  when the app has a `[locale]` segment).
- Root layout: `metadataBase`, title template `%s — Brand` (a template title such as "Create Next App" becomes the
  brand), description, Open Graph, Twitter card, robots (noindex when `DH_NOINDEX=1`), verification tokens,
  `<html lang>`, JSON-LD script. A canonical in the root layout is **removed** (every page would inherit it and
  claim to be the home page) and set per page instead.
- Every static page: `alternates.canonical` = its own route, plus the title/description from
  `.deckhand/copy.json → seo.pages` when the page has none. The owner's existing titles are never replaced.
- `app/opengraph-image.tsx` (1200×630, brand colour + name + tagline), `app/manifest.ts`, `app/not-found.tsx`
  (a real 404), `public/llms.txt`, the IndexNow key file.
- Vite / static sites: the same in `index.html` head tags + static `public/robots.txt`, `sitemap.xml`, `llms.txt`.
Not automatic (the audit reports them): `'use client'` pages (move the interactivity to a child component),
dynamic routes (`generateMetadata`), Pages Router `<Head>`, a client-rendered SPA (pre-render it).

## The words (the model's job — deterministic checks follow)
Write into `.deckhand/copy.json`:
```json
{ "seo": { "description": "one sentence for the whole site",
  "pages": { "/": { "title": "Artisan bakery in Lyon — Maison Pain", "description": "…" },
             "/wedding-cakes": { "title": "Wedding cakes in Lyon, made to order", "description": "…" } } } }
```
- **Title** 30–60 characters, unique, the page's main query first (service + city for a local business), the
  brand last (the template appends it; a title that already contains the brand is used as is).
- **Description** 70–160 characters, unique: what, for whom, where, one concrete reason to click. Facts only.
- **H1**: one per page, says what the page is (compose/try-on keep one).
- **Home first paragraph** (answer-first, what AI answers quote): "<Brand> is a <service> in <city> for
  <audience> — <proof: since 2009 / 4.9★ on Google / same-day delivery>". ≥ 150 words on the home page.
- **One page per service** the owner sells (people search services, not company names); one page per REAL
  location only — never city pages with swapped names (doorway pages are penalised).
- **Alt text**: what the photo shows, ≤ 125 characters, no keyword lists; decorative images `alt=""`.
- **Links**: descriptive text ("see our wedding cakes"), never "click here"; every key page linked from the nav or
  the home page.
- **FAQ** only with real customer questions, answered in 1–3 sentences (AI engines quote them). Google removed FAQ
  rich results on 2026-05-07: do not promise a special result.
- Keywords come from the research (what competitors that rank use, what customers type); the owner confirms them
  (`seo.keywords`). Never stuff them; once in title, H1 and first paragraph is enough.

## The owner's part (PENDING.md, refreshed by every audit — end every report with it)
Facts (asked once, batched, click paths in the line itself): domain · top 3–5 search phrases · cities served ·
primary category (the same one as on Google Business Profile — the #1 local factor) · address or "service area" ·
phone · hours · email · price range · real logo (square ≥ 112 px) · social profiles actually used · directory
listings · who is behind the business · real photos · where real reviews live.
Actions: **Google Business Profile** (claim, verify, 100% complete, same NAP and category) · **Search Console**
(domain property via DNS TXT — the agent adds the record through the DNS API; submit the sitemap) · **Bing
Webmaster Tools** (import from Search Console — Bing's index feeds ChatGPT search and Copilot) · **Bing Places +
Apple Business Connect** · **ask real customers for Google reviews** and answer each one (`dh ops add
review-request` automates the ask). Mark done with `dh brief set seo.gbp=claimed` etc. — the line disappears.

## Never
- Invent facts, reviews, ratings, awards, "as seen in" or opening hours. No `aggregateRating`/`review` markup on
  the business's own entity (not eligible, risks a manual action).
- Keyword stuffing, hidden text, doorway/city-swap pages, bought links, link exchanges, AI-spun duplicate pages.
- A preview indexed beside the real domain: previews set the build variable `DH_NOINDEX=1`
  (`dh deploy target` says so for sslip/http URLs); the production app never sets it.
- `nosnippet` / `max-snippet:0` unless the owner explicitly wants a page out of AI Overviews.
- Blocking AI answer bots; meta keywords; a canonical in the root layout.

## Proof
`dh seo audit` (source; plus rendered pages from the dev server or `--url`) · `dh verify` row `seo` on the
production build (launch-breakers block G4) · after launch: Search Console coverage + Rich Results Test + PageSpeed
Insights (Core Web Vitals good = LCP < 2.5 s, INP < 200 ms, CLS < 0.1) — link them in the report, never claim
rankings.
