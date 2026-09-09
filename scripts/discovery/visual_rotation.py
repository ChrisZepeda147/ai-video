"""Approved asset selection for future render scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from discovery.config import visual_recent_exclude_days


def get_approved_asset(
    store,
    *,
    niche: str | None = None,
    exclude_recent: bool = True,
    variation_family: str | None = None,
) -> dict | None:
    """
    Select an approved production asset favoring low usage and variety.

    Excludes rejected, auto_rejected, and exhausted assets.
    """
    rows = store.list_approved_visual_assets(niche=niche, variation_family=variation_family)
    if not rows:
        return None

    cutoff = None
    if exclude_recent:
        days = visual_recent_exclude_days()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    eligible = []
    for row in rows:
        if row.get("status") != "approved":
            continue
        if not row.get("production_asset"):
            continue
        max_usage = row.get("max_usage")
        usage = row.get("usage_count") or 0
        if max_usage is not None and usage >= max_usage:
            continue
        if cutoff and row.get("last_used_at"):
            try:
                last = datetime.fromisoformat(row["last_used_at"].replace("Z", "+00:00"))
                if last >= cutoff:
                    continue
            except ValueError:
                pass
        eligible.append(row)

    if not eligible:
        # Relax recent exclusion if nothing available
        if exclude_recent:
            return get_approved_asset(
                store,
                niche=niche,
                exclude_recent=False,
                variation_family=variation_family,
            )
        return None

    # Prefer lower usage, then older last_used_at, then spread reference families
    eligible.sort(
        key=lambda r: (
            r.get("usage_count") or 0,
            r.get("last_used_at") or "",
            r.get("reference_id") or 0,
        )
    )
    return eligible[0]


def record_asset_usage(store, asset_id: int) -> None:
    """Increment usage and mark exhausted when max_usage reached."""
    store.increment_visual_asset_usage(asset_id)
