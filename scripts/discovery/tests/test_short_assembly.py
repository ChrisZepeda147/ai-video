"""Tests for Short assembly pipeline."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from discovery.acquire import clip_source_segment, extract_audio_segment
from discovery.captions import build_ass_captions
from discovery.models import ReferenceVideo
from discovery.production_projects import (
    approve_project,
    build_project_timeline,
    create_production_project,
    slugify,
)
from discovery.store import DiscoveryStore
from discovery.timeline import plan_timeline
from discovery.transcription.mock import MockTranscriptionProvider


def seed_source(store, *, external_id: str = "short0000001") -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Motivation clip",
        description="Discipline speech excerpt",
        channel="Clips",
        duration_sec=60.0,
        production_asset=False,
    )
    ref_id = store.upsert_reference(ref, is_new=True)
    sid = store.create_source_media(
        title="Motivation clip",
        source_mode="audio",
        media_type="audio",
        reference_id=ref_id,
        platform="youtube",
        external_id=external_id,
        url=ref.url,
        local_path="/tmp/fake.mp3",
    )
    store.update_source_media_download(
        sid,
        status="acquired",
        download_path="/tmp/fake.mp3",
        local_path="/tmp/fake.mp3",
    )
    return sid


class ShortAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "short.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        self.store = DiscoveryStore(self.db_path)
        self.source_id = seed_source(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_slugify(self) -> None:
        self.assertEqual(slugify("Luxury Motivation Short!"), "luxury-motivation-short")

    def test_timeline_audio_visuals(self) -> None:
        timeline = plan_timeline(
            duration_sec=12.0,
            format_profile="audio_visuals",
            visual_assets=[
                {"id": 1, "asset_type": "image", "local_path": "/a.png"},
                {"id": 2, "asset_type": "video", "local_path": "/b.mp4"},
            ],
        )
        self.assertGreaterEqual(len(timeline["segments"]), 2)

    def test_timeline_source_video_visuals(self) -> None:
        timeline = plan_timeline(
            duration_sec=15.0,
            format_profile="source_video_visuals",
            visual_assets=[{"id": 1, "asset_type": "image", "local_path": "/a.png"}],
            source_segment_path="/seg.mp4",
        )
        types = [s["type"] for s in timeline["segments"]]
        self.assertIn("source_video", types)

    def test_captions_with_hook(self) -> None:
        from discovery.transcription.base import TranscriptSegment

        ass = build_ass_captions(
            [TranscriptSegment("Hello world", 0.0, 2.0)],
            preset="viral_bold",
            hook_text="THIS IS WHY MOST PEOPLE FAIL",
        )
        self.assertIn("THIS IS WHY MOST PEOPLE FAIL", ass)

    def test_asr_mock_stores_timestamps(self) -> None:
        from discovery.source_media import transcribe_source_media_with_asr

        provider = MockTranscriptionProvider()
        source = transcribe_source_media_with_asr(self.store, self.source_id, provider=provider)
        self.assertIn("Discipline", source.transcript or "")
        updated = self.store.get_source_media(self.source_id)
        self.assertTrue(updated and updated.transcript_json)

    def test_source_not_marked_used_before_approval(self) -> None:
        project = create_production_project(
            self.store,
            title="Test Short",
            source_media_id=self.source_id,
            format_profile="audio_visuals",
        )
        source = self.store.get_source_media(self.source_id)
        self.assertFalse(source.actually_used_in_content)
        self.assertEqual(project.status, "draft")

    def test_source_marked_used_after_approval(self) -> None:
        project = create_production_project(
            self.store,
            title="Approved Short",
            source_media_id=self.source_id,
            format_profile="audio_visuals",
        )
        self.store.update_production_project_status(project.project_id, "review")
        self.store.update_production_project_rendered(
            project.project_id,
            output_path=str(Path(self.tmp.name) / "final.mp4"),
            duration_sec=30.0,
            monetization_confidence=70,
            rights_confidence=50,
            reuse_confidence=10,
            risk_explanations_json="{}",
            status="review",
        )
        Path(self.tmp.name, "final.mp4").write_bytes(b"fake")
        approve_project(self.store, project.project_id)
        source = self.store.get_source_media(self.source_id)
        self.assertTrue(source.actually_used_in_content)

    def test_duplicate_approval_does_not_double_register(self) -> None:
        project = create_production_project(
            self.store,
            title="Twice Approved",
            source_media_id=self.source_id,
        )
        self.store.update_production_project_status(project.project_id, "review")
        self.store.update_production_project_rendered(
            project.project_id,
            output_path=str(Path(self.tmp.name) / "final2.mp4"),
            duration_sec=20.0,
            monetization_confidence=70,
            rights_confidence=50,
            reuse_confidence=10,
            risk_explanations_json="{}",
            status="review",
        )
        Path(self.tmp.name, "final2.mp4").write_bytes(b"fake")
        approve_project(self.store, project.project_id)
        approve_project(self.store, project.project_id)
        source = self.store.get_source_media(self.source_id)
        self.assertTrue(source.actually_used_in_content)

    @unittest.mock.patch("discovery.acquire._ypd")
    def test_acquire_reuses_existing_downloader(self, mocked_ypd) -> None:
        from discovery.acquire import acquire_source_media

        mocked_ypd.return_value.download_videos.return_value = [
            {
                "status": "ok",
                "source_file": str(Path(self.tmp.name) / "raw.mp4"),
                "file_path": str(Path(self.tmp.name) / "raw.mp4"),
            }
        ]
        Path(self.tmp.name, "raw.mp4").write_bytes(b"x")
        result = acquire_source_media(self.store, self.source_id)
        mocked_ypd.return_value.download_videos.assert_called_once()
        self.assertEqual(result.status, "acquired")

    def test_workbench_project_without_reference(self) -> None:
        project = create_production_project(
            self.store,
            title="Original luxury motivation",
            format_profile="original_story",
        )
        self.assertIsNone(self.store.get_production_project(project.project_id).source_media_id)

    @unittest.mock.patch("discovery.acquire.subprocess.run")
    def test_audio_extraction_ffmpeg(self, mocked_run) -> None:
        src = Path(self.tmp.name) / "full.m4a"
        out = Path(self.tmp.name) / "clip.m4a"
        src.write_bytes(b"audio")
        extract_audio_segment(src, out, start_sec=5.0, end_sec=15.0)
        mocked_run.assert_called_once()
        cmd = mocked_run.call_args[0][0]
        self.assertIn("ffmpeg", cmd[0])
        self.assertIn("-vn", cmd)

    @unittest.mock.patch("discovery.acquire._ypd")
    @unittest.mock.patch("discovery.acquire.subprocess.run")
    def test_video_clip_uses_downloader_export(self, mocked_run, mocked_ypd) -> None:
        raw = Path(self.tmp.name) / "raw.mp4"
        raw.write_bytes(b"video")
        self.store.update_source_media_download(
            self.source_id,
            status="acquired",
            download_path=str(raw),
            raw_local_path=str(raw),
            local_path=str(raw),
        )
        self.store._conn.execute(
            "UPDATE source_media SET media_type = 'video', source_mode = 'video' WHERE id = ?",
            (self.source_id,),
        )
        self.store._conn.commit()
        clip_source_segment(self.store, self.source_id, start_sec=0.0, end_sec=10.0)
        mocked_ypd.return_value.export_clip.assert_called_once()

    def test_timeline_original_story(self) -> None:
        timeline = plan_timeline(
            duration_sec=20.0,
            format_profile="original_story",
            visual_assets=[
                {"id": 1, "asset_type": "image", "local_path": "/a.png"},
                {"id": 2, "asset_type": "video", "local_path": "/b.mp4"},
            ],
        )
        types = [s["type"] for s in timeline["segments"]]
        self.assertIn("image", types)
        self.assertIn("ai_video", types)

    def test_mixed_image_video_timeline_motion(self) -> None:
        timeline = plan_timeline(
            duration_sec=18.0,
            format_profile="audio_visuals",
            visual_assets=[
                {"id": 1, "asset_type": "image", "local_path": "/a.png"},
                {"id": 2, "asset_type": "video", "local_path": "/b.mp4"},
                {"id": 3, "asset_type": "image", "local_path": "/c.png"},
            ],
        )
        image_seg = next(s for s in timeline["segments"] if s["type"] == "image")
        self.assertEqual(image_seg.get("motion"), "zoom_in")

    def test_transcript_reuse_fuzzy_match(self) -> None:
        from discovery.reuse_detection import check_global_reuse

        self.store.create_source_media(
            title="Re-upload clip",
            source_mode="audio",
            media_type="audio",
            platform="youtube",
            external_id="other0000001",
            url="https://www.youtube.com/watch?v=other0000001",
            transcript="Discipline beats motivation every single day in life.",
        )
        report = check_global_reuse(
            self.store,
            platform="youtube",
            external_id="new0000001",
            transcript="Discipline beats motivation every single day for winners.",
        )
        self.assertTrue(any("Fuzzy transcript" in e for e in report.explanations))

    def test_audio_fingerprint_fallback(self) -> None:
        from discovery.reuse_detection import audio_fingerprint, chromaprint_fingerprint

        path = Path(self.tmp.name) / "sample.m4a"
        path.write_bytes(b"0123456789" * 100)
        self.assertTrue(audio_fingerprint(str(path)))
        self.assertEqual(chromaprint_fingerprint(str(path)), "")

    def test_final_risk_scoring_does_not_block(self) -> None:
        from discovery.production_risk import score_finished_short

        timeline = plan_timeline(
            duration_sec=10.0,
            format_profile="audio_visuals",
            visual_assets=[{"id": 1, "asset_type": "image", "local_path": "/a.png"}],
        )
        project = create_production_project(
            self.store,
            title="Low score short",
            source_media_id=self.source_id,
        )
        risk = score_finished_short(
            self.store,
            project_id=project.project_id,
            source_media_id=self.source_id,
            format_profile="audio_visuals",
            timeline=timeline,
            source_duration=10.0,
        )
        self.assertIsNotNone(risk.monetization_confidence)
        self.assertIsNotNone(risk.reuse_confidence)

    def test_reject_project_status(self) -> None:
        from discovery.production_projects import reject_project

        project = create_production_project(self.store, title="Reject me")
        reject_project(self.store, project.project_id)
        updated = self.store.get_production_project(project.project_id)
        self.assertEqual(updated.status, "rejected")

    @unittest.mock.patch("discovery.render_short.subprocess.run")
    @unittest.mock.patch("discovery.render_short._probe_duration", return_value=12.0)
    def test_render_command_construction(self, _probe, mocked_run) -> None:
        from discovery.render_short import render_short

        img = Path(self.tmp.name) / "frame.png"
        img.write_bytes(b"png")
        audio = Path(self.tmp.name) / "audio.m4a"
        audio.write_bytes(b"audio")
        timeline = plan_timeline(
            duration_sec=6.0,
            format_profile="audio_visuals",
            visual_assets=[{"id": 1, "asset_type": "image", "local_path": str(img)}],
        )
        def fake_run(cmd, **kwargs):
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"fake-video")
            return unittest.mock.Mock(returncode=0)

        mocked_run.side_effect = fake_run
        result = render_short(
            slug="test-render",
            timeline=timeline,
            audio_path=str(audio),
            transcript_segments=[{"text": "Hello", "start": 0.0, "end": 2.0}],
            hook_text="HOOK TEXT",
        )
        self.assertTrue(Path(result.output_path).is_file())
        self.assertGreater(mocked_run.call_count, 0)

    def _seed_approved_visual(self, asset_type: str = "image") -> int:
        path = Path(self.tmp.name) / f"asset.{ 'png' if asset_type == 'image' else 'mp4' }"
        path.write_bytes(b"x")
        asset_id = self.store.create_visual_asset(
            concept_id=None,
            reference_id=None,
            niche="motivation",
            variation_family=None,
            asset_type=asset_type,
            provider="mock",
            model=None,
            prompt="Luxury car at dusk",
            local_path=str(path),
            status="approved",
        )
        return asset_id

    def test_build_project_timeline_with_visuals(self) -> None:
        img_id = self._seed_approved_visual("image")
        vid_id = self._seed_approved_visual("video")
        project = create_production_project(
            self.store,
            title="Timeline build",
            source_media_id=self.source_id,
            format_profile="audio_visuals",
        )
        timeline = build_project_timeline(
            self.store,
            project.project_id,
            visual_asset_ids=[img_id, vid_id],
            duration_sec=12.0,
        )
        self.assertGreaterEqual(len(timeline["segments"]), 2)
        updated = self.store.get_production_project(project.project_id)
        self.assertEqual(updated.status, "ready")


if __name__ == "__main__":
    unittest.main()
