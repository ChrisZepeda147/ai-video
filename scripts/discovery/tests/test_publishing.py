"""Tests for social publishing layer — all providers mocked."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from discovery.models import ReferenceVideo
from discovery.production_projects import approve_project, create_production_project
from discovery.publishing.accounts import import_mock_account, verify_publishing_account
from discovery.publishing.jobs import (
    cancel_publishing_job,
    create_publishing_jobs,
    publish_due_jobs,
    publish_job,
    retry_publishing_job,
)
from discovery.store import DiscoveryStore


def seed_approved_project(store, tmp: Path) -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id="pub00000001",
        url="https://www.youtube.com/watch?v=pub00000001",
        title="Publish test clip",
        description="Test",
        channel="Clips",
        duration_sec=30.0,
        production_asset=False,
    )
    ref_id = store.upsert_reference(ref, is_new=True)
    sid = store.create_source_media(
        title="Publish test",
        source_mode="audio",
        media_type="audio",
        reference_id=ref_id,
        platform="youtube",
        external_id="pub00000001",
        url=ref.url,
        local_path=str(tmp / "fake.mp3"),
    )
    output = tmp / "final.mp4"
    output.write_bytes(b"fake-video")
    project = create_production_project(
        store,
        title="Approved Short",
        source_media_id=sid,
        format_profile="audio_visuals",
    )
    store.update_production_project_status(project.project_id, "review")
    store.update_production_project_rendered(
        project.project_id,
        output_path=str(output),
        duration_sec=30.0,
        monetization_confidence=40,
        rights_confidence=35,
        reuse_confidence=60,
        risk_explanations_json="{}",
        status="review",
    )
    approve_project(store, project.project_id)
    return project.project_id


class PublishingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "pub.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        os.environ["DISCOVERY_PUBLISH_DRY_RUN"] = "1"
        os.environ["DISCOVERY_PUBLISH_PROVIDER"] = "mock"
        self.store = DiscoveryStore(self.db_path)
        self.project_id = seed_approved_project(self.store, Path(self.tmp.name))
        self.yt_account = import_mock_account(
            self.store, platform="youtube", display_name="LuxuryMindset", username="LuxuryMindset", niche="luxury"
        )
        self.tt_account = import_mock_account(
            self.store, platform="tiktok", display_name="LuxuryMindset", username="LuxuryMindset", niche="luxury"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)
        os.environ.pop("DISCOVERY_PUBLISH_DRY_RUN", None)
        os.environ.pop("DISCOVERY_PUBLISH_PROVIDER", None)

    def test_multiple_accounts_per_platform(self) -> None:
        second = import_mock_account(
            self.store, platform="youtube", display_name="HorrorStories", username="HorrorStories", niche="horror"
        )
        accounts = self.store.list_publishing_accounts(platform="youtube")
        self.assertEqual(len(accounts), 2)
        self.assertIn(second, [a.id for a in accounts])

    def test_approved_project_can_create_jobs(self) -> None:
        results = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account, self.tt_account],
            title="Luxury discipline",
            caption="Stay focused",
            hashtags="#luxury #mindset",
        )
        self.assertEqual(len(results), 2)
        self.assertEqual({r.status for r in results}, {"draft"})

    def test_unapproved_project_rejected(self) -> None:
        draft = create_production_project(self.store, title="Draft only")
        with self.assertRaises(ValueError):
            create_publishing_jobs(
                self.store,
                production_project_id=draft.project_id,
                account_ids=[self.yt_account],
            )

    def test_publish_now_job(self) -> None:
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        result = publish_job(self.store, created[0].job_id)
        self.assertIn(result.status, {"published", "processing"})
        self.assertTrue(result.platform_post_id)

    def test_scheduled_job(self) -> None:
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.tt_account],
            scheduled_at="2099-01-01T12:00:00+00:00",
        )
        job = self.store.get_publishing_job(created[0].job_id)
        self.assertEqual(job.status, "scheduled")

    def test_multi_platform_separate_jobs(self) -> None:
        results = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account, self.tt_account],
        )
        platforms = {self.store.get_publishing_job(r.job_id).platform for r in results}
        self.assertEqual(platforms, {"youtube", "tiktok"})

    def test_duplicate_request_does_not_double_publish(self) -> None:
        first = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        published = publish_job(self.store, first[0].job_id)
        again = publish_job(self.store, first[0].job_id)
        self.assertTrue(again.duplicate)
        self.assertEqual(published.platform_post_id, again.platform_post_id)
        dup_create = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        self.assertTrue(dup_create[0].duplicate)

    def test_retry_failed_job(self) -> None:
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        job_id = created[0].job_id
        self.store.fail_publishing_job(job_id, "network timeout")
        result = retry_publishing_job(self.store, job_id)
        self.assertIn(result.status, {"published", "processing"})

    def test_cancel_scheduled(self) -> None:
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
            scheduled_at="2099-06-01T10:00:00+00:00",
        )
        result = cancel_publishing_job(self.store, created[0].job_id)
        self.assertEqual(result.status, "cancelled")

    def test_publish_due_worker(self) -> None:
        create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
            scheduled_at="2000-01-01T00:00:00+00:00",
        )
        results = publish_due_jobs(self.store, limit=5)
        self.assertGreaterEqual(len(results), 1)

    def test_verify_account(self) -> None:
        info = verify_publishing_account(self.store, self.yt_account)
        self.assertTrue(info["ok"])

    def test_low_risk_does_not_block_publish(self) -> None:
        project = self.store.get_production_project(self.project_id)
        self.assertLess(project.reuse_confidence or 0, 70)
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        result = publish_job(self.store, created[0].job_id)
        self.assertIn(result.status, {"published", "processing"})

    def test_source_still_marked_used_from_approval(self) -> None:
        project = self.store.get_production_project(self.project_id)
        source = self.store.get_source_media(project.source_media_id)
        self.assertTrue(source.actually_used_in_content)

    def test_publishing_history_records_account(self) -> None:
        created = create_publishing_jobs(
            self.store,
            production_project_id=self.project_id,
            account_ids=[self.yt_account],
        )
        publish_job(self.store, created[0].job_id)
        history = self.store.list_published_jobs_for_project(self.project_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].account_id, self.yt_account)
        self.assertEqual(history[0].platform, "youtube")


if __name__ == "__main__":
    unittest.main()
