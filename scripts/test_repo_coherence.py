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
               if (m := re.match(r"^\s*(?:- )?run:\s+(?![|>'\"])(.*)$", line)) and ": " in m.group(1)]
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


if __name__ == "__main__":
    unittest.main()
