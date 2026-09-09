"""
Creative DNA analysis for viral references.

REFERENCE VIDEO != PRODUCTION ASSET
Uses metadata only — never downloads or renders reference footage.
"""

from __future__ import annotations

import json
from typing import Any

from discovery.config import ANALYSIS_VERSION
from discovery.models import ReferenceAnalysis
from discovery.providers.base import AnalysisProvider, ReferenceContext
from discovery.store import DiscoveryStore


def build_reference_context(store: DiscoveryStore, reference_id: int) -> ReferenceContext:
    bundle = store.get_reference_bundle(reference_id)
    if bundle is None:
        raise ValueError(f"Reference not found: {reference_id}")
    ref = bundle["reference"]
    return ReferenceContext(
        reference_id=reference_id,
        platform=ref.platform,
        external_id=ref.external_id,
        url=ref.url,
        title=ref.title,
        description=ref.description,
        channel=ref.channel,
        duration_sec=ref.duration_sec,
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
        published_at=ref.published_at,
        source_query=ref.source_query,
        virality_score=ref.virality_score,
        niches=[{"niche": n.niche, "score": n.relevance_score} for n in bundle["niches"]],
        metrics=bundle["metrics"],
    )


def flatten_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    inferred = payload.get("inferred") or {}
    transferable = payload.get("transferable_patterns") or []
    avoid = payload.get("avoid_copying") or []
    if isinstance(transferable, list):
        transferable = json.dumps(transferable)
    if isinstance(avoid, list):
        avoid = json.dumps(avoid)
    return {
        "genre": inferred.get("genre"),
        "hook_type": inferred.get("hook_type"),
        "emotional_trigger": inferred.get("emotional_trigger"),
        "pacing_style": inferred.get("pacing_style"),
        "tension_structure": inferred.get("tension_structure"),
        "story_structure": inferred.get("story_structure"),
        "setting_type": inferred.get("setting_type"),
        "visual_mood": inferred.get("visual_mood"),
        "visual_energy": inferred.get("visual_energy"),
        "camera_style": inferred.get("camera_style"),
        "lighting_style": inferred.get("lighting_style"),
        "subject_type": inferred.get("subject_type"),
        "ending_style": inferred.get("ending_style"),
        "transferable_patterns": transferable,
        "avoid_copying": avoid,
    }


def analyze_reference(
    store: DiscoveryStore,
    reference_id: int,
    provider: AnalysisProvider,
) -> ReferenceAnalysis:
    context = build_reference_context(store, reference_id)
    payload = provider.analyze_reference(context)
    flat = flatten_analysis(payload)
    return store.save_analysis(
        reference_id=reference_id,
        provider=provider.provider_name,
        model=provider.model_name,
        analysis_version=ANALYSIS_VERSION,
        analysis_json=payload,
        **flat,
    )
