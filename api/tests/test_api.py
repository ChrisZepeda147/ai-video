"""Tests for the discovery FastAPI layer."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from discovery.models import ReferenceVideo  # noqa: E402
from discovery.scoring import compute_virality_metrics  # noqa: E402
from discovery.store import DiscoveryStore  # noqa: E402


def seed_reference(store: DiscoveryStore, *, external_id: str, title: str) -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title=title,
        description="Test reference",
        channel="Test Channel",
        duration_sec=58.0,
        view_count=1_000_000,
        like_count=40_000,
        comment_count=1_000,
        published_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        thumbnail_url="https://i.ytimg.com/vi/abc123/hqdefault.jpg",
        source_query="scary story",
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
    store.upsert_niche_link(ref_id, "horror", 0.95, "test")
    return ref_id


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "api-test.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        self.store = DiscoveryStore(self.db_path)
        seed_reference(self.store, external_id="api00000001", title="Foggy mountain road story")
        seed_reference(self.store, external_id="api00000002", title="Parking garage horror")
        self.store.close()

        from api.main import app  # noqa: E402

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_stats_endpoint(self) -> None:
        response = self.client.get("/api/discovery/stats")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_references"], 2)
        self.assertIn("concepts_ready", payload)
        self.assertIn("visuals_waiting_review", payload)

    def test_references_endpoint(self) -> None:
        response = self.client.get("/api/discovery/references?limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["items"]), 2)
        first = payload["items"][0]
        self.assertIn("title", first)
        self.assertFalse(first["production_asset"])
        self.assertIn("niches", first)

    def test_top_endpoint(self) -> None:
        response = self.client.get("/api/discovery/top?min_score=0&limit=5")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["count"], 1)

    def test_niche_filter(self) -> None:
        response = self.client.get("/api/discovery/references?niche=horror&limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)

    def test_search_filter(self) -> None:
        response = self.client.get("/api/discovery/references?search=parking&limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertIn("Parking", payload["items"][0]["title"])

    def test_niches_endpoint(self) -> None:
        response = self.client.get("/api/discovery/niches")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("items", payload)
        self.assertTrue(any(item["niche"] == "horror" for item in payload["items"]))


class DiscoveryApiEmptyDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "empty.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        DiscoveryStore(self.db_path).close()

        from api.main import app  # noqa: E402

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_empty_references(self) -> None:
        response = self.client.get("/api/discovery/references")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["items"], [])


class MockAnalysisProvider:
    provider_name = "mock"
    model_name = "mock-v1"

    def analyze_reference(self, context) -> dict:
        return {
            "observed": {"title": context.title},
            "inferred": {
                "genre": "horror",
                "hook_type": "immediate danger",
                "emotional_trigger": "fear",
                "pacing_style": "slow burn",
                "story_structure": "escalation",
                "visual_mood": "dark",
            },
            "transferable_patterns": ["isolation + threat"],
            "avoid_copying": ["exact dialogue"],
        }

    def generate_concepts(
        self, *, context, analysis, count, niche, existing_concepts, performance_context=None
    ) -> list[dict]:
        families = [
            "foggy mountain road",
            "empty parking garage",
            "late-night train",
            "industrial hallway",
            "boat at night",
        ]
        templates = {
            "foggy mountain road": {
                "title": "The Switchback Doesn't End",
                "hook_idea": "The GPS lost signal three switchbacks ago.",
                "visual_premise": "Dashboard glow on pine-lined cliff road in fog",
                "subject": "delivery driver",
                "story_premise": "Headlights reveal a figure standing where the road should drop off.",
            },
            "empty parking garage": {
                "title": "Level B Has No Exit",
                "hook_idea": "Every ramp I took brought me back to the same pillar.",
                "visual_premise": "Fluorescent flicker over concrete levels and echoing tires",
                "subject": "night-shift nurse",
                "story_premise": "Footsteps keep pace on the level above, always one floor up.",
            },
            "late-night train": {
                "title": "The Last Car Is Empty Except One Seat",
                "hook_idea": "The conductor said this train stopped running in 1998.",
                "visual_premise": "Window reflection shows a car that is not there in the glass",
                "subject": "college commuter",
                "story_premise": "Every stop adds another passenger only I can see.",
            },
            "industrial hallway": {
                "title": "Do Not Enter After Shift Change",
                "hook_idea": "The badge scanner worked on a door that was welded shut yesterday.",
                "visual_premise": "Steam and red emergency lamps in a long factory corridor",
                "subject": "maintenance temp",
                "story_premise": "Something drags metal behind the pipes, getting closer each lap.",
            },
            "boat at night": {
                "title": "The Marina After Closing",
                "hook_idea": "My boat was the only one tied up, but the wake came from two.",
                "visual_premise": "Black water reflections and bobbing dock lines",
                "subject": "fisherman",
                "story_premise": "A second engine idles under the pier where no boat is moored.",
            },
        }
        out = []
        for i in range(count):
            family = families[i % len(families)]
            tpl = templates[family]
            out.append(
                {
                    "title": tpl["title"],
                    "niche": niche or "horror",
                    "hook_idea": tpl["hook_idea"],
                    "visual_premise": tpl["visual_premise"],
                    "setting": family,
                    "subject": tpl["subject"],
                    "story_premise": tpl["story_premise"],
                    "variation_family": family,
                    "originality_notes": f"Distinct family: {family}",
                }
            )
        return out


class DiscoveryApiPostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "post-test.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        self.store = DiscoveryStore(self.db_path)
        self.ref_id = seed_reference(self.store, external_id="post00000001", title="Post test ref")
        self.store.close()

        from api import main as api_main  # noqa: E402

        self.api_main = api_main
        api_main._provider = lambda: MockAnalysisProvider()  # type: ignore[attr-defined]
        self.client = TestClient(api_main.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_scan_post_calls_engine(self) -> None:
        from discovery.models import DiscoveryRunStats  # noqa: E402

        fake_stats = DiscoveryRunStats(
            ids_found=5,
            ids_new=3,
            ids_updated=1,
            ids_existing=1,
            detail_requests=2,
            searches_executed=1,
        )
        with unittest.mock.patch(
            "api.main.ingest_youtube_search", return_value=fake_stats
        ) as mocked:
            response = self.client.post(
                "/api/discovery/scan",
                json={"query": "scary story", "niche": "horror", "limit": 10},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ids_new"], 3)
        mocked.assert_called_once()

    def test_discover_respects_max_searches_param(self) -> None:
        from discovery.models import MultiDiscoverResult  # noqa: E402

        fake = MultiDiscoverResult(searches_executed=3, ids_new=2)
        with unittest.mock.patch(
            "api.main.run_multi_niche_discovery", return_value=fake
        ) as mocked:
            response = self.client.post(
                "/api/discovery/discover",
                json={"max_searches": 3},
            )
        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        self.assertEqual(kwargs["max_searches"], 3)

    def test_analyze_endpoint(self) -> None:
        response = self.client.post(
            f"/api/discovery/references/{self.ref_id}/analyze",
            json={"reanalyze": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNotNone(payload["item"])
        self.assertEqual(payload["item"]["reference_id"], self.ref_id)

    def test_analyze_returns_cached_without_reanalyze(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        response = self.client.post(
            f"/api/discovery/references/{self.ref_id}/analyze",
            json={"reanalyze": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["item"]["cached"])

    def test_generate_concepts(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        response = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 2, "niche": "horror"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stored"], 2)
        self.assertEqual(len(payload["concepts"]), 2)

    def test_list_and_approve_concepts(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        gen = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 1},
        )
        concept_id = gen.json()["concepts"][0]["id"]
        approve = self.client.post(
            "/api/discovery/concepts/approve",
            json={"concept_ids": [concept_id]},
        )
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()["count"], 1)
        listing = self.client.get("/api/discovery/concepts?status=approved")
        self.assertEqual(listing.json()["count"], 1)

    def test_scan_requires_query(self) -> None:
        response = self.client.post("/api/discovery/scan", json={"query": "  "})
        self.assertEqual(response.status_code, 400)

    def test_concept_generation_respects_exhaustion(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        store = DiscoveryStore(self.db_path)
        store._conn.execute(
            "UPDATE reference_videos SET max_concepts = 1 WHERE id = ?",
            (self.ref_id,),
        )
        store._conn.commit()
        store.close()

        first = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 1},
        )
        second = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 3},
        )
        self.assertEqual(first.json()["stored"], 1)
        self.assertEqual(second.json()["stored"], 0)
        self.assertTrue(second.json()["skipped_exhaustion"])

    def test_approve_does_not_double_increment_counter(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        gen = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 1},
        )
        concept_id = gen.json()["concepts"][0]["id"]
        self.client.post("/api/discovery/concepts/approve", json={"concept_ids": [concept_id]})
        self.client.post("/api/discovery/concepts/approve", json={"concept_ids": [concept_id]})

        store = DiscoveryStore(self.db_path)
        row = store._conn.execute(
            "SELECT concepts_approved FROM reference_videos WHERE id = ?",
            (self.ref_id,),
        ).fetchone()
        store.close()
        self.assertEqual(row[0], 1)

    def test_invalid_status_transition_skipped(self) -> None:
        self.client.post(f"/api/discovery/references/{self.ref_id}/analyze", json={})
        gen = self.client.post(
            f"/api/discovery/references/{self.ref_id}/concepts",
            json={"count": 1},
        )
        concept_id = gen.json()["concepts"][0]["id"]
        self.client.post("/api/discovery/concepts/approve", json={"concept_ids": [concept_id]})
        shortlist = self.client.post(
            "/api/discovery/concepts/shortlist",
            json={"concept_ids": [concept_id]},
        )
        self.assertEqual(shortlist.json()["count"], 0)

    def test_analyze_unknown_reference_404(self) -> None:
        response = self.client.post("/api/discovery/references/99999/analyze", json={})
        self.assertEqual(response.status_code, 404)

    def test_create_source_media_audio(self) -> None:
        response = self.client.post(
            "/api/source-media",
            json={"source_mode": "audio", "reference_id": self.ref_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["source_mode"], "audio")

    def test_freeform_generation_job(self) -> None:
        response = self.client.post(
            "/api/generation/jobs",
            json={
                "origin_type": "freeform",
                "prompt_summary": "Luxury supercar night images",
                "image_count": 2,
                "video_count": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["reference_id"])

    def test_visuals_review_endpoint(self) -> None:
        store = DiscoveryStore(self.db_path)
        store.create_visual_asset(
            concept_id=None,
            reference_id=None,
            niche="luxury",
            variation_family="test",
            asset_type="image",
            provider="test",
            model="test",
            prompt="review test",
            status="review",
        )
        store.close()
        response = self.client.get("/api/visuals/review")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["count"], 1)


class PilotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "pilot_api.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        for i in range(3):
            seed_reference(
                DiscoveryStore(self.db_path),
                external_id=f"pilotapi{i:09d}",
                title=f"Unused luxury podcast clip {i}",
            )
        DiscoveryStore(self.db_path).close()
        from api.main import app  # noqa: E402

        self.client = TestClient(app)

    def tearDown(self) -> None:
        if hasattr(self, "client"):
            self.client.close()
        os.environ.pop("DISCOVERY_DB_PATH", None)
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_preflight_endpoint(self) -> None:
        response = self.client.get("/api/preflight")
        self.assertEqual(response.status_code, 200)
        self.assertIn("groups", response.json())

    def test_create_pilot_batch(self) -> None:
        response = self.client.post(
            "/api/pilot/batches",
            json={"name": "API Pilot", "niche": "luxury", "batch_size": 2},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 2)


    def test_video_library_includes_legacy_catalog(self) -> None:
        response = self.client.get("/api/videos/library")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("items", payload)
        self.assertIn("summary", payload)
        self.assertGreaterEqual(payload["summary"]["legacy"], 1)
        slugs = {item["slug"] for item in payload["items"]}
        self.assertIn("dont-go-inside", slugs)

    def test_import_videos_endpoint(self) -> None:
        response = self.client.post("/api/videos/import", json={"rebuild_catalog": True})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("imported_count", payload)
        self.assertIn("results", payload)

    def test_shorts_build_defaults(self) -> None:
        response = self.client.get("/api/shorts/build/defaults")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("speech_query", payload)
        self.assertIn("visual_styles", payload)
        self.assertGreaterEqual(len(payload["visual_styles"]), 3)

    def test_shorts_pool_list(self) -> None:
        response = self.client.get("/api/shorts/pool")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("speech", payload)
        self.assertIn("broll", payload)


class AnalyticsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "analytics_api.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        os.environ["DISCOVERY_PUBLISH_DRY_RUN"] = "1"
        os.environ["DISCOVERY_PUBLISH_PROVIDER"] = "mock"
        DiscoveryStore(self.db_path).close()
        from api.main import app  # noqa: E402

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_analytics_overview_and_refresh(self) -> None:
        overview = self.client.get("/api/analytics/overview")
        self.assertEqual(overview.status_code, 200)
        self.assertIn("total_published_posts", overview.json())
        refresh = self.client.post("/api/analytics/refresh", json={"force": True, "limit": 5})
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("refreshed", refresh.json())

    def test_analytics_patterns_endpoints(self) -> None:
        for path in ("/api/analytics/hooks", "/api/analytics/topics", "/api/analytics/formats", "/api/analytics/visuals"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("items", response.json())


class ProductionLibraryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "library_api.sqlite"
        os.environ["DISCOVERY_DB_PATH"] = str(self.db_path)
        DiscoveryStore(self.db_path).close()
        from api.main import app  # noqa: E402

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("DISCOVERY_DB_PATH", None)

    def test_library_list_empty(self) -> None:
        response = self.client.get("/api/library/videos")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_command_submit_dry_run(self) -> None:
        os.environ["CURSOR_BRIDGE_DRY_RUN"] = "1"
        try:
            response = self.client.post(
                "/api/commands",
                json={"command": "Reply with exactly: PONG"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("job_key", payload)
            self.assertIn(payload["status"], {"queued", "running", "completed"})
        finally:
            os.environ.pop("CURSOR_BRIDGE_DRY_RUN", None)

    def test_commands_status(self) -> None:
        response = self.client.get("/api/commands/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cursor_agent_available", response.json())

    def test_combinations_catalog_empty(self) -> None:
        response = self.client.get("/api/library/combinations/catalog")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("audio_by_speaker", payload)
        self.assertIn("visual_packs", payload)
        self.assertIn("chris", payload["owners"])


if __name__ == "__main__":
    unittest.main()
