"""Extract creative ingredients from a production project for analytics."""

from __future__ import annotations

import json
import re
from typing import Any


HOOK_FORMULAS = (
    "contrarian_statement",
    "curiosity_gap",
    "direct_advice",
    "fear",
    "story_reveal",
    "status_aspiration",
    "question",
    "other",
)


def classify_hook_formula(hook_text: str | None, caption: str | None = None) -> str:
    text = f"{hook_text or ''} {caption or ''}".lower()
    if not text.strip():
        return "other"
    if any(w in text for w in ("never", "most people", "wrong", "mistake", "lie", "truth")):
        return "contrarian_statement"
    if "?" in text or any(w in text for w in ("what if", "why", "how", "secret")):
        return "curiosity_gap" if "?" in text else "question"
    if any(w in text for w in ("fear", "scared", "danger", "warning", "avoid")):
        return "fear"
    if any(w in text for w in ("story", "happened", "realized", "found out")):
        return "story_reveal"
    if any(w in text for w in ("luxury", "rich", "success", "million", "win", "discipline")):
        return "status_aspiration"
    if any(w in text for w in ("you should", "do this", "stop", "start", "always", "never")):
        return "direct_advice"
    return "other"


def extract_project_features(store, job) -> dict[str, Any]:
    """Build feature dict from production project + linked entities."""
    project = store.get_production_project(job.production_project_id)
    if not project:
        return {}

    features: dict[str, Any] = {
        "niche": project.niche,
        "format_profile": project.format_profile,
        "origin_type": getattr(project, "origin_type", None),
        "duration_sec": project.duration_sec,
        "caption_preset": project.caption_preset,
        "hook_text": project.hook_text,
        "monetization_confidence": project.monetization_confidence,
        "rights_confidence": project.rights_confidence,
        "reuse_confidence": project.reuse_confidence,
    }

    if project.concept_id:
        concept = store.get_concept(project.concept_id)
        if concept:
            features.update(
                {
                    "concept_id": concept.id,
                    "concept_title": concept.title,
                    "hook_idea": concept.hook_idea,
                    "visual_premise": concept.visual_premise,
                    "variation_family": concept.variation_family,
                    "mood": concept.mood,
                    "setting": concept.setting,
                }
            )

    source_type = "original"
    if project.source_media_id:
        source = store.get_source_media(project.source_media_id)
        if source:
            source_type = source.source_mode or source.media_type
            features.update(
                {
                    "source_media_id": source.id,
                    "source_mode": source.source_mode,
                    "source_channel": source.platform,
                    "source_external_id": source.external_id,
                    "source_title": source.title,
                }
            )
            if source.reference_id:
                ref = store.get_reference_by_id(source.reference_id)
                if ref:
                    features["source_channel_name"] = ref.channel
                    features["source_reference_title"] = ref.title
    features["source_type"] = source_type

    image_count = 0
    video_count = 0
    source_video_sec = 0.0
    visual_families: list[str] = []
    visuals = store.list_project_visual_assets(project.id)
    for v in visuals:
        if v.get("asset_type") == "image":
            image_count += 1
        elif v.get("asset_type") == "video":
            video_count += 1
        fam = v.get("variation_family") or v.get("niche")
        if fam:
            visual_families.append(str(fam))

    if project.timeline_json:
        try:
            timeline = json.loads(project.timeline_json)
            for seg in timeline.get("segments", []):
                if seg.get("type") == "source_video":
                    source_video_sec += max(0.0, float(seg.get("end", 0)) - float(seg.get("start", 0)))
        except json.JSONDecodeError:
            pass

    dur = float(project.duration_sec or 1)
    features.update(
        {
            "image_count": image_count,
            "video_count": video_count,
            "visual_families": visual_families,
            "source_video_coverage": round(source_video_sec / dur, 3) if dur else 0,
            "generated_visual_coverage": round(1.0 - (source_video_sec / dur), 3) if dur else 0,
        }
    )

    hook_formula = classify_hook_formula(project.hook_text, job.caption)
    features["hook_formula"] = hook_formula
    return features
