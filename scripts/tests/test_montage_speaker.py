#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_motivation_job as job
from montage_speaker import SpeechSpeakerMismatchError, enforce_requested_speaker
from youtube_popular_downloader import VideoCandidate


class MontageSpeakerTests(unittest.TestCase):
    def test_mismatch_fails_when_title_does_not_match(self) -> None:
        candidate = VideoCandidate(
            video_id="5THO8LEmANI",
            title="Joe Rogan: The Desire To Get Better!",
            url="https://youtu.be/x",
            channel="JRE",
            view_count=1,
            duration_seconds=3600.0,
            published_at=None,
            source="search",
        )
        with self.assertRaises(SpeechSpeakerMismatchError):
            enforce_requested_speaker(
                requested="Jordan Peterson",
                candidate=candidate,
                excerpt="",
                title_match_fn=job.speaker_matches,
            )

    def test_pooled_rogan_rejected_for_tate(self) -> None:
        self.assertFalse(
            job.speaker_matches(
                VideoCandidate(
                    video_id="x",
                    title="Joe Rogan motivation",
                    url="https://youtu.be/x",
                    channel="",
                    view_count=None,
                    duration_seconds=60.0,
                    published_at=None,
                    source="search",
                ),
                "Andrew Tate",
            )
        )


if __name__ == "__main__":
    unittest.main()
