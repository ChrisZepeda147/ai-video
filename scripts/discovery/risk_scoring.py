"""Advisory risk scoring for source media and generation jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from discovery.reuse_detection import ReuseReport


@dataclass
class RiskScores:
    monetization_confidence: float = 50.0
    rights_confidence: float = 50.0
    reuse_confidence: float = 0.0
    monetization_level: str = "yellow"
    rights_level: str = "yellow"
    reuse_level: str = "green"
    explanations: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "monetization_confidence": round(self.monetization_confidence, 1),
            "rights_confidence": round(self.rights_confidence, 1),
            "reuse_confidence": round(self.reuse_confidence, 1),
            "monetization_level": self.monetization_level,
            "rights_level": self.rights_level,
            "reuse_level": self.reuse_level,
            "explanations": self.explanations,
        }


def _level(score: float, *, invert: bool = False) -> str:
    """Green/yellow/orange/red bands. Higher is better unless invert=True."""
    value = 100 - score if invert else score
    if value >= 75:
        return "green"
    if value >= 50:
        return "yellow"
    if value >= 25:
        return "orange"
    return "red"


def score_source_media(
    *,
    source_mode: str,
    media_type: str,
    platform: str | None,
    has_transcript: bool,
    reuse_report: ReuseReport,
    is_original: bool = False,
) -> RiskScores:
    """Advisory scores — never auto-reject on uncertain risk."""
    scores = RiskScores()
    scores.reuse_confidence = reuse_report.reuse_confidence
    scores.explanations = {
        "monetization": [],
        "rights": [],
        "reuse": list(reuse_report.explanations),
    }

    if is_original or source_mode == "original":
        scores.monetization_confidence = 88.0
        scores.rights_confidence = 92.0
        scores.explanations["monetization"].append("Original AI visuals and custom editing")
        scores.explanations["rights"].append("No third-party source media attached")
    elif media_type in {"audio", "video"} and platform:
        scores.monetization_confidence = 45.0
        scores.rights_confidence = 40.0
        scores.explanations["monetization"].append("Third-party platform media — monetization uncertain")
        scores.explanations["rights"].append("Permission status unknown for external clip")
        if has_transcript:
            scores.monetization_confidence += 12.0
            scores.explanations["monetization"].append("Transcript available for unique captioning/editing")
    elif source_mode == "topic":
        scores.monetization_confidence = 72.0
        scores.rights_confidence = 78.0
        scores.explanations["monetization"].append("Topic-only mode — no direct media reuse")
        scores.explanations["rights"].append("Reference metadata only")
    else:
        scores.monetization_confidence = 60.0
        scores.rights_confidence = 55.0

    if reuse_report.actually_used_in_content:
        scores.reuse_confidence = max(scores.reuse_confidence, 70.0)
    elif reuse_report.seen_as_reference:
        scores.reuse_confidence = max(scores.reuse_confidence, 10.0)

    scores.monetization_level = _level(scores.monetization_confidence)
    scores.rights_level = _level(scores.rights_confidence)
    scores.reuse_level = _level(scores.reuse_confidence, invert=True)

    return scores


def risk_explanations_json(scores: RiskScores) -> str:
    return json.dumps(scores.to_dict())
