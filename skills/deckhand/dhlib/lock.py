"""A tiny cross-process lock: an O_EXCL lock file next to the thing being changed (stdlib only)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def locked(path, timeout: float = 15.0, stale: float = 30.0):
    """Hold `<path>.lock` while the body runs. A lock older than `stale` seconds belongs to a dead process: take it over."""
    lp = Path(str(path) + ".lock")
    lp.parent.mkdir(parents=True, exist_ok=True)
    end = time.time() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > stale:
                    lp.unlink()
                    continue
            except OSError:
                continue
            if time.time() > end:
                raise TimeoutError(f"lock busy: {lp}")
            time.sleep(0.02)
        except PermissionError:          # Windows: the holder is deleting it right now
            if time.time() > end:
                raise
            time.sleep(0.02)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        try:
            lp.unlink()
        except OSError:
            pass
