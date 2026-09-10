"""Motivation job reuse policy behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_motivation_job as job  # noqa: E402
from youtube_popular_downloader import VideoCandidate  # noqa: E402


def _candidate(video_id: str) -> VideoCandidate:
    return VideoCandidate(
        video_id=video_id,
        title=f"Speech {video_id}",
        channel="Andrew Tate",
        url=f"https://www.youtube.com/watch?v={video_id}",
        view_count=100_000,
        duration_seconds=600,
        published_at=None,
        source="search",
    )


class MotivationReuseTests(unittest.TestCase):
    @patch.object(job, "discover_search")
    @patch.object(job, "used_ids", return_value={"used123"})
    def test_allow_includes_used_source(self, _used, discover) -> None:
        discover.return_value = [_candidate("used123"), _candidate("fresh456")]
        results = job.search_speeches(
            query="Andrew Tate motivational speech",
            speaker="Andrew Tate",
            limit=8,
            reuse_policy="allow",
        )
        ids = [item.video_id for item in results]
        self.assertIn("used123", ids)

    @patch.object(job, "discover_search")
    @patch.object(job, "used_ids", return_value={"used123"})
    def test_require_new_excludes_used_source(self, _used, discover) -> None:
        discover.return_value = [_candidate("used123"), _candidate("fresh456")]
        results = job.search_speeches(
            query="Andrew Tate motivational speech",
            speaker="Andrew Tate",
            limit=8,
            reuse_policy="require_new",
        )
        ids = [item.video_id for item in results]
        self.assertNotIn("used123", ids)
        self.assertIn("fresh456", ids)

    @patch.object(job, "check_toolchain", return_value={"ffmpeg": {"found": False}, "ffprobe": {"found": False}})
    def test_prepare_speech_fails_fast_on_missing_ffmpeg(self, _check) -> None:
        with self.assertRaises(job.MotivationJobError) as ctx:
            job.prepare_speech(
                audio_dir=Path("."),
                url_file=Path("url.txt"),
                speaker="Andrew Tate",
                speech_query="Andrew Tate motivational speech",
                speech_url="",
                min_seconds=60,
                max_seconds=90,
                reuse_policy="allow",
            )
        self.assertEqual(ctx.exception.code, "FFMPEG_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
