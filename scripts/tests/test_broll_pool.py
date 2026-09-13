#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import broll_pool


class BrollPoolTests(unittest.TestCase):
    def test_subject_pool_slug_uses_primary_tokens(self) -> None:
        slug = broll_pool.subject_pool_slug("Porsche sports car cinematic 4k short")
        self.assertTrue(slug.startswith("porsche"))

    def test_subjects_match_on_shared_primary_token(self) -> None:
        left = "Porsche sports car cinematic 4k short"
        right = ["porsche", "gt3rs", "cinematic"]
        self.assertTrue(broll_pool.subjects_match(left, right))

    def test_named_models_do_not_share_brand_pool(self) -> None:
        query = "Ferrari 488 Pista night city cinematic 4k driving"
        self.assertTrue(broll_pool.subjects_match(query, ["ferrari", "488", "pista"]))
        self.assertFalse(broll_pool.subjects_match(query, ["ferrari", "sf90", "stradale"]))
        self.assertFalse(broll_pool.subjects_match(query, ["ferrari", "roma", "coastal"]))

    def test_stash_and_take_roundtrip(self) -> None:
        root = Path(self.id().split(".")[-1])
        shutil_rmtree = __import__("shutil").rmtree
        shutil_rmtree(root, ignore_errors=True)
        jobs_root = root / "motivational"
        clips_dir = jobs_root / "job-a" / "clips"
        clips_dir.mkdir(parents=True)
        used = clips_dir / "aaa_part01.mp4"
        unused = clips_dir / "bbb_part01.mp4"
        used.write_bytes(b"used")
        unused.write_bytes(b"unused")
        subject = "Porsche sports car cinematic 4k short"

        with patch("broll_pool._clip_fps", return_value=30.0):
            stashed = broll_pool.stash_unused_clips(
                jobs_root,
                subject=subject,
                clips_dir=clips_dir,
                used={used},
            )
            self.assertEqual(len(stashed), 1)
            self.assertFalse(unused.exists())
            self.assertTrue(used.exists())

            next_job = jobs_root / "job-b" / "clips"
            taken = broll_pool.take_from_pool(
                jobs_root,
                subject=subject,
                clips_dir=next_job,
            )
        self.assertEqual(len(taken), 1)
        self.assertTrue(taken[0].name == "bbb_part01.mp4")
        self.assertFalse(
            broll_pool.list_pool_clips(broll_pool.pool_dir_for_subject(jobs_root, subject))
        )

        shutil_rmtree = __import__("shutil").rmtree
        shutil_rmtree(root, ignore_errors=True)

    def test_take_from_pool_deletes_low_fps(self) -> None:
        root = Path("broll-pool-low-fps")
        jobs_root = root / "motivational"
        subject = "Porsche sports car cinematic 4k short"
        pool_dir = broll_pool.pool_dir_for_subject(jobs_root, subject)
        broll_pool._write_pool_meta(pool_dir, subject=subject)
        low = pool_dir / "low24_part01.mp4"
        high = pool_dir / "high60_part01.mp4"
        low.write_bytes(b"low")
        high.write_bytes(b"high")
        clips_dir = jobs_root / "job" / "clips"

        def fake_fps(path: Path) -> float:
            return 24.0 if "low24" in path.name else 60.0

        with patch("broll_pool._clip_fps", side_effect=fake_fps):
            taken = broll_pool.take_from_pool(
                jobs_root,
                subject=subject,
                clips_dir=clips_dir,
            )
        self.assertEqual([item.name for item in taken], ["high60_part01.mp4"])
        self.assertFalse(low.exists())
        shutil_rmtree = __import__("shutil").rmtree
        shutil_rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
