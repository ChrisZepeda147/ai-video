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

from build_stills_slideshow import (
    _ass_header,
    _words_from_event,
    normalize_caption_align,
    parse_json3_words,
)


class CaptionWordTests(unittest.TestCase):
    def test_phrase_event_splits_into_words(self) -> None:
        words = _words_from_event(
            {
                "tStartMs": 16310,
                "dDurationMs": 2360,
                "segs": [{"utf8": "It's so ridiculously easy."}],
            }
        )
        self.assertEqual([text for _when, text in words], ["It's", "so", "ridiculously", "easy."])
        self.assertAlmostEqual(words[0][0], 16.31, places=2)
        self.assertLess(words[-1][0], 16.31 + 2.36)

    def test_parse_json3_words_filters_window(self) -> None:
        payload = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 1850, "segs": [{"utf8": "You have a destiny."}]},
                {"tStartMs": 18670, "dDurationMs": 1330, "segs": [{"utf8": "It's so easy to be in."}]},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subs.en.json3"
            path.write_text(json.dumps(payload), encoding="utf-8")
            kept = parse_json3_words(path, start=0.0, duration=18.67)
        texts = [word for _start, _end, word in kept]
        self.assertIn("destiny.", texts)
        self.assertNotIn("in.", texts)

    def test_center_header_uses_middle_alignment(self) -> None:
        header = _ass_header(width=1080, height=1920, caption_align="center")
        self.assertIn(",5,80,80,80,1", header)
        self.assertEqual(normalize_caption_align(None, caption_mode="word"), "center")
        self.assertEqual(normalize_caption_align(None, caption_mode="phrase"), "lower_middle")


if __name__ == "__main__":
    unittest.main()
