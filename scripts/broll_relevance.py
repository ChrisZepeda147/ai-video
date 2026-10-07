"""Lightweight B-roll query ↔ candidate relevance."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_popular_downloader import VideoCandidate

from broll_frame_gate import subject_tokens

SCENIC_HINTS = frozenset(
    {
        "alpine",
        "autumn",
        "cedar",
        "cinematic",
        "dawn",
        "desert",
        "fall",
        "fog",
        "foggy",
        "forest",
        "lake",
        "landscape",
        "mist",
        "misty",
        "mountain",
        "mountains",
        "nature",
        "ocean",
        "river",
        "scenic",
        "sunrise",
        "sunset",
        "valley",
        "water",
        "waterfall",
        "wilderness",
        "woods",
    }
)

UNRELATED_STRONG = frozenset(
    {
        "coaster",
        "gameplay",
        "gaming",
        "minecraft",
        "motorcycle",
        "parkour",
        "pov",
        "ride",
        "roller",
        "subway",
        "theme",
        "tour",
        "game",
    }
)

NOISE = frozenset({"60fps", "4k", "8k", "hd", "uhd", "video", "cinematic"})


def query_subject_tokens(query: str, subject: str = "") -> set[str]:
    raw = set(subject_tokens(query, subject))
    return {t for t in raw if t not in NOISE and len(t) > 2}


def relevance_score(*, query: str, subject: str, candidate: "VideoCandidate") -> float:
    want = query_subject_tokens(query, subject)
    if not want:
        return 0.0
    hay = f"{candidate.title} {candidate.channel or ''}".lower()
    hay_tokens = set(re.findall(r"[a-z0-9]+", hay))
    shared = want & hay_tokens
    scenic = want & SCENIC_HINTS
    scenic_hit = len(scenic & hay_tokens)
    score = float(len(shared) * 3 + scenic_hit * 2)
    if UNRELATED_STRONG & hay_tokens and not shared:
        score -= 25.0
    if "roller" in hay_tokens and "coaster" in hay_tokens and not (want & {"lake", "mountain", "nature"}):
        score -= 40.0
    return score


def is_low_relevance(*, query: str, subject: str, candidate: "VideoCandidate") -> bool:
    return relevance_score(query=query, subject=subject, candidate=candidate) < 2.0
