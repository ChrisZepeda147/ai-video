"""Rank / filter B-roll YouTube candidates for fast acquisition."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_popular_downloader import VideoCandidate

LONG_AMBIENT_RE = re.compile(
    r"\b(\d+\s*hour|\d+h\b|8\s*hour|10\s*hour|24\s*hour|relaxation film|"
    r"ambient|for sleep|sleep music|static image|slideshow)\b",
    re.IGNORECASE,
)

IDEAL_MIN_SEC = 120.0
IDEAL_MAX_SEC = 20 * 60.0
SOFT_MAX_SEC = 45 * 60.0
HARD_SKIP_SEC = 3 * 3600.0


def scenic_duration_score(duration: float | None) -> float:
    if duration is None:
        return 0.0
    if duration >= HARD_SKIP_SEC:
        return -1000.0
    if duration < 30:
        return -50.0
    if IDEAL_MIN_SEC <= duration <= IDEAL_MAX_SEC:
        return 100.0 - abs(duration - 600.0) / 60.0
    if duration <= SOFT_MAX_SEC:
        return 40.0 - (duration - IDEAL_MAX_SEC) / 120.0
    return -200.0 - (duration - SOFT_MAX_SEC) / 360.0


def title_penalty(title: str) -> float:
    if LONG_AMBIENT_RE.search(title or ""):
        return -500.0
    return 0.0


def rank_broll_candidates(candidates: list[VideoCandidate]) -> list[VideoCandidate]:
    def score(item: VideoCandidate) -> float:
        base = scenic_duration_score(item.duration_seconds)
        base += title_penalty(item.title)
        if item.fps is not None and item.fps >= 50:
            base += 30.0
        elif item.fps is not None and item.fps >= 30:
            base -= 40.0
        elif item.fps is not None:
            base -= 80.0
        views = item.view_count or 0
        base += min(views / 100_000.0, 20.0)
        return base

    return sorted(candidates, key=score, reverse=True)


def should_prefer_section_download(
    *,
    source_duration: float | None,
    clip_length: int,
    parts_needed: int,
    start_offset: float = 0.0,
) -> bool:
    if source_duration is None or source_duration <= 0:
        return False
    parts_request = max(1, parts_needed + 1)
    material = parts_request * clip_length
    usable = max(source_duration - start_offset, 0.0)
    if usable <= clip_length * 1.5:
        return False
    if material < usable * 0.85:
        return True
    return usable > 20 * 60.0


def section_start_fractions(count: int) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [0.5]
    if count == 2:
        return [0.25, 0.75]
    presets = [0.15, 0.5, 0.8, 0.35, 0.65, 0.42, 0.58, 0.72]
    return presets[:count]
