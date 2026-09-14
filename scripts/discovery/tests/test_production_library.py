"""Tests for production library and command jobs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from discovery.command_jobs import build_agent_prompt, create_command_job
from discovery.cursor_bridge import run_agent
from discovery.auto_register import auto_register_final_output, find_video_by_slug
from unittest.mock import patch

from discovery.production_library import (
    check_reuse,
    delete_video,
    get_video,
    list_videos,
    register_video,
    update_video_posting_status,
)
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

    def test_mark_used_moves_final_between_folders(self) -> None:
        root = Path(self.tmp.name) / "repo"
        lib = root / "downloads" / "production_library"
        job = root / "downloads" / "job"
        job.mkdir(parents=True)
        lib.mkdir(parents=True)
        src = job / "speech.mp4"
        src.write_bytes(b"\x00" * 120_000)

        with patch("discovery.production_library.project_root", return_value=root):
            with patch("discovery.production_library.production_library_dir", return_value=lib):
                video = register_video(
                    self.store,
                    title="Night Drive",
                    speaker="Test Speaker",
                    final_output_path=str(src.relative_to(root).as_posix()),
                    copy_final_to_library=True,
                )
                unused = lib / "unused" / video["video_key"] / "final.mp4"
                used = lib / "used" / video["video_key"] / "final.mp4"
                self.assertTrue(unused.is_file())
                self.assertFalse(used.exists())
                self.assertIn("/unused/", str(video["final_output_path"]).replace("\\", "/"))
                self.assertFalse(video.get("used"))
                self.assertEqual(video.get("finished_bucket"), "unused")

                marked = update_video_posting_status(
                    self.store,
                    int(video["id"]),
                    owner="chris",
                    tiktok=True,
                )
                self.assertTrue(used.is_file())
                self.assertFalse(unused.exists())
                self.assertTrue(marked.get("used"))
                self.assertEqual(marked.get("finished_bucket"), "used")
                self.assertIn("/used/", str(marked["final_output_path"]).replace("\\", "/"))

                unused_list = list_videos(self.store, used=False, playable_only=False, heal=False)
                used_list = list_videos(self.store, used=True, playable_only=False, heal=False)
                self.assertEqual(len(unused_list), 0)
                self.assertEqual(len(used_list), 1)

                unmarked = update_video_posting_status(
                    self.store,
                    int(video["id"]),
                    owner="chris",
                    tiktok=False,
                )
                self.assertTrue(unused.is_file())
                self.assertFalse(used.exists())
                self.assertFalse(unmarked.get("used"))
                self.assertEqual(unmarked.get("finished_bucket"), "unused")

    def test_delete_video_removes_local_files(self) -> None:
        root = Path(self.tmp.name) / "repo-delete"
        lib = root / "downloads" / "production_library"
        job = root / "downloads" / "motivational" / "night-drive"
        output = job / "output"
        output.mkdir(parents=True)
        lib.mkdir(parents=True)
        src = output / "night-drive-motivation.mp4"
        src.write_bytes(b"\x00" * 120_000)
        (job / "audio").mkdir()
        (job / "audio" / "speech.mp3").write_bytes(b"speech")
        pool = root / "downloads" / "broll_pool" / "clip.mp4"
        pool.parent.mkdir(parents=True)
        pool.write_bytes(b"\x00" * 120_000)

        with patch("discovery.production_library.project_root", return_value=root):
            with patch("discovery.production_library.production_library_dir", return_value=lib):
                video = register_video(
                    self.store,
                    title="Night Drive",
                    slug="night-drive",
                    speaker="Test Speaker",
                    final_output_path=str(src.relative_to(root).as_posix()),
                    components=[{"component_type": "visual", "local_path": str(pool.relative_to(root).as_posix())}],
                    copy_final_to_library=True,
                )
                unused_dir = lib / "unused" / video["video_key"]
                unused = unused_dir / "final.mp4"
                self.assertTrue(unused.is_file())

                result = delete_video(self.store, int(video["id"]))
                self.assertIsNotNone(result)
                self.assertFalse(unused_dir.exists())
                self.assertFalse(job.exists())
                self.assertTrue(pool.is_file())
                self.assertIsNone(get_video(self.store, int(video["id"])))


if __name__ == "__main__":
    unittest.main()
