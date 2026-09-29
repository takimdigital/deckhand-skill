"""llm_context.py — the cold-start map must be exact, deterministic and unable to rot silently (stdlib unittest)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_context as L  # noqa: E402


class LlmContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = L.load_tree()
        cls.text, cls.broken = L.build(cls.files)
        cls.lines = cls.text.split("\n")

    def test_deterministic(self):
        again, _ = L.build(L.load_tree())
        self.assertEqual(self.text, again)

    def test_the_curated_core_resolves(self):
        self.assertEqual(self.broken, [])
        self.assertNotIn("⚠UNRESOLVED", self.text)

    def test_index_line_ranges_are_exact(self):
        rows = re.findall(r"^- §(\d+) (.+): L(\d+)-L(\d+)$", self.text, re.M)
        self.assertGreater(len(rows), 10)
        for n, title, a, b in rows:
            self.assertEqual(self.lines[int(a) - 1], f"## §{n} {title}")
            nxt = self.lines[int(b)] if int(b) < len(self.lines) else ""
            self.assertTrue(nxt.startswith("## §") or nxt == "", (title, nxt))

    def test_an_anchor_renders_its_exact_line(self):
        m = re.search(r"\bopen@tryon/lib/engine\.mjs:(\d+)", self.text)
        self.assertIsNotNone(m)
        src = self.files[L.SKILL + "tryon/lib/engine.mjs"].split("\n")
        self.assertIn("export async function open(", src[int(m.group(1)) - 1])

    def test_every_pointer_lands_on_its_symbol(self):
        pointers = re.findall(r"\b([A-Za-z_$][\w$.]*)@([\w./-]+\.(?:py|mjs|cjs|js)):(\d+)", self.text)
        self.assertGreater(len(pointers), 150)
        for sym, path, line in pointers:
            full = L.full(path, self.files)
            self.assertIsNotNone(full, path)
            src = self.files[full].split("\n")[int(line) - 1]
            self.assertIn(sym.split(".")[-1], src, f"{sym}@{path}:{line} -> {src.strip()[:80]}")

    def test_every_module_entry_lands_on_its_definition(self):
        checked, path = 0, None
        for ln in self.lines:
            m = re.match(r"^#### (\S+)  \(", ln)
            if m:
                path = L.full(m.group(1), self.files)
                continue
            if not path or not re.match(r"^  (api|int:|const:)", ln):
                continue
            for name, line in re.findall(r"(?:^  api (?:class )?|\s)([A-Za-z_$][\w$]*)(?:\([^@]*\))?@(\d+)", ln):
                src = self.files[path].split("\n")[int(line) - 1]
                self.assertIn(name if name != "default" else "export default", src, f"{path}:{line} {name}")
                checked += 1
        self.assertGreater(checked, 400)

    def test_a_broken_anchor_is_caught_with_its_core_line(self):
        files = dict(self.files)
        files[L.CORE] = "## X\nsee [[dhlib/state.py#no_such_function]] and [[dh:no-such-cmd]] and [[!NOT_A_CODE]] and [[nope/file.py]]\n"
        text, broken = L.build(files)
        self.assertEqual(len(broken), 4)
        self.assertTrue(all(b.startswith(f"{L.CORE}:2:") for b in broken))
        self.assertIn("⚠UNRESOLVED[dhlib/state.py#no_such_function]", text)

    def test_flags_added_in_loops_and_parent_parsers_are_listed(self):
        # review 2026-09-27 (N5): a cold agent reading §8 thought `pending add --why` and `vault set --here` did not exist
        self.assertRegex(self.text, r"(?m)^- dh pending .*\[--why WHY\].*\[--when WHEN\]")
        self.assertRegex(self.text, r"(?m)^- dh vault \[--here\|--machine\]")

    def test_every_command_and_code_file_is_listed(self):
        dh, _ = L.dh_commands(self.files, L.analyze(self.files))
        for cmd, _spec in dh:
            self.assertRegex(self.text, rf"(?m)^- dh {re.escape(cmd)}\b")
        for c, *_ in L.tryon_commands(self.files):
            self.assertRegex(self.text, rf"(?m)^- tryon {re.escape(c)}\b")
        for p in self.files:
            if Path(p).suffix in L.CODE_EXT and not L.is_test(p) and not L.collapsed(p) and self.files[p]:
                self.assertIn(f"#### {L.short(p)}  (", self.text, p)

    def test_a_code_change_changes_the_map(self):
        files = dict(self.files)
        path = L.SKILL + "dhlib/state.py"
        files[path] = files[path].replace("def gate_pass(", "def gate_passed_renamed(")
        text, _ = L.build(files)
        self.assertIn("gate_passed_renamed", text)
        self.assertNotEqual(text, self.text)

    def test_windows_line_endings_do_not_change_the_output(self):
        crlf = {p: (L.decode(p, t.replace("\n", "\r\n").encode("utf-8")) if t is not None else None) for p, t in self.files.items()}
        self.assertEqual(L.build(crlf)[0], self.text)

    def test_check_fails_when_stale_and_passes_after_regenerating(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            for p, t in self.files.items():
                dest = Path(tmp) / p
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((Path(L.ROOT) / p).read_bytes())
            root = L.ROOT
            L.ROOT = Path(tmp)                                  # not a git checkout: the walker path is used
            try:
                self.assertEqual(L.main(["--check", "--quiet"]), 1)      # no LLM_CONTEXT.md yet = stale
                self.assertEqual(L.main(["--quiet"]), 0)
                self.assertEqual(L.main(["--check", "--quiet"]), 0)
                self.assertEqual((Path(tmp) / L.OUT).read_text(encoding="utf-8"), self.text)
                p = Path(tmp) / L.SKILL / "dhlib" / "state.py"
                p.write_text(p.read_text(encoding="utf-8") + "\n\ndef added_later():\n    pass\n", encoding="utf-8")
                self.assertEqual(L.main(["--check", "--quiet"]), 1)      # the code moved on, the map did not
            finally:
                L.ROOT = root


if __name__ == "__main__":
    unittest.main()
