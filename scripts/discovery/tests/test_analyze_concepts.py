"""Tests for Creative DNA analysis and concept generation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from discovery.analyze import analyze_reference
from discovery.concepts import generate_concepts_for_reference, select_top_reference_id
from discovery.models import ReferenceVideo
from discovery.providers.base import ProviderError, ReferenceContext
from discovery.providers.factory import build_analysis_provider
from discovery.scoring import compute_virality_metrics
from discovery.store import DiscoveryStore


class MockAnalysisProvider:
    provider_name = "mock"
    model_name = "mock-v1"

    def __init__(self) -> None:
        self.concept_payloads: list[list[dict]] = []

    def analyze_reference(self, context: ReferenceContext) -> dict:
        return {
            "observed": {
                "title": context.title,
                "description_summary": (context.description or "")[:120],
                "format_signals_from_text": ["POV text story"],
            },
            "inferred": {
                "genre": "horror",
                "hook_type": "immediate danger warning",
                "emotional_trigger": "fear of isolation",
                "pacing_style": "slow burn then spike",
                "tension_structure": "escalating threat",
                "story_structure": "first-person escalation",
                "setting_type": "night driving isolation",
                "visual_mood": "dark, tense (INFERRED from text)",
                "visual_energy": "low to high",
                "camera_style": "POV dashcam feel (INFERRED)",
                "lighting_style": "low light, headlights (INFERRED)",
                "subject_type": "lone driver",
                "ending_style": "unresolved threat",
                "retention_hypothesis": "curiosity about unseen threat",
            },
            "transferable_patterns": [
                "isolation + escalating unseen threat",
                "night vehicle setting",
            ],
            "avoid_copying": [
                "exact dialogue",
                "exact story beats",
                "creator identity",
                "original footage",
            ],
        }

    def generate_concepts(
        self,
        *,
        context: ReferenceContext,
        analysis: dict,
        count: int,
        niche: str | None,
        existing_concepts: list[dict[str, str]],
        performance_context: str | None = None,
    ) -> list[dict]:
        if self.concept_payloads:
            batch = self.concept_payloads.pop(0)
            return batch[:count]
        families = [
            "foggy mountain road",
            "empty parking garage",
            "late-night train",
            "industrial hallway",
            "boat at night",
        ]
        out = []
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
                    "camera_movement": f"move style {i + 1}",
                    "mood": f"mood variant {i + 1}",
                    "story_premise": tpl["story_premise"],
                    "variation_family": family,
                    "originality_notes": f"Distinct family: {family}",
                }
            )
        return out


def seed_reference(store: DiscoveryStore, *, external_id: str = "ref00000001") -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Don't stop driving at 2AM (true story)",
        description="A creepy night drive story with escalating texts.",
        channel="Story Channel",
        duration_sec=58.0,
        view_count=2_000_000,
        like_count=80_000,
        comment_count=3_000,
        published_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
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


class AnalyzeConceptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.store = DiscoveryStore(self.db_path)
        self.ref_id = seed_reference(self.store)
        self.provider = MockAnalysisProvider()

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_one_reference_stores_creative_dna_analysis(self) -> None:
        analysis = analyze_reference(self.store, self.ref_id, self.provider)
        self.assertEqual(analysis.reference_id, self.ref_id)
        self.assertEqual(analysis.provider, "mock")
        self.assertIn("observed", analysis.analysis_json or {})
        self.assertIn("inferred", analysis.analysis_json or {})
        count = self.store._conn.execute(
            "SELECT COUNT(*) FROM reference_analyses WHERE reference_id = ?",
            (self.ref_id,),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_repeated_analysis_versions_without_corruption(self) -> None:
        first = analyze_reference(self.store, self.ref_id, self.provider)
        second = analyze_reference(self.store, self.ref_id, self.provider)
        self.assertNotEqual(first.id, second.id)
        latest = self.store.get_latest_analysis(self.ref_id)
        assert latest is not None
        self.assertEqual(latest.id, second.id)
        count = self.store._conn.execute(
            "SELECT COUNT(*) FROM reference_analyses WHERE reference_id = ?",
            (self.ref_id,),
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_one_reference_generates_multiple_concepts(self) -> None:
        analyze_reference(self.store, self.ref_id, self.provider)
        result = generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=5,
            provider=self.provider,
            niche="horror",
            ensure_analysis=False,
        )
        self.assertEqual(result.stored, 5)
        rows = self.store.list_concepts(reference_id=self.ref_id)
        self.assertEqual(len(rows), 5)
        families = {row.variation_family for row in rows}
        self.assertEqual(len(families), 5)

    def test_concepts_linked_to_reference(self) -> None:
        analysis = analyze_reference(self.store, self.ref_id, self.provider)
        result = generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=2,
            provider=self.provider,
            ensure_analysis=False,
        )
        for concept in result.concepts:
            self.assertEqual(concept.reference_id, self.ref_id)
            self.assertEqual(concept.analysis_id, analysis.id)

    def test_near_duplicate_concepts_rejected(self) -> None:
        analyze_reference(self.store, self.ref_id, self.provider)
        duplicate = {
            "title": "Foggy mountain road terror",
            "niche": "horror",
            "hook_idea": "You shouldn't stop on the foggy mountain road.",
            "visual_premise": "POV moving through foggy mountain road at night",
            "setting": "foggy mountain road",
            "subject": "lone traveler",
            "camera_movement": "slow forward drift",
            "mood": "tense isolation",
            "story_premise": "Unseen threat on foggy mountain road.",
            "variation_family": "foggy mountain road",
            "originality_notes": "duplicate",
        }
        self.provider.concept_payloads = [[duplicate, duplicate]]
        result = generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=2,
            provider=self.provider,
            ensure_analysis=False,
        )
        self.assertEqual(result.stored, 1)
        self.assertEqual(result.rejected_similar, 1)

    def test_reference_exhaustion_limit_respected(self) -> None:
        analyze_reference(self.store, self.ref_id, self.provider)
        self.store._conn.execute(
            "UPDATE reference_videos SET max_concepts = 2 WHERE id = ?",
            (self.ref_id,),
        )
        self.store._conn.commit()
        first = generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=2,
            provider=self.provider,
            ensure_analysis=False,
        )
        second = generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=3,
            provider=self.provider,
            ensure_analysis=False,
        )
        usage = self.store.get_reference_usage(self.ref_id)
        self.assertEqual(first.stored, 2)
        self.assertEqual(second.stored, 0)
        self.assertTrue(usage["exhausted"])

    def test_concepts_never_become_production_assets(self) -> None:
        analyze_reference(self.store, self.ref_id, self.provider)
        generate_concepts_for_reference(
            self.store,
            reference_id=self.ref_id,
            count=1,
            provider=self.provider,
            ensure_analysis=False,
        )
        bad = self.store._conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE production_asset != 0"
        ).fetchone()[0]
        ref_bad = self.store._conn.execute(
            "SELECT COUNT(*) FROM reference_videos WHERE production_asset != 0"
        ).fetchone()[0]
        self.assertEqual(bad, 0)
        self.assertEqual(ref_bad, 0)

    def test_top_reference_selection_uses_virality(self) -> None:
        low_id = seed_reference(self.store, external_id="low00000001")
        self.store._conn.execute(
            "UPDATE reference_videos SET view_count = 1000 WHERE id = ?",
            (low_id,),
        )
        self.store._conn.commit()
        metrics = compute_virality_metrics(
            view_count=1000,
            like_count=None,
            comment_count=None,
            published_at="2020-01-01T00:00:00+00:00",
        )
        self.store.save_metrics_with_snapshots(
            low_id, metrics, view_count=1000, like_count=None, comment_count=None
        )
        self.store.upsert_niche_link(low_id, "horror", 0.8, "test")

        picked = select_top_reference_id(self.store, niche="horror", min_score=0)
        self.assertEqual(picked, self.ref_id)

    def test_missing_ai_credentials_fail_cleanly(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError):
                build_analysis_provider(provider="auto")


if __name__ == "__main__":
    unittest.main()
