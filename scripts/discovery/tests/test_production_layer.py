"""Tests for production layer: source media, generation jobs, reuse, review."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from discovery.config import generation_jobs_dir, project_root
from discovery.generation_jobs import create_generation_job, import_generation_job
from discovery.models import ReferenceVideo
from discovery.reuse_detection import check_global_reuse, transcript_hash
from discovery.risk_scoring import score_source_media
from discovery.source_media import create_source_media
from discovery.store import DiscoveryStore
from discovery.workbench import create_freeform_job


def seed_reference(store: DiscoveryStore, *, external_id: str = "prod00000001") -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Motivational discipline speech remix",
        description="Andrew Tate style discipline motivation about waking up early.",
        channel="Motivation Clips",
        duration_sec=45.0,
        view_count=500_000,
        like_count=20_000,
        comment_count=800,
        published_at="2026-01-01T00:00:00+00:00",
    )
    return store.upsert_reference(ref, is_new=True)


class ProductionLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "production.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        self.store = DiscoveryStore(self.db_path)
        self.ref_id = seed_reference(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_audio_source_mode(self) -> None:
        result = create_source_media(
            self.store,
            title="Discipline audio clip",
            source_mode="audio",
            reference_id=self.ref_id,
        )
        self.assertEqual(result.source.source_mode, "audio")
        self.assertEqual(result.source.media_type, "audio")
        self.assertFalse(result.source.production_asset)

    def test_video_source_mode(self) -> None:
        result = create_source_media(
            self.store,
            title="Podcast video clip",
            source_mode="video",
            media_type="video",
            reference_id=self.ref_id,
        )
        self.assertEqual(result.source.source_mode, "video")

    def test_freeform_job_without_reference(self) -> None:
        result = create_freeform_job(
            self.store,
            "Create 4 luxury supercar images",
            image_count=4,
            video_count=0,
        )
        self.assertIsNone(result.job.reference_id)
        self.assertIsNone(result.job.concept_id)
        self.assertEqual(result.job.origin_type, "freeform")
        self.assertEqual(result.job.image_count, 4)
        job_dir = Path(result.job.output_dir or "")
        self.assertTrue((job_dir / "job.json").is_file())
        self.assertTrue((job_dir / "CURSOR_GENERATION_PROMPT.md").is_file())

    def test_image_only_job(self) -> None:
        result = create_generation_job(
            self.store,
            origin_type="freeform",
            prompt_summary="Nighttime mansion stills",
            image_count=3,
            video_count=0,
        )
        payload = json.loads(Path(result.job.job_json_path).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["outputs"]), 3)
        self.assertTrue(all(o["asset_type"] == "image" for o in payload["outputs"]))

    def test_video_only_job(self) -> None:
        result = create_generation_job(
            self.store,
            origin_type="freeform",
            prompt_summary="Moving horror hallway clip",
            image_count=0,
            video_count=2,
        )
        payload = json.loads(Path(result.job.job_json_path).read_text(encoding="utf-8"))
        self.assertEqual(len(payload["outputs"]), 2)
        self.assertTrue(all(o["asset_type"] == "video" for o in payload["outputs"]))

    def test_mixed_job(self) -> None:
        result = create_generation_job(
            self.store,
            origin_type="concept",
            prompt_summary="Luxury mood board",
            image_count=6,
            video_count=2,
            reference_id=self.ref_id,
        )
        self.assertEqual(result.job.image_count, 6)
        self.assertEqual(result.job.video_count, 2)

    def test_global_reuse_seen_as_reference(self) -> None:
        report = check_global_reuse(self.store, reference_id=self.ref_id)
        self.assertTrue(report.seen_as_reference)

    def test_low_risk_scores_do_not_block_source_creation(self) -> None:
        report = check_global_reuse(
            self.store,
            platform="youtube",
            external_id="unknown00001",
            transcript="brand new unique transcript never used before xyz",
        )
        risk = score_source_media(
            source_mode="audio",
            media_type="audio",
            platform="youtube",
            has_transcript=True,
            reuse_report=report,
        )
        result = create_source_media(
            self.store,
            title="Third party podcast clip",
            source_mode="audio",
            platform="youtube",
            external_id="unknown00001",
            transcript="brand new unique transcript never used before xyz",
        )
        self.assertIsNotNone(result.source.id)
        self.assertLess(risk.rights_confidence, 60)

    def test_idempotent_import(self) -> None:
        result = create_generation_job(
            self.store,
            origin_type="freeform",
            prompt_summary="Test import",
            image_count=1,
            video_count=0,
        )
        job_dir = Path(result.job.output_dir or "")
        out_path = job_dir / "output" / "images" / "image_01.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

        first = import_generation_job(self.store, result.job.id)
        second = import_generation_job(self.store, result.job.id)
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_generated_assets_not_production_before_approval(self) -> None:
        result = create_generation_job(
            self.store,
            origin_type="freeform",
            prompt_summary="Approval test",
            image_count=1,
            video_count=0,
        )
        job_dir = Path(result.job.output_dir or "")
        out_path = job_dir / "output" / "images" / "image_01.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 64)
        import_generation_job(self.store, result.job.id)
        row = self.store._conn.execute(
            "SELECT production_asset, status FROM visual_assets ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(int(row["production_asset"]), 0)
        self.assertIn(row["status"], {"review", "auto_rejected", "generated"})

    def test_review_lists_image_and_video_types(self) -> None:
        for asset_type in ("image", "video"):
            self.store.create_visual_asset(
                concept_id=None,
                reference_id=None,
                niche="luxury",
                variation_family="test",
                asset_type=asset_type,
                provider="test",
                model="test",
                prompt=f"test {asset_type}",
                status="review",
            )
        images = self.store.list_visual_assets_for_review_extended(asset_type="image")
        videos = self.store.list_visual_assets_for_review_extended(asset_type="video")
        self.assertGreaterEqual(len(images), 1)
        self.assertGreaterEqual(len(videos), 1)


if __name__ == "__main__":
    unittest.main()
