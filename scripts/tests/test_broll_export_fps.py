#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from youtube_popular_downloader import VideoCandidate, export_clip


class BrollExportFpsTests(unittest.TestCase):
    def test_export_clip_preserves_usable_source_fps(self) -> None:
        src = Path("source.mp4")
        out = Path("out.mp4")
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return None

        with patch("youtube_popular_downloader.probe_fps", return_value=60.0):
            with patch("youtube_popular_downloader.subprocess.run", side_effect=fake_run):
                export_clip(
                    src,
                    out,
                    start=0.0,
                    duration=12.0,
                    aspect_ratio="9:16",
                    max_height=1080,
                )
        self.assertEqual(len(captured), 1)
        cmd = captured[0]
        self.assertIn("-r", cmd)
        idx = cmd.index("-r")
        self.assertTrue(float(cmd[idx + 1]) >= 50.0)


class BrollSectionPreferTests(unittest.TestCase):
    def test_short_source_prefers_sections_when_material_fraction_small(self) -> None:
        from broll_candidate_rank import should_prefer_section_download

        self.assertTrue(
            should_prefer_section_download(
                source_duration=139.0,
                clip_length=24,
                parts_needed=3,
            )
        )
        self.assertFalse(
            should_prefer_section_download(
                source_duration=40.0,
                clip_length=24,
                parts_needed=1,
            )
        )


class BrollRelevanceFilterTests(unittest.TestCase):
    def test_roller_coaster_low_relevance_for_scenic_query(self) -> None:
        from broll_relevance import is_low_relevance

        cand = VideoCandidate(
            video_id="rc",
            title="Front Seat POV Roller Coaster Ride 4K 60fps",
            url="https://www.youtube.com/watch?v=rc",
            channel="ThemePark",
            view_count=100_000,
            duration_seconds=600,
            published_at=None,
            source="test",
            fps=60.0,
        )
        self.assertTrue(
            is_low_relevance(
                query="cedar fog valley lake dawn cinematic 60fps",
                subject="cedar fog valley lake dawn cinematic 60fps",
                candidate=cand,
            )
        )

    def test_hard_reject_long_ambient(self) -> None:
        from broll_candidate_filter import hard_reject_reason

        cand = VideoCandidate(
            video_id="sleep",
            title="10 Hour Rain and Thunder Sleep Video",
            url="https://www.youtube.com/watch?v=sleep",
            channel="Relax",
            view_count=1_000_000,
            duration_seconds=10 * 3600,
            published_at=None,
            source="test",
            fps=60.0,
        )
        reason = hard_reject_reason(
            cand,
            query="foggy mountain lake",
            subject="foggy mountain lake",
            format_ok=True,
        )
        self.assertEqual(reason, "duration_too_long")


if __name__ == "__main__":
    unittest.main()
