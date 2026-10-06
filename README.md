<p align="center">
  <img src="assets/logo.svg" width="108" alt="Deckhand — an agent skill that turns a $5 server and a $10 domain into a live business">
</p>

<h1 align="center">Deckhand</h1>

<p align="center">
  <b>Bring a $5 server and a $10 domain (or $0).<br>
  Your AI agent turns them into a live business. You go find the clients.</b>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="https://github.com/takimdigital/deckhand-skill/actions/workflows/ci.yml"><img alt="CI status" src="https://img.shields.io/github/actions/workflow/status/takimdigital/deckhand-skill/ci.yml?branch=main&label=CI"></a>
  <img alt="Version: 2.5.0" src="https://img.shields.io/badge/version-2.5.0-blueviolet.svg">
  <img alt="Works with Claude Code, Codex, Cursor, Hermes, OpenCode, Gemini CLI" src="https://img.shields.io/badge/works%20with-Claude%20Code%20%7C%20Codex%20%7C%20Cursor%20%7C%20Hermes-black.svg">
</p>

---

Most "AI website builders" hand you a zip file, a demo page that says *"Build faster with Acme"*, and a
prayer. Then the deploy fails, the agent apologizes, tries the same thing again, and bills you for it.

**Deckhand is the opposite.** One skill folder for your AI agent (Claude Code, Codex, Cursor, Hermes,
OpenCode, Gemini CLI…). The agent plans every page and every click, builds from real human-designed
components, puts **your** words and **your** brand on them, and ships the site to **your** server. Then it
keeps it running. Scripts do the boring parts, so you don't pay AI tokens for boilerplate. Every "done" is a
command's output, never a promise.

> **You:** *"Build my bakery's ordering site and put it online."*
> **Agent:** asks you 3 things → shows you the plan → shows you the site running → lets you click any section
> and try other designs → ships it → hands you the URL, where the logins live, and the proof.

**New here and not technical? → [Use cases, step by step](docs/USE-CASES.md).** Copy a sentence, paste it to
your agent, done.

## ☕ The uncomfortable math

**"I can't afford to start a business"**: you, holding a $9 *Venti Macha Luxa Choco-Caca Laka Frappé*.

| Your coffee | What it covers |
| --- | --- |
| one $5 drink | one month of a real server |
| one $10 drink | a real domain, for a whole year |
| three drinks | your entire business, live, for a month |

You're not broke. You've been paying for the wrong thing. **Actually broke? Keep the coffee.** The $0 track
is real: a free Oracle server, and a domain is optional. It's live in production, and paying stays an
offer, never a gate.

## 🚀 Start in 2 minutes

```bash
git clone https://github.com/takimdigital/deckhand-skill.git
cd deckhand-skill && ./install.sh        # Windows: powershell -ExecutionPolicy Bypass -File install.ps1
```

The installer finds your agents (Claude Code, Codex, Cursor, Hermes, OpenCode, Gemini CLI) and installs into
each one. You need Python 3.9+ and Node 18+, and nothing else. Then open your agent and say what you want.
Using Claude Code? `./install.sh --claude-hook` makes every new, resumed or compacted session in a Deckhand project
start from where that project stands.

## 🧭 What happens when you ask

```text
define → research → plan ─✋→ build ─✋→ brand → try-on ─✋→ review ─✋→ deploy → operate
```

✋ = it **stops and waits for your OK** (phased mode, the default). Prefer it hands-off? Say *"auto mode"*.

| step | what the agent does | how you know it's really done |
|---|---|---|
| define | asks what you sell, to whom, in which languages | a brief |
| research | your top 3 competitors: what they do well, where they're weak | 3 real links with strengths and gaps |
| plan | every page, button and form, wired. **No dead ends allowed** | a checker refuses orphan pages, links to nowhere, forms with no success or error state |
| build | from a vetted open-source base, **your own** past site, your existing site, or from scratch | the site runs on your computer, and you click around |
| brand | your name, colours, icon; the template's traces out; your words, not AI filler | a leak check finds no leftovers, and a copy check finds no AI slop (11 languages) |
| try-on | you click sections and swap or tune them (below) | nothing open, nothing half-done |
| review | build, types, secrets, every link answers, honesty | a green report |
| deploy | your server via Coolify, then a smoke test | a live URL, and `HANDOFF.md` with everything you own |
| operate | changes, rollbacks, bots that watch the site and the business | the bots report to you |

