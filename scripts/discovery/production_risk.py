"""Final advisory risk scoring for finished Shorts."""

from __future__ import annotations

import json
from typing import Any

from discovery.risk_scoring import RiskScores, score_source_media
from discovery.reuse_detection import ReuseReport, check_global_reuse


def score_finished_short(
    store,
    *,
    project_id: int,
    source_media_id: int | None,
    format_profile: str,
    timeline: dict[str, Any],
    source_duration: float,
) -> RiskScores:
    reuse_report = ReuseReport()
    if source_media_id:
        source = store.get_source_media(source_media_id)
        if source:
            reuse_report = check_global_reuse(
                store,
                platform=source.platform,
                external_id=source.external_id,
                transcript=source.transcript,
                local_audio_path=source.local_path,
                reference_id=source.reference_id,
            )

    source = store.get_source_media(source_media_id) if source_media_id else None
    base = score_source_media(
        source_mode=source.source_mode if source else "original",
        media_type=source.media_type if source else "original",
        platform=source.platform if source else None,
        has_transcript=bool(source and source.transcript),
        reuse_report=reuse_report,
        is_original=format_profile == "original_story",
    )

    ai_segments = [s for s in timeline.get("segments", []) if s.get("type") in {"image", "ai_video"}]
    ai_ratio = len(ai_segments) / max(1, len(timeline.get("segments", [])))
    base.monetization_confidence += ai_ratio * 20
    base.rights_confidence += ai_ratio * 15
    if format_profile == "original_story":
        base.monetization_confidence += 10
        base.rights_confidence += 12

    base.monetization_confidence = min(100.0, base.monetization_confidence)
    base.rights_confidence = min(100.0, base.rights_confidence)
    base.reuse_confidence = reuse_report.reuse_confidence
    base.explanations.setdefault("monetization", []).append(
        f"AI/original visual coverage ~{ai_ratio:.0%} of timeline"
    )
    base.explanations.setdefault("rights", []).append(
        f"Source clip duration ~{source_duration:.1f}s in {format_profile} format"
    )
    from discovery.risk_scoring import _level

    base.monetization_level = _level(base.monetization_confidence)
    base.rights_level = _level(base.rights_confidence)
    base.reuse_level = _level(base.reuse_confidence, invert=True)
    return base


def risk_explanations_json(scores: RiskScores) -> str:
    return json.dumps(scores.to_dict())
