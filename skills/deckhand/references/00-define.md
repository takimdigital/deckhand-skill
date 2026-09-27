# 00 — DEFINE (the only interview)

**Objective:** a complete `.deckhand/brief.json` + the run's mode and path, in ONE owner round-trip.
**Inputs:** the profile (machine + this project's, `dh profile show`) + the owner's notes `profile.md`, `dh profile doctor`,
`dh workflow query` (a proven path for this kind of project), whatever the owner already said.
**Output:** `dh phase done define` green.

## Procedure
1. `dh profile doctor` — record what access exists. Profile fields are answers: never ask them again.
   No profile → create it in the same batch (only fields that change behaviour; no secrets).
2. `dh workflow query` — the 3 workflows that fit best (reasons, proof, what they miss). Show them in plain words;
   the owner picks one or none. Picked: `dh workflow use <ref>` and add its `ask_upfront` questions to this round
   (they include questions past runs learned too late). None: continue; the run itself becomes a workflow later.
3. Draft every brief field you can infer from the conversation; mark inferred ones in `assumed[]`.
4. Ask the rest in ONE message, each question with a proposed default (the owner answers "1a 3b" or "default"):

| # | field | ask (plain words) | default |
|---|---|---|---|
| Q0 | mode | "Step by step (I stop at 4 checkpoints) or end-to-end?" | `phased` |
| Q0b | for whom | "Is this your business, a client's, or a product you will sell to many businesses (a boilerplate)?" (client: their settings and keys stay in this project; product: a fictional demo company in the seed, the buyers' facts in settings) | `me` |
| Q1 | path | "Start from a proven open-source app, from your own saved base, from your existing site/repo, or from scratch?" | `pool` (or `mine` if the personal pool has a fit) |
| Q2 | business | "What does it do, in one line?" + a 3–5 word `category` for research queries | — |
| Q3 | shape | saas · marketplace · booking · catalogue · leadgen · internal (suggest one) | inferred |
| Q4 | audience + market + languages | "Who buys, where, in which languages?" (ar/he/fa/ur ⇒ RTL) | profile languages |
| Q5 | features (day one) | accounts · payments · booking · admin · i18n · search · notifications · files · blog | from shape |
| Q6 | brand | name, tagline, colour, logo (or "derive it") | derive |
| Q7 | money | subscription · one-off · commission · invoice · not yet | — |
| Q8 | content | "Do you have real copy/photos, or should I draft and you correct?" | draft-then-correct |
| Q9 | hosting | own VPS + domain · free preview ($0: Oracle + free domain, or no domain: Coolify's generated URL) · undecided | profile |

5. Write it: `dh brief set business="…" category="…" deliverable=own|client|product shape=… languages=fr,en audience="…" features=… brand.name="…"`.
   `dh init` first if there is no run (`--mode`, `--path`, `--for` from Q0/Q0b/Q1). For a client, their keys go in
   with `dh vault set NAME` inside the project (the client's own layer; never the owner's machine vault).
6. Read back a 5-line summary, then `dh phase done define` and continue (no gate here). Every choice the owner
   made in chat that the brief does not hold → `dh note decision "…"` now. What only the owner can do (a key, an
   account, a client's facts) → `dh pending add` in the same message. A question that belongs to a later phase (the
   domain at deploy, the product's price at review) is announced now and parked: `dh pending add … --when "deploy"`.

## Rules
- MUST NOT ask for a fact the profile, its notes (`profile.md`), the brief, the repo or a token can answer.
- Everything a later phase will need from the owner is asked in THIS round — a question asked late re-opens work
  (`dh autopsy --workflow` counts them).
- "You decide" ⇒ take the default, add the field to `assumed[]`, say so in the read-back.
- Hosting on an existing VPS: capture RAM/vCPU now (Coolify floor: 2 vCPU / 2 GB; 4 GB comfortable).
- `path=existing`: `dh adopt <path|url>` is allowed during define (read-only analysis of their code
  answers half the brief); nothing is modified before G2 except deckhand's own lines (the `.gitignore` block and
  the AGENTS.md/CLAUDE.md cold-start block — tell the owner).
- Lead-gen (plumber, lawyer, bakery site): fully supported — `path=scratch` + `dh compose` builds it from
  licensed marketing blocks; the pool is for software-shaped apps.
