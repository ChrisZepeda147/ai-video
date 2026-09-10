#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

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

    def test_stash_and_take_roundtrip(self) -> None:
        root = Path(self.id().split(".")[-1])
        jobs_root = root / "motivational"
        clips_dir = jobs_root / "job-a" / "clips"
        clips_dir.mkdir(parents=True)
        used = clips_dir / "aaa_part01.mp4"
        unused = clips_dir / "bbb_part01.mp4"
        used.write_bytes(b"used")
        unused.write_bytes(b"unused")
        subject = "Porsche sports car cinematic 4k short"

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


if __name__ == "__main__":
    unittest.main()
