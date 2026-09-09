"""Tests for discovery SQLite store."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discovery.models import ReferenceVideo
from discovery.store import DiscoveryStore, now_iso


def sample_ref(
    external_id: str = "abc12345678",
    *,
    title: str = "Creepy Story Short",
    source_query: str = "creepy story",
) -> ReferenceVideo:
    return ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title=title,
        channel="Test Channel",
        channel_id="UC_test",
        description="A scary story told in 60 seconds.",
        duration_sec=58.0,
        view_count=1_250_000,
        like_count=45_000,
        comment_count=900,
        published_at="2026-01-15T12:00:00Z",
        thumbnail_url="https://i.ytimg.com/vi/test/hqdefault.jpg",
        source_query=source_query,
        production_asset=False,
    )


class DiscoveryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.store = DiscoveryStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_duplicate_youtube_ids_do_not_create_duplicate_records(self) -> None:
        ref = sample_ref("dup11111111")
        self.store.upsert_reference(ref, is_new=True)
        self.store.upsert_reference(ref, is_new=False)

        count = self.store._conn.execute("SELECT COUNT(*) FROM reference_videos").fetchone()[0]
        self.assertEqual(count, 1)

        row = self.store.get_reference("youtube", "dup11111111")
        assert row is not None
        self.assertEqual(row.external_id, "dup11111111")

    def test_production_asset_defaults_to_false(self) -> None:
        ref = sample_ref("prod00000001")
        self.store.upsert_reference(ref, is_new=True)

        row = self.store._conn.execute(
            "SELECT production_asset FROM reference_videos WHERE external_id = ?",
            ("prod00000001",),
        ).fetchone()
        self.assertEqual(row["production_asset"], 0)

        stats = self.store.catalog_stats()
        self.assertEqual(stats.production_assets, 0)

    def test_metadata_is_stored_correctly(self) -> None:
        ref = sample_ref("meta22222222")
        self.store.upsert_reference(ref, is_new=True)

        stored = self.store.get_reference("youtube", "meta22222222")
        assert stored is not None
        self.assertEqual(stored.title, "Creepy Story Short")
        self.assertEqual(stored.channel, "Test Channel")
        self.assertEqual(stored.channel_id, "UC_test")
        self.assertEqual(stored.description, "A scary story told in 60 seconds.")
        self.assertEqual(stored.duration_sec, 58.0)
        self.assertEqual(stored.view_count, 1_250_000)
        self.assertEqual(stored.like_count, 45_000)
        self.assertEqual(stored.comment_count, 900)
        self.assertEqual(stored.published_at, "2026-01-15T12:00:00Z")
        self.assertEqual(stored.thumbnail_url, "https://i.ytimg.com/vi/test/hqdefault.jpg")
        self.assertEqual(stored.source_query, "creepy story")
        self.assertFalse(stored.production_asset)

    def test_needs_refresh_respects_cooldown(self) -> None:
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(microsecond=0).isoformat()

        self.assertFalse(self.store.needs_refresh(recent, cooldown_hours=24))
        self.assertTrue(self.store.needs_refresh(old, cooldown_hours=24))
        self.assertTrue(self.store.needs_refresh(recent, cooldown_hours=0))

    def test_touch_last_seen_updates_timestamp(self) -> None:
        ref = sample_ref("touch33333333")
        self.store.upsert_reference(ref, is_new=True)
        before = self.store.get_reference("youtube", "touch33333333")
        assert before is not None

        new_ts = "2099-01-01T00:00:00+00:00"
        updated = self.store.touch_last_seen("youtube", ["touch33333333"], when=new_ts)
        self.assertEqual(updated, 1)

        after = self.store.get_reference("youtube", "touch33333333")
        assert after is not None
        row = self.store._conn.execute(
            "SELECT last_seen_at FROM reference_videos WHERE external_id = ?",
            ("touch33333333",),
        ).fetchone()
        self.assertEqual(row["last_seen_at"], new_ts)

    def test_discovery_runs_are_recorded(self) -> None:
        run_id = self.store.start_discovery_run(
            platform="youtube",
            source_query="creepy story",
            search_limit=10,
        )
        from discovery.models import DiscoveryRunStats

        stats = DiscoveryRunStats(ids_found=3, ids_new=2, ids_updated=1, ids_skipped_refresh=0)
        self.store.finish_discovery_run(run_id, stats=stats, status="ok")

        row = self.store._conn.execute(
            "SELECT * FROM discovery_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        self.assertEqual(row["platform"], "youtube")
        self.assertEqual(row["source_query"], "creepy story")
        self.assertEqual(row["search_limit"], 10)
        self.assertEqual(row["ids_found"], 3)
        self.assertEqual(row["ids_new"], 2)
        self.assertEqual(row["ids_updated"], 1)
        self.assertEqual(row["status"], "ok")
        self.assertIsNotNone(row["finished_at"])

        catalog = self.store.catalog_stats()
        self.assertEqual(catalog.discovery_runs, 1)


if __name__ == "__main__":
    unittest.main()
