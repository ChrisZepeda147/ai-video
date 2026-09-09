"""Data-informed performance profiles per niche/account."""

from __future__ import annotations

import json
from typing import Any

from discovery.analytics.patterns import (
    aggregate_formats,
    aggregate_hooks,
    aggregate_topics,
    aggregate_visuals,
)
from discovery.store import DiscoveryStore, now_iso


def build_performance_profile(
    store: DiscoveryStore,
    *,
    niche: str,
    account_id: int | None = None,
    lookback: int = 30,
) -> dict[str, Any]:
    rows = store.list_analytics_posts_with_latest(
        niche=niche,
        account_id=account_id,
        limit=lookback,
    )
    if not rows:
        profile = {
            "niche": niche,
            "account_id": account_id,
            "sample_size": 0,
            "data_confidence": "low",
            "data_confidence_label": "LOW DATA CONFIDENCE",
            "summary": "Insufficient published data yet.",
            "recommendation_mix": {"proven_patterns": 0.7, "experiments": 0.3},
        }
        store.upsert_performance_profile(niche=niche, account_id=account_id, profile=profile, sample_size=0)
        return profile

    hooks = aggregate_hooks(rows)
    topics = aggregate_topics(rows)
    formats = aggregate_formats(rows)
    visuals = aggregate_visuals(rows)

    durations = []
    for row in rows:
        features = row.get("features") or {}
        if isinstance(features, str):
            features = json.loads(features)
        if features.get("duration_sec"):
            durations.append(float(features["duration_sec"]))

    best_hook = hooks[0]["hook_formula"] if hooks else None
    best_format = formats[0]["format"] if formats else None
    best_visual = visuals[0]["visual_style"] if visuals else None
    best_topic = topics[0]["topic"] if topics else None
    duration_range = None
    if durations:
        durations.sort()
        lo = durations[max(0, len(durations) // 4)]
        hi = durations[min(len(durations) - 1, (3 * len(durations)) // 4)]
        duration_range = f"{int(lo)}–{int(hi)} sec"

    sample = len(rows)
    confidence = "low" if sample < 5 else ("medium" if sample < 15 else "high")
    profile = {
        "niche": niche,
        "account_id": account_id,
        "sample_size": sample,
        "data_confidence": confidence,
        "data_confidence_label": "LOW DATA CONFIDENCE" if confidence == "low" else confidence.upper(),
        "best_hook_formula": best_hook,
        "best_topic": best_topic,
        "best_format": best_format,
        "best_visual_style": best_visual,
        "best_length_range": duration_range,
        "top_hooks": hooks[:5],
        "top_topics": topics[:5],
        "top_formats": formats[:5],
        "top_visuals": visuals[:5],
        "recommendation_mix": {"proven_patterns": 0.7, "experiments": 0.3},
        "summary": _profile_summary(best_hook, best_format, best_visual, duration_range),
        "disclaimer": "Data-informed guidance — not rigid rules. Preserve diversity.",
    }
    store.upsert_performance_profile(
        niche=niche,
        account_id=account_id,
        profile=profile,
        sample_size=len(rows),
    )
    return profile


def _profile_summary(
    hook: str | None,
    fmt: str | None,
    visual: str | None,
    length: str | None,
) -> str:
    parts = []
    if hook:
        parts.append(f"hooks like '{hook}'")
    if fmt:
        parts.append(f"format '{fmt}'")
    if visual:
        parts.append(f"visuals '{visual}'")
    if length:
        parts.append(f"length {length}")
    if not parts:
        return "Not enough recent performance data."
    return "Recent winners associated with " + ", ".join(parts) + "."
