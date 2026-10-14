"""Tests for speech_acquire validation helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from speech_acquire import (
    SpeechAcquireStats,
    speech_search_queries,
    speech_search_query_ladder,
    validate_downloaded_audio,
)


class TestSpeechAcquire(unittest.TestCase):
    def test_rejects_tiny_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abc123_test.mp3"
            path.write_bytes(b"x" * 100)

            def probe(_p: Path) -> float:
                return 45.0

            result = validate_downloaded_audio(path, min_seconds=30.0, probe_duration_fn=probe)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "incomplete_download")

    def test_accepts_valid_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abc123_test.mp3"
            path.write_bytes(b"x" * 200_000)

            def probe(_p: Path) -> float:
                return 42.0

            result = validate_downloaded_audio(path, min_seconds=30.0, probe_duration_fn=probe)
            self.assertTrue(result.ok)
            self.assertAlmostEqual(result.duration, 42.0)

    def test_speech_ladder_rotates_on_attempt_offset(self) -> None:
        ladder = speech_search_query_ladder("David Goggins", "")
        self.assertGreaterEqual(len(ladder), 3)
        q0, f0 = speech_search_queries("David Goggins", "", attempt_offset=0)
        q1, f1 = speech_search_queries("David Goggins", "", attempt_offset=1)
        self.assertNotEqual(q0, q1)

    def test_failure_details_aggregate(self) -> None:
        stats = SpeechAcquireStats(speaker="Jocko")
        stats.candidates_attempted = 3
        stats.audio_too_short = 2
        stats.subtitle_429 = 1
        details = stats.failure_details()
        self.assertEqual(details["speaker"], "Jocko")
        self.assertEqual(details["too_short"], 2)
        self.assertEqual(details["subtitle_429"], 1)


if __name__ == "__main__":
    unittest.main()
