# Try-on playground

A real Next.js site kept as **source only**, so any try-on test starts from it instead of building a site from scratch
(`create-next-app` + `npm install` + `dh compose`, several minutes and a network).

| | |
|---|---|
| `tryon-site/` | Deckhand's own scaffold + the default `dh compose` (navbar, hero, features, pricing, faq, cta, footer), a plan and brief for a fictional bakery. No `node_modules`, `.next`, `.git`, `.env`, run state or try-on state. |
| `playground.mjs` | `restore` · `reset` · `start` · `kitchen` · `snapshot` |
| `playground.json` | what the snapshot holds and which Deckhand version made it |
| `playground.test.mjs` | structural test (always) and a real dev-server test (`DH_PLAYGROUND=1`) |

## Use it

```bash
node playground/playground.mjs restore              # ~/deckhand-playground/tryon-site (or --to DIR): copy, install once, git init
node playground/playground.mjs start                # try-on setup + dev server + try-on proxy; prints the URL, Ctrl+C stops
node playground/playground.mjs reset                # throw away every try-on change: source back to the snapshot
```

Open the printed URL and click **Try-on**. Two pages:

- `/` : the composed site (7 sections).
- `/kitchen-sink` : **one owner element for each fit-check reference** (45 of them; the catalog knows 58 slot kinds, several share a reference: hero, pricing, tabs, dialog, table, sidebar, chart,
  calendar…), written from the fit-check's own reference sections (`skills/deckhand/tryon/lib/fitcheck.mjs`), so it never drifts from
  what the catalog can be tried against.

`restore` is safe to run over an existing playground and always ends with a clean git commit, so `git diff` shows exactly what a
try-on session changed and `git checkout .` undoes it.

## Refresh the snapshot

After a change to `dh scaffold` or `dh compose`, or to keep the playground current with a new Deckhand:

```bash
dh scaffold --to <dir> && dh compose --project <dir>      # a fresh site, BEFORE any try-on click
node playground/playground.mjs snapshot --from <dir>      # strips paths, try-on state, node_modules; restores next.config.ts from git
```

`playground.test.mjs` fails if the snapshot imports something its file does not export (the bug that once made the default compose
answer HTTP 500) or holds a local path.

## Tests

```bash
node --test playground/playground.test.mjs                       # seconds
DH_PLAYGROUND=1 node --test playground/playground.test.mjs       # restores, starts a dev server, checks / and /kitchen-sink (about 40 s)
```
