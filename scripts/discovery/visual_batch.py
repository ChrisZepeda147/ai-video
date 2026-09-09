"""Weekly visual batch generation across concepts and reference families."""

from __future__ import annotations

from collections import defaultdict

from discovery.config import visual_batch_max, visual_max_per_reference
from discovery.visuals import generate_visual_variants
from discovery.visual_providers.factory import build_visual_provider


def select_concepts_for_batch(
    store,
    *,
    niche: str | None = None,
    count: int | None = None,
    max_per_reference: int | None = None,
) -> list[dict]:
    """Pick strong concepts spread across reference families."""
    target = count if count is not None else visual_batch_max()
    per_ref_limit = max_per_reference if max_per_reference is not None else visual_max_per_reference()

    candidates = store.list_concepts_for_visual_batch(niche=niche, limit=target * 4)
    ref_counts: dict[int, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    selected: list[dict] = []

    for concept in candidates:
        if len(selected) >= target:
            break
        ref_id = concept.get("reference_id")
        if ref_id is None:
            continue
        if ref_counts[ref_id] >= per_ref_limit:
            continue
        family = concept.get("variation_family") or "general"
        # Soft cap: avoid one family taking more than half the batch
        if family_counts[family] >= max(1, target // 2):
            continue
        selected.append(concept)
        ref_counts[ref_id] += 1
        family_counts[family] += 1

    return selected


def run_visual_batch(
    store,
    *,
    niche: str | None = None,
    count: int | None = None,
    variants_per_concept: int = 1,
    provider=None,
) -> list:
    """Queue/generate assets for a weekly batch."""
    concepts = select_concepts_for_batch(store, niche=niche, count=count)
    provider = provider or build_visual_provider()
    all_assets = []

    for concept in concepts:
        assets = generate_visual_variants(
            store,
            concept_id=concept["id"],
            count=variants_per_concept,
            provider=provider,
        )
        all_assets.extend(assets)

    return all_assets
