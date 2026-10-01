"""Repo coherence: what the docs, hints and error messages tell a model or an owner to run must exist, and the
numbers the README claims must be true. A renamed command or a new one that nobody documented fails here
(stdlib unittest; reuses llm_context's extraction of the command surface)."""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_context as L  # noqa: E402

PROSE = {"is", "the", "a", "and", "or", "to", "call", "calls", "command", "commands", "shim", "on", "itself", "cli",
         "control", "control-plane", "uses", "in", "prints", "reads", "it", "from", "with", "that", "writes", "json", "output", "plane"}
TRYON_PROSE = {"prints", "is", "engine", "session", "sessions", "setup", "overlay", "helper", "stamps", "stamp", "and",
               "or", "state", "request", "draft", "drafts", "variant", "variants", "button", "panel", "the", "a", "to",
               "registry", "catalog", "for", "without", "itself", "keeps", "runs", "works", "click", "data"}


class Coherence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = L.load_tree()
        mods = L.analyze(cls.files)
        dh, _ = L.dh_commands(cls.files, mods)
        cls.dh = {c: spec for c, spec in dh}
        cls.actions = {}
        cls.flags = {}
        for c, spec in dh:
            first = spec["args"][0] if spec["args"] else ""
            m = re.match(r"^\{([^}]*)\}", first)
            cls.actions[c] = set(m.group(1).split("|")) if m else None
            cls.flags[c] = set(re.findall(r"--[\w-]+", " ".join(spec["args"]))) | {"--project"}
        cls.tryon = {c for c, *_ in L.tryon_commands(cls.files)}
        cls.texts = {p: t for p, t in cls.files.items()
                     if t is not None and not L.collapsed(p) and "fixtures" not in p and not p.startswith("scripts/")
                     and p != "CHANGELOG.md"}

    def test_every_dh_command_mentioned_exists(self):
        bad = []
        for p, t in self.texts.items():
            for i, ln in enumerate(t.split("\n"), 1):
                for m in re.finditer(r"(?<![\w/.<-])dh\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*(?:\|[a-z][\w-]*)*))?((?:\s+--[a-z][\w-]*)*)", ln):
                    sub, act, fl = m.group(1), m.group(2), m.group(3)
                    if sub in PROSE:
                        continue
                    if sub not in self.dh:
                        bad.append(f"{p}:{i} dh {sub}")
                        continue
                    if act and self.actions.get(sub) and sub not in ("phase", "reopen", "gate"):
                        bad += [f"{p}:{i} dh {sub} {a}" for a in act.split("|") if a not in self.actions[sub]]
                    bad += [f"{p}:{i} dh {sub} {f}" for f in re.findall(r"--[\w-]+", fl) if f not in self.flags[sub]]
        self.assertEqual(bad, [])

    def test_every_tryon_command_mentioned_exists(self):
        bad = []
        for p, t in self.texts.items():
            for i, ln in enumerate(t.split("\n"), 1):
                for m in re.finditer(r"(?:`|\$T |cli\.mjs\s+|node tryon/cli\.mjs\s+)?(?<![\w/.-])tryon\s+([a-z][\w-]*)", ln):
                    c = m.group(1)
                    if c not in self.tryon and c not in TRYON_PROSE:
                        bad.append(f"{p}:{i} tryon {c}")
                for m in re.finditer(r"\$T\s+([a-z][\w-]*)", ln):
                    if m.group(1) not in self.tryon:
                        bad.append(f"{p}:{i} $T {m.group(1)}")
        self.assertEqual(bad, [])

    def test_the_command_surface_is_documented(self):
        skill = self.files["skills/deckhand/SKILL.md"]
        tryon_doc = skill + self.files["skills/deckhand/references/50-tryon.md"]
        missing = [f"dh {c}" for c in self.dh if not re.search(rf"\bdh {re.escape(c)}\b", skill)]
        missing += [f"tryon {c}" for c in self.tryon if not re.search(rf"(\b|\||\$T ){re.escape(c)}\b", tryon_doc)]
        self.assertEqual(missing, [], "add them to SKILL.md §4 (or references/50-tryon.md)")

    def test_relative_markdown_links_resolve(self):
        names = set(self.files) | {L.OUT}
        dirs = {os.path.dirname(p) for p in self.files}
        bad = []
        for p, t in self.files.items():
            if t is None or not p.endswith(".md") or "/templates/" in p:
                continue
            for i, ln in enumerate(t.split("\n"), 1):
                for m in re.finditer(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", ln):
                    u = m.group(1)
                    if re.match(r"^(https?:|mailto:)", u):
                        continue
                    tgt = os.path.normpath(os.path.join(os.path.dirname(p), u)).replace("\\", "/")
                    if tgt not in names and tgt not in dirs:
                        bad.append(f"{p}:{i} {u}")
        self.assertEqual(bad, [])

    def test_skill_paths_mentioned_exist(self):
        bad = []
        rx = re.compile(r"(?<![\w./<>-])((?:references|templates|ops/scripts|dhlib|tryon/lib|data)/[\w.-]+(?:/[\w.-]+)*\.(?:md|py|mjs|cjs|json|jsonl|yml|yaml|sh|ts|tsx))")
        for p, t in self.texts.items():
            for i, ln in enumerate(t.split("\n"), 1):
                for m in rx.finditer(ln):
                    rel = m.group(1)
                    if L.full(rel, self.files) is None:
                        bad.append(f"{p}:{i} {rel}")
        self.assertEqual(bad, [])

    def test_workflow_run_lines_are_valid_yaml(self):
        # a plain `run: …` value holding ": " is a YAML mapping error: GitHub drops the whole workflow (release.yml
        # lost its workflow_dispatch trigger this way on 2026-09-29); such a command goes in a `run: |` block
        wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        bad = [f"{f.name}:{i}" for f in sorted(wf.glob("*.yml")) for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
               if (m := re.match(r"^\s*(?:- )?(?:run|name):\s+(?![|>'\"])(.*)$", line)) and ": " in m.group(1)]
        self.assertEqual(bad, [])

    def test_readme_test_counts_are_true(self):
        count = lambda pattern, glob: sum(len(re.findall(pattern, t, re.M)) for p, t in self.files.items()  # noqa: E731
                                          if t is not None and Path(p).match(glob))
        actual = {"try-on": count(r"^\s*test\(", "skills/deckhand/tryon/test/*.test.mjs"),
                  "control-plane": count(r"^\s*def test_", "skills/deckhand/tests/test_*.py"),
                  "server-client": count(r"^\s*def test_", "skills/deckhand/ops/tests/test_*.py"),
                  "repo": count(r"^\s*def test_", "scripts/test_*.py")}
        readme = self.files["README.md"]
        claimed = {k: int(n) for n, k in re.findall(r"(\d+) (try-on|control-plane|server-client|repo)\b", readme)}
        self.assertEqual(claimed, actual, "update the CI line in README.md ✅ Proven")


class DocNumbers(unittest.TestCase):
    """Numbers the docs state must be derived from the source of truth, not typed twice."""
    ROOT = Path(__file__).resolve().parents[1]

    def read(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_invariant_count_matches_skill_md(self):
        sec = self.read("skills/deckhand/SKILL.md").split("## 3. Invariants", 1)[1].split("\n## 4.", 1)[0]
        n = len(re.findall(r"^(\d+)\. \*\*", sec, re.M))
        self.assertEqual([int(x) for x in re.findall(r"^(\d+)\. \*\*", sec, re.M)], list(range(1, n + 1)))
        bad = []
        for rel in ("README.md", "docs/USE-CASES.md", "docs/architecture-atlas.html", "skills/deckhand/SKILL.md", "AGENTS.md", "playground/README.md"):
            p = self.ROOT / rel
            if not p.exists():
                continue
            for m in re.finditer(r"\b(\d+|twelve|thirteen) (?:non-negotiable )?invariants\b", p.read_text(encoding="utf-8"), re.I):
                if m.group(1).lower() != str(n):
                    bad.append(f"{rel}: {m.group(0)}")
        self.assertEqual(bad, [], f"SKILL.md §3 lists {n} invariants")
        atlas = self.read("docs/architecture-atlas.html")
        table = atlas.split('id="invariants"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(len(re.findall(r"<tr><td>\d+</td>", table)), n)

    def test_subcommand_count_matches_the_parser(self):
        sys.path.insert(0, str(self.ROOT / "skills" / "deckhand"))
        from dhlib.cli import build_parser
        import argparse
        subs = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        n = len(subs.choices)
        atlas = self.read("docs/architecture-atlas.html")
        for m in re.finditer(r"\b(\d+) (?:<code>dh</code> )?subcommands", atlas):
            self.assertEqual(int(m.group(1)), n, m.group(0))
        self.assertIn("(%d subcommands)" % n, atlas)
        mapped = set(re.findall(r"\bdh ([a-z]+)", atlas.split('id="commands"', 1)[1]))
        self.assertEqual(sorted(set(subs.choices) - mapped - {"tryon"}), [], "commands missing from the atlas command map")

    def test_slot_kind_claims_match_the_index(self):
        import json
        items = json.loads(self.read("skills/deckhand/data/components.index.json"))["items"]
        n = len({i["slot"] for i in items})
        for rel in ("docs/architecture-atlas.html", "playground/README.md"):
            t = self.read(rel)
            self.assertIn("%d slot kinds" % n, t, rel)
            self.assertNotIn("about 45", t, rel)

    def test_cli_flags_reference_is_current_and_complete(self):
        import subprocess
        r = subprocess.run([sys.executable, str(self.ROOT / "scripts" / "gen_cli_flags.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = self.read("skills/deckhand/references/cli-flags.md")
        for flag in ("--cause", "--lane", "--buzz", "--shape", "--baseline-research", "--install-hook"):
            self.assertIn(flag, doc)
        self.assertIn("references/cli-flags.md", self.read("skills/deckhand/SKILL.md"))

    def test_version_check_covers_atlas_and_release_notes(self):
        import subprocess
        r = subprocess.run([sys.executable, str(self.ROOT / "scripts" / "version_check.py")], capture_output=True, text=True)
        self.assertIn("atlas header", r.stdout)
        self.assertIn("release notes", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_review_reference_lists_every_verify_row(self):
        src = self.read("skills/deckhand/dhlib/verify.py")
        rows = set(re.findall(r'row\("([a-z0-9-]+)"', src))
        doc = self.read("skills/deckhand/references/60-review.md")
        self.assertEqual(sorted(r for r in rows if f"| {r} |" not in doc), [])

    def test_data_cross_references(self):
        import json
        d = self.ROOT / "skills" / "deckhand"
        names = set(json.loads((d / "data" / "harness.json").read_text(encoding="utf-8"))) - {"why"}
        wf = (d / "dhlib" / "workflow.py").read_text(encoding="utf-8")
        body = wf.split("def harness", 1)[1].split("def todo_how", 1)[0]
        self.assertEqual(names, set(re.findall(r'return "([a-z-]+)"', body)))
        for b in json.loads((d / "data" / "bots.json").read_text(encoding="utf-8"))["bots"]:
            if b.get("script"):
                self.assertTrue((d / "templates" / "bots" / b["script"]).exists(), b["id"])
        ids = {i["id"] for i in json.loads((d / "data" / "components.index.json").read_text(encoding="utf-8"))["items"]}
        verdicts = set()
        for f in (d / "data" / "checks").glob("*.json"):
            verdicts |= set(json.loads(f.read_text(encoding="utf-8"))["verdicts"])
        self.assertEqual(ids ^ verdicts, set())


    # ---- the architecture atlas: the numbers and names a script can check are checked here --------------------------

    def atlas_text(self):
        import html
        return html.unescape(re.sub(r"<[^>]+>", " ", self.read("docs/architecture-atlas.html")))

    def test_atlas_fit_verdict_counts_match_the_checks_data(self):
        import json
        d = self.ROOT / "skills" / "deckhand" / "data" / "checks"
        real = {}
        for f in d.glob("*.json"):
            for v in json.loads(f.read_text(encoding="utf-8"))["verdicts"].values():
                real[v["v"]] = real.get(v["v"], 0) + 1
        m = re.search(r"(\d+) fits · (\d+) partial · (\d+) refused · (\d+) broken · (\d+) unchecked", self.atlas_text())
        self.assertIsNotNone(m, "the atlas states the fit-check verdict counts")
        self.assertEqual([int(x) for x in m.groups()],
                         [real.get("fits", 0), real.get("partial", 0), real.get("refused", 0), real.get("broken", 0), 0])

    def test_atlas_rule_pack_and_lesson_counts_match_the_code(self):
        import json
        sys.path.insert(0, str(self.ROOT / "skills" / "deckhand"))
        from dhlib import suggest
        d = self.ROOT / "skills" / "deckhand" / "data"
        atlas = self.atlas_text()
        packs = len([p for p in (d / "slop").glob("*.json") if not p.name.startswith("_")])
        lessons = len([ln for ln in (d / "lessons.seed.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()])
        registries = len(list((d / "checks").glob("*.json")))
        items = len(json.loads((d / "components.index.json").read_text(encoding="utf-8"))["items"])
        self.assertIn(f"{len(suggest.RULES)} deterministic rules", atlas)
        self.assertIn(f"{packs} language packs", atlas)
        self.assertIn(f"({lessons} lessons, S-001…S-{lessons:03d})", atlas)
        self.assertIn(f"({registries} registries)", atlas)
        self.assertIn(f"{items:,} indexed components", atlas)

    def test_atlas_gate_examples_classify_as_it_says(self):
        sys.path.insert(0, str(self.ROOT / "skills" / "deckhand"))
        from dhlib import state
        for q in ("go", "ok", "yes", "approved", "looks good", "lgtm", "ship it", "go live", "go ahead", "let's go", "G1 ok"):
            self.assertEqual(state.classify_quote(q), "approve", q)
        for q in ("ok, make the hero bigger", "yes but add a pricing page", "ok but add a pricing page", ""):
            self.assertEqual(state.classify_quote(q), "change_request", q)
        self.assertEqual(state.classify_quote("G1 ok, but add a pricing page"), "approve_with_changes")
        for q in ("don't ship it", "wait", "ok, I'll look tomorrow"):
            self.assertTrue(state.is_hold(q), q)

    def test_atlas_names_the_refusal_codes_an_owner_meets(self):
        sys.path.insert(0, str(self.ROOT / "skills" / "deckhand"))
        code = "\n".join(p.read_text(encoding="utf-8") for p in (self.ROOT / "skills" / "deckhand" / "dhlib").glob("*.py"))
        atlas = self.atlas_text()
        codes = ("NO_RUN", "RUN_CORRUPT", "USAGE", "NOT_REACHED", "ALREADY_DONE", "NOT_FORCEABLE", "LOCK_BUSY", "BRIEF_CORRUPT",
                 "DIRTY_TREE", "VERIFY_STALE", "NO_TARGET", "DEPLOY_FAILED", "SMOKE_FAILED")
        for c in codes:
            self.assertIn(f'"{c}"', code, f"{c} is no longer raised: drop it from this list")
        self.assertEqual([c for c in codes if c not in atlas], [], "the atlas has to name these refusals")

    def test_atlas_has_none_of_the_claims_found_false(self):
        """Each phrase was in the atlas and contradicted the code (found by the 2.4.4 read of every section)."""
        atlas = self.atlas_text()
        raw = self.read("docs/architecture-atlas.html")
        wrong = {
            "drift by mtime": "G1 stores content hashes of the plan files; older runs compare the last commit time (state.plan_drift)",
            ".<name>.deckhand-scaffold": "scaffold builds in a unique sibling dh-scaffold-<name>-<hex> (build.py)",
            'non-blocking "not checked"': "a verify that could not run routes is a blocking red row (verify.py)",
            "(gitignored runtime)": "only the run logs and local state are gitignored (util.GITIGNORE_LINES)",
            "phrase w,": "the slop weights are in data/slop/_common.json",
            "claim by claim against the 2.4.1": "the atlas is checked against the current code",
            "about 230 claims": "an unverifiable count",
            "(~95 KB), 3-pass copy transplant (~96 KB)": "engine.mjs is ~100 KB and transplant.mjs ~98 KB",
        }
        found = {k: why for k, why in wrong.items() if k in atlas or k.replace("<", "&lt;").replace(">", "&gt;") in raw}
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
