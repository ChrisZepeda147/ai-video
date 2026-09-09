"""Tests for analytics + learning layer — all platform calls mocked."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery.analytics.concept_context import build_performance_context
from discovery.analytics.discovery_feedback import compute_internal_fit
from discovery.analytics.patterns import (
    aggregate_hooks,
    compare_format_profiles,
)
from discovery.analytics.profiles import build_performance_profile
from discovery.analytics.refresh import refresh_analytics, refresh_interval_hours, should_refresh_job
from discovery.analytics.scoring import score_post_performance
from discovery.analytics.workbench_context import enrich_workbench_query, query_wants_performance_context
from discovery.models import ReferenceVideo
from discovery.production_projects import approve_project, create_production_project
from discovery.publishing.accounts import import_mock_account
from discovery.publishing.jobs import create_publishing_jobs, publish_job
from discovery.store import DiscoveryStore


def seed_published_job(store, tmp: Path, *, niche: str = "luxury", hook: str = "Most people never build real discipline") -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=f"an{niche[:3]}000001",
        url="https://www.youtube.com/watch?v=an000000001",
        title=f"{niche} discipline clip",
        description="Success mindset podcast",
        channel="Mindset Clips",
        duration_sec=45.0,
        production_asset=False,
    )
    ref_id = store.upsert_reference(ref, is_new=True)
    store.upsert_niche_link(ref_id, niche, 0.9, "test")
    sid = store.create_source_media(
        title="Analytics test source",
        source_mode="audio",
        media_type="audio",
        reference_id=ref_id,
        platform="youtube",
        external_id=ref.external_id,
        url=ref.url,
        local_path=str(tmp / "fake.mp3"),
    )
    output = tmp / "final.mp4"
    output.write_bytes(b"fake-video")
    project = create_production_project(
        store,
        title=f"{niche.title()} Short",
        source_media_id=sid,
        format_profile="audio_visuals",
        niche=niche,
        hook_text=hook,
        caption_preset="viral_bold",
    )
    store.update_production_project_status(project.project_id, "review")
    store.update_production_project_rendered(
        project.project_id,
        output_path=str(output),
        duration_sec=45.0,
        monetization_confidence=40,
        rights_confidence=35,
        reuse_confidence=60,
        risk_explanations_json="{}",
        status="review",
    )
    approve_project(store, project.project_id)
    account_id = import_mock_account(
        store, platform="youtube", display_name=f"{niche} Account", username=f"{niche}_acct", niche=niche
    )
    jobs = create_publishing_jobs(
        store,
        production_project_id=project.project_id,
        account_ids=[account_id],
        title=f"{niche.title()} Short",
    )
    publish_job(store, jobs[0].job_id)
    job = store.get_publishing_job(jobs[0].job_id)
    assert job and job.platform_post_id
    return jobs[0].job_id


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "analytics.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        os.environ["DISCOVERY_PUBLISH_DRY_RUN"] = "1"
        os.environ["DISCOVERY_PUBLISH_PROVIDER"] = "mock"
        self.store = DiscoveryStore(self.db_path)
        self.job_id = seed_published_job(self.store, Path(self.tmp.name))

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_refresh_creates_snapshot_and_features(self) -> None:
        results = refresh_analytics(self.store, job_id=self.job_id, force=True)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].refreshed)
        features = self.store.get_analytics_post_features(self.job_id)
        self.assertIsNotNone(features)
        self.assertIsNotNone(features.hook_formula)
        latest = self.store.get_latest_analytics_snapshot(self.job_id)
        self.assertIsNotNone(latest)
        self.assertIsNotNone(latest.views)
        self.assertIsNotNone(latest.performance_score)
        self.assertIn(latest.performance_tier, ("underperforming", "average", "strong", "breakout"))

    def test_snapshots_accumulate(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        history = self.store.list_analytics_snapshots_for_job(self.job_id)
        self.assertGreaterEqual(len(history), 2)

    def test_cooldown_skips_unnecessary_refresh(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        should, reason = should_refresh_job(self.store, self.job_id, force=False)
        self.assertFalse(should)
        self.assertTrue(reason and reason.startswith("cooldown"))

    def test_scoring_normalizes_by_account_baseline(self) -> None:
        score = score_post_performance(
            {"views": 50000, "likes": 2000, "comments": 100},
            account_baseline_views=10000,
            account_baseline_engagement=0.04,
            published_at="2026-03-01T12:00:00+00:00",
        )
        self.assertGreaterEqual(score["performance_score"], 40)
        self.assertGreater(score["views_vs_account_median"], 1.0)

    def test_hook_aggregation(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        rows = self.store.list_analytics_posts_with_latest(limit=10)
        hooks = aggregate_hooks(rows)
        self.assertTrue(hooks)
        self.assertIn("hook_formula", hooks[0])

    def test_format_comparison(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        rows = self.store.list_analytics_posts_with_latest(limit=10)
        comparison = compare_format_profiles(rows)
        self.assertIn("source_audio", comparison)

    def test_performance_profile(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        profile = build_performance_profile(self.store, niche="luxury")
        self.assertEqual(profile["sample_size"], 1)
        row = self.store.get_performance_profile("luxury")
        self.assertIsNotNone(row)

    def test_internal_fit_keeps_external_virality_separate(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        build_performance_profile(self.store, niche="luxury")
        ref_rows = self.store.list_dashboard_references(niche="luxury", limit=1)
        ref_id = int(ref_rows[0]["reference"].id)
        fit = compute_internal_fit(self.store, reference_id=ref_id, niche="luxury")
        self.assertIn("components", fit)
        self.assertIn("external_virality", fit["components"])
        self.assertIn("internal_performance_fit", fit["components"])

    def test_concept_context_advisory(self) -> None:
        refresh_analytics(self.store, job_id=self.job_id, force=True)
        build_performance_profile(self.store, niche="luxury")
        ctx = build_performance_context(self.store, niche="luxury")
        self.assertIsNotNone(ctx)
        self.assertIn("experiments", ctx.lower())

    def test_workbench_performance_query(self) -> None:
        self.assertTrue(query_wants_performance_context("Find unused clips similar to our best-performing videos"))
        enriched, meta = enrich_workbench_query(self.store, "best-performing luxury visuals", niche="luxury")
        self.assertTrue(meta["performance_aware"] or "luxury" in enriched)

    def test_missing_metrics_handled(self) -> None:
        score = score_post_performance(
            {},
            account_baseline_views=1000,
            account_baseline_engagement=0.03,
            published_at=None,
        )
        self.assertEqual(score["performance_tier"], "underperforming")

    def test_refresh_interval_prioritizes_recent(self) -> None:
        from datetime import datetime, timezone

        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.assertLess(refresh_interval_hours(recent, last_snapshot_at=None), 24)

    @patch("discovery.analytics.refresh.build_publishing_provider")
    def test_provider_error_graceful(self, mock_build) -> None:
        class Broken:
            platform = "youtube"

            def fetch_post_metrics(self, credentials, platform_post_id):
                raise RuntimeError("API down")

        mock_build.return_value = Broken()
        result = refresh_analytics(self.store, job_id=self.job_id, force=True)[0]
        self.assertFalse(result.refreshed)
        self.assertIn("API down", result.error or "")


if __name__ == "__main__":
    unittest.main()