**Stop anywhere, continue anywhere.** Every step is saved in the project itself, so a fresh session (or another
AI) picks up at the exact next step, with your decisions and your to-do list. The agent tells you when it's safe
to start fresh.

## 🪄 The parts nobody else does

**Try-on: click any section of your site and swap it.** Four licensed designs appear **in your colours,
with your text, your links and your photos**, and ← → flips between them instantly. Fake "trusted by"
logos, stock photos and newsletter boxes that post nowhere are hidden. Keep bakes it in, Discard puts your
file back byte for byte. Catalog: 1,247 MIT components (Tailark, Shadcn UI Blocks, blocks.so, shadcn, Magic UI, Smooth UI, Kokonut,
basecn), each staged by a fit check before an owner sees it.

**Tune it: don't replace it, adjust it.** Pick a section and choose *quieter · bolder · airier · clearer ·
softer · sharper*, or dial spacing, headline size, weight, corners, depth, contrast and width. What you see
is exactly what gets kept. **Site** does the same for the whole look: accent colour, warm or cool
neutrals, corners, density, headline scale, fonts. Or just tell your agent *"make the hero airier"* or *"warmer
greys, rounder corners"*. No AI is needed to apply any of it, so none is charged.

**Nothing fits? Ask the AI, labelled.** Your agent writes one version, once. Deckhand checks it before you
see it: all your words and links, only your colours, no invented facts, nothing to install. It shows up
with a purple **AI-generated** badge. You always know what a human designed and what a model wrote.

**It learns from its mistakes, without guessing.** `dh autopsy` reads the session log with no AI involved.
It finds every failure (including the ones hidden behind `| tail`), what actually fixed each one, and how
often it came back. The next session gets the fix before the error happens, and a safe fix can replay
itself (`dh run --fix`). Workflows that worked twice show up as *"this worked last time"*.

**Proven paths instead of improvisation.** AIs are good at words and design, bad at planning 40 steps ahead
without a slip. So Deckhand keeps **workflows**: the exact path that worked before, from the first question to the
last command, each step with what it must print. At the start, the agent asks Deckhand for the 3 workflows that fit
your project best (a plumbing kit finds the cleaning one: same roles, same flows, other words), you pick one, and it
walks it step by step. Your own workflows stay on your computer; good ones can be shared with everyone through a
reviewed pull request.

**An autopsy that tells you what you should have been asked.** At any moment, `dh autopsy --workflow` replays the
session with no AI involved: every question the agent asked you and what you answered, which answers came too late
and forced work to be redone, where the run left its workflow, what each failure cost in minutes. Then it proposes
fixes to the workflow, each with the reason and the evidence, and asks you where to save the ones you accept: your
own workflows, the community's, or nowhere. It reads Claude Code sessions, Hermes' own session store, or any chat
log, and it never edits Deckhand itself: Deckhand's own bugs go into a separate report for its maintainer.

**It tells you what to do next, and why.** After the list of what waits on you, every report ends with a few
optional suggestions, ranked NOW · SOON · LATER: a failure that keeps coming back, a checkpoint worth reviewing, workflow
improvements waiting for your choice, a deferred task that is now due, a finished run worth keeping as a workflow. Each
one comes with its reason and the exact command. None of it is guessed: every suggestion is computed from the project's
own files, the same files give the same list, and one you don't want goes quiet for a week.

**Parallel builders that don't collide.** For a bigger app, the plan is cut into exactly as many packages as your
agent can run in parallel, grouped so two builders never touch the same folder, with one shared rules file. The
agent builds the foundation first, dispatches the builders, then re-checks their work itself instead of trusting
their summaries.

**Build a product to sell, not only a business.** Tell it *"a boilerplate for cleaning companies that I'll sell"*:
the demo company is fictional and lives only in the seed (with a script that wipes it), each buyer's own details go in
the app's settings, and the review checks the buyer's kit (README, licence, customization guide).

