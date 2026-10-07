#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broll_source_subprocess import run_broll_source_subprocess
from youtube_popular_downloader import VideoCandidate


def _candidate() -> VideoCandidate:
    return VideoCandidate(
        video_id="abc123",
        title="Mountain lake 60fps",
        url="https://www.youtube.com/watch?v=abc123",
        channel="Nature",
        view_count=50_000,
        duration_seconds=300,
        published_at=None,
        source="test",
        fps=60.0,
    )


class BrollSubprocessTimeoutTests(unittest.TestCase):
    def test_timeout_kills_tree_and_cleans_workspace(self) -> None:
        job_dir = Path("/tmp/job")
        proc = MagicMock()
        proc.poll.side_effect = [None, None, 1]
        proc.pid = 4242
        proc.stdout = iter([])

        with patch("broll_source_subprocess.subprocess.Popen", return_value=proc):
            with patch("broll_source_subprocess.kill_process_tree") as kill:
                with patch("broll_source_subprocess.cleanup_workspace") as cleanup:
                    with patch("broll_source_subprocess.time.perf_counter") as perf:
                        perf.side_effect = [0.0, 0.0, 200.0]
                        result = run_broll_source_subprocess(
                            job_dir=job_dir,
                            candidate=_candidate(),
                            clip_length=24,
                            parts_needed=2,
                            start_offset=0.0,
                            split_full_source=False,
                            subject="lake",
                            use_vision=False,
                            frame_gate=False,
                            jobs_root=None,
                            preflight={"fps": 60, "height": 1080},
                            timeout_sec=105.0,
                        )
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("timeout"))
        kill.assert_called_with(4242)
        cleanup.assert_called()


if __name__ == "__main__":
    unittest.main()
