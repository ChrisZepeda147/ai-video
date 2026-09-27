"""Tests for weekly ChatGPT paste parser."""

from __future__ import annotations

import unittest

from discovery.weekly_paste import build_week_progress, parse_weekly_paste


SAMPLE = """
MONDAY
1. David Goggins | ocean drone cinematic 60fps
2. Jocko Willink | gym workout cinematic
3. Andrew Tate | porsche exterior night drive
Images to make video 1: black 911 charcoal fog

TUESDAY
1. Alex Hormozi | penthouse skyline view
2. Chris Williamson | apartment window rain
3. David Goggins | desert road sunrise
"""


class TestWeeklyPaste(unittest.TestCase):
    def test_parse_week(self) -> None:
        slots, warnings = parse_weekly_paste(SAMPLE)
        self.assertGreaterEqual(len(slots), 6)
        self.assertFalse(any("No videos" in w for w in warnings))
        mon = [s for s in slots if s["day"] == "mon"]
        self.assertEqual(mon[0]["speaker"], "David Goggins")
        self.assertIn("911", mon[0]["image_prompt"])

    def test_parse_day_with_date_suffix(self) -> None:
        text = """
MONDAY (September 29, 2026)
1. David Goggins | ocean drone cinematic 60fps
2. Jocko Willink | gym workout cinematic
3. Andrew Tate | porsche exterior night drive
"""
        slots, warnings = parse_weekly_paste(text)
        self.assertEqual(len(slots), 3)
        self.assertFalse(any("No videos" in w for w in warnings))

    def test_parse_markdown_chatgpt(self) -> None:
        text = """
Here is your week:

**MONDAY**
1. **David Goggins** | ocean drone cinematic 60fps
2) Jocko Willink | gym workout cinematic
3. Andrew Tate - porsche exterior night drive

**TUESDAY**
1. Alex Hormozi | penthouse skyline view
2. Chris Williamson | apartment window rain
3. David Goggins | desert road sunrise
"""
        slots, _warnings = parse_weekly_paste(text)
        self.assertGreaterEqual(len(slots), 6)
        mon = [s for s in slots if s["day"] == "mon"]
        self.assertEqual(mon[0]["speaker"], "David Goggins")

    def test_focus_advances_after_monday_done(self) -> None:
        slots = [
            {"day": "mon", "slot": 1, "status": "done", "speaker": "A", "visual_direction": "v"},
            {"day": "mon", "slot": 2, "status": "done", "speaker": "B", "visual_direction": "v"},
            {"day": "mon", "slot": 3, "status": "done", "speaker": "C", "visual_direction": "v"},
            {"day": "tue", "slot": 1, "status": "queued", "speaker": "D", "visual_direction": "v"},
        ]
        prog = build_week_progress(slots)
        self.assertEqual(prog["focus_day"], "tue")


if __name__ == "__main__":
    unittest.main()
