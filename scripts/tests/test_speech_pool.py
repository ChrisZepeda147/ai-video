#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import speech_pool
from build_motivation_job import leftover_speech_windows


def _json3_words(words: list[tuple[float, str]]) -> dict:
    return {
        "events": [
            {
                "tStartMs": int(when * 1000),
                "segs": [{"utf8": text}],
            }
            for when, text in words
        ]
    }


class SpeechPoolTests(unittest.TestCase):
    def test_speaker_pool_slug(self) -> None:
        self.assertEqual(speech_pool.speaker_pool_slug("Andrew Tate"), "andrew-tate")

    def test_clamp_pooled_speech_honors_max_seconds(self) -> None:
        from build_motivation_job import clamp_pooled_speech_duration

        self.assertEqual(clamp_pooled_speech_duration(26.4, 22.0), 22.0)
        self.assertEqual(clamp_pooled_speech_duration(18.0, 22.0), 18.0)

    def test_youtube_id_from_url(self) -> None:
        self.assertEqual(
            speech_pool.youtube_id_from_url("https://www.youtube.com/watch?v=abcdefghijk"),
            "abcdefghijk",
        )

    def test_leftover_windows_split_after_used_minute(self) -> None:
        words: list[tuple[float, str]] = []
        for second in range(0, 200):
            text = "word." if second in {64, 129, 194} else "word"
            words.append((float(second), text))
        with tempfile.TemporaryDirectory() as tmp:
            captions = Path(tmp) / "subs.en.json3"
            captions.write_text(json.dumps(_json3_words(words)), encoding="utf-8")
            leftover = leftover_speech_windows(
                captions,
                used_start=0.0,
                used_duration=64.45,
                min_seconds=60.0,
                max_seconds=90.0,
                source_duration=200.0,
            )
        self.assertGreaterEqual(len(leftover), 1)
        self.assertGreaterEqual(leftover[0][0], 64.0)
        self.assertGreaterEqual(leftover[0][1], 60.0)
        self.assertLessEqual(leftover[0][1], 90.0)

    def test_speech_window_starts_and_ends_on_sentences(self) -> None:
        from build_motivation_job import _pick_window_from_words

        words = [
            (0.0, "Hello"),
            (0.4, "there."),
            (1.2, "You"),
            (1.5, "must"),
            (1.8, "work."),
            (22.0, "Keep"),
            (22.4, "going"),
            (22.8, "now."),
        ]
        picked = _pick_window_from_words(words, min_seconds=20, max_seconds=28, default_start=1.2)
        self.assertIsNotNone(picked)
        start, duration = picked
        self.assertAlmostEqual(start, 1.2, places=2)
        self.assertGreaterEqual(start + duration, 22.8)
        mid = _pick_window_from_words(words, min_seconds=20, max_seconds=28, default_start=1.5)
        self.assertIsNotNone(mid)
        self.assertAlmostEqual(mid[0], 1.2, places=2)

    def test_stash_and_take_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp) / "motivational"
            audio_a = jobs_root / "job-a" / "audio"
            audio_a.mkdir(parents=True)
            leftover_mp3 = audio_a / "stash.mp3"
            leftover_caps = audio_a / "stash.json3"
            leftover_mp3.write_bytes(b"audio")
            leftover_caps.write_text("{}", encoding="utf-8")
            dest = speech_pool.stash_excerpt(
                jobs_root,
                speaker="Andrew Tate",
                youtube_id="abcdefghijk",
                title="Demo speech",
                url="https://www.youtube.com/watch?v=abcdefghijk",
                start=70.0,
                duration=65.0,
                excerpt="this leftover minute is a new unused speech excerpt",
                audio=leftover_mp3,
                captions=leftover_caps,
            )
            self.assertIsNotNone(dest)
            self.assertFalse(leftover_mp3.exists())

            audio_b = jobs_root / "job-b" / "audio"
            taken = speech_pool.take_from_pool(
                jobs_root,
                speaker="Andrew Tate",
                audio_dir=audio_b,
            )
            self.assertIsNotNone(taken)
            assert taken is not None
            self.assertEqual(taken.start, 70.0)
            self.assertTrue((audio_b / "speech.mp3").is_file())
            self.assertTrue((audio_b / "subs.en.json3").is_file())
            self.assertFalse(speech_pool.list_pooled_excerpts(jobs_root, speaker="Andrew Tate"))


if __name__ == "__main__":
    unittest.main()
