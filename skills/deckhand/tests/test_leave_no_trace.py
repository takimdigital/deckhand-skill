"""Nothing a Python test creates may outlive the run. `shutil.rmtree(x, ignore_errors=True)` silently FAILS on Windows when the tree
holds a git repository (its objects are read-only), so every such test left a folder behind, run after run. Tests remove their
folders with tests/tmpclean.py:rmtree, which clears the read-only bit and retries."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tmpclean  # noqa: E402


class LeaveNoTrace(unittest.TestCase):
    def test_no_test_swallows_rmtree_errors(self):
        bad = []
        for f in sorted(HERE.glob("test_*.py")):
            if f.name == Path(__file__).name:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"shutil\.rmtree\(.*ignore_errors\s*=\s*True", line):
                    bad.append(f"{f.name}:{i}")
        self.assertEqual(bad, [], "use `from tmpclean import rmtree` (read-only safe) instead of shutil.rmtree(..., ignore_errors=True)")

    def test_rmtree_removes_a_tree_with_read_only_git_objects(self):
        import os
        import stat
        d = Path(tempfile.mkdtemp())
        obj = d / "proj" / ".git" / "objects" / "ab"
        obj.mkdir(parents=True)
        f = obj / "cdef"
        f.write_text("x", encoding="utf-8")
        os.chmod(f, stat.S_IREAD)
        tmpclean.rmtree(d)
        self.assertFalse(d.exists())
        tmpclean.rmtree(d)                       # a second call on a missing folder is a no-op


if __name__ == "__main__":
    unittest.main()
