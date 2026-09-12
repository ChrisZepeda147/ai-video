#!/usr/bin/env python3
"""CLI wrapper for DrivenVisuals render quality gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from discovery.render_quality_gate import check_render_quality


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a finished MP4 before publishing.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--expected-duration", type=float, default=None)
    parser.add_argument("--subject", default="", help="B-roll subject for opener check")
    args = parser.parse_args()

    report = check_render_quality(
        args.video,
        expected_duration=args.expected_duration,
        subject=args.subject,
    )
    for warning in report.warnings:
        print(f"WARN: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")
    print("OK" if report.ok else "FAIL")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
