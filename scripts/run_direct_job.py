#!/usr/bin/env python3
"""Run one direct-montage command job in an isolated process (weekly / detached worker)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.command_montage import run_direct_montage_command
from discovery.config import load_env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-key", required=True)
    args = parser.parse_args()
    load_env()
    run_direct_montage_command(job_key=args.job_key, block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
