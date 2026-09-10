#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_text_clip as text_clip
import text_overlay as overlay


class TextOverlayTests(unittest.TestCase):
    def test_wrap_text_breaks_long_lines(self) -> None:
        wrapped = overlay.wrap_text("one two three four five six seven eight nine", max_chars=12)
        self.assertIn(r"\N", wrapped)

    def test_build_static_ass_uses_place(self) -> None:
        ass = overlay.build_static_ass(
            "Stay locked in.",
            duration=20.0,
            place="bottom-center",
        )
        self.assertIn("Alignment, MarginL", ass)
        self.assertIn(",2,40,40,", ass)
        self.assertIn("0:00:00.00,0:00:20.00", ass)

    def test_segment_length_defaults_to_fifth_of_duration(self) -> None:
        self.assertAlmostEqual(text_clip.segment_length_for(20.0, None), 5.0)
        self.assertAlmostEqual(text_clip.segment_length_for(60.0, None), 10.0)


if __name__ == "__main__":
    unittest.main()
