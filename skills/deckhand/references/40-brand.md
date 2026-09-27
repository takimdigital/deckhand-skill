# 40 — BRAND (their identity in, the template's out)

**Objective:** nothing on the site says the base's name, a demo company, lorem ipsum, a fake client logo or
a placeholder the owner has not accepted. **Output:** `dh rebrand check` 0 blocking; `dh phase done brand`.

## Procedure
1. `dh rebrand scan` — identity surface: package name, metadata, site config, template names, assets.
2. `dh brief set brand.name=… brand.tagline=… brand.primary=#hex` (if not set), then `dh rebrand apply`
   (`--dry` first when unsure): package name, metadata title/description, config names, template display
   names, `--primary` token, monogram `app/icon.svg` when there is no logo.
3. Copy pass (the model's real job here): `dh slop brief` first (the words and patterns to avoid, per language),
   then rewrite page copy from `copy.json`/brief in the owner's voice and languages. Headlines state the outcome for
   the audience; one CTA verb per section; no superlatives the owner cannot prove; concrete nouns (prices, streets,
   hours, names) over adjectives. RTL languages: `dir="rtl"` on `<html>` + logical CSS properties.
4. `dh rebrand check` until 0 blocking — it includes `ai-slop`: a text scored slop blocks, one to review warns. Each
   hit names its fix; rewrite, never reword the same cliché. `dh slop check` alone is the fast loop. A brand or trade
   word: `dh slop allow "word"`. A real customer quote: `dh:slop-ok` on its line. Warnings (placeholder images, docs
   mentions, review-level copy) are listed to the owner.
   Existing site (adopt): `dh slop check --url <their live URL>` shows the owner which pages already read as AI.
5. SEO — `references/45-seo.md`: page titles/descriptions into `copy.json → seo.pages`, then `dh seo apply` (new
   and existing sites) or `dh seo audit` + DECISION NEEDED (bases). The owner's missing facts land in PENDING.md.

## Rules
- LICENSE, NOTICE, THIRD_PARTY_NOTICES are never edited.
- Images: owner-supplied or generated diagrams/illustrations the owner approves; never stock photos presented
  as the business; `/deckhand-placeholder.svg` is allowed until G4, never at deploy.
- Testimonials, client logos, ratings, "as seen in": real + owner-confirmed, or removed.
