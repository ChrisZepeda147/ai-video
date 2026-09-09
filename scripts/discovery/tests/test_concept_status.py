"""Tests for concept status workflow."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discovery.models import ReferenceVideo
from discovery.scoring import compute_virality_metrics
from discovery.store import DiscoveryStore


def seed_reference(store: DiscoveryStore) -> tuple[int, int]:
    ref = ReferenceVideo(
        platform="youtube",
        external_id="statusref00001",
        url="https://www.youtube.com/watch?v=statusref00001",
        title="Test reference",
        description="Test",
        channel="Ch",
        duration_sec=58.0,
        view_count=100_000,
        like_count=1000,
        comment_count=100,
        published_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        production_asset=False,
    )
    ref_id = store.upsert_reference(ref, is_new=True, refreshed=True)
    metrics = compute_virality_metrics(
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
        published_at=ref.published_at,
    )
    store.save_metrics_with_snapshots(
        ref_id,
        metrics,
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
    )
    analysis = store.save_analysis(
        reference_id=ref_id,
        provider="mock",
        model="mock",
        analysis_version="v1",
        analysis_json={"inferred": {"genre": "horror"}},
    )
    concept = store.save_concept(
        reference_id=ref_id,
        analysis_id=analysis.id,
        niche="horror",
        title="Concept A",
        status="generated",
    )
    return ref_id, concept.id


class ConceptStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DiscoveryStore(Path(self.tmp.name) / "test.sqlite")
        self.ref_id, self.concept_id = seed_reference(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_shortlist_from_generated(self) -> None:
        updated = self.store.update_concept_status(self.concept_id, "shortlisted")
        self.assertEqual(updated.status, "shortlisted")

    def test_approve_increments_counter_once(self) -> None:
        self.store.approve_concepts([self.concept_id])
        usage = self.store.get_reference_usage(self.ref_id)
        self.assertEqual(usage["concepts_approved"], 1)
        self.store.approve_concepts([self.concept_id])
        usage = self.store.get_reference_usage(self.ref_id)
        self.assertEqual(usage["concepts_approved"], 1)

    def test_reject_from_approved_decrements_counter(self) -> None:
        self.store.approve_concepts([self.concept_id])
        self.store.reject_concepts([self.concept_id])
        usage = self.store.get_reference_usage(self.ref_id)
        self.assertEqual(usage["concepts_approved"], 0)

    def test_invalid_transition_rejected(self) -> None:
        self.store.update_concept_status(self.concept_id, "rejected")
        with self.assertRaises(ValueError):
            self.store.update_concept_status(self.concept_id, "shortlisted")

    def test_list_concepts_by_status(self) -> None:
        self.store.shortlist_concepts([self.concept_id])
        rows = self.store.list_concepts(status="shortlisted")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
