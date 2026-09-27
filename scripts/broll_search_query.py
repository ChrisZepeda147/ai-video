"""Turn storyboard / edit briefs into YouTube B-roll search queries."""

from __future__ import annotations

import re

BEAT_SPLIT = re.compile(r"[→>]|/{1}|\bor\b|\bto\b", re.IGNORECASE)
STORYBOARD_MARK = re.compile(r"[→>]| then |\s/\s|\sto\s", re.IGNORECASE)
WEAK_BEAT = frozenset(
    {
        "alarm",
        "ending",
        "freedom",
        "shoes",
        "arrow",
        "start",
        "end",
    }
)

SCENE_SEARCHES: tuple[tuple[str, str], ...] = (
    ("bedroom", "dark bedroom morning cinematic 60fps"),
    ("gym", "gym workout cinematic 60fps"),
    ("office", "late night office work cinematic 60fps"),
    ("work", "late night office work cinematic 60fps"),
    ("sunrise", "sunrise city skyline 60fps"),
    ("skyline", "sunrise city skyline 60fps"),
    ("city", "sunrise city skyline 60fps"),
    ("supercar", "supercar exterior driving 60fps"),
    ("porsche", "porsche exterior driving 60fps"),
    ("ferrari", "ferrari exterior driving 60fps"),
    ("road", "empty road dawn cinematic 60fps"),
    ("highway", "empty highway dawn cinematic 60fps"),
    ("apartment", "luxury penthouse window skyline view cinematic 60fps"),
    ("penthouse", "penthouse window city skyline view cinematic 60fps"),
    ("yacht", "luxury yacht cinematic 60fps"),
)


def is_storyboard_query(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    return bool(STORYBOARD_MARK.search(text)) or text.count("/") >= 2


def _beats(query: str) -> list[str]:
    parts = [part.strip(" .,-") for part in BEAT_SPLIT.split(query) if part.strip()]
    return [part for part in parts if part]


def _searches_for_beat(beat: str) -> list[str]:
    lower = beat.lower()
    compact = re.sub(r"[^a-z0-9]+", " ", lower).strip()
    words = compact.split()
    if not words or all(word in WEAK_BEAT for word in words):
        return []
    found: list[str] = []
    for key, search in SCENE_SEARCHES:
        if key in compact and search not in found:
            found.append(search)
    if found:
        return found
    keep = [word for word in words if word not in WEAK_BEAT and len(word) > 2][:4]
    if not keep:
        return []
    query = " ".join(keep)
    if "60fps" not in query and "50fps" not in query:
        query = f"{query} 60fps"
    return [query]


def expand_broll_search_queries(query: str) -> list[str]:
    """Return one or more YouTube searches. Storyboards become scene queries."""
    text = (query or "").strip()
    if not text:
        return []
    if not is_storyboard_query(text):
        return [text]
    found: list[str] = []
    seen: set[str] = set()
    for beat in _beats(text):
        for search in _searches_for_beat(beat):
            if search in seen:
                continue
            seen.add(search)
            found.append(search)
    return found or [re.sub(r"[→>/]+", " ", text).strip()]


def gate_subject_for_query(query: str, subject: str = "") -> str:
    """Storyboards mix objects — do not force a single-object frame gate."""
    if is_storyboard_query(query):
        return ""
    return (subject or query).strip()
