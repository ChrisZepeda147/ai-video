"""Tests for DrivenVisuals preset helpers."""

from __future__ import annotations

import unittest

from discovery.driven_visuals import driven_beat_duration, parse_daily_video_briefs
from build_stills_slideshow import group_words_into_phrases


class DrivenVisualsTests(unittest.TestCase):
    def test_opening_beats_faster_than_settled(self) -> None:
        opening = driven_beat_duration(elapsed=1.0, remaining=60.0)
        settled = driven_beat_duration(elapsed=20.0, remaining=40.0)
        self.assertLess(opening, settled)

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
