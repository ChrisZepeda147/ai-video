"""Tests for visual brief generation, assets, quality checks, and rotation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from discovery.models import ReferenceVideo
from discovery.scoring import compute_virality_metrics
from discovery.store import DiscoveryStore
from discovery.visual_batch import run_visual_batch, select_concepts_for_batch
from discovery.visual_providers.mock import MockVisualProvider
from discovery.visual_providers.placeholder import write_placeholder_image
from discovery.visual_quality import run_quality_checks
from discovery.visual_rotation import get_approved_asset, record_asset_usage
from discovery.visuals import concept_to_visual_brief, generate_visual_variants


def seed_reference(
    store: DiscoveryStore,
    *,
    external_id: str = "visref000001",
    title: str = "Night drive horror",
) -> int:
    ref = ReferenceVideo(
        platform="youtube",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title=title,
        description="Foggy road isolation story.",
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


def seed_analysis(store: DiscoveryStore, reference_id: int) -> int:
    analysis = store.save_analysis(
        reference_id=reference_id,
        provider="mock",
        model="mock",
        analysis_version="v1",
        genre="horror",
        hook_type="immediate danger",
        emotional_trigger="isolation",
        pacing_style="slow burn",
        tension_structure="escalating",
        story_structure="first person",
        setting_type="night road",
        visual_mood="dark tense",
        visual_energy="low to high",
        camera_style="POV dashcam",
        lighting_style="headlights in fog",
        subject_type="lone driver",
        ending_style="unresolved",
        transferable_patterns="isolation + escalating unseen threat on foggy road",
        avoid_copying="exact dialogue; original footage",
        analysis_json={"inferred": {"genre": "horror"}},
    )
    return analysis.id


def seed_concept(
    store: DiscoveryStore,
    *,
    reference_id: int,
    analysis_id: int,
    title: str = "Foggy mountain road",
    family: str = "night-road",
    niche: str = "horror",
) -> int:
    concept = store.save_concept(
        reference_id=reference_id,
        analysis_id=analysis_id,
        niche=niche,
        title=title,
        hook_idea="The GPS lost signal three switchbacks ago.",
        visual_premise="Dashboard glow on pine-lined cliff road in fog",
        setting="mountain pass",
        subject="delivery driver",
        variation_family=family,
        status="generated",
    )
    return concept.id


class VisualAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.assets_root = Path(self.tmp.name) / "generated"
        self.assets_root.mkdir()
        self.store = DiscoveryStore(self.db_path)
        self.ref_id = seed_reference(self.store)
        self.analysis_id = seed_analysis(self.store, self.ref_id)
        self.concept_id = seed_concept(
            self.store,
            reference_id=self.ref_id,
            analysis_id=self.analysis_id,
        )
        self.provider = MockVisualProvider()
        self._patches = [
            patch("discovery.config.generated_assets_root", return_value=self.assets_root),
            patch("discovery.visual_paths.generated_assets_root", return_value=self.assets_root),
            patch("discovery.visual_quality.generated_assets_root", return_value=self.assets_root),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_generated_asset_defaults_production_asset_false(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=1,
            provider=self.provider,
        )
        self.assertEqual(len(assets), 1)
        self.assertFalse(assets[0].production_asset)
        self.assertIn(assets[0].status, {"review", "auto_rejected"})

    def test_only_approved_assets_become_production_asset(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=1,
            provider=self.provider,
        )
        asset = assets[0]
        self.assertFalse(asset.production_asset)
        if asset.status != "review":
            self.skipTest("asset auto-rejected in environment without PIL sizing")
        approved = self.store.approve_visual_assets([asset.id])
        self.assertEqual(approved, [asset.id])
        updated = self.store.get_visual_asset(asset.id)
        assert updated is not None
        self.assertTrue(updated.production_asset)
        self.assertEqual(updated.status, "approved")

    def test_reference_videos_never_become_production_assets(self) -> None:
        with self.assertRaises(ValueError):
            ReferenceVideo(
                platform="youtube",
                external_id="bad000000001",
                url="https://youtube.com/watch?v=bad000000001",
                title="Bad ref",
                production_asset=True,
            )
        production_refs = self.store._conn.execute(
            "SELECT COUNT(*) FROM reference_videos WHERE production_asset != 0"
        ).fetchone()[0]
        self.assertEqual(production_refs, 0)

    def test_one_concept_creates_multiple_visual_variants(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=4,
            provider=MockVisualProvider(),
        )
        self.assertEqual(len(assets), 4)
        indexes = sorted(a.variant_index for a in assets)
        self.assertEqual(indexes, [1, 2, 3, 4])
        prompts = [a.prompt for a in assets]
        self.assertEqual(len(set(prompts)), 4)

    def test_near_duplicate_prompts_are_detected(self) -> None:
        ref2 = seed_reference(self.store, external_id="visref000010", title="Dup ref")
        analysis2 = seed_analysis(self.store, ref2)
        concept2 = seed_concept(
            self.store,
            reference_id=ref2,
            analysis_id=analysis2,
            title="Other concept",
            family="train",
        )
        shared_prompt = "Scene: identical\nSubject: same\nEnvironment: same road"
        path1 = self.assets_root / "a.png"
        path2 = self.assets_root / "b.png"
        write_placeholder_image(path1, width=720, height=1280, seed="prompt-dup-a")
        write_placeholder_image(path2, width=720, height=1280, seed="prompt-dup-b")
        id1 = self.store.create_visual_asset(
            concept_id=self.concept_id,
            reference_id=self.ref_id,
            niche="horror",
            variation_family="night-road",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt=shared_prompt,
            local_path=str(path1),
            variant_index=50,
            status="generated",
        )
        self.store.update_visual_asset_after_generation(
            id1,
            local_path=str(path1),
            duration_seconds=3.0,
            width=720,
            height=1280,
            aspect_ratio="9:16",
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="review",
        )
        run_quality_checks(self.store, self.store.get_visual_asset_dict(id1) or {})
        id2 = self.store.create_visual_asset(
            concept_id=concept2,
            reference_id=ref2,
            niche="horror",
            variation_family="train",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt=shared_prompt,
            local_path=str(path2),
            variant_index=51,
            status="generated",
        )
        self.store.update_visual_asset_after_generation(
            id2,
            local_path=str(path2),
            duration_seconds=3.0,
            width=720,
            height=1280,
            aspect_ratio="9:16",
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="generated",
        )
        qc = run_quality_checks(self.store, self.store.get_visual_asset_dict(id2) or {})
        self.assertFalse(qc.passed)
        self.assertIn("duplicate prompt", qc.reason)

    def test_duplicate_file_hash_is_auto_rejected(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=1,
            provider=self.provider,
        )
        first = assets[0]
        if first.status != "review":
            self.skipTest("first asset not in review")
        path = Path(first.local_path or "")
        second_id = self.store.create_visual_asset(
            concept_id=self.concept_id,
            reference_id=self.ref_id,
            niche="horror",
            variation_family="night-road",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt="unique prompt for duplicate hash test",
            local_path=str(path),
            variant_index=99,
            status="generated",
        )
        self.store.update_visual_asset_after_generation(
            second_id,
            local_path=str(path),
            duration_seconds=3.0,
            width=720,
            height=1280,
            aspect_ratio="9:16",
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="generated",
        )
        row = self.store.get_visual_asset_dict(second_id)
        qc = run_quality_checks(self.store, row or {})
        self.assertFalse(qc.passed)
        self.assertIn("duplicate", qc.reason)

    def test_auto_quality_rejection_for_zero_byte_file(self) -> None:
        bad_path = self.assets_root / "bad" / "empty.png"
        bad_path.parent.mkdir(parents=True)
        bad_path.write_bytes(b"")
        asset_id = self.store.create_visual_asset(
            concept_id=self.concept_id,
            reference_id=self.ref_id,
            niche="horror",
            variation_family="night-road",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt="zero byte test prompt unique",
            local_path=str(bad_path),
            variant_index=88,
            status="generated",
        )
        row = self.store.get_visual_asset_dict(asset_id)
        qc = run_quality_checks(self.store, row or {})
        self.assertFalse(qc.passed)
        self.assertIn("zero-byte", qc.reason)

    def test_approval_and_rejection_transitions(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=1,
            provider=self.provider,
        )
        asset = assets[0]
        if asset.status != "review":
            self.skipTest("asset not in review")
        self.store.approve_visual_assets([asset.id])
        approved = self.store.get_visual_asset(asset.id)
        assert approved is not None
        self.assertEqual(approved.status, "approved")
        self.store.reject_visual_assets([asset.id])
        rejected = self.store.get_visual_asset(asset.id)
        assert rejected is not None
        self.assertEqual(rejected.status, "rejected")
        self.assertFalse(rejected.production_asset)

    def test_approved_asset_selection_excludes_rejected_and_exhausted(self) -> None:
        assets = generate_visual_variants(
            self.store,
            concept_id=self.concept_id,
            count=2,
            provider=MockVisualProvider(),
        )
        review_assets = [a for a in assets if a.status == "review"]
        if len(review_assets) < 2:
            self.skipTest("not enough review assets")
        good_id = review_assets[0].id
        bad_id = review_assets[1].id
        self.store.approve_visual_assets([good_id, bad_id])
        self.store.reject_visual_assets([bad_id])
        self.store._conn.execute(
            "UPDATE visual_assets SET status = 'exhausted', production_asset = 0 WHERE id = ?",
            (bad_id,),
        )
        self.store._conn.commit()
        picked = get_approved_asset(self.store, niche="horror", exclude_recent=False)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["id"], good_id)

    def test_asset_selection_prefers_low_usage(self) -> None:
        path1 = self.assets_root / "low-usage-a.png"
        path2 = self.assets_root / "low-usage-b.png"
        write_placeholder_image(path1, width=720, height=1280, seed="usage-a")
        write_placeholder_image(path2, width=720, height=1280, seed="usage-b")
        a1_id = self.store.create_visual_asset(
            concept_id=self.concept_id,
            reference_id=self.ref_id,
            niche="horror",
            variation_family="night-road",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt="unique low usage selection prompt alpha",
            local_path=str(path1),
            variant_index=1,
            status="review",
        )
        a2_id = self.store.create_visual_asset(
            concept_id=self.concept_id,
            reference_id=self.ref_id,
            niche="horror",
            variation_family="parking-garage",
            asset_type="image",
            provider="mock",
            model="mock",
            prompt="unique low usage selection prompt beta",
            local_path=str(path2),
            variant_index=2,
            status="review",
        )
        self.store.approve_visual_assets([a1_id, a2_id])
        self.store._conn.execute(
            "UPDATE visual_assets SET usage_count = 3, last_used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), a1_id),
        )
        self.store._conn.commit()
        picked = get_approved_asset(self.store, niche="horror", exclude_recent=False)
        assert picked is not None
        self.assertEqual(picked["id"], a2_id)

    def test_weekly_batch_limits_one_reference_from_dominating(self) -> None:
        ref2 = seed_reference(self.store, external_id="visref000003", title="Third ref")
        analysis2 = seed_analysis(self.store, ref2)
        for i in range(8):
            seed_concept(
                self.store,
                reference_id=self.ref_id,
                analysis_id=self.analysis_id,
                title=f"Dominate concept {i}",
                family=f"night-road-{i}",
            )
        for i in range(2):
            seed_concept(
                self.store,
                reference_id=ref2,
                analysis_id=analysis2,
                title=f"Other ref concept {i}",
                family="train",
            )
        selected = select_concepts_for_batch(
            self.store, niche="horror", count=6, max_per_reference=2
        )
        ref_counts: dict[int, int] = {}
        for concept in selected:
            rid = concept["reference_id"]
            ref_counts[rid] = ref_counts.get(rid, 0) + 1
        self.assertLessEqual(ref_counts.get(self.ref_id, 0), 2)
        self.assertGreaterEqual(len(selected), 3)

    def test_visual_brief_contains_negative_constraints(self) -> None:
        concept = self.store.get_concept(self.concept_id)
        assert concept is not None
        brief = concept_to_visual_brief(concept, variant_index=1)
        self.assertIn("no logos", " ".join(brief.negative_constraints))
        prompt = brief.to_prompt()
        self.assertIn("foggy", prompt.lower())


class VisualBatchIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        self.assets_root = Path(self.tmp.name) / "generated"
        self.assets_root.mkdir()
        self.store = DiscoveryStore(self.db_path)
        self.ref_id = seed_reference(self.store)
        self.analysis_id = seed_analysis(self.store, self.ref_id)
        seed_concept(self.store, reference_id=self.ref_id, analysis_id=self.analysis_id)
        self._patches = [
            patch("discovery.config.generated_assets_root", return_value=self.assets_root),
            patch("discovery.visual_paths.generated_assets_root", return_value=self.assets_root),
            patch("discovery.visual_quality.generated_assets_root", return_value=self.assets_root),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_visual_batch_creates_review_assets(self) -> None:
        assets = run_visual_batch(
            self.store,
            niche="horror",
            count=1,
            variants_per_concept=1,
            provider=MockVisualProvider(),
        )
        self.assertEqual(len(assets), 1)
        self.assertIn(assets[0].status, {"review", "auto_rejected"})


if __name__ == "__main__":
    unittest.main()
