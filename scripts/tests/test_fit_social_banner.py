#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fit_social_banner as banner


def _scene(width: int = 1280, height: int = 720) -> Image.Image:
    image = Image.new("RGB", (width, height), (8, 8, 12))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 220, 620, 500), fill=(240, 160, 190))
    draw.rectangle((8, 210, 50, 280), fill=(18, 16, 18))
    draw.rectangle((40, 510, 620, 680), fill=(70, 40, 50))
    for x in range(980, 1200, 18):
        draw.ellipse((x, 340, x + 3, 343), fill=(180, 170, 120))
    return image


class FitSocialBannerTests(unittest.TestCase):
    def test_facebook_preset_is_retina_cover(self) -> None:
        preset = banner.PRESETS["facebook-cover"]
        self.assertEqual((preset.width, preset.height), (1640, 624))
        self.assertEqual(preset.safe_left, 266)
        self.assertEqual(preset.safe_right, 1374)

    def test_youtube_preset_uses_official_safe_zone(self) -> None:
        preset = banner.PRESETS["youtube-banner"]
        self.assertEqual((preset.width, preset.height), (2560, 1440))
        self.assertEqual(preset.safe_width, 1546)
        self.assertEqual(preset.safe_height, 423)
        self.assertEqual(preset.safe_left, 507)
        self.assertEqual(preset.safe_top, 509)
        self.assertEqual(preset.default_fit, "safe")

    def test_cover_fills_banner_with_no_side_bars(self) -> None:
        preset = banner.PRESETS["facebook-cover"]
        fitted, _, _ = banner.fit_social_banner(_scene(), preset=preset, mode="cover")
        self.assertEqual(fitted.size, (1640, 624))
        self.assertNotEqual(fitted.getpixel((2, 320)), (0, 0, 0))
        self.assertNotEqual(fitted.getpixel((1637, 320)), (0, 0, 0))

    def test_subject_safe_keeps_full_car_in_mobile_crop(self) -> None:
        preset = banner.PRESETS["facebook-cover"]
        fitted, subject, _ = banner.fit_social_banner(
            _scene(),
            preset=preset,
            subject_safe=True,
        )
        self.assertEqual(fitted.size, (1640, 624))
        self.assertIsNotNone(subject)
        assert subject is not None
        self.assertGreaterEqual(subject.left, preset.safe_left)
        self.assertLessEqual(subject.right, preset.safe_right)
        sample = fitted.getpixel((subject.left + subject.width // 2, subject.top + subject.height // 3))
        self.assertGreater(sample[0], 150)

    def test_youtube_safe_keeps_car_in_all_device_strip(self) -> None:
        preset = banner.PRESETS["youtube-banner"]
        fitted, subject, _ = banner.fit_social_banner(_scene(), preset=preset, mode="safe")
        self.assertEqual(fitted.size, (2560, 1440))
        self.assertIsNotNone(subject)
        assert subject is not None
        self.assertGreaterEqual(subject.left, preset.safe_left)
        self.assertLessEqual(subject.right, preset.safe_right)
        self.assertGreaterEqual(subject.top, preset.safe_top)
        self.assertLessEqual(subject.bottom, preset.safe_bottom)
        sample = fitted.getpixel((subject.left + subject.width // 2, subject.top + subject.height // 3))
        self.assertGreater(sample[0], 150)

    def test_detect_subject_includes_wing_pad(self) -> None:
        box = banner.detect_subject_box(_scene())
        self.assertIsNotNone(box)
        assert box is not None
        self.assertLessEqual(box.left, 24)
        self.assertGreater(box.right, 600)

    def test_extra_left_math_parks_subject(self) -> None:
        extra = banner.extra_left_for_safe_zone(
            src_w=1280,
            subject_left=90,
            out_w=1640,
            safe_left=266,
            padding=40,
        )
        scale = 1640 / (1280 + extra)
        self.assertGreaterEqual((90 + extra) * scale, 306)

    def test_contain_can_pad(self) -> None:
        preset = banner.PRESETS["facebook-cover"]
        fitted, _, _ = banner.fit_social_banner(
            _scene(800, 800),
            preset=preset,
            mode="contain",
            fill=(0, 0, 0),
        )
        self.assertEqual(fitted.size, (1640, 624))
        self.assertEqual(fitted.getpixel((2, 312)), (0, 0, 0))

    def test_cli_writes_youtube_previews(self) -> None:
        folder = Path(__file__).resolve().parent / "_tmp_banner"
        folder.mkdir(exist_ok=True)
        source = folder / "in.jpg"
        output = folder / "out.jpg"
        preview = folder / "preview.jpg"
        sizes = folder / "sizes.jpg"
        _scene().save(source, format="JPEG", quality=90)
        try:
            banner.main(
                [
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--preset",
                    "youtube-banner",
                    "--preview",
                    str(preview),
                    "--sizes-preview",
                    str(sizes),
                ]
            )
            self.assertTrue(output.is_file())
            self.assertTrue(preview.is_file())
            self.assertTrue(sizes.is_file())
            with Image.open(output) as written:
                self.assertEqual(written.size, (2560, 1440))
        finally:
            for path in (source, output, preview, sizes):
                if path.exists():
                    path.unlink()
            if folder.exists():
                folder.rmdir()


if __name__ == "__main__":
    unittest.main()
