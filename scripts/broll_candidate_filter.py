"""Hard reject rules before scheduling B-roll acquisition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from broll_candidate_rank import LONG_AMBIENT_RE
from broll_relevance import is_low_relevance

if TYPE_CHECKING:
    from youtube_popular_downloader import VideoCandidate

NORMAL_MAX_DURATION_SEC = 60 * 60.0


def hard_reject_reason(
    candidate: "VideoCandidate",
    *,
    query: str,
    subject: str,
    allow_long_fallback: bool = False,
    format_ok: bool = True,
) -> str | None:
    duration = candidate.duration_seconds
    if duration is not None and duration >= NORMAL_MAX_DURATION_SEC and not allow_long_fallback:
        return "duration_too_long"
    title = candidate.title or ""
    if LONG_AMBIENT_RE.search(title):
        return "duration_too_long"
    if duration is not None and duration >= 3 * 3600 and not allow_long_fallback:
        return "duration_too_long"
    if not format_ok:
        return "no_50fps_format"
    if query.strip() and is_low_relevance(query=query, subject=subject, candidate=candidate):
        return "low_relevance"
    return None