**Nothing joins on trust.** A template or component library someone found is checked first. Copyleft,
no licence, paywalls, paid packages, committed passwords and dead repos are refused, with the reason and
what would be accepted instead.

**Your own library of starting points.** A site you shipped becomes a private base on **your** GitHub
(`dh harvest --push`): brand removed, secret scan first, marked "verified + live". Next client: one command
to start from it, from any computer.

**Research you can check, not trust.** Every fact about your market (a competitor's price, what customers
complain about, a local rule) is stored with the exact sentence it came from and the page it's on. Deckhand
reopens every page and checks the sentence is really there, so an invented or misremembered "fact" can't slip
into your plan. The words your customers actually use are copied from real pages, not guessed. When several
agents research at once, none of them reads a page another one already read.

**Found on Google and in AI answers, from day one.**
- **What the scripts write, from your own facts:** crawl rules, a sitemap, a title and description per page,
  canonicals, the card shown when someone shares your link, your business details for search engines, a real 404
  page, and instant Bing indexing (Bing feeds ChatGPT search and Copilot).
- **What they catch:** the small mistakes that quietly sink sites, like every page claiming to be the home page,
  a preview address getting indexed, or "Create Next App" left as the title.
- **What only you can do** goes on your to-do list with the exact clicks: your Google Business Profile, Search
  Console, Bing, reviews, your address and hours.

Nobody can promise #1. We make sure nothing in our control is missing.

**Switch sessions without fear, even to another AI.** Long chats get worse, and a fresh one used to forget
everything. Deckhand keeps a one-page summary of each project on your computer, rebuilt after every step from the
project's own files: where it stands, what's done and the proof, what's in progress, what you decided, what's
waiting on you, and the exact next command. It also tells you whether it's safe to start fresh right now, and
if not, why. Open a new session in Claude, Codex, Cursor or any other agent, and it carries on from there. Working
for clients? Each client's settings and keys stay in that client's project, on your machine, never on GitHub.

**It runs the business, not just the website.** An uptime watchdog and a broken-link audit run on a
schedule from day one, and backups and dependencies are checked too. Business bots (weekly KPIs, lead digest,
failed payments, booking reminders, review requests, low stock) come as ready specs and skeletons that your
agent wires to your app.

## 🪙 Why it costs so few tokens

- **Scripts do the deterministic work**: planning checks, building, swapping, tuning, rebranding, verifying,
  deploying, autopsy. The model writes words and your app's logic, not boilerplate.
- **One instruction at a time.** `dh next` tells the agent exactly one thing to do and which short page to read.
- **Zero AI calls per click** in try-on and tune.
- **Failures are paid once**: a known error prints its proven fix instantly, instead of 20 minutes of re-debugging.
- **Fresh sessions start small.** A new session reads a one-page summary of the project (about 1,500 tokens)
  instead of dragging a long, diluted chat along.

## ✅ Proven, and what isn't yet

Run for real in this release:

- In a browser, on a real Next.js 16 site:
  - try-on variants carried the owner's text 4/4;
  - an AI draft appeared, passed its checks and was labelled;
  - Tune changed the page exactly (spacing 96→144px, headline 48→60px) and reset exactly;
  - Site changes were applied and undone after a reload.
- A landing page composed from scratch in about 6 seconds, with 34 of 34 of the owner's words placed.
- The autopsy on a real 369-command session found:
  - 23 failures a pipe had hidden;
  - a trap that recurred 3 times;
  - the exact edit that fixed a failed check.
- SEO applied to a real Next.js 16 site:
  - the production build passed;
  - every page served a unique title, a description, a self-canonical on the real domain, share tags and the
    business details for search engines;
  - unknown pages answered 404;
  - preview mode served noindex.
- Session resume, tested in CI on Ubuntu and Windows: the summary is rebuilt after every command, the "safe to start fresh"
  verdict turns NO on unexplained edits and failures, the re-check catches a stale verify or a plan edited after
  approval, and one client's keys are invisible from another client's project.
