# 50 — TRY-ON (live section/component swap, zero model calls per click)

**Objective:** the owner compares real, licensed alternatives for any part of their running site — in
their colours, with their words — and keeps one. **Done:** no open session. **Gate G3:** design approved.

## Operate
```bash
T="node <skill>/tryon/cli.mjs"
$T doctor --project .          # framework, wiring, dev server, stamps in HTML, tokens
$T setup  --project .          # dev-only stamp loader (next.config / vite.config wrapped once, journaled)
# restart the dev server, then:
$T serve  --project .          # prints http://127.0.0.1:3999 — give THIS URL to the owner (background it)
```
The owner: click **Try-on** (bottom right) → click any section/button → confirm what it is (hero, pricing,
cta…) → **Show variants** (4, 6, 8 or 12 at once) → ←/→ to compare (instant) → **More · N left** brings the next
batch from the pool after the ones on screen (never a design already shown or refused; up to 30 per try) →
**Keep** (Enter) or **Discard** (Esc) → optional **Save to my library** (ranks first next time). The agent does
nothing per click; do not poll.

Headless (no browser in the harness, or scripted):
```bash
$T query --slot hero --project .                                   # ranked candidates, no writes
$T try --file components/hero.tsx --line 6 --col 5 --slot hero --count 4
$T more --id <S> --batch 4    # the next 4 designs from the pool, after the ones shown (POOL_EMPTY when spent)
$T show --id <S> --idx 2      # the dev page now shows variant 2
$T keep --id <S> --idx 2      # or: discard --id <S>   (byte-exact restore)
```
`--only id,id` stages exactly those designs (a flag report's reproduce command). `--no-install` refuses candidates needing new npm packages instead of installing them. With the dev server's URL
(`--url`, else the one `dh dev start` recorded) `try` also proves the page still builds (below); `--page /pricing`
loads that route instead of `/`, `--no-verify` skips it.

## Tune it (adjust, don't replace) and Site (the whole look) — no model calls
Picker panel → **Tune it**: presets (quieter · bolder · airy · compact · clarity · softer · sharper) and
knobs (spacing, headlines, weight, corners, depth, contrast, width). Each change is an exact Tailwind class
transform of the picked element's subtree, recomputed from the original every time and written to the
file; HMR shows it, so what the owner sees is what is kept. **Keep** finishes, **Reset**/**Close** restore
the file byte-exact — or, if the owner edited the file meanwhile, puts back only what the knobs changed and keeps
their edit. On a button (a Link inside `<Button asChild>` tunes the Button) a knob with nothing to transform adds its
class (pill → `rounded-full`, raised → `shadow-md`); a knob that finds nothing says why and where to go instead
(Site → Corners). "Describe it to the AI" hands the note to the gated, labelled AI draft (below).
**Site** (button beside Try-on): accent (curated swatches or any colour), neutrals (neutral/warm/cool),
corners (`--radius`), density (`--spacing`, Tailwind 4), headline scale (`--text-2xl…9xl`), body and heading
fonts. The preview sets the EXACT values apply writes (from the same function); **Apply** writes one marked
`dh:theme` block at the end of the global stylesheet (light + dark) and, for fonts, rewrites `next/font` in
the root layout by AST (the body rule beats a hard-coded `font-family`); **Undo last apply** restores both
files byte-exact, one apply at a time, back to the original (10 kept). Fonts need Next (`next/font`); a Vite site
gets every other knob. Engines: `lib/tune.mjs`, `lib/sitetheme.mjs` (helper endpoints `tune-*` / `theme-*`).
**From chat, without a browser** — the owner says "make the hero airier" or "warmer greys, rounder corners":
```bash
$T tune  --file components/hero.tsx --line 12 --col 5 --preset airy    # or --density 1 --size -1 --corners round …
$T tune  --id <T> --keep        # or --reset (byte-exact)
$T theme                        # current knobs + every allowed value (accents, fonts)
$T theme --neutrals warm --corners round [--accent teal|#0f766e] [--density airy] [--headlines larger] [--body Inter --heading Fraunces]
$T theme --undo                 # byte-exact restore of the last apply (again: the one before, to the original)
```
Unknown knobs or values are refused (`BAD_DIAL`, `BAD_THEME`) with the allowed list — nothing is written.

## No licensed design fits? The AI draft (labelled, gated)
The owner can ask for an AI-written variant: "Ask AI to draft one" appears when a slot has no licensed
design, when none can hold their content (`NO_CANDIDATES` / `NO_VARIANTS`), and as **AI draft** in the
variant bar (it then joins the licensed variants being compared). You are called once per request, never per click:
```bash
$T drafts --project .            # pending requests; `--wait` blocks until one exists (background it, no polling)
# read brief_file → "brief": the owner's exact content (text, markup, links, images, lists), the note,
# the project's primitives/packages and the rules. Write the component into write_to/draft.tsx, then:
$T draft-check --id <D>          # optional dry run of the gates
$T draft-done  --id <D>          # gate → staged beside the other variants → the owner's page switches to it
```
Gates (a failure lists every problem; fix and re-run `draft-done`): every owner word, link target, image
and bullet present · token colour classes only (no hex/rgb/hsl/oklch, no `bg-[#…]`) · imports = react,
next/*, the project's ui primitives/utils, installed packages · images = the owner's or the placeholder ·
links = the owner's hrefs only · no fetch / env · `.tsx`/`.ts` files only. Words you add beyond the
owner's are allowed only as short UI copy, and are shown as "its own words" and recorded with `ai: true`;
`dh rebrand check` warns (does not block) until the owner confirms or rewrites them. Never invent facts
(prices, numbers, names, reviews, logos, dates). The variant is labelled AI-generated in the bar; its file
header says so on keep; no third-party licence notice is written for it.

## A registry the owner found
`$T registry vet --index https://x.dev/r/registry.json --repo owner/name` → accepted or refused with reasons
(not on the refused list · permissive licence evidenced by the source repo · shadcn schema · items that map
to slots · sampled items download with their source: a 401/402/403 or a content-less "pro" item is a
paywall). `registry add` indexes it into `~/.deckhand/catalog/` — it ranks beside the shipped catalog.
`registry list` / `registry remove --id x`.

## What the engine guarantees
- Location: every JSX element carries `data-dh="file:line:col"` in dev (AST, vendored parser — works with
  TypeScript 7 projects); the overlay resolves the clicked node and its owners.
- Candidates: `data/components.index.json` (773 MIT items; the navbars include every Tailark hero's own header),
  ranked by slot, primitive base (a Radix project never gets Base UI code), missing deps, personal library first
  (for the same slot only), then design diversity. Outside Next (Vite), `next/link` and `next/image` in a design
  become local stand-ins written beside it.
- Theme: palette classes → the project's semantic tokens; the site's own `components/ui/*` primitives are
  reused; a site without tokens gets a token layer derived from its own background/foreground + measured accent.
- Content: headings, text, prices, buttons+links (CTA to CTA, link to link), images, inputs and `.map()`
  list data are transplanted by role/order; repeated cards pair item by item (twin rows of the same card
  shape count as one list; the row that fits the owner's count wins, unused rows hide whole); two-tone
  headings take the heading in the bright half and a subtitle, or nothing, in the muted half; extra demo
  buttons/cards hide; brand-logo rows, stock photos and the design's `©` never pass as the owner's. Words beside a
  link are kept (a notice bar's line, a sentence with a link inside); figures (120+, 98%, 24h) pair with figures;
  the owner's logo row replaces the design's demo brands; the owner's `<form>` replaces the design's form whole
  (their action and fields); a comparison table fills a design's table row by row, column names over the columns;
  a component whose words are prop defaults (`title = "…"`) gets the owner's words as those props; a label that
  switches on hover shows the owner's label; a card template's own "Get Started" becomes the owner's button text.
- Honesty: every word a staged design still shows of its own is dashed (constant text, an illustration's demo
  rows, words inside a component); a design form (newsletter, "enter your email") is hidden unless the slot is a
  form page (contact, login, signup) or the owner's element has one — and a design with no place for the owner's
  form is not offered; a list field the design also reads as a value (`{t.period && …}`) is emptied, never shown
  undashed; footer/navbar menus come from the plan
  (`.deckhand/sitemap.json` nav + page titles) and social rows keep only the owner's networks
  (`brief.brand.social`); a site without a plan shows none of the design's demo menus or networks — its own links
  reach the page through the content slots (a footer's titled columns fill the design's columns, links included).
  The bar shows the fit ("your content 8/8") and dashes any demo copy that is left, inside lists too (a
  testimonial's "role" line the owner never wrote); keep records it in `.deckhand/demo-copy.json`, which
  `dh rebrand check` blocks on until rewritten.
- Mapping: FAQ questions (`<summary>`, `<dt>`, or the first of two paragraphs) go to the design's question; a quote
  to the quote and the author line to the name; "Custom" in a plan's price spot is the price; a design's "/month" is
  dropped when the owner's price already says it; a single-card design takes one whole testimonial, never half of
  the next; company logos inside cards hide one by one, never the cards.
- Build safety: a design's variant props on the project's own primitives are fitted to what those take (a Veil
  `<Card variant="outline">` against a shadcn Card without variants would fail `next build` once kept); a design is
  wired only if everything it imports loads from the project — every named import and
  `NS.Part` / `<NS.Part>` read exists, and a package the import itself needs is installed — else `BROKEN_IMPORT`
  and the next candidate takes its place. Designs that need no install come first (a running dev server may not
  see a new package until it restarts); a project with the `radix-ui` umbrella gets `radix-ui/<part>` imports
  instead of an install. Through the helper (and `try` with a dev URL) the page is then loaded until the dev server
  shows the new variants or an error: an error restores the file at once, drops the variants it points at and
  reopens the rest (the bar says how many were removed), or ends in `BUILD_BROKE` with the file restored. A package
  installed for a try stays in package.json and is named (`installedKept`, also on Discard).
- The page older than the file: the overlay sends what was clicked (tag + start of its text) with its stamp. The
  engine checks the element at the stamp is that one, else finds it again nearest the old line; if it cannot be
  sure, `ELEMENT_NOT_FOUND` with a **Reload the page and pick again** button (nothing written). After Keep or
  Discard the next pick reloads the page first. Swap, Tune and the AI draft share this. A click deep inside a
  section still offers the whole section; a click on a button picks the button, not its label.
- Vite: the build check asks Vite for the edited module and each design's module (a Vite page renders in the
  browser, so its HTML never shows a variant); `doctor` looks for stamps in the entry module.
- Keep: wrapper collapses to one component under `components/sections/<slug>/`, literal copy baked in,
  show/hide switches resolved, unused files pruned, `THIRD_PARTY_NOTICES.md` updated.
- Production: stamps are dev-only (`dh verify` row `prod-clean`); `$T clean` unwires before release
  (the token layer stays if a kept section uses it).

## Troubleshooting
| symptom | cause → fix |
|---|---|
| bar says "page did not update" | compile error in the dev server log → fix or Discard; `dh learn match --log .deckhand/dev.log` |
| no stamps (`doctor: stampsInHtml false`) | dev server not restarted after `setup` |
| HMR blocked / "Blocked cross-origin request" | open the helper URL (it rewrites Origin to localhost), not 127.0.0.1:3000 |
| `NO_CANDIDATES` | slot mislabeled, or base mismatch (`hidden` count) — pick the right slot |
| `POOR_FIT` skips | the design cannot hold ≥50% of the owner's content (a card or button: all of it), or has no place for their form — honest skip; the message names the closest fit: pick another kind of section in the list, More, or the AI draft |
| `ELEMENT_NOT_FOUND` + "reload" | the page is older than the file (a session added/removed lines, an edit) → click the button (or reload) and pick again |
| `BROKEN_IMPORT` / `NEEDS_DEPS` skips | the design imports something this project cannot load / needs an install while install-free designs exist — honest skip, the next design is shown |
| `BUILD_BROKE` (file restored) or "N variant(s) removed" | those designs broke the page build and were taken out at once; if a package was just installed (`installedKept`), restart the dev server and try again |
| `DRAFT_REJECTED` | read `problems`, fix the draft files, run `draft-done` again (the owner's page is untouched until it passes) |
