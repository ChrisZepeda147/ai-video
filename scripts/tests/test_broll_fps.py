#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from youtube_popular_downloader import (
    VideoCandidate,
    listed_fps_from_entry,
    pick_usable_fps_candidates,
    title_suggests_usable_fps,
)


def _candidate(video_id: str, title: str, *, fps: float | None = None, views: int = 1000) -> VideoCandidate:
    return VideoCandidate(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel="test",
        view_count=views,
        duration_seconds=120,
        published_at=None,
        source="test",
        fps=fps,
    )


class BrollFpsTests(unittest.TestCase):
    def test_title_detects_50_and_60_fps(self) -> None:
        self.assertTrue(title_suggests_usable_fps("Huracan canyon run 4K 60fps"))
        self.assertTrue(title_suggests_usable_fps("Luxury Lamborghini 50 FPS"))
        self.assertFalse(title_suggests_usable_fps("Aventador SVJ cinematic 4K"))

    def test_listed_fps_uses_highest_format(self) -> None:
        fps = listed_fps_from_entry(
            {
                "fps": 24,
                "formats": [{"fps": 24}, {"fps": 60}, {"fps": None}],
            }
        )
        self.assertEqual(fps, 60.0)

    def test_pick_skips_known_low_fps_without_probe(self) -> None:
        kept = pick_usable_fps_candidates(
            [
                _candidate("low", "Aventador cinematic 4K", fps=24.0, views=9_000_000),
                _candidate("good", "Huracan 4K 60fps", fps=60.0, views=20_000),
            ],
            limit=2,
            probe=False,
        )
        self.assertEqual([item.video_id for item in kept], ["good"])


if __name__ == "__main__":
    unittest.main()
