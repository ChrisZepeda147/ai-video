"""Performance context for concept generation — advisory, not auto-decisions."""

from __future__ import annotations

import json
from typing import Any

from discovery.analytics.profiles import build_performance_profile
from discovery.config import analytics_exploit_ratio


def build_performance_context(store, *, niche: str | None, account_id: int | None = None) -> str | None:
    if not niche:
        return None
    row = store.get_performance_profile(niche, account_id=account_id)
    if row:
        profile = json.loads(row.profile_json)
    else:
        profile = build_performance_profile(store, niche=niche, account_id=account_id)
    if profile.get("sample_size", 0) < 1:
        return None

    exploit = analytics_exploit_ratio()
    experiment = round(1.0 - exploit, 2)
    parts = [
        f"Recent internal performance for niche '{niche}' (sample={profile.get('sample_size')}):",
        profile.get("summary") or "",
        f"Guidance mix: ~{int(exploit * 100)}% proven patterns, ~{int(experiment * 100)}% experiments.",
        "Use winning mechanics as inspiration — do NOT clone exact prior videos.",
        "Preserve variation families and originality vs existing concepts.",
    ]
    return "\n".join(p for p in parts if p)


def performance_context_dict(store, *, niche: str | None) -> dict[str, Any]:
    text = build_performance_context(store, niche=niche)
    if not text:
        return {}
    return {"performance_context": text, "exploit_ratio": analytics_exploit_ratio()}
