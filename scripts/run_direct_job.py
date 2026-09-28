#!/usr/bin/env python3
"""Run one direct-montage command job in an isolated process (weekly / detached worker)."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.command_montage import run_direct_montage_command
from discovery.config import load_env, project_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-key", required=True)
    args = parser.parse_args()
    load_env()
    log_path = project_root() / "data" / "logs" / "weekly-montage-worker.log"
    try:
        run_direct_montage_command(job_key=args.job_key, block=True)
        return 0
    except Exception:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\nFATAL job {args.job_key}:\n")
            log.write(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
