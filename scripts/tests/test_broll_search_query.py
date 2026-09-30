#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broll_frame_gate import wants_vehicle
from broll_search_query import (
    expand_broll_search_queries,
    gate_subject_for_query,
    is_storyboard_query,
)


BRIEF = (
    "Dark early-morning bedroom → alarm / shoes / empty road → "
    "gym or late-night work → sunrise city → moving supercar / freedom ending."
)


class BrollSearchQueryTests(unittest.TestCase):
    def test_plain_query_stays_one_search(self) -> None:
        self.assertFalse(is_storyboard_query("dubai penthouse city skyline 60fps"))
        self.assertEqual(
            expand_broll_search_queries("dubai penthouse city skyline 60fps"),
            ["dubai penthouse city skyline 60fps"],
        )
        self.assertEqual(
            gate_subject_for_query("dubai penthouse city skyline 60fps"),
            "dubai penthouse city skyline 60fps",
        )

    def test_storyboard_expands_to_scene_searches(self) -> None:
        self.assertTrue(is_storyboard_query(BRIEF))
        queries = expand_broll_search_queries(BRIEF)
        self.assertGreaterEqual(len(queries), 4)
        blob = " ".join(queries)
        self.assertIn("bedroom", blob)
        self.assertIn("road", blob)
        self.assertIn("gym", blob)
        self.assertIn("city", blob)
        self.assertIn("supercar", blob)
        self.assertNotIn("alarm", blob)
        self.assertNotIn("freedom", blob)
        self.assertEqual(gate_subject_for_query(BRIEF, subject=BRIEF), "")
        self.assertFalse(wants_vehicle(BRIEF))
        self.assertTrue(wants_vehicle("porsche 911 gt3 exterior 60fps"))

    def test_weekly_hike_sunrise_expands(self) -> None:
        queries = expand_broll_search_queries("Dark 5AM hike → sunrise")
        self.assertGreaterEqual(len(queries), 2)
        blob = " ".join(queries).lower()
        self.assertIn("hiking", blob)
        self.assertIn("sunrise", blob)
        self.assertFalse(is_storyboard_query("Dark 5AM hike → sunrise"))

    def test_to_storyboard_still_finds_road_city_car(self) -> None:
        brief = (
            "Dark early-morning bedroom → alarm / shoes / empty road to gym "
            "or late-night work to sunrise city to moving supercar / freedom ending."
        )
        self.assertTrue(is_storyboard_query(brief))
        queries = expand_broll_search_queries(brief)
        blob = " ".join(queries)
        self.assertIn("bedroom", blob)
        self.assertIn("road", blob)
        self.assertIn("gym", blob)
        self.assertIn("city", blob)
        self.assertIn("supercar", blob)


if __name__ == "__main__":
    unittest.main()
