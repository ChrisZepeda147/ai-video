"""Aggregate performance patterns — hooks, topics, formats, visuals, accounts."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def _avg_score(rows: list[dict[str, Any]]) -> float:
    scores = [float(r.get("performance_score") or 0) for r in rows if r.get("performance_score") is not None]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def _group_aggregate(
    rows: list[dict[str, Any]],
    key_fn,
    *,
    label_key: str,
    min_samples: int = 1,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = key_fn(row)
        if not label:
            continue
        groups[str(label)].append(row)
    results = []
    for label, items in groups.items():
        if len(items) < min_samples:
            continue
        views = [int(i.get("views") or 0) for i in items]
        results.append(
            {
                label_key: label,
                "post_count": len(items),
                "avg_performance_score": _avg_score(items),
                "avg_views": round(sum(views) / len(views)) if views else 0,
                "breakout_count": sum(1 for i in items if i.get("performance_tier") == "breakout"),
            }
        )
    results.sort(key=lambda x: (x["avg_performance_score"], x["post_count"]), reverse=True)
    return results


def aggregate_hooks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _group_aggregate(rows, lambda r: r.get("hook_formula"), label_key="hook_formula")


def aggregate_topics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def topic_key(row: dict[str, Any]) -> str | None:
        features = row.get("features") or {}
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        return (
            features.get("concept_title")
            or features.get("source_title")
            or features.get("niche")
        )

    return _group_aggregate(rows, topic_key, label_key="topic", min_samples=1)


def aggregate_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def source_key(row: dict[str, Any]) -> str | None:
        features = row.get("features") or {}
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        return features.get("source_channel_name") or features.get("source_channel")

    return _group_aggregate(rows, source_key, label_key="source", min_samples=1)


def aggregate_formats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def format_key(row: dict[str, Any]) -> str | None:
        features = row.get("features") or {}
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        profile = features.get("format_profile") or "unknown"
        source_type = features.get("source_type") or "unknown"
        return f"{profile}:{source_type}"

    return _group_aggregate(rows, format_key, label_key="format", min_samples=1)


def aggregate_visuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def visual_key(row: dict[str, Any]) -> str | None:
        features = row.get("features") or {}
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        families = features.get("visual_families") or []
        if families:
            return str(families[0])
        return features.get("variation_family") or features.get("mood")

    return _group_aggregate(rows, visual_key, label_key="visual_style", min_samples=1)


def aggregate_accounts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _group_aggregate(rows, lambda r: r.get("account_id"), label_key="account_id")


def compare_format_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare source-audio vs source-video style formats."""
    audio_rows: list[dict[str, Any]] = []
    video_rows: list[dict[str, Any]] = []
    for row in rows:
        features = row.get("features") or {}
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        mode = str(features.get("source_mode") or features.get("source_type") or "")
        if "audio" in mode:
            audio_rows.append(row)
        elif "video" in mode:
            video_rows.append(row)
    return {
        "source_audio": {
            "post_count": len(audio_rows),
            "avg_performance_score": _avg_score(audio_rows),
        },
        "source_video": {
            "post_count": len(video_rows),
            "avg_performance_score": _avg_score(video_rows),
        },
    }
