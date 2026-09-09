"""Tests for pilot preflight, batches, and pending tasks."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery.models import ReferenceVideo
from discovery.pilot.batches import create_pilot_batch, get_pilot_results, run_pending_pilot_tasks
from discovery.pilot.preflight import run_preflight
from discovery.pilot.progress import compute_item_stages, refresh_item_progress
from discovery.production_projects import approve_project, create_production_project
from discovery.publishing.accounts import import_mock_account
from discovery.publishing.jobs import create_publishing_jobs, create_test_publish_job, publish_test_upload
from discovery.store import DiscoveryStore
from discovery.analytics.profiles import build_performance_profile


def seed_reference(store, *, external_id: str, title: str, niche: str = "luxury") -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title=title,
        description="Discipline and success podcast clip motivational",
        channel="Mindset Podcast",
        duration_sec=55.0,
        production_asset=False,
    )
    ref_id = store.upsert_reference(ref, is_new=True)
    store.upsert_niche_link(ref_id, niche, 0.9, "test")
    return ref_id


class PilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "pilot.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        os.environ["DISCOVERY_PUBLISH_DRY_RUN"] = "1"
        os.environ["DISCOVERY_PUBLISH_PROVIDER"] = "mock"
        self.store = DiscoveryStore(self.db_path)
        for i in range(5):
            seed_reference(
                self.store,
                external_id=f"pilotref{i:09d}",
                title=f"Unused podcast discipline clip {i}",
            )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_preflight_returns_grouped_checks(self) -> None:
        report = run_preflight(self.store)
        self.assertIn("core", report["groups"])
        self.assertIn("summary", report)
        self.assertIn("pilot_ready", report["summary"])

    def test_preflight_optional_deps_warn_not_fail(self) -> None:
        report = run_preflight(self.store)
        statuses = {c["status"] for g in report["groups"].values() for c in g}
        self.assertTrue(statuses.issubset({"ready", "warning", "not_configured"}))

    def test_create_pilot_batch_mixed_strategies(self) -> None:
        batch_id = create_pilot_batch(
            self.store,
            name="Luxury Pilot",
            niche="luxury",
            account_id=None,
            batch_size=3,
        )
        items = self.store.list_pilot_batch_items(batch_id)
        self.assertEqual(len(items), 3)
        strategies = {i.strategy for i in items}
        self.assertIn("podcast_audio", strategies)
        self.assertIn("source_video", strategies)
        self.assertIn("original_freeform", strategies)

    def test_progress_stages_computed(self) -> None:
        batch_id = create_pilot_batch(self.store, name="T", niche="luxury", account_id=None, batch_size=1)
        item = self.store.list_pilot_batch_items(batch_id)[0]
        stages = refresh_item_progress(self.store, item.id)
        self.assertIn("reference", stages)
        self.assertIn("visual_generation", stages)

    def test_run_pending_does_not_live_publish(self) -> None:
        batch_id = create_pilot_batch(self.store, name="T", niche="luxury", account_id=None, batch_size=1)
        report = run_pending_pilot_tasks(self.store, batch_id=batch_id, live_publish=False)
        self.assertFalse(report.errors or any("live" in t.action for t in report.tasks))

    def test_pilot_results_aggregation(self) -> None:
        batch_id = create_pilot_batch(self.store, name="T", niche="luxury", account_id=None, batch_size=2)
        results = get_pilot_results(self.store, batch_id)
        self.assertEqual(len(results), 2)
        self.assertIn("disclaimer", results[0])

    def test_test_publish_requires_live(self) -> None:
        ref_id = seed_reference(self.store, external_id="pub00000002", title="Test")
        sid = self.store.create_source_media(
            title="Test",
            source_mode="audio",
            media_type="audio",
            reference_id=ref_id,
            platform="youtube",
            external_id="pub00000002",
            url="https://example.com",
            local_path=str(Path(self.tmp.name) / "fake.mp3"),
        )
        output = Path(self.tmp.name) / "final.mp4"
        output.write_bytes(b"fake")
        project = create_production_project(
            self.store, title="Test Short", source_media_id=sid, niche="luxury"
        )
        self.store.update_production_project_rendered(
            project.project_id,
            output_path=str(output),
            duration_sec=30.0,
            monetization_confidence=40,
            rights_confidence=35,
            reuse_confidence=60,
            risk_explanations_json="{}",
            status="review",
        )
        approve_project(self.store, project.project_id)
        account_id = import_mock_account(
            self.store, platform="youtube", display_name="Pilot YT", username="pilot", niche="luxury"
        )
        job = create_test_publish_job(
            self.store,
            production_project_id=project.project_id,
            account_id=account_id,
        )
        with self.assertRaises(ValueError):
            publish_test_upload(self.store, job.job_id, live=False)

    def test_test_publish_mock_when_live(self) -> None:
        ref_id = seed_reference(self.store, external_id="pub00000003", title="Test2")
        sid = self.store.create_source_media(
            title="Test2",
            source_mode="audio",
            media_type="audio",
            reference_id=ref_id,
            platform="youtube",
            external_id="pub00000003",
            url="https://example.com",
            local_path=str(Path(self.tmp.name) / "fake2.mp3"),
        )
        output = Path(self.tmp.name) / "final2.mp4"
        output.write_bytes(b"fake")
        project = create_production_project(
            self.store, title="Test Short 2", source_media_id=sid, niche="luxury"
        )
        self.store.update_production_project_rendered(
            project.project_id,
            output_path=str(output),
            duration_sec=30.0,
            monetization_confidence=40,
            rights_confidence=35,
            reuse_confidence=60,
            risk_explanations_json="{}",
            status="review",
        )
        approve_project(self.store, project.project_id)
        account_id = import_mock_account(
            self.store, platform="youtube", display_name="Pilot YT2", username="pilot2", niche="luxury"
        )
        job = create_test_publish_job(
            self.store,
            production_project_id=project.project_id,
            account_id=account_id,
        )
        result = publish_test_upload(self.store, job.job_id, live=True)
        self.assertIn(result.status, ("published", "processing"))

    def test_analytics_low_data_confidence(self) -> None:
        profile = build_performance_profile(self.store, niche="luxury")
        self.assertEqual(profile.get("data_confidence"), "low")
        self.assertEqual(profile.get("data_confidence_label"), "LOW DATA CONFIDENCE")

    def test_publish_still_requires_approval(self) -> None:
        from discovery.publishing.jobs import publish_job

        account_id = import_mock_account(
            self.store, platform="youtube", display_name="X", username="x", niche="luxury"
        )
        project = create_production_project(self.store, title="Draft", niche="luxury")
        with self.assertRaises(ValueError):
            create_publishing_jobs(
                self.store,
                production_project_id=project.project_id,
                account_ids=[account_id],
            )


if __name__ == "__main__":
    unittest.main()
