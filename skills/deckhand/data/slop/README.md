# AI-slop language packs

`dh slop` finds copy that reads as if a model wrote it: "In today's fast-paced world", "seamless", "elevate your…",
"It's not just X, it's Y", three em dashes in a paragraph, every sentence the same length. It is a script: no model
call, no token, the same text always gets the same verdict.

There is **one engine** (`dhlib/slop.py`) and **one data file per language** (this folder). Adding a language, or
teaching an existing one a new cliché, is a JSON edit. No code.

## How a text is scored

Each hit weighs points (`_common.json → weights`): a strong tell 3, a buzz word 1, a phrase its own `w`, a
superlative with no number beside it 2, and so on. Points per 100 words give the verdict: **clean** below 4,
**review** from 4, **slop** from 10. One strong hit always means at least review. A chatbot reply pasted on a page
(`kind: "leak"`) is always slop. The brand phase (`dh rebrand check`) blocks on slop and warns on review.

Language-free signals run for every language, even one without a pack: em dashes, exclamation marks, decorative
emoji (🚀 ✨), and flat sentence rhythm.

## A pack (`<lang>.json`, schema `deckhand.slop/1`)

| field | what |
|---|---|
| `lang`, `name` | ISO 639 code (the file name), the language's own name |
| `maturity` | `seed` (written by the maintainer) · `reviewed` (checked by a native speaker who writes copy) |
| `script` | `latin` (word boundaries) · `cjk` (Japanese, Chinese: substring match, words ≈ characters / 2) · `hangul` |
| `stopwords` | ~30 common function words: how a text is recognised as this language |
| `suffixes`, `drop_e` | endings tried after each single word (`leverage` → leverages, leveraged, leveraging) |
| `words.strong` | words that almost never appear in honest small-business copy. `a\|b\|c` lists forms |
| `words.buzz` | words that are fine once and slop in a pile |
| `fixes` | `word → what to write instead` (shown with every hit) |
| `phrases` | `{id, kind, w, rx, example, fix}`: `rx` is a case-insensitive regex; `example` must match it |
| `transitions` | sentence-opening connectors (Furthermore, De plus…): flagged from the second one in a text |
| `superlatives` | best, meilleur…: flagged when the sentence has no number |
| `and` | the words that close a list, for the "three of everything" signal |
| `thresholds`, `weights` | optional overrides of `_common.json` (zh and ja turn the em-dash rule off) |
| `examples.slop`, `examples.clean` | at least 2 of each. **They are the pack's test.** |

Phrase kinds: `opener`, `hedge`, `structure`, `cta`, `closer`, `filler`, `claim`, `leak`.

## Contributing

1. Edit or add `<lang>.json`. Keep regexes plain: no lookarounds, no backreferences, no nested quantifiers like
   `(a+)+` (the lint refuses them, so a pack can never hang anyone's check).
2. Add a slop example that uses your new words, and keep the clean examples clean: real copy a good local business
   would write (prices, hours, streets, names).
3. `python3 skills/deckhand/dh.py slop lint skills/deckhand/data/slop/<lang>.json`. It fails when a slop example
   scores clean, a clean example does not, a phrase misses its own example, or the language is not detected.
4. `python3 -m unittest skills/deckhand/tests/test_slop.py`, then open a pull request.

Found a tic on one site? `dh slop add "word or phrase" --lang fr` applies it on your machine at once
(`~/.deckhand/slop/fr.json`); `dh slop export --lang fr` writes a bundle to contribute. Brand and trade words are
never slop on their own site: `dh slop allow "robust"` (the project's `.deckhand/slop.json`). A real customer's quote
stays theirs: put `dh:slop-ok` on its line.

What is deliberately not flagged: casual words ("I mean", "you know", "kind of") are what human writing has and model
writing lacks; plain verbs ("build", "improve") carry no signal on their own.
