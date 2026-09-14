"""Tests for playable media and motivation job validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discovery.media_paths import (
    is_complete_motivation_job,
    is_playable_file,
    is_previewable_output,
    motivation_job_slug_from_rel,
)


class MediaPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_motivation_job_slug_from_output_path(self) -> None:
        rel = "downloads/motivational/combo-chris-1-2-20260101-120000/output/combo-chris-1-2-20260101-120000-motivation.mp4"
        self.assertEqual(motivation_job_slug_from_rel(rel), "combo-chris-1-2-20260101-120000")

    def test_motivation_job_slug_from_dated_output_path(self) -> None:
        rel = "downloads/motivational/2026-09-13/yacht-motivation/output/yacht-motivation-motivation.mp4"
        self.assertEqual(motivation_job_slug_from_rel(rel), "yacht-motivation")

    def test_incomplete_combo_job_is_not_previewable(self) -> None:
        slug = "combo-chris-4-1-20260910-204530"
        job_dir = self.root / "downloads" / "motivational" / slug
        out_dir = job_dir / "output"
        audio_dir = job_dir / "audio"
        out_dir.mkdir(parents=True)
        audio_dir.mkdir(parents=True)
        output = out_dir / f"{slug}-motivation.mp4"
        output.write_bytes(b"\x00" * 200_000)
        rel = output.relative_to(self.root).as_posix()
        self.assertFalse(is_complete_motivation_job(self.root, slug, output_path=output))
        self.assertFalse(is_previewable_output(self.root, rel))

    def test_complete_motivation_job_is_previewable(self) -> None:
        slug = "valid-motivation-job"
        job_dir = self.root / "downloads" / "motivational" / "2026-09-13" / slug
        clips_dir = job_dir / "clips"
        out_dir = job_dir / "output"
        audio_dir = job_dir / "audio"
        clips_dir.mkdir(parents=True)
        out_dir.mkdir(parents=True)
        audio_dir.mkdir(parents=True)
        (audio_dir / "speech.mp3").write_bytes(b"\x00" * 10_000)
        (clips_dir / "clip_part01.mp4").write_bytes(b"\x00" * 200_000)
        output = out_dir / f"{slug}-motivation.mp4"
        output.write_bytes(b"\x00" * 200_000)
        rel = output.relative_to(self.root).as_posix()
        self.assertTrue(is_complete_motivation_job(self.root, slug, output_path=output))
        self.assertTrue(is_previewable_output(self.root, rel))
        self.assertTrue(is_playable_file(output))


if __name__ == "__main__":
    unittest.main()
