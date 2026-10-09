#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import broll_frame_gate
import build_motivation_job
from build_stills_slideshow import _ass_header, normalize_caption_align


def _save_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _top_title_bar(*, label: str = "AUTUMN") -> bytes:
    img = Image.new("RGB", (320, 560), (18, 22, 28))
    draw = ImageDraw.Draw(img)
    draw.rectangle((24, 12, 296, 86), fill=(245, 245, 245))
    draw.rectangle((36, 28, 284, 70), fill=(12, 12, 16))
    try:
        font = ImageFont.load_default()
        draw.text((48, 36), label, fill=(255, 255, 255), font=font)
    except OSError:
        draw.text((48, 36), label, fill=(255, 255, 255))
    for y in range(120, 520):
        for x in range(0, 320, 4):
            img.putpixel((x, y), (30 + (x % 40), 45 + (y % 30), 38))
    return _save_png(img)


def _bottom_branding_bar() -> bytes:
    img = Image.new("RGB", (320, 560), (22, 26, 32))
    for y in range(40, 480):
        for x in range(0, 320, 5):
            img.putpixel((x, y), (50 + (x % 35), 60 + (y % 25), 55))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 488, 320, 552), fill=(250, 250, 250))
    draw.text((90, 508), "4K STOCK CHANNEL", fill=(0, 0, 0))
    return _save_png(img)


def _bright_sky_scene() -> bytes:
    img = Image.new("RGB", (320, 560), (90, 100, 110))
    for y in range(0, int(560 * 0.35)):
        for x in range(320):
            img.putpixel((x, y), (228, 232, 238))
    for y in range(int(560 * 0.35), 560):
        for x in range(0, 320, 3):
            img.putpixel((x, y), (35 + (x % 20), 48 + (y % 18), 42))
    return _save_png(img)


def _city_lights_scene() -> bytes:
    night = Image.new("RGB", (320, 560), (8, 10, 18))
    for x in range(12, 308, 7):
        for y in range(80, 480, 11):
            night.putpixel((x, y), (210, 180, 90))
            if x + 1 < 320:
                night.putpixel((x + 1, y), (160, 140, 70))
    return _save_png(night)


class SourceTextOverlayTests(unittest.TestCase):
    def test_top_title_detected_on_scenic_subject(self) -> None:
        png = _top_title_bar()
        regions = broll_frame_gate.source_text_overlay_regions(png)
        self.assertIn("top", regions)
        reasons = broll_frame_gate.frame_fail_reasons(
            png, subject="Desert mountains at sunset"
        )
        self.assertIn("source-text-top", reasons)

    def test_bottom_branding_detected(self) -> None:
        png = _bottom_branding_bar()
        regions = broll_frame_gate.source_text_overlay_regions(png)
        self.assertIn("bottom", regions)

    def test_bright_sky_not_rejected(self) -> None:
        png = _bright_sky_scene()
        regions = broll_frame_gate.source_text_overlay_regions(png)
        self.assertEqual(regions, [])
        reasons = broll_frame_gate.frame_fail_reasons(
            png, subject="mountain sunrise cinematic"
        )
        self.assertNotIn("source-text-top", reasons)

    def test_city_lights_not_false_positive(self) -> None:
        png = _city_lights_scene()
        subject = "high rise apartment view"
        self.assertNotIn("source-text-top", broll_frame_gate.source_text_overlay_regions(png))
        self.assertNotIn(
            "source-text-top",
            broll_frame_gate.frame_fail_reasons(png, subject=subject),
        )

    def test_large_crop_rejected(self) -> None:
        png = _top_title_bar(label="AUTUMN FALL COLLECTION 4K")
        est = broll_frame_gate.estimate_source_text_crop_percent(png, "top")
        self.assertTrue(est is None or est <= broll_frame_gate.MAX_SOURCE_TEXT_CROP)

    def test_safe_small_crop_within_limit(self) -> None:
        png = _top_title_bar(label="AUTUMN")
        est = broll_frame_gate.estimate_source_text_crop_percent(png, "top")
        self.assertIsNotNone(est)
        self.assertLessEqual(est or 0.0, broll_frame_gate.MAX_SOURCE_TEXT_CROP)
        self.assertGreater(est or 0.0, 0.0)

    def test_one_rejected_clip_does_not_drop_clean_clip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp) / "motivational"
            jobs_root.mkdir(parents=True)
            good = jobs_root / "clean_part01.mp4"
            bad = jobs_root / "dirty_part01.mp4"
            good.write_bytes(b"\x00")
            bad.write_bytes(b"\x00")
            top_png = _top_title_bar()
            clean_png = _bright_sky_scene()

            def fake_probe(_path: Path) -> float:
                return 12.0

            def fake_scan(_clip, *, duration, subject=""):
                return [{"t": 0.0, "ok": True, "reasons": []}]

            with patch("build_motivation_job.probe_duration", side_effect=fake_probe), patch(
                "build_motivation_job.scan_clip_local", side_effect=fake_scan
            ), patch(
                "build_motivation_job.longest_clean_span", return_value=(0.0, 10.0)
            ), patch("build_motivation_job._trim_clip_to_span"), patch(
                "build_motivation_job.lookup_gate_result", return_value=None
            ), patch(
                "build_motivation_job.store_gate_result"
            ), patch(
                "build_motivation_job.drop_low_fps_clips",
                side_effect=lambda clips, delete=True: clips,
            ), patch(
                "broll_frame_gate.assess_clip_source_text_overlay",
                side_effect=lambda path, *, duration, subject: (
                    {"reject": True, "regions": ["top"]}
                    if "dirty" in path.name
                    else {"reject": False, "regions": []}
                ),
            ):
                kept = build_motivation_job.filter_broll_clip_list(
                    [good, bad],
                    subject="desert mountains sunset",
                    use_vision=False,
                    frame_gate=True,
                    jobs_root=jobs_root,
                    delete_rejects=False,
                    required_clips=2,
                )
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0].name, "clean_part01.mp4")

    def test_center_word_captions_unchanged(self) -> None:
        header = _ass_header(width=1080, height=1920, caption_align="center")
        self.assertIn(",5,80,80,", header)
        self.assertEqual(normalize_caption_align(None, caption_mode="word"), "center")


if __name__ == "__main__":
    unittest.main()
