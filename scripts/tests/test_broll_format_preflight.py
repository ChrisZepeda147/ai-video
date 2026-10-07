#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broll_format_preflight import inspect_usable_formats


class BrollFormatPreflightTests(unittest.TestCase):
    def test_skips_when_no_50fps_format(self) -> None:
        fake_info = {
            "formats": [
                {"vcodec": "avc1", "height": 4320, "fps": 30.0},
                {"vcodec": "avc1", "height": 1080, "fps": 24.0},
            ]
        }
        fake_ydl = unittest.mock.MagicMock()
        fake_ydl.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = (
            fake_info
        )
        with patch("broll_format_preflight.yt_dlp", fake_ydl):
            ok, reason, _meta = inspect_usable_formats("https://youtu.be/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "no_50fps_format")

    def test_accepts_1440_60(self) -> None:
        fake_info = {
            "formats": [
                {"vcodec": "avc1", "height": 1440, "fps": 60.0, "format_id": "248"},
            ]
        }
        fake_ydl = unittest.mock.MagicMock()
        fake_ydl.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = (
            fake_info
        )
        with patch("broll_format_preflight.yt_dlp", fake_ydl):
            ok, reason, meta = inspect_usable_formats("https://youtu.be/x")
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(meta.get("height"), 1440)


if __name__ == "__main__":
    unittest.main()
