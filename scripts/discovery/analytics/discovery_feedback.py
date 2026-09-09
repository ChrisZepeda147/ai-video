"""Internal performance fit for references — separate from external virality."""

from __future__ import annotations

import json
import re
from typing import Any

from discovery.analytics.profiles import build_performance_profile


def _keywords(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if len(t) > 3}


def compute_internal_fit(
    store,
    *,
    reference_id: int,
    niche: str | None = None,
) -> dict[str, Any]:
    """Score 0–100: how well reference topics/formats match our recent winners."""
    ref = store.get_reference_by_id(reference_id)
    if not ref:
        return {"internal_fit_score": None, "internal_fit_note": None, "components": {}}

    ref_niche = niche
    if not ref_niche:
        niches = store.get_niches_for_reference(reference_id)
        ref_niche = niches[0].niche if niches else None

    profile_row = store.get_performance_profile(ref_niche) if ref_niche else None
    if not profile_row:
        if ref_niche:
            profile = build_performance_profile(store, niche=ref_niche)
        else:
            return {
                "internal_fit_score": None,
                "internal_fit_note": "No niche assigned for internal fit.",
                "components": {"external_virality": ref.virality_score},
            }
    else:
        profile = json.loads(profile_row.profile_json)

    if profile.get("sample_size", 0) < 1:
        return {
            "internal_fit_score": None,
            "internal_fit_note": "Insufficient published performance data for this niche.",
            "components": {"external_virality": ref.virality_score},
        }

    ref_text = f"{ref.title} {ref.description or ''} {ref.channel or ''}"
    ref_kw = _keywords(ref_text)
    score = 40.0
    matches: list[str] = []

    best_topic = profile.get("best_topic") or ""
    if best_topic and _keywords(str(best_topic)) & ref_kw:
        score += 20.0
        matches.append(f"topic overlap with recent winner '{best_topic}'")

    best_hook = profile.get("best_hook_formula") or ""
    if best_hook:
        hook_words = {
            "contrarian_statement": {"never", "wrong", "mistake", "truth"},
            "curiosity_gap": {"secret", "why", "what"},
            "status_aspiration": {"success", "rich", "luxury", "discipline"},
            "fear": {"scared", "danger", "warning"},
        }.get(best_hook, set())
        if hook_words & ref_kw:
            score += 15.0
            matches.append(f"hook style aligned with winning '{best_hook}'")

    best_visual = profile.get("best_visual_style") or ""
    if best_visual and str(best_visual).lower() in ref_text.lower():
        score += 15.0
        matches.append(f"visual theme overlap with '{best_visual}'")

    score = min(100.0, max(0.0, score))
    note = (
        "Similar topics/formats have recently performed well on our accounts."
        if matches
        else "Limited overlap with recent internal winners."
    )
    return {
        "internal_fit_score": round(score, 1),
        "internal_fit_note": note,
        "internal_fit_signals": matches,
        "components": {
            "external_virality": ref.virality_score,
            "internal_performance_fit": round(score, 1),
        },
    }
