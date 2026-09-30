"""Tests for Combination Board catalog, pairing memory, and render orchestration."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from discovery.combination_render import render_combination
from discovery.combinations import (
    catalog_payload,
    combination_status,
    ensure_combination_usage_for_library_video,
    import_usage_from_videos,
    list_audio_catalog,
    record_combination_usage,
    sync_combination_usage_from_posted_videos,
    sync_visual_packs,
)
from discovery.config import project_root
from discovery.production_library import register_video, update_video_posting_status
from discovery.store import DiscoveryStore


class CombinationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.store = DiscoveryStore(self.db_path)
        self.root = project_root()
        self.job_slug = f"test-combo-{uuid.uuid4().hex[:8]}"
        self.job_dir = self.root / "downloads" / "motivational" / self.job_slug
        audio_dir = self.job_dir / "audio"
        clips_dir = self.job_dir / "clips"
        audio_dir.mkdir(parents=True)
        clips_dir.mkdir(parents=True)
        (audio_dir / "speech.mp3").write_bytes(b"fake-mp3-content")
        (audio_dir / "subs.en.json3").write_text(
            json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Go"}]}]}),
            encoding="utf-8",
        )
        (clips_dir / "abc_part01.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42")
        (clips_dir / "abc_part02.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42")

        rel_audio = f"downloads/motivational/{self.job_slug}/audio/speech.mp3"
        video = register_video(
            self.store,
            title="Tate Test",
            slug=self.job_slug,
            speaker="Andrew Tate",
            topic="motivation",
            source_url="https://www.youtube.com/watch?v=abc123xyz12",
            source_external_id="abc123xyz12",
            transcript_segment="Work hard every day.",
            final_output_path=f"downloads/motivational/{self.job_slug}/output/final.mp4",
            duration_sec=67.0,
            metadata={"pipeline": "build_motivation_job", "broll_ids": ["abc123", "def456"], "visual_style": "luxury supercar"},
            copy_final_to_library=False,
            components=[
                {"component_type": "audio", "local_path": rel_audio},
                {"component_type": "caption", "local_path": f"downloads/motivational/{self.job_slug}/audio/subs.en.json3"},
                {"component_type": "visual", "local_path": f"downloads/motivational/{self.job_slug}/clips/abc_part01.mp4"},
            ],
        )
        self.video_id = int(video["id"])
        row = self.store._conn.execute(
            "SELECT id FROM production_video_components WHERE video_id = ? AND component_type = 'audio'",
            (self.video_id,),
        ).fetchone()
        self.audio_id = int(row["id"])
        sync_visual_packs(self.store)
        pack_row = self.store._conn.execute("SELECT id FROM production_visual_packs LIMIT 1").fetchone()
        self.assertIsNotNone(pack_row)
        self.pack_id = int(pack_row["id"])

    def tearDown(self) -> None:
        self.store.close()
        if self.job_dir.is_dir():
            shutil.rmtree(self.job_dir, ignore_errors=True)
        self.tmp.cleanup()

    def test_audio_catalog_and_visual_packs(self) -> None:
        audio = list_audio_catalog(self.store)
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]["speaker"], "Andrew Tate")
        self.assertTrue(audio[0]["display_id"].endswith("A"))
        catalog = catalog_payload(self.store, owner="chris")
        self.assertIn("Andrew Tate", catalog["audio_by_speaker"])
        self.assertGreaterEqual(catalog["visual_pack_count"], 1)

    def test_owner_separate_usage_and_cross_owner_warning(self) -> None:
        record_combination_usage(
            self.store,
            owner="chris",
            audio_component_id=self.audio_id,
            visual_pack_id=self.pack_id,
            rendered_video_id=self.video_id,
            force=True,
        )
        chris = combination_status(self.store, owner="chris", audio_component_id=self.audio_id)
        stephen = combination_status(self.store, owner="stephen", audio_component_id=self.audio_id)
        chris_item = chris["visuals"][0]
        stephen_item = stephen["visuals"][0]
        self.assertTrue(chris_item["used_by_selected_owner"])
        self.assertFalse(chris_item["available"])
        self.assertTrue(stephen_item["used_by_other_owner"])
        self.assertTrue(stephen_item["available"])

    def test_posting_status_records_combination_usage(self) -> None:
        update_video_posting_status(
            self.store,
            self.video_id,
            owner="chris",
            tiktok=True,
            marked_by="test",
        )
        chris = combination_status(self.store, owner="chris", audio_component_id=self.audio_id)
        item = chris["visuals"][0]
        self.assertTrue(item["used_by_selected_owner"])

    def test_sync_posted_videos_updates_combinations(self) -> None:
        self.store._conn.execute(
            "UPDATE production_library_videos SET posted = 1 WHERE id = ?",
            (self.video_id,),
        )
        self.store._conn.commit()
        out = sync_combination_usage_from_posted_videos(self.store, owner="stephen")
        self.assertGreaterEqual(out["video_count"], 1)
        stephen = combination_status(self.store, owner="stephen", audio_component_id=self.audio_id)
        self.assertTrue(stephen["visuals"][0]["used_by_selected_owner"])

    def test_ensure_usage_helper(self) -> None:
        result = ensure_combination_usage_for_library_video(
            self.store, self.video_id, owners=["chris"]
        )
        self.assertTrue(result["ok"])

    def test_import_usage_idempotent(self) -> None:
        first = import_usage_from_videos(self.store, owner="stephen", video_ids=[self.video_id])
        second = import_usage_from_videos(self.store, owner="stephen", video_ids=[self.video_id])
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)

    def test_duplicate_transcript_collapses_to_one_audio_slot(self) -> None:
        shared = "Work hard every day."
        second_slug = f"test-combo-dup-{uuid.uuid4().hex[:8]}"
        second_dir = self.root / "downloads" / "motivational" / second_slug
        audio_dir = second_dir / "audio"
        audio_dir.mkdir(parents=True)
        (audio_dir / "speech.mp3").write_bytes(b"different-mp3-bytes-for-same-words")
        rel_audio = f"downloads/motivational/{second_slug}/audio/speech.mp3"
        register_video(
            self.store,
            title="Tate duplicate transcript",
            slug=second_slug,
            speaker="Andrew Tate",
            topic="motivation",
            source_url="https://www.youtube.com/watch?v=dup12345678",
            source_external_id="dup12345678",
            transcript_segment=shared,
            final_output_path=f"downloads/motivational/{second_slug}/output/final.mp4",
            duration_sec=67.0,
            metadata={"pipeline": "build_motivation_job"},
            copy_final_to_library=False,
            components=[{"component_type": "audio", "local_path": rel_audio}],
        )
        audio = list_audio_catalog(self.store)
        tate = [item for item in audio if item["speaker"] == "Andrew Tate"]
        self.assertEqual(len(tate), 1)
        self.assertTrue(tate[0]["display_id"].endswith("A"))

    @patch("build_motivation_job.render_job")
    @patch("build_clips_montage.probe_duration", return_value=67.0)
    def test_render_reuses_renderer_and_records_usage(self, _probe, mock_render) -> None:
        def _fake_render(**kwargs):
            output = kwargs["output"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"\x00\x00\x00\x20ftypmp42")

        mock_render.side_effect = _fake_render
        result = render_combination(
            self.store,
            owner="stephen",
            audio_component_id=self.audio_id,
            visual_pack_id=self.pack_id,
            force_usage=True,
        )
        self.assertTrue(mock_render.called)
        self.assertIn("video", result)
        self.assertGreater(int(result["video"]["id"]), 0)
        usage = self.store._conn.execute(
            "SELECT * FROM production_combination_usage WHERE owner = 'stephen'"
        ).fetchone()
        self.assertIsNotNone(usage)
        self.assertEqual(int(usage["audio_component_id"]), self.audio_id)
        self.assertEqual(int(usage["visual_pack_id"]), self.pack_id)

    @patch("build_motivation_job.ensure_broll_clips")
    @patch("build_motivation_job.render_job")
    @patch("build_clips_montage.probe_duration", return_value=67.0)
    def test_render_hydrates_missing_clip_folder(self, _probe, mock_render, mock_ensure) -> None:
        def _fake_render(**kwargs):
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_bytes(b"\x00\x00\x00\x20ftypmp42")

        def _fake_ensure(**kwargs):
            clips_dir = kwargs["clips_dir"]
            clips_dir.mkdir(parents=True, exist_ok=True)
            (clips_dir / "hydrated_part01.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42")

        mock_render.side_effect = _fake_render
        mock_ensure.side_effect = _fake_ensure
        shutil.rmtree(self.job_dir / "clips")
        self.store._conn.execute(
            "UPDATE production_visual_packs SET clips_root_path = NULL WHERE id = ?",
            (self.pack_id,),
        )
        self.store._conn.commit()

        result = render_combination(
            self.store,
            owner="chris",
            audio_component_id=self.audio_id,
            visual_pack_id=self.pack_id,
            force_usage=True,
        )
        self.assertTrue(mock_ensure.called)
        self.assertTrue(mock_render.called)
        self.assertGreater(int(result["video"]["id"]), 0)

    @patch("build_motivation_job.render_job")
    @patch("build_clips_montage.probe_duration", return_value=67.0)
    def test_version_link_on_render(self, _probe, mock_render) -> None:
        def _fake_render(**kwargs):
            kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["output"].write_bytes(b"\x00\x00\x00\x20ftypmp42")

        mock_render.side_effect = _fake_render
        result = render_combination(
            self.store,
            owner="chris",
            audio_component_id=self.audio_id,
            visual_pack_id=self.pack_id,
            version_label="10A",
        )
        self.assertEqual(result["video"].get("parent_video_id"), self.video_id)


if __name__ == "__main__":
    unittest.main()
