"""Tests for direct montage command parsing."""

from __future__ import annotations

import unittest

from discovery.command_montage import is_direct_montage_command, parse_montage_command


SAMPLE = """
Make a new 9:16 motivational Short using the luxury-clips-montage workflow.
Run `python scripts/build_motivation_job.py` with appropriate flags.
Owner account: chris — record combination usage for this owner when done.
Before picking audio or visuals — do not reuse the same excerpt unless instructions allow.
Search for audio (any type — speech, podcast clip, interview, etc.): alex hormozi
Visual / B-roll search: skyline financial district night supercar
Default target length: 60–90 seconds unless extra instructions override.

Extra instructions:
Source:
Official video "Why AI Won't Make You Rich in 2026"

Hook:
AI WON'T MAKE YOU RICH
"""


class TestCommandMontage(unittest.TestCase):
    def test_detect_montage(self) -> None:
        self.assertTrue(is_direct_montage_command(SAMPLE))

    def test_parse_fields(self) -> None:
        plan = parse_montage_command(SAMPLE)
        assert plan is not None
        self.assertEqual(plan["owner"], "chris")
        self.assertEqual(plan["hook"], "AI WON'T MAKE YOU RICH")
        self.assertIn("Why AI", plan["speech_query"] or "")
        self.assertEqual(plan["min_seconds"], 60.0)
        self.assertEqual(plan["max_seconds"], 90.0)
        self.assertEqual(plan["reuse_policy"], "allow")

    def test_extra_instructions_can_require_new(self) -> None:
        plan = parse_montage_command(
            SAMPLE + "\n\nExtra instructions:\nDo not reuse. Unused-only B-roll.\n"
        )
        assert plan is not None
        self.assertEqual(plan["reuse_policy"], "require_new")

    def test_extra_parses_two_short_videos(self) -> None:
        text = """
Make a new 9:16 motivational Short using the luxury-clips-montage workflow.
Search for audio: chris williamson motivational speech
Visual / B-roll search: beautiful ocean views
Default target length: 60–90 seconds unless extra instructions override.
Extra instructions:
two videos 30-45 seconds long. first clip should be a stunning view
"""
        plan = parse_montage_command(text)
        assert plan is not None
        self.assertEqual(plan["min_seconds"], 30.0)
        self.assertEqual(plan["max_seconds"], 45.0)
        self.assertEqual(plan["video_count"], 2)
        self.assertEqual(plan.get("speaker"), "Chris Williamson")


if __name__ == "__main__":
    unittest.main()
