"""Age-based metadata refresh intervals for reference videos."""

from __future__ import annotations

from discovery.config import (
    refresh_hours_old,
    refresh_hours_recent,
    refresh_hours_stable,
    refresh_hours_viral,
)


def metadata_refresh_hours(*, age_hours: float | None) -> float:
    """
    How long to wait before re-fetching statistics for a reference.

    Very recent viral candidates refresh more often; stable old references rarely.
    """
    if age_hours is None:
        return refresh_hours_stable()
    if age_hours <= 48:
        return refresh_hours_viral()
    if age_hours <= 24 * 7:
        return refresh_hours_recent()
    if age_hours <= 24 * 30:
        return refresh_hours_stable()
    return refresh_hours_old()
