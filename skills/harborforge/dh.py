#!/usr/bin/env python3
"""Deckhand control plane entry point: `python3 dh.py <command>` (Windows: `py dh.py <command>`).
Stdlib only, Python 3.9+. Start with `dh.py next`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dhlib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
