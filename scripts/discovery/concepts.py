"""
Original concept generation from Creative DNA.

Planning objects only — not production assets or finished stories.
"""

from __future__ import annotations

from dataclasses import dataclass

from discovery.analyze import analyze_reference, build_reference_context
from discovery.analytics.concept_context import build_performance_context
from discovery.config import concept_similarity_threshold, max_concepts_per_reference
from discovery.models import Concept, ReferenceAnalysis
from discovery.providers.base import AnalysisProvider
from discovery.similarity import is_too_similar
from discovery.store import DiscoveryStore


@dataclass
class ConceptGenerationResult:
    reference_id: int
    analysis_id: int
    requested: int
    stored: int
    rejected_similar: int
    skipped_exhaustion: int
    concepts: list[Concept]


def _concept_dict(concept: Concept) -> dict[str, str]:
    return {
        "title": concept.title,
        "hook_idea": concept.hook_idea or "",
        "visual_premise": concept.visual_premise or "",
        "setting": concept.setting or "",
        "subject": concept.subject or "",
        "story_premise": concept.story_premise or "",
        "variation_family": concept.variation_family or "",
    }


def reference_remaining_capacity(store: DiscoveryStore, reference_id: int) -> int:
    usage = store.get_reference_usage(reference_id)
    if usage["exhausted"]:
        return 0
    cap = usage["max_concepts"] or max_concepts_per_reference()
    return max(0, cap - usage["concepts_generated"])


def select_top_reference_id(
    store: DiscoveryStore,
    *,
    niche: str | None,
    min_score: float,
) -> int:
    rows = store.list_top_references(niche=niche, min_score=min_score, limit=1)
    if not rows:
        raise ValueError(
            f"No reference found for niche={niche!r} with min_score={min_score}. "
            "Run discovery ingest first."
        )
    ref_id = rows[0].reference.id
    if ref_id is None:
        raise ValueError("Top reference missing internal id")
    return ref_id


def generate_concepts_for_reference(
    store: DiscoveryStore,
    *,
    reference_id: int,
    count: int,
    provider: AnalysisProvider,
    niche: str | None = None,
    analysis: ReferenceAnalysis | None = None,
    ensure_analysis: bool = True,
) -> ConceptGenerationResult:
    remaining = reference_remaining_capacity(store, reference_id)
    if remaining <= 0:
        store.mark_reference_exhausted(reference_id)
        return ConceptGenerationResult(
            reference_id=reference_id,
            analysis_id=analysis.id if analysis else 0,
            requested=count,
            stored=0,
            rejected_similar=0,
            skipped_exhaustion=count,
            concepts=[],
        )

    want = min(count, remaining)
    if analysis is None:
        analysis = store.get_latest_analysis(reference_id)
    if analysis is None and ensure_analysis:
        analysis = analyze_reference(store, reference_id, provider)
    if analysis is None:
        raise ValueError(
            f"No Creative DNA analysis for reference {reference_id}. Run analyze first."
        )

    context = build_reference_context(store, reference_id)
    existing_rows = store.list_concept_dicts(reference_id=reference_id, limit=200)
    niche_rows = store.list_concept_dicts(niche=niche, limit=100) if niche else []
    compare_pool = existing_rows + [row for row in niche_rows if row not in existing_rows]

    performance_context = build_performance_context(store, niche=niche)
    raw_concepts = provider.generate_concepts(
        context=context,
        analysis=analysis.analysis_json or {},
        count=want,
        niche=niche,
        existing_concepts=compare_pool,
        performance_context=performance_context,
    )

    threshold = concept_similarity_threshold()
    stored: list[Concept] = []
    rejected = 0

    for item in raw_concepts:
        if len(stored) >= want:
            break
        candidate = {
            "title": str(item.get("title") or "Untitled concept"),
            "hook_idea": str(item.get("hook_idea") or ""),
            "visual_premise": str(item.get("visual_premise") or ""),
            "setting": str(item.get("setting") or ""),
            "subject": str(item.get("subject") or ""),
            "story_premise": str(item.get("story_premise") or ""),
            "variation_family": str(item.get("variation_family") or ""),
        }
        if is_too_similar(
            candidate,
            compare_pool + [_concept_dict(c) for c in stored],
            threshold=threshold,
        ):
            rejected += 1
            continue
        concept = store.save_concept(
            reference_id=reference_id,
            analysis_id=analysis.id,
            niche=str(item.get("niche") or niche or ""),
            title=candidate["title"],
            hook_idea=candidate["hook_idea"],
            visual_premise=candidate["visual_premise"],
            setting=candidate["setting"],
            subject=candidate["subject"],
            camera_movement=str(item.get("camera_movement") or ""),
            mood=str(item.get("mood") or ""),
            story_premise=candidate["story_premise"],
            variation_family=candidate["variation_family"],
            originality_notes=str(item.get("originality_notes") or ""),
            status="generated",
        )
        stored.append(concept)
        compare_pool.append(candidate)

    store.record_concepts_generated(reference_id, len(stored))
    if reference_remaining_capacity(store, reference_id) <= 0:
        store.mark_reference_exhausted(reference_id)

    return ConceptGenerationResult(
        reference_id=reference_id,
        analysis_id=analysis.id,
        requested=count,
        stored=len(stored),
        rejected_similar=rejected,
        skipped_exhaustion=max(0, count - want),
        concepts=stored,
    )
