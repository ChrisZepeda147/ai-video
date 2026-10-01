"""B-roll download plan defaults — montage jobs should not split hour-long sources by default."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_motivation_job as job  # noqa: E402


class BrollDownloadPlanTests(unittest.TestCase):
    def test_default_plan_uses_capped_parts_not_full_split(self) -> None:
        clips_limit, _clip_length, max_parts = job.broll_download_plan(
            duration=90.0,
            segment_length=18.0,
            clips_limit=5,
            clip_length=24,
            max_parts=3,
        )
        self.assertIsNotNone(max_parts)
        self.assertLessEqual(clips_limit, 6)


if __name__ == "__main__":
    unittest.main()
