#!/usr/bin/env python3
"""CLI entry: pause active production on this machine."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from discovery.production_pause import main

if __name__ == "__main__":
    raise SystemExit(main())
