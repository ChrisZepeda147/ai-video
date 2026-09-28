"""Reuse policy + toolchain helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery.reuse_policy import parse_reuse_policy
from toolchain_env import classify_download_error, check_toolchain


class ReusePolicyTests(unittest.TestCase):
    def test_default_allow(self) -> None:
        self.assertEqual(parse_reuse_policy("Make an Andrew Tate motivational video."), "allow")

    def test_require_new_phrases(self) -> None:
        self.assertEqual(parse_reuse_policy("Find something we have never used before."), "require_new")
        self.assertEqual(parse_reuse_policy("Use an unused clip from Tate."), "require_new")

    def test_prefer_new_phrases(self) -> None:
        self.assertEqual(parse_reuse_policy("Prefer new B-roll but same speaker."), "prefer_new")

    def test_make_short_boilerplate_stays_allow(self) -> None:
        text = (
            "Check combinations catalog — do not reuse the same excerpt unless instructions allow.\n"
            "Use `--reuse-policy require_new` when instructions say do not reuse.\n"
            "Visual / B-roll search: sunrise city skyline 60fps"
        )
        self.assertEqual(parse_reuse_policy(text), "allow")

    def test_weekly_montage_brief_stays_allow(self) -> None:
        from discovery.motivation_command_brief import compose_from_slot

        cmd = compose_from_slot(
            {
                "day": "mon",
                "slot": 1,
                "speaker": "Goggins",
                "visual_direction": "Sunrise mountain summit",
                "week_start": "2026-09-28",
                "owner": "chris",
            }
        )
        self.assertEqual(parse_reuse_policy(cmd), "allow")


class ToolchainTests(unittest.TestCase):
    def test_classify_ffmpeg_missing(self) -> None:
        err = "ERROR: Postprocessing: ffprobe and ffmpeg not found."
        self.assertEqual(classify_download_error(err), "FFMPEG_NOT_FOUND")

    def test_check_toolchain_shape(self) -> None:
        report = check_toolchain()
        self.assertIn("ffmpeg", report)
        self.assertIn("ffprobe", report)
        self.assertIn("yt-dlp", report)

    def test_ffmpeg_dir_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ffmpeg.exe").write_text("", encoding="utf-8")
            (root / "ffprobe.exe").write_text("", encoding="utf-8")
            with patch.dict(os.environ, {"FFMPEG_DIR": str(root)}, clear=False):
                from toolchain_env import ffmpeg_location

                self.assertEqual(ffmpeg_location(), str(root))


if __name__ == "__main__":
    unittest.main()
