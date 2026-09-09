"""Tests for discovery engine orchestration."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discovery.engine import ingest_youtube_search, run_multi_niche_discovery
from discovery.models import ReferenceVideo
from discovery.sources.youtube import item_to_reference
from discovery.store import DiscoveryStore


def api_video_item(video_id: str, *, views: str = "1000000") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Scary mystery thriller {video_id}",
            "channelTitle": "Channel X",
            "channelId": "UC_x",
            "description": "creepy horror crime story",
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "thumbnails": {"high": {"url": f"https://img/{video_id}.jpg"}},
        },
        "contentDetails": {"duration": "PT58S"},
        "statistics": {"viewCount": views, "likeCount": "1000", "commentCount": "50"},
    }


class FakeYouTubeClient:
    def __init__(self, mapping: dict[str, list[str]] | None = None) -> None:
        self.mapping = mapping or {}
        self.search_calls: list[str] = []
        self.detail_calls: list[list[str]] = []

    def search_video_ids(self, *, query: str, limit: int, shorts_only: bool) -> list[str]:
        self.search_calls.append(query)
        ids = self.mapping.get(query, [f"id{len(self.search_calls):02d}000000001"])
        return ids[:limit]

    def fetch_video_details(self, video_ids: list[str]) -> list[ReferenceVideo]:
        self.detail_calls.append(list(video_ids))
        refs: list[ReferenceVideo] = []
        for vid in video_ids:
            ref = item_to_reference(api_video_item(vid), source_query=None)
            if ref:
                refs.append(ref)
        return refs


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.niches_path = Path(self.tmp.name) / "niches.json"
        self.niches_path.write_text(
            json.dumps(
                {
                    "horror": {
                        "enabled": True,
                        "search_terms": ["scary story", "creepy story"],
                        "keywords": ["scary", "horror"],
                        "maximum_searches_per_discovery_run": 2,
                    },
                    "mystery": {
                        "enabled": True,
                        "search_terms": ["mystery story"],
                        "keywords": ["mystery"],
                        "maximum_searches_per_discovery_run": 1,
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_max_searches_global_limit_respected(self) -> None:
        store = DiscoveryStore(self.db_path)
        fake = FakeYouTubeClient(
            {
                "scary story": ["aaaaaaaaaaa"],
                "creepy story": ["bbbbbbbbbbb"],
                "mystery story": ["ccccccccccc"],
            }
        )
        result = run_multi_niche_discovery(
            store,
            max_searches=2,
            per_search_limit=1,
            force_search=True,
            niches_config_path=self.niches_path,
            client=fake,
        )
        store.close()
        self.assertEqual(result.searches_executed, 2)
        self.assertGreaterEqual(result.searches_skipped_limit, 1)

    def test_search_cooldown_skips_repeat_query(self) -> None:
        store = DiscoveryStore(self.db_path)
        fake = FakeYouTubeClient({"creepy story": ["ddddddddddd"]})

        ingest_youtube_search(
            store,
            query="creepy story",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
            niches_config_path=self.niches_path,
        )
        stats2 = ingest_youtube_search(
            store,
            query="creepy story",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=False,
            search_cooldown_hours_override=24,
            niches_config_path=self.niches_path,
        )
        store.close()
        self.assertEqual(len(fake.search_calls), 1)
        self.assertEqual(stats2.searches_skipped, 1)

    def test_force_bypasses_search_cooldown(self) -> None:
        store = DiscoveryStore(self.db_path)
        fake = FakeYouTubeClient({"creepy story": ["eeeeeeeeeee"]})

        ingest_youtube_search(
            store,
            query="creepy story",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
            niches_config_path=self.niches_path,
        )
        ingest_youtube_search(
            store,
            query="creepy story",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
            niches_config_path=self.niches_path,
        )
        store.close()
        self.assertEqual(len(fake.search_calls), 2)

    def test_metadata_refresh_respects_age_based_timing(self) -> None:
        store = DiscoveryStore(self.db_path)
        fake = FakeYouTubeClient(
            {
                "creepy story": ["fffffffffff"],
                "other query": ["fffffffffff"],
            }
        )

        ingest_youtube_search(
            store,
            query="creepy story",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
            niches_config_path=self.niches_path,
        )
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        store._conn.execute(
            "UPDATE reference_videos SET last_refreshed_at = ?, published_at = ? WHERE external_id = ?",
            (recent, recent, "fffffffffff"),
        )
        store._conn.commit()

        stats = ingest_youtube_search(
            store,
            query="other query",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
            niches_config_path=self.niches_path,
        )
        store.close()
        self.assertEqual(len(fake.detail_calls), 1)
        self.assertEqual(stats.ids_skipped_refresh, 1)

    def test_top_references_sort_by_virality_score(self) -> None:
        store = DiscoveryStore(self.db_path)
        low = ReferenceVideo(
            platform="youtube",
            external_id="low00000001",
            url="https://youtube.com/watch?v=low00000001",
            title="Low",
            view_count=1_000,
            published_at="2020-01-01T00:00:00+00:00",
            production_asset=False,
        )
        high = ReferenceVideo(
            platform="youtube",
            external_id="high0000001",
            url="https://youtube.com/watch?v=high0000001",
            title="High",
            view_count=2_000_000,
            published_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            production_asset=False,
        )
        from discovery.scoring import compute_virality_metrics

        low_id = store.upsert_reference(low, is_new=True, refreshed=True)
        high_id = store.upsert_reference(high, is_new=True, refreshed=True)
        low_m = compute_virality_metrics(
            view_count=low.view_count,
            like_count=None,
            comment_count=None,
            published_at=low.published_at,
        )
        high_m = compute_virality_metrics(
            view_count=high.view_count,
            like_count=50_000,
            comment_count=2_000,
            published_at=high.published_at,
        )
        store.save_metrics_with_snapshots(
            low_id, low_m, view_count=low.view_count, like_count=None, comment_count=None
        )
        store.save_metrics_with_snapshots(
            high_id,
            high_m,
            view_count=high.view_count,
            like_count=50_000,
            comment_count=2_000,
        )
        store.upsert_niche_link(low_id, "horror", 0.9, "test")
        store.upsert_niche_link(high_id, "horror", 0.9, "test")

        top = store.list_top_references(niche="horror", min_score=0, limit=10)
        store.close()
        self.assertEqual(top[0].reference.external_id, "high0000001")
        self.assertGreater(top[0].reference.virality_score or 0, top[1].reference.virality_score or 0)


if __name__ == "__main__":
    unittest.main()
