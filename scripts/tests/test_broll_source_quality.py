#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broll_source_quality import unwanted_broll_title_reason
from youtube_popular_downloader import VideoCandidate


class BrollSourceQualityTests(unittest.TestCase):
    def test_minecraft_longplay_blocked(self) -> None:
        title = "Rainy Lake House - Minecraft Relaxing Longplay (No Commentary) 1.20"
        self.assertEqual(unwanted_broll_title_reason(title), "minecraft")

    def test_scenic_relaxation_autumn_blocked(self) -> None:
        title = "AUTUMN - Scenic Relaxation Film With Inspiring Cinematic Music - 4K"
        self.assertEqual(unwanted_broll_title_reason(title), "scenic_overlay_film")

    def test_real_forest_ok(self) -> None:
        title = "Pacific Northwest Rain Forest Drone 4K 60fps"
        self.assertIsNone(unwanted_broll_title_reason(title))

    def test_golden_sparrow_video_song_blocked(self) -> None:
        title = (
            "Golden Sparrow - 8K Video Song | Dhanush | Priyanka Mohan | "
            "Pavish | Anikha | GV Prakash #NEEK"
        )
        self.assertEqual(unwanted_broll_title_reason(title), "music_dance_video")

    def test_is_music_video_detects_video_song(self) -> None:
        from youtube_popular_downloader import VideoCandidate, is_music_video

        cand = VideoCandidate(
            video_id="ghGjlx5ZBWk",
            title="Golden Sparrow - 8K Video Song | Dhanush",
            url="https://youtu.be/ghGjlx5ZBWk",
            channel="T-Series",
            view_count=1_000_000,
            duration_seconds=240,
            published_at=None,
            source="test",
        )
        self.assertTrue(is_music_video(cand))


if __name__ == "__main__":
    unittest.main()
