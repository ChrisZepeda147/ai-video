#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_clips_montage as montage
import build_motivation_job as job
from broll_candidate_rank import rank_broll_candidates, scenic_duration_score, section_start_fractions
from broll_pool import subjects_match
from broll_search_cache import get_cached_candidates, store_cached_candidates
from montage_timing import montage_timer
from youtube_popular_downloader import VideoCandidate, broll_format_selector, download_broll_source_parts


class BrollSpeedTests(unittest.TestCase):
    def test_short_montages_require_at_most_eight_files(self) -> None:
        subject = "autumn lake surrounded by mountains cinematic 60fps"
        for duration in (60.0, 76.0, 90.0):
            needed = montage.broll_pool_files_required(
                target_duration=duration,
                segment_length=montage.segment_length_for_duration(duration),
                layout="single",
                driven_pacing=True,
                subject=subject,
            )
            self.assertLessEqual(needed, 8, msg=f"{duration}s")
            self.assertGreaterEqual(needed, 3)

    def test_long_relaxation_ranks_below_normal_scenic(self) -> None:
        short = VideoCandidate(
            video_id="a",
            title="Autumn mountain lake 4K scenic",
            url="https://youtu.be/a",
            channel="nature",
            view_count=100_000,
            duration_seconds=600.0,
            published_at=None,
            source="search",
            fps=60.0,
        )
        long_relax = VideoCandidate(
            video_id="b",
            title="10 hour autumn lake relaxation for sleep",
            url="https://youtu.be/b",
            channel="ambient",
            view_count=5_000_000,
            duration_seconds=36_000.0,
            published_at=None,
            source="search",
            fps=60.0,
        )
        ranked = rank_broll_candidates([long_relax, short])
        self.assertEqual(ranked[0].video_id, "a")
        self.assertGreater(scenic_duration_score(short.duration_seconds), scenic_duration_score(long_relax.duration_seconds))

    def test_search_cache_hit_avoids_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp)
            store_cached_candidates(
                jobs_root,
                query="autumn mountain lake",
                min_views=0,
                min_duration=0,
                candidates=[
                    {
                        "video_id": "cached1",
                        "title": "Lake",
                        "url": "https://youtu.be/cached1",
                        "channel": "x",
                        "view_count": 1,
                        "duration_seconds": 600.0,
                        "published_at": None,
                        "source": "search",
                        "fps": 60.0,
                    }
                ],
            )
            with patch.object(job, "_discover_broll_candidates_for_search") as discover:
                out = job._discover_candidates_for_query(
                    "autumn mountain lake",
                    limit=5,
                    subject="lake",
                    min_views=0,
                    min_duration=0,
                    reuse_policy="allow",
                    exclude_source_ids=set(),
                    jobs_root=jobs_root,
                )
                discover.assert_not_called()
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0].video_id, "cached1")

    def test_failed_ids_override_cached_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp)
            store_cached_candidates(
                jobs_root,
                query="forest",
                min_views=0,
                min_duration=0,
                candidates=[
                    {
                        "video_id": "bad",
                        "title": "Forest",
                        "url": "https://youtu.be/bad",
                        "channel": "x",
                        "view_count": 1,
                        "duration_seconds": 600.0,
                        "published_at": None,
                        "source": "search",
                        "fps": 60.0,
                    }
                ],
            )
            out = job._discover_candidates_for_query(
                "forest",
                limit=5,
                subject="forest",
                min_views=0,
                min_duration=0,
                reuse_policy="allow",
                exclude_source_ids={"bad"},
                jobs_root=jobs_root,
            )
            self.assertEqual(out, [])

    def test_second_cache_read_avoids_network_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp)
            store_cached_candidates(
                jobs_root,
                query="sunset ocean",
                min_views=0,
                min_duration=0,
                candidates=[
                    {
                        "video_id": "c1",
                        "title": "Ocean sunset",
                        "url": "https://youtu.be/c1",
                        "channel": "x",
                        "view_count": 1,
                        "duration_seconds": 480.0,
                        "published_at": None,
                        "source": "search",
                        "fps": 60.0,
                    }
                ],
            )
            self.assertIsNotNone(
                get_cached_candidates(
                    jobs_root,
                    query="sunset ocean",
                    min_views=0,
                    min_duration=0,
                )
            )
            with patch.object(job, "_discover_broll_candidates_for_search") as discover:
                job._discover_candidates_for_query(
                    "sunset ocean",
                    limit=5,
                    subject="ocean",
                    min_views=0,
                    min_duration=0,
                    reuse_policy="allow",
                    exclude_source_ids=set(),
                    jobs_root=jobs_root,
                )
                discover.assert_not_called()

    def test_format_prefers_1440_then_1080_before_4k(self) -> None:
        sel = broll_format_selector()
        self.assertIn("height<=1440", sel)
        self.assertIn("height<=1080", sel)
        self.assertIn("height<=2160", sel)
        self.assertLess(sel.index("height<=1440"), sel.index("height<=2160"))

    def test_partial_section_failure_falls_back(self) -> None:
        candidate = VideoCandidate(
            video_id="z",
            title="Long lake",
            url="https://youtu.be/z",
            channel="c",
            view_count=1,
            duration_seconds=3600.0,
            published_at=None,
            source="search",
            fps=60.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch(
                "youtube_popular_downloader._download_broll_section_to_part",
                return_value=None,
            ), patch(
                "youtube_popular_downloader.download_videos",
                return_value=[{"status": "ok", "video_id": "z", "parts": []}],
            ) as full_dl:
                record = download_broll_source_parts(
                    candidate,
                    output_dir=out_dir,
                    clip_length=24,
                    parts_needed=2,
                )
                full_dl.assert_called_once()
                self.assertIn(record.get("download_mode"), {"full_fallback", "full"})

    def test_timing_total_matches_top_level_sum(self) -> None:
        montage_timer().reset(slug="timing-test")
        with montage_timer().stage_top("prepare_speech"):
            time.sleep(0.05)
        with montage_timer().stage_top("ensure_broll"):
            with montage_timer().stage_child("pool_lookup"):
                time.sleep(0.02)
        with montage_timer().stage_top("render"):
            time.sleep(0.03)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            montage_timer().emit()
        text = buf.getvalue()
        self.assertIn("slug=timing-test", text)
        self.assertIn("MONTAGE_TIMING_TOTAL", text)
        self.assertIn("MONTAGE_TIMING_TOP_LEVEL_SUM", text)
        wall = float(text.split("wall_seconds=")[1].split()[0])
        top = float(text.split("MONTAGE_TIMING_TOP_LEVEL_SUM")[1].split("seconds=")[1].split()[0])
        self.assertLess(abs(wall - top), 0.25)

    def test_scenic_subject_pool_matching(self) -> None:
        self.assertTrue(
            subjects_match(
                "autumn lake surrounded by mountains",
                ["mountain", "lake", "autumn"],
            )
        )

    def test_section_fractions_spaced(self) -> None:
        fr = section_start_fractions(3)
        self.assertEqual(fr, [0.15, 0.5, 0.8])

    def test_download_requests_missing_plus_margin(self) -> None:
        clips_dir = Path(tempfile.mkdtemp())
        try:
            candidate = VideoCandidate(
                video_id="freshdl",
                title="Lake",
                url="https://youtu.be/freshdl",
                channel="c",
                view_count=1,
                duration_seconds=900.0,
                published_at=None,
                source="search",
                fps=60.0,
            )
            with patch(
                "build_motivation_job.download_broll_source_parts",
            ) as dl_parts, patch(
                "build_motivation_job.filter_broll_clip_list",
                return_value=[clips_dir / "freshdl_part01.mp4"],
            ):
                dl_parts.return_value = {"status": "ok", "video_id": "freshdl"}
                job.download_broll_candidates(
                    clips_dir,
                    [candidate],
                    clip_length=24,
                    max_parts=3,
                    parts_needed=2,
                    frame_gate=False,
                    raise_if_empty=False,
                )
                dl_parts.assert_called_once()
                kwargs = dl_parts.call_args.kwargs
                self.assertEqual(kwargs.get("parts_needed"), 2)
        finally:
            for p in clips_dir.glob("*"):
                p.unlink(missing_ok=True)
            clips_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
