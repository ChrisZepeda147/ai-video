"""Tests for YouTube metadata ingestion (mocked API)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from discovery.models import ReferenceVideo
from discovery.engine import ingest_youtube_search
from discovery.sources.youtube import YouTubeApiClient, item_to_reference
from discovery.store import DiscoveryStore


def api_video_item(video_id: str, *, duration: str = "PT58S", views: str = "1000000") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Title {video_id}",
            "channelTitle": "Channel X",
            "channelId": "UC_x",
            "description": "Desc",
            "publishedAt": "2026-02-01T00:00:00Z",
            "thumbnails": {"high": {"url": f"https://img/{video_id}.jpg"}},
        },
        "contentDetails": {"duration": duration},
        "statistics": {
            "viewCount": views,
            "likeCount": "1000",
            "commentCount": "50",
        },
    }


class FakeYouTubeClient:
    def __init__(self, video_ids: list[str]) -> None:
        self.video_ids = video_ids
        self.search_calls = 0
        self.detail_calls: list[list[str]] = []

    def search_video_ids(self, *, query: str, limit: int, shorts_only: bool) -> list[str]:
        self.search_calls += 1
        return self.video_ids[:limit]

    def fetch_video_details(self, video_ids: list[str]) -> list[ReferenceVideo]:
        self.detail_calls.append(list(video_ids))
        refs: list[ReferenceVideo] = []
        for vid in video_ids:
            item = api_video_item(vid)
            ref = item_to_reference(item, source_query=None)
            if ref:
                refs.append(ref)
        return refs


class YouTubeApiBatchTests(unittest.TestCase):
    def test_item_to_reference_parses_metadata(self) -> None:
        ref = item_to_reference(api_video_item("vid12345678"), source_query="test query")
        assert ref is not None
        self.assertEqual(ref.external_id, "vid12345678")
        self.assertEqual(ref.view_count, 1_000_000)
        self.assertEqual(ref.duration_sec, 58.0)
        self.assertFalse(ref.production_asset)

    def test_api_client_fetches_details_in_batches(self) -> None:
        client = YouTubeApiClient("fake-key")
        mock_service = MagicMock()
        client._youtube = mock_service

        ids = [f"id{i:02d}" for i in range(55)]
        list_mock = mock_service.videos.return_value.list

        def execute_side_effect() -> dict:
            call_args = list_mock.call_args
            batch_ids = call_args.kwargs["id"].split(",")
            return {"items": [api_video_item(vid) for vid in batch_ids]}

        list_mock.return_value.execute.side_effect = execute_side_effect

        refs = client.fetch_video_details(ids)
        self.assertEqual(len(refs), 55)
        self.assertEqual(list_mock.call_count, 2)
        first_id_arg = list_mock.call_args_list[0].kwargs["id"]
        self.assertEqual(len(first_id_arg.split(",")), 50)
        second_id_arg = list_mock.call_args_list[1].kwargs["id"]
        self.assertEqual(len(second_id_arg.split(",")), 5)

    def test_ingest_dedupes_and_records_run(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "test.sqlite"
        store = DiscoveryStore(db_path)
        fake = FakeYouTubeClient(["aaaaaaaaaaa", "bbbbbbbbbbb"])

        stats = ingest_youtube_search(
            store,
            query="creepy story",
            limit=2,
            shorts_only=False,
            client=fake,
            force_search=True,
        )
        self.assertEqual(stats.ids_found, 2)
        self.assertEqual(stats.ids_new, 2)
        self.assertEqual(fake.search_calls, 1)
        self.assertEqual(len(fake.detail_calls), 1)

        # Second ingest within cooldown should skip detail fetch.
        stats2 = ingest_youtube_search(
            store,
            query="creepy story",
            limit=2,
            shorts_only=False,
            client=fake,
            force_search=True,
        )
        self.assertEqual(stats2.ids_skipped_refresh, 2)
        self.assertEqual(stats2.ids_new, 0)
        self.assertEqual(len(fake.detail_calls), 1)

        run_count = store._conn.execute("SELECT COUNT(*) FROM discovery_runs").fetchone()[0]
        self.assertEqual(run_count, 2)

        total = store._conn.execute("SELECT COUNT(*) FROM reference_videos").fetchone()[0]
        self.assertEqual(total, 2)

        store.close()
        tmp.cleanup()

    def test_duplicate_ingest_updates_not_inserts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "test.sqlite"
        store = DiscoveryStore(db_path)
        fake = FakeYouTubeClient(["ccccccccccc"])

        ingest_youtube_search(
            store,
            query="first",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
        )
        ingest_youtube_search(
            store,
            query="second",
            limit=1,
            shorts_only=False,
            client=fake,
            force_search=True,
        )

        count = store._conn.execute("SELECT COUNT(*) FROM reference_videos").fetchone()[0]
        self.assertEqual(count, 1)
        row = store._conn.execute(
            "SELECT source_query FROM reference_videos WHERE external_id = ?",
            ("ccccccccccc",),
        ).fetchone()
        self.assertEqual(row["source_query"], "second")

        store.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
