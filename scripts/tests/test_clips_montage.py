#!/usr/bin/env python3
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_clips_montage as montage


class ClipsMontageTests(unittest.TestCase):
    def test_segment_length_scales_with_duration(self) -> None:
        self.assertAlmostEqual(montage.segment_length_for_duration(60.0), 12.0)
        self.assertAlmostEqual(montage.segment_length_for_duration(90.0), 18.0)
        self.assertAlmostEqual(montage.segment_length_for_duration(45.0), 9.0)

    def test_min_unique_clips_for_longer_video(self) -> None:
        short = montage.min_unique_clips_needed(
            duration=60.0,
            segment_length=12.0,
            layout="single",
        )
        long = montage.min_unique_clips_needed(
            duration=90.0,
            segment_length=18.0,
            layout="single",
        )
        self.assertEqual(short, 5)
        self.assertEqual(long, 5)

    def test_driven_23s_broll_pool_capped(self) -> None:
        needed = montage.broll_pool_files_required(
            target_duration=22.72,
            segment_length=8.0,
            layout="single",
            driven_pacing=True,
            subject="lamborghini huracan exterior 60fps",
        )
        self.assertGreaterEqual(needed, 3)
        self.assertLessEqual(needed, 12)

    def test_clip_picker_recycles_when_exhausted(self) -> None:
        clips = [
            Path("aaa_part01.mp4"),
            Path("aaa_part02.mp4"),
            Path("bbb_part01.mp4"),
        ]
        picker = montage._ClipPicker(clips, random.Random(0))
        picked = [picker.pick() for _ in range(len(clips))]
        self.assertEqual(len(picked), len(clips))
        self.assertEqual(len(set(picked)), len(clips))
        again = picker.pick()
        self.assertIn(again, clips)

    def test_clip_picker_consume_and_unused(self) -> None:
        clips = [
            Path("aaa_part01.mp4"),
            Path("bbb_part01.mp4"),
            Path("ccc_part01.mp4"),
        ]
        picker = montage._ClipPicker(clips, random.Random(0))
        first = clips[0]
        picker.consume(first)
        leftover = picker.unused_clips()
        self.assertNotIn(first, leftover)
        self.assertEqual(len(leftover), 2)

    def test_accepts_any_readable_fps(self) -> None:
        self.assertFalse(montage.is_usable_fps(0.0))
        self.assertTrue(montage.is_usable_fps(23.976))
        self.assertTrue(montage.is_usable_fps(24.0))
        self.assertTrue(montage.is_usable_fps(25.0))
        self.assertTrue(montage.is_usable_fps(29.97))
        self.assertTrue(montage.is_usable_fps(30.0))
        self.assertTrue(montage.is_usable_fps(48.0))
        self.assertTrue(montage.is_usable_fps(50.0))
        self.assertTrue(montage.is_usable_fps(59.94))
        self.assertTrue(montage.is_usable_fps(60.0))


if __name__ == "__main__":
    unittest.main()
