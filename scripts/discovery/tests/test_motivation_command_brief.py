"""Tests for shared montage command brief."""

from __future__ import annotations

import unittest

from discovery.motivation_command_brief import compose_montage_command, visual_production_hints


class TestMotivationCommandBrief(unittest.TestCase):
    def test_owner_and_combination_line(self) -> None:
        text = compose_montage_command(owner="chris", broll_query="ocean drone")
        self.assertIn("record combination usage", text)
        self.assertIn("production_library_cli.py", text)

    def test_car_hint(self) -> None:
        hints = visual_production_hints("porsche 911 night drive")
        self.assertTrue(any("exterior" in h.lower() for h in hints))


if __name__ == "__main__":
    unittest.main()
