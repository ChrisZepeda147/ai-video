"""Tests for virality scoring."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from discovery.scoring import compute_virality_metrics


class ViralityScoringTests(unittest.TestCase):
    def test_recent_fast_video_scores_higher_than_old_slow(self) -> None:
        now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        recent = compute_virality_metrics(
            view_count=1_000_000,
            like_count=40_000,
            comment_count=2_000,
            published_at=(now - timedelta(days=2)).isoformat(),
            now=now,
        )
        old = compute_virality_metrics(
            view_count=10_000_000,
            like_count=200_000,
            comment_count=50_000,
            published_at=(now - timedelta(days=5 * 365)).isoformat(),
            now=now,
        )
        self.assertGreater(recent.virality_score, old.virality_score)
        self.assertGreater(recent.views_per_day or 0, old.views_per_day or 0)

    def test_missing_engagement_fields_do_not_crash(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        metrics = compute_virality_metrics(
            view_count=500_000,
            like_count=None,
            comment_count=None,
            published_at=(now - timedelta(hours=12)).isoformat(),
            now=now,
        )
        self.assertIsNone(metrics.like_ratio)
        self.assertIsNone(metrics.comment_ratio)
        self.assertGreater(metrics.virality_score, 0)
        self.assertLessEqual(metrics.virality_score, 100)


if __name__ == "__main__":
    unittest.main()
