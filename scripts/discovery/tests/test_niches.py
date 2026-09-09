"""Tests for niche assignment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discovery.models import ReferenceVideo
from discovery.niches import assign_niches_for_reference, load_niches_config
from discovery.store import DiscoveryStore


class NicheAssignmentTests(unittest.TestCase):
    def test_one_reference_can_belong_to_several_niches(self) -> None:
        niches = load_niches_config()
        assignments = assign_niches_for_reference(
            niches,
            query="scary story",
            title="A creepy mystery thriller at midnight",
            description="Horror relationship crime story",
            primary_niche="horror",
        )
        names = {name for name, _, _ in assignments}
        self.assertIn("horror", names)
        self.assertGreaterEqual(len(names), 2)

    def test_duplicate_discovery_updates_niche_links_not_videos(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "test.sqlite"
        store = DiscoveryStore(db_path)
        ref = ReferenceVideo(
            platform="youtube",
            external_id="niche1111111",
            url="https://www.youtube.com/watch?v=niche1111111",
            title="Scary mystery thriller story",
            description="creepy horror",
            view_count=100_000,
            published_at="2026-02-01T00:00:00+00:00",
            production_asset=False,
        )
        ref_id = store.upsert_reference(ref, is_new=True, refreshed=True)
        store.upsert_niche_link(ref_id, "horror", 0.95, "search_term")
        store.upsert_niche_link(ref_id, "mystery", 0.88, "keyword_rules")

        store.upsert_niche_link(ref_id, "thriller", 0.91, "keyword_rules")
        count = store._conn.execute("SELECT COUNT(*) FROM reference_videos").fetchone()[0]
        niche_count = store._conn.execute(
            "SELECT COUNT(*) FROM reference_niches WHERE reference_id = ?",
            (ref_id,),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(niche_count, 3)

        store.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
