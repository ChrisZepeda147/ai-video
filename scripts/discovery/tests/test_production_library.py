"""Tests for production library and command jobs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from discovery.command_jobs import build_agent_prompt, create_command_job
from discovery.config import project_root
from discovery.cursor_bridge import run_agent
from discovery.auto_register import auto_register_final_output, find_video_by_slug
from discovery.production_library import check_reuse, register_video
from discovery.store import DiscoveryStore


class ProductionLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.store = DiscoveryStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_register_and_reuse_check(self) -> None:
        video = register_video(
            self.store,
            title="Discipline Short",
            speaker="Alex Hormozi",
            topic="discipline",
            source_url="https://www.youtube.com/watch?v=abc123xyz12",
            source_start_sec=100.0,
            source_end_sec=130.0,
            transcript_segment="You need discipline every single day.",
            final_output_path="downloads/test/final.mp4",
            copy_final_to_library=False,
        )
        self.assertEqual(video["video_key"], "video_000001")
        report = check_reuse(
            self.store,
            source_external_id="abc123xyz12",
            source_start_sec=110.0,
            source_end_sec=120.0,
            transcript="You need discipline every single day.",
            speaker="Alex Hormozi",
            topic="discipline",
        )
        self.assertTrue(report["safe_to_proceed"])
        self.assertTrue(report["prior_usage_detected"])
        self.assertTrue(report["advisory_only"])
        self.assertTrue(report["already_used"])
        self.assertTrue(report["prior_timestamp_ranges"])

    def test_command_job_creation(self) -> None:
        job = create_command_job(
            self.store,
            user_command="Make a test video about focus.",
        )
        self.assertTrue(job["job_key"].startswith("cmd_"))
        prompt = build_agent_prompt(user_command="Test", store=self.store)
        self.assertIn("register_production_video.py", prompt)
        self.assertIn("production library", prompt.lower())

    def test_auto_register_idempotent(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "test-short.mp4"
            final.write_bytes(b"\x00\x00\x00\x20ftypmp42")
            first = auto_register_final_output(
                self.store,
                final_path=final,
                slug="test-auto-slug",
                title="Test Auto",
                pipeline="test",
            )
            self.assertIsNotNone(first)
            second = auto_register_final_output(
                self.store,
                final_path=final,
                slug="test-auto-slug",
                pipeline="test",
            )
            self.assertEqual(first["id"], second["id"])
            self.assertIsNotNone(find_video_by_slug(self.store, "test-auto-slug"))

    def test_cursor_bridge_dry_run(self) -> None:
        os.environ["CURSOR_BRIDGE_DRY_RUN"] = "1"
        try:
            result = run_agent("Say hello", job_id="test")
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
        finally:
            os.environ.pop("CURSOR_BRIDGE_DRY_RUN", None)


if __name__ == "__main__":
    unittest.main()
