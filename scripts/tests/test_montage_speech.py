#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from montage_speech import (
    PreparedSpeechRejected,
    excerpt_looks_incomplete,
    validate_prepared_speech_file,
)


class MontageSpeechTests(unittest.TestCase):
    def test_excerpt_complete_sentence_ok(self) -> None:
        self.assertFalse(
            excerpt_looks_incomplete("Discipline yourself before the world does it for you.")
        )

    def test_excerpt_ellipsis_incomplete(self) -> None:
        self.assertTrue(excerpt_looks_incomplete("You need to change your..."))

    def test_reject_too_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / "speech.mp3"
            mp3.write_bytes(b"x" * 2000)
            with patch("montage_speech.log_montage_speech_reject") as reject:
                with self.assertRaises(PreparedSpeechRejected):
                    validate_prepared_speech_file(
                        speech_mp3=mp3,
                        requested_speaker="Jordan Peterson",
                        source_video_id="abc123",
                        excerpt="A complete thought ends here.",
                        min_seconds=30.0,
                        probe_duration_fn=lambda _p: 18.4,
                    )
                reject.assert_called_once()
                self.assertEqual(reject.call_args.kwargs.get("reason"), "too_short")

    def test_ok_logs_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / "speech.mp3"
            mp3.write_bytes(b"x" * 2000)
            with patch("montage_speech.log_montage_speech_ok") as ok:
                dur = validate_prepared_speech_file(
                    speech_mp3=mp3,
                    requested_speaker="Jordan Peterson",
                    source_video_id="abc123",
                    excerpt="Stand up straight with your shoulders back.",
                    min_seconds=30.0,
                    probe_duration_fn=lambda _p: 42.6,
                )
                self.assertAlmostEqual(dur, 42.6)
                ok.assert_called_once()


if __name__ == "__main__":
    unittest.main()
