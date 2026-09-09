"""Workbench queries enriched with analytics performance context."""

from __future__ import annotations

import json
import re
from typing import Any

from discovery.analytics.profiles import build_performance_profile


PERFORMANCE_QUERY_RE = re.compile(
    r"best[- ]perform|winning|top[- ]perform|breakout|strongest|our best",
    re.I,
)


def query_wants_performance_context(query: str) -> bool:
    return bool(PERFORMANCE_QUERY_RE.search(query))


def performance_keywords_for_query(store, query: str, *, niche: str | None = None) -> list[str]:
    """Extract keywords from winning profile when query asks for performance-aware search."""
    if not query_wants_performance_context(query):
        return []
    detected_niche = niche
    if not detected_niche:
        for candidate in ("luxury", "horror", "success", "motivation", "relationship"):
            if candidate in query.lower():
                detected_niche = candidate
                break
    if not detected_niche:
        return []

    row = store.get_performance_profile(detected_niche)
    profile = json.loads(row.profile_json) if row else build_performance_profile(store, niche=detected_niche)
    keywords: list[str] = []
    for key in ("best_topic", "best_visual_style", "best_hook_formula", "best_format"):
        val = profile.get(key)
        if val:
            keywords.extend(re.findall(r"[a-z0-9']+", str(val).lower()))
    return [k for k in keywords if len(k) > 3][:12]


def enrich_workbench_query(store, query: str, *, niche: str | None = None) -> tuple[str, dict[str, Any]]:
    """Append performance keywords to search; return metadata for UI."""
    extra = performance_keywords_for_query(store, query, niche=niche)
    meta: dict[str, Any] = {"performance_aware": bool(extra), "injected_keywords": extra}
    if not extra:
        return query, meta
    enriched = f"{query} {' '.join(extra)}".strip()
    return enriched, meta
