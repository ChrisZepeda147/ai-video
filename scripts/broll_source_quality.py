"""Reject B-roll sources that are gameplay, Minecraft, or scenic overlay films."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_popular_downloader import VideoCandidate

MINECRAFT_RE = re.compile(
    r"\b(minecraft|roblox|fortnite|minetest|block\s*game)\b",
    re.IGNORECASE,
)
GAME_LONGPLAY_RE = re.compile(
    r"\b(longplay|let'?s\s+play|gameplay|no commentary)\b.*\b(minecraft|roblox)\b|"
    r"\b(minecraft|roblox)\b.*\b(longplay|let'?s\s+play|gameplay)\b",
    re.IGNORECASE,
)
SCENIC_OVERLAY_FILM_RE = re.compile(
    r"\b(scenic relaxation film|relaxation film with|"
    r"scenic relaxation|with inspiring cinematic music|"
    r"animals cute\s*-\s*scenic)\b",
    re.IGNORECASE,
)
VIRTUAL_WALK_RE = re.compile(
    r"\b(virtual hike|virtual walk|virtual tour)\b",
    re.IGNORECASE,
)
MUSIC_DANCE_RE = re.compile(
    r"\b(video\s+song|\d+k?\s*video\s+song|music\s+video|official\s+video|"
    r"dance\s+(video|cover|routine|performance)|choreography|"
    r"bollywood|tollywood|kollywood|"
    r"lyric\s+video|audio\s+launch)\b",
    re.IGNORECASE,
)
PEOPLE_EVENT_RE = re.compile(
    r"\b(wedding\s+dance|party\s+dance|flash\s+mob|dancers?\s+dancing|"
    r"dance\s+challenge|tiktok\s+dance)\b",
    re.IGNORECASE,
)


def unwanted_broll_title_reason(title: str) -> str | None:
    text = (title or "").strip()
    if not text:
        return None
    if MINECRAFT_RE.search(text):
        return "minecraft"
    if GAME_LONGPLAY_RE.search(text):
        return "gaming_longplay"
    if SCENIC_OVERLAY_FILM_RE.search(text):
        return "scenic_overlay_film"
    if VIRTUAL_WALK_RE.search(text) and re.search(
        r"\b(4k|8k|60fps|relax|asmr)\b", text, re.IGNORECASE
    ):
        return "virtual_walkthrough"
    if MUSIC_DANCE_RE.search(text):
        return "music_dance_video"
    if PEOPLE_EVENT_RE.search(text):
        return "people_dance_event"
    return None


def unwanted_broll_candidate(candidate: "VideoCandidate") -> str | None:
    return unwanted_broll_title_reason(candidate.title or "")


def _titles_cache_path(jobs_root: Path | None) -> Path | None:
    if jobs_root is None:
        return None
    return jobs_root / "broll-pool" / "source_titles.json"


def _load_titles_cache(jobs_root: Path | None) -> dict[str, str]:
    path = _titles_cache_path(jobs_root)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


def remember_source_title(jobs_root: Path | None, *, video_id: str, title: str) -> None:
    path = _titles_cache_path(jobs_root)
    if path is None or not video_id.strip() or not title.strip():
        return
    cache = _load_titles_cache(jobs_root)
    cache[video_id.strip()] = title.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def source_id_block_reason(
    video_id: str,
    *,
    jobs_root: Path | None = None,
    title: str | None = None,
) -> str | None:
    vid = (video_id or "").strip()
    if not vid:
        return None
    resolved = (title or "").strip()
    if not resolved:
        cache = _load_titles_cache(jobs_root)
        resolved = cache.get(vid, "")
    if not resolved:
        try:
            from youtube_popular_downloader import discover_urls

            batch = discover_urls([f"https://www.youtube.com/watch?v={vid}"])
            if batch:
                resolved = batch[0].title or ""
                remember_source_title(jobs_root, video_id=vid, title=resolved)
        except Exception:
            return None
    return unwanted_broll_title_reason(resolved)
