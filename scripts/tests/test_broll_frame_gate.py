#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import broll_frame_gate


def _png(color: tuple[int, int, int], *, blob: tuple[int, int, int] | None = None, busy: bool = False) -> bytes:
    img = Image.new("RGB", (160, 280), color)
    if blob:
        for x in range(50, 110):
            for y in range(40, 140):
                img.putpixel((x, y), blob)
    if busy:
        for x in range(0, 160, 3):
            for y in range(0, 280, 3):
                img.putpixel((x, y), ((x * 3) % 180 + 40, (y * 2) % 120 + 30, 70))
        for x in range(20, 140):
            for y in range(90, 190):
                img.putpixel((x, y), (200, 18 + (x % 20), 22))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class BrollFrameGateTests(unittest.TestCase):
    def test_subject_tokens_drop_filler(self) -> None:
        tokens = broll_frame_gate.subject_tokens("luxury porsche gt3rs cinematic 4k short")
        self.assertIn("porsche", tokens)
        self.assertIn("gt3rs", tokens)
        self.assertNotIn("cinematic", tokens)
        self.assertNotIn("luxury", tokens)

    def test_title_matches_alias(self) -> None:
        self.assertTrue(broll_frame_gate.title_matches_subject("911 GT3 RS Night Drive", ["porsche"]))
        self.assertFalse(broll_frame_gate.title_matches_subject("Miami villa tour 4k", ["porsche"]))

    def test_title_card_and_skin_rejected(self) -> None:
        title = _png((8, 8, 8))
        face = _png((30, 30, 30), blob=(190, 120, 90))
        car = _png((40, 44, 48), busy=True)
        self.assertIn("title-card", broll_frame_gate.frame_fail_reasons(title))
        self.assertIn("talking-head", broll_frame_gate.frame_fail_reasons(face))
        self.assertEqual(broll_frame_gate.frame_fail_reasons(car), [])

    def test_window_requires_clean_first_frame(self) -> None:
        title = _png((6, 6, 6))
        car = _png((40, 44, 48), busy=True)
        bad = broll_frame_gate.window_report([title, car, car, car, car])
        good = broll_frame_gate.window_report([car, car, car, car, car])
        self.assertFalse(bad["ok"])
        self.assertTrue(good["ok"])

    def test_clean_spans_clip_out_bad_middle(self) -> None:
        samples = [
            {"t": 0.0, "ok": True, "reasons": []},
            {"t": 1.0, "ok": True, "reasons": []},
            {"t": 2.0, "ok": True, "reasons": []},
            {"t": 3.0, "ok": True, "reasons": []},
            {"t": 4.0, "ok": False, "reasons": ["talking-head"]},
            {"t": 5.0, "ok": False, "reasons": ["missing-subject"]},
            {"t": 6.0, "ok": True, "reasons": []},
            {"t": 7.0, "ok": True, "reasons": []},
        ]
        spans = broll_frame_gate.clean_spans(samples, min_length=3.0)
        self.assertEqual(spans, [(0.0, 4.0)])
        longest = broll_frame_gate.longest_clean_span(samples, min_length=2.0)
        self.assertEqual(longest, (0.0, 4.0))

    def test_vehicle_gate_rejects_establishing_shots(self) -> None:
        qc = Path(__file__).resolve().parents[2] / "downloads" / "motivational" / "porsche-gt3rs-motivation" / "output" / "qc"
        harbor = qc / "t0-5.png"
        boats = qc / "t3.png"
        car = qc / "t10.png"
        if not (harbor.is_file() and boats.is_file() and car.is_file()):
            self.skipTest("porsche QC frames not on disk")
        subject = "porsche gt3rs"
        self.assertIn("missing-subject", broll_frame_gate.frame_fail_reasons(harbor.read_bytes(), subject))
        self.assertIn("missing-subject", broll_frame_gate.frame_fail_reasons(boats.read_bytes(), subject))
        self.assertNotIn("missing-subject", broll_frame_gate.frame_fail_reasons(car.read_bytes(), subject))

    def test_vehicle_opener_prompt_rejects_cabin(self) -> None:
        prompt = broll_frame_gate.vision_prompt("Ferrari 488 Pista", opener=True)
        self.assertIn("full_exterior", prompt)
        self.assertIn("cabin", prompt.lower())
        self.assertIn("rear", prompt.lower())
        regular = broll_frame_gate.vision_prompt("Ferrari 488 Pista", opener=False)
        self.assertIn("cabin", regular.lower())

    def test_opener_verdict_rejects_rear_and_coffee(self) -> None:
        coffee = '{"object":"coffee tamper","view":"other","full_exterior":true}'
        rear = '{"object":"ferrari rear","view":"rear","full_exterior":true}'
        hero = '{"object":"red ferrari coupe","view":"three_quarter","full_exterior":true}'
        host = '{"object":"man with ferrari","view":"front","full_exterior":true}'
        self.assertFalse(broll_frame_gate.parse_opener_verdict(coffee))
        self.assertFalse(broll_frame_gate.parse_opener_verdict(rear))
        self.assertFalse(broll_frame_gate.parse_opener_verdict(host))
        self.assertTrue(broll_frame_gate.parse_opener_verdict(hero))

    def test_opener_local_rejects_bridge_keeps_hero(self) -> None:
        root = Path(__file__).resolve().parents[2]
        bridge = (
            root
            / "downloads"
            / "motivational"
            / "lambo-huracan-night-city"
            / "output"
            / "opener-check"
            / "t0.jpg"
        )
        hero = (
            root
            / "downloads"
            / "motivational"
            / "lambo-huracan-night-city"
            / "output"
            / "clip-preview"
            / "miami_1.jpg"
        )
        if not (bridge.is_file() and hero.is_file()):
            self.skipTest("huracan opener preview frames not on disk")
        self.assertIn("weak-opener", broll_frame_gate.opener_fail_reasons(bridge.read_bytes()))
        self.assertEqual(broll_frame_gate.opener_fail_reasons(hero.read_bytes()), [])

    def test_cabin_gate_drops_windshield_and_gauge(self) -> None:
        root = (
            Path(__file__).resolve().parents[2]
            / "downloads"
            / "motivational"
            / "lambo-dream-car"
            / "preview"
            / "all"
        )
        windshield = root / "xEIKiO3ZgZQ_part04.jpg"
        gauge = root / "Ey29z3LwcyU_part04.jpg"
        side = root / "-5wQWMvhMwo_part08.jpg"
        if not (windshield.is_file() and gauge.is_file() and side.is_file()):
            self.skipTest("lambo cabin preview frames not on disk")
        subject = "lamborghini huracan"
        self.assertIn("cabin", broll_frame_gate.frame_fail_reasons(windshield.read_bytes(), subject))
        self.assertIn("cabin", broll_frame_gate.frame_fail_reasons(gauge.read_bytes(), subject))
        self.assertNotIn("cabin", broll_frame_gate.frame_fail_reasons(side.read_bytes(), subject))

    def test_opener_jump_cut_detects_shot_change(self) -> None:
        same = [_png((20, 20, 24), busy=True) for _ in range(4)]
        changed = [
            _png((20, 20, 24), busy=True),
            _png((20, 20, 24), busy=True),
            _png((180, 40, 30)),
            _png((180, 40, 30)),
        ]
        self.assertFalse(broll_frame_gate.opener_has_jump_cut(same))
        self.assertTrue(broll_frame_gate.opener_has_jump_cut(changed))
        stamps = broll_frame_gate.sample_clip_stamps(8.0, step=1.0)
        self.assertGreaterEqual(len(stamps), 6)
        self.assertLess(stamps[0], 1.0)
        self.assertLess(stamps[-1], 8.0)


if __name__ == "__main__":
    unittest.main()
