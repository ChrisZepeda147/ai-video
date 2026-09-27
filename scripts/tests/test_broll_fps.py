#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from youtube_popular_downloader import (
    BROLL_MAX_SOURCE_SECONDS,
    VideoCandidate,
    filter_unwanted,
    is_sleep_ambiance,
    listed_fps_from_entry,
    pick_usable_fps_candidates,
    title_suggests_usable_fps,
)


def _candidate(
    video_id: str,
    title: str,
    *,
    fps: float | None = None,
    views: int = 1000,
    duration: float = 120,
) -> VideoCandidate:
    return VideoCandidate(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel="test",
        view_count=views,
        duration_seconds=duration,
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

    def test_sleep_and_eight_hour_sources_are_dropped(self) -> None:
        sleep = _candidate(
            "sleep",
            "(No Ads) Rainy Night in a Luxury NYC Apartment Bedroom Ambience for Sleep & Relax",
            fps=60.0,
            views=2_000_000,
            duration=8 * 3600,
        )
        piano = _candidate(
            "piano",
            "SINGAPORE 8K Video Ultra HD With Soft Piano Music - 60 FPS",
            fps=60.0,
            views=1_000_000,
            duration=3600,
        )
        good = _candidate(
            "good",
            "Dubai penthouse night city skyline 60fps",
            fps=60.0,
            views=80_000,
            duration=180,
        )
        self.assertTrue(is_sleep_ambiance(sleep))
        self.assertTrue(is_sleep_ambiance(piano))
        self.assertFalse(is_sleep_ambiance(good))
        kept = filter_unwanted(
            [sleep, piano, good],
            limit=8,
            exclude_music=True,
            exclude_trailers=True,
            exclude_live=True,
            background_gameplay_only=False,
            min_views=50_000,
            min_duration=30,
            max_duration=BROLL_MAX_SOURCE_SECONDS,
            exclude_sleep=True,
            quiet=True,
        )
        self.assertEqual([item.video_id for item in kept], ["good"])

    def test_vlog_and_channel_intro_are_dropped(self) -> None:
        intro = _candidate(
            "intro",
            "HBO: Space Intro Remastered | (60 Fps) HD - 1983",
            fps=60.0,
            views=2_000_000,
        )
        vlog = _candidate(
            "vlog",
            "day in a life vlog | realistic corporate life, working 9-5 office job",
            fps=60.0,
            views=500_000,
        )
        good = _candidate(
            "good",
            "gym workout cinematic 60fps",
            fps=60.0,
            views=80_000,
        )
        kept = filter_unwanted(
            [intro, vlog, good],
            limit=8,
            exclude_music=True,
            exclude_trailers=True,
            exclude_live=True,
            background_gameplay_only=False,
            min_views=50_000,
            min_duration=30,
            max_duration=BROLL_MAX_SOURCE_SECONDS,
            exclude_sleep=True,
            quiet=True,
        )
        self.assertEqual([item.video_id for item in kept], ["good"])

    def test_realestate_tours_skipped_when_view_only(self) -> None:
        tour = _candidate(
            "tour",
            "NYC Night Apartment Tour || Manhattan Studio High-Rise w/ Floor to Ceiling Windows",
            fps=60.0,
            views=500_000,
        )
        stock = _candidate(
            "view",
            "city skyline window view cinematic 60fps",
            fps=60.0,
            views=80_000,
        )
        kept = filter_unwanted(
            [tour, stock],
            limit=8,
            exclude_music=True,
            exclude_trailers=True,
            exclude_live=True,
            exclude_realestate_tours=True,
            background_gameplay_only=False,
            min_views=50_000,
            min_duration=30,
            max_duration=BROLL_MAX_SOURCE_SECONDS,
            exclude_sleep=True,
            quiet=True,
        )
        self.assertEqual([item.video_id for item in kept], ["view"])


if __name__ == "__main__":
    unittest.main()