- A real run on Hermes (Windows, a cleaning-company boilerplate) was dissected step by step. Its 20 problems are fixed
  in code, each with a test: a gate passed on the agent's paraphrase of a change request, a base that could not land
  in the planning folder, a database kept alive by hand for hours, ports Windows reserves, 22 work packages for 4
  builders, and a Windows `HOSTNAME` trap.
- CI on every push, Ubuntu and Windows: 174 try-on + 443 control-plane + 40 server-client + 31 repo tests.

Not yet proven live: a full `dh deploy ship` against a real server (it uses the same Coolify client that
was proven live in v1), the first real run of the $0 Oracle track, and the Claude Code session hook inside a
live Claude Code session (its output is tested, not yet watched in the app). I'd rather tell you than let you
find out.

## 🔒 Rules it never breaks

Your facts are never invented: unknown prices, reviews or addresses go in a *"still needed from you"*
list. Secrets live in a private vault, never in chat or git. Each project keeps its own settings and keys,
where you choose once (inside the project, shared on your machine, or a folder of yours), and a client's keys stay
in that client's project. Only permissive licences are used, and their notices are kept. Dev tools never ship to production.
Your code, your server, your data. Stop using Deckhand tomorrow and everything keeps running.

## 🙏 A note from me

I'm building this with my own money: the servers, the AI tokens, the test runs. I want one tool that works
for **everyone**, not just developers: the baker, the barber, the freelancer who froze at the word "DNS".
I'm not a big company, and I'll get things wrong. When it breaks, [open an issue](https://github.com/takimdigital/deckhand-skill/issues):
that's worth as much to me as a thank-you.

If it saved you time or made you money: **[☕ buy me a coffee](https://buymeacoffee.com/takimdigital)** or
⭐ star the repo. Both keep it going and free, forever.

## ❓ FAQ

**Do I need to code?** No. You answer questions, approve 4 checkpoints, and do the few things only you can
do (like creating an account), each with exact click paths. → [Use cases](docs/USE-CASES.md)

**Will it look AI-generated?** No. Sections are human-designed and MIT-licensed, restyled to your brand and
filled with your words, and you pick them by clicking. When the AI does write a design, it's labelled.
The words are checked too: a script (no AI) flags copy that reads as machine-written ("elevate your…",
"in today's fast-paced world", em dashes everywhere) in 11 languages, and the brand step does not pass until it
is rewritten. It can read your current site as well: `dh slop check --url https://your-site`.

**I already have a site.** Say *"take my existing site and make it look premium."* Try-on, Tune and Site work
on it directly.

**Is anything paid required?** No. Open-source parts, Coolify on your own server, and a real $0 track.

**My chat got long. Can I start over without losing anything?** Yes. Ask *"can I start a fresh session now?"*
The agent answers from a check, not a guess (and writes down what's missing if the answer is no). Then open a
new session, with any AI, and say *"continue my site"*. →
[Use case 12](docs/USE-CASES.md#12-start-a-fresh-session-or-switch-ai-without-losing-anything)

**Working on Deckhand with an AI?** Tell it to read [`LLM_CONTEXT.md`](LLM_CONTEXT.md) first. It's the whole repo
in one file, written for a model and regenerated from the code on every change, so a brand-new session starts
with full context. For the human-readable picture — the 9-phase state machine, the gate classifier, the try-on
click loop, the AI-draft gates and every command, with diagrams — open the
[architecture atlas](docs/architecture-atlas.html).

**Does it work with Hermes, not only Claude Code?** Yes. `dh` detects the agent it runs in and prints that agent's
own syntax (Hermes: background terminals, `process_manage`, `delegate_task`; Claude Code: background tasks, sub-agents,
todo list). The autopsy reads Hermes' own session store directly.

**Coming from v1?** The five skills are now one (`skills/deckhand`), including `deckhand-profile`: your
`~/.deckhand/profile.md` and `~/.deckhand/pending.md` keep working (`dh profile show`, `dh pending`). If an agent still
has an old copy of one of those skills installed, delete it. See the [changelog](CHANGELOG.md).

## 📄 License

[MIT](LICENSE)
