"""Dark-luxury FFmpeg grade for motivational montages."""

from __future__ import annotations

# Charcoal / slate with a light plum cast — do not brighten.
DARK_LUXURY_VF = (
    "eq=brightness=-0.07:contrast=1.10:saturation=0.72,"
    "colorbalance=rs=-0.03:gs=-0.02:bs=0.05,"
    "hue=s=0.92"
)


def grade_filter(*, enabled: bool = True) -> str | None:
    return DARK_LUXURY_VF if enabled else None
