"""Remove a test's temp folder even where git made its files read-only (Windows). Self-contained: tests import it as `tmpclean`."""
import os
import shutil
import stat
import sys
import time
from pathlib import Path


def rmtree(path) -> None:
    p = Path(path)

    def fix(func, target, _exc=None):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except FileNotFoundError:
            pass

    for attempt in range(4):                         # a just-killed process may still hold a file for a moment
        if not p.exists():
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(p, onexc=fix)
            else:
                shutil.rmtree(p, onerror=fix)
        except OSError:
            pass
        if not p.exists():
            return
        time.sleep(0.25 * (attempt + 1))
