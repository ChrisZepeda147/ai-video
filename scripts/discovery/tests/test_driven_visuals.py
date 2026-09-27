"""Tests for DrivenVisuals preset helpers."""

from __future__ import annotations

import unittest

from discovery.driven_visuals import (
    driven_beat_duration,
    parse_daily_video_briefs,
    planning_segment_length,
    speech_window_defaults,
    vehicle_opener_hold_sec,
)
from build_clips_montage import _beat_duration
from build_stills_slideshow import _ass_escape, _ass_header, group_words_into_phrases


class DrivenVisualsTests(unittest.TestCase):
    def test_opening_beats_faster_than_settled(self) -> None:
        opening = driven_beat_duration(elapsed=1.0, remaining=60.0)
        settled = driven_beat_duration(elapsed=20.0, remaining=40.0)
        self.assertLess(opening, settled)

    def test_car_opener_holds_full_exterior(self) -> None:
        hold = vehicle_opener_hold_sec()
        self.assertGreaterEqual(hold, 5.0)
        car_open = _beat_duration(
            accumulated=0.0,
            remaining=27.0,
            segment_length=8.0,
            driven_pacing=True,
            subject="Lamborghini Huracan night city",
        )
        yacht_open = _beat_duration(
            accumulated=0.0,
            remaining=27.0,
            segment_length=8.0,
            driven_pacing=True,
            subject="luxury yacht cinematic",
        )
        self.assertGreaterEqual(car_open, hold)
        self.assertLess(yacht_open, hold)

    def test_parse_daily_brief_blocks(self) -> None:
        text = """
VIDEO 1
Speaker: Jocko Willink
Hook: YOU ARE WASTING YOUR TIME
Visual direction: gym, sunrise, discipline

VIDEO 2
Speaker: David Goggins
Hook: NOBODY TELLS YOU THIS
"""
        briefs = parse_daily_video_briefs(text)
        self.assertEqual(len(briefs), 2)
        self.assertEqual(briefs[0]["speaker"], "Jocko Willink")
        self.assertEqual(briefs[1]["hook"], "NOBODY TELLS YOU THIS")

    def test_planning_beats_blend_not_all_fast(self) -> None:
        plan = planning_segment_length(driven_pacing=True, fallback=15.8, duration=79.0)
        self.assertGreater(plan, 2.0)
        self.assertLess(plan, 4.0)

    def test_speech_window_defaults_are_short(self) -> None:
        lo, hi = speech_window_defaults()
        self.assertLessEqual(hi, 30)

    def test_ass_keeps_word_gaps(self) -> None:
        self.assertEqual(_ass_escape("YOU CANNOT BE"), "YOU  CANNOT  BE")

    def test_caption_styles_are_vertically_centered(self) -> None:
        header = _ass_header(width=1080, height=1920)
        self.assertIn(",5,80,80,0,1", header)
        self.assertNotIn(",2,80,80,120,1", header)

    def test_phrase_grouping(self) -> None:
        words = [
            (0.0, 0.2, "You"),
            (0.2, 0.4, "don't"),
            (0.4, 0.6, "get"),
            (0.6, 0.8, "to"),
            (0.8, 1.0, "walk"),
            (1.0, 1.2, "away"),
        ]
        phrases = group_words_into_phrases(words, min_words=2, max_words=3)
        self.assertGreaterEqual(len(phrases), 2)
        self.assertIn("YOU", phrases[0][2])


if __name__ == "__main__":
    unittest.main()
