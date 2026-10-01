#!/usr/bin/env python3
"""
Find popular YouTube background gameplay for AI voiceover repurposing.

Best for: subway-surfers / parkour / satisfying mobile game footage with no
commentary, high views, and enough length to lay an AI story + TTS + captions.

Discovery modes:
  trending  — popular background gameplay (default)
  search    — keyword search, ranked by fit + views
  urls      — download explicit video URLs or IDs from a file

Examples:
  python scripts/youtube_popular_downloader.py trending --limit 5 --dry-run
  python scripts/youtube_popular_downloader.py search --query "minecraft parkour no commentary" --limit 10
  python scripts/youtube_popular_downloader.py urls --file urls.txt

Set YOUTUBE_API_KEY for richer trending metadata (free tier: 10k units/day).
Get a key: https://console.cloud.google.com/apis/credentials
Enable "YouTube Data API v3" on your project.

Legal: Only download and repost content you own or have rights to use.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import content_reuse
from build_clips_montage import MIN_USABLE_FPS, is_usable_fps, probe_fps

try:
    import yt_dlp
except ImportError:
    print("Missing dependency: pip install -r scripts/requirements-youtube.txt", file=sys.stderr)
    sys.exit(1)

# YouTube video category IDs (for API trending filter)
CATEGORY_IDS = {
    "film": "1",
    "autos": "2",
    "music": "10",
    "pets": "15",
    "sports": "17",
    "gaming": "20",
    "blogging": "22",
    "comedy": "23",
    "entertainment": "24",
    "news": "25",
    "howto": "26",
    "education": "27",
    "science": "28",
    "nonprofit": "29",
}


MUSIC_CATEGORY_ID = "10"
MUSIC_TITLE_RE = re.compile(
    r"(official\s+(music\s+)?video|official\s+audio|lyric(s)?(\s+video)?|"
    r"\(\s*audio\s*\)|\[\s*audio\s*\]|music\s+video|mv\b|visualizer|"
    r"audio\s+only)",
    re.IGNORECASE,
)
MUSIC_CHANNEL_RE = re.compile(r"(vevo|\btopic\b)", re.IGNORECASE)
TRAILER_TITLE_RE = re.compile(
    r"\b(official\s+)?(teaser(\s+trailer)?|trailer|sneak\s*peek|first\s+look)\b",
    re.IGNORECASE,
)
LIVE_TITLE_RE = re.compile(
    r"(🔴|\blive\b|\blivestream\b|\b24/?7\b|\bstate of play\b|\bdirect\b|\bshowcase\b)",
    re.IGNORECASE,
)
BACKGROUND_GAMEPLAY_TITLE_RE = re.compile(
    r"\b(no commentary|without commentary|background gameplay|satisfying|"
    r"parkour|subway surfers|mobile gameplay|asmr gameplay|screen record|"
    r"sandwich runner|hole\.io|driving gameplay|minecraft parkour|"
    r"geometry dash|relaxing gameplay|idle game|mobile game|"
    r"gameplay loop|hours|4k gameplay)\b",
    re.IGNORECASE,
)
COMMENTARY_HEAVY_RE = re.compile(
    r"\b(i beat|i won|react(s|ion)?|vs every|every rank|playing every|"
    r"funny moments|stream highlights|facecam|just chatting|podcast|"
    r"interview|tier list|rage|roast|how to fish|caseoh|jynxzi|xqc)\b",
    re.IGNORECASE,
)
REALESTATE_TOUR_RE = re.compile(
    r"\b(house tour|home tour|property tour|mansion tour|estate tour|"
    r"luxury house tour|mega mansion tour|full tour|room tour|walkthrough|"
    r"apartment tour|condo tour|penthouse tour|studio tour|flat tour|"
    r"inside a \$|inside the \$|inside this \$|inside a £|touring a \$|"
    r"must see.{0,12}inside|realtor|open house|real estate|dream home|"
    r"mega mansion|hour tour|travel video|night cities|capital of|"
    r"apartment tour\s*\|\||\|\|\s*.*apartment)\b",
    re.IGNORECASE,
)
SIM_GAME_FOOTAGE_TITLE_RE = re.compile(
    r"\b(forza\s+horizon|assetto\s+corsa|beam\.?ng|need\s+for\s+speed|\bnfs\b|"
    r"gta\s+v\b|\bgta\b.*mods|unreal\s+engine|wuthering\s+waves|"
    r"rtx\s+\d{3,4}|gran\s+turismo|project\s+cars|\bgrid\s+2019\b|"
    r"asphalt\s+[89]|driveclub|"
    r"speed\s+art\s*\+\s*gameplay|anime\s+lamborghini)\b",
    re.IGNORECASE,
)
CABIN_TITLE_RE = re.compile(
    r"\b(interior|cabin|cockpit|dashboard|walkaround|start[\s-]?up)\b",
    re.IGNORECASE,
)
SLEEP_AMBIENCE_RE = re.compile(
    r"(for\s+sleep|sleep\s*&\s*relax|bedroom\s+ambience|rainy\s+night|"
    r"soft\s+piano|no\s+ads|white\s+noise|ambience\s+for|"
    r"\b\d+\s*hours?\b|10\s*hour|8\s*hour)",
    re.IGNORECASE,
)
BROLL_MAX_SOURCE_SECONDS = 20 * 60
VLOG_OR_INTRO_RE = re.compile(
    r"\b(vlog|day in (a |the )?life|grwm|get ready with me|facecam|"
    r"intro remastered|channel intro|logo animation|hbo:|"
    r"come with me|follow me|what i rent|what i pay|my rent|"
    r"living alone|roommate tour|hostel tour)\b",
    re.IGNORECASE,
)

BACKGROUND_SEARCH_QUERIES = [
    "satisfying mobile game no commentary",
    "subway surfers gameplay no commentary",
    "minecraft parkour no commentary 4k",
    "mobile game all levels no commentary",
    "background gameplay for youtube shorts",
    "relaxing gameplay no commentary",
    "sandwich runner gameplay no commentary",
    "gta driving gameplay no commentary",
]


FPS_TITLE_RE = re.compile(r"\b(50|59\.94|60)\s*fps\b", re.IGNORECASE)


@dataclass
class VideoCandidate:
    video_id: str
    title: str
    url: str
    channel: str
    view_count: int | None
    duration_seconds: float | None
    published_at: str | None
    source: str
    category_id: str | None = None
    fps: float | None = None


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "downloads" / "youtube"


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len].rstrip(". ") or "video"


def _parse_view_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def _parse_fps(value: Any) -> float | None:
    if value is None:
        return None
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return None
    return fps if fps > 0 else None


def listed_fps_from_entry(entry: dict[str, Any] | None) -> float | None:
    if not entry:
        return None
    values: list[float] = []
    top = _parse_fps(entry.get("fps"))
    if top is not None:
        values.append(top)
    for fmt in entry.get("formats") or []:
        fps = _parse_fps(fmt.get("fps"))
        if fps is not None:
            values.append(fps)
    return max(values) if values else None


def title_suggests_usable_fps(title: str) -> bool:
    return bool(FPS_TITLE_RE.search(title or ""))


def probe_listed_fps(url: str) -> float | None:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        **_toolchain_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return listed_fps_from_entry(info if isinstance(info, dict) else None)


def pick_usable_fps_candidates(
    candidates: list[VideoCandidate],
    *,
    limit: int,
    probe: bool = True,
) -> list[VideoCandidate]:
    ranked = sorted(
        candidates,
        key=lambda video: (
            title_suggests_usable_fps(video.title),
            video.fps is not None and is_usable_fps(video.fps),
            video.view_count or 0,
        ),
        reverse=True,
    )
    kept: list[VideoCandidate] = []
    skipped = 0
    for video in ranked:
        fps = video.fps
        if fps is None and probe:
            try:
                fps = probe_listed_fps(video.url)
            except Exception:
                fps = None
            video.fps = fps
        if fps is not None and not is_usable_fps(fps):
            skipped += 1
            continue
        if fps is None and not title_suggests_usable_fps(video.title):
            skipped += 1
            continue
        kept.append(video)
        if len(kept) >= limit:
            break
    if skipped:
        print(f"Filtered out {skipped} source(s) under {int(MIN_USABLE_FPS)}fps.")
    return kept


def _video_from_ytdlp_entry(entry: dict[str, Any], source: str) -> VideoCandidate | None:
    video_id = entry.get("id")
    if not video_id:
        return None
    return VideoCandidate(
        video_id=video_id,
        title=entry.get("title") or "(untitled)",
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel=entry.get("uploader") or entry.get("channel") or "unknown",
        view_count=_parse_view_count(entry.get("view_count")),
        duration_seconds=entry.get("duration"),
        published_at=entry.get("upload_date"),
        source=source,
        category_id=str(entry["categories"][0]) if entry.get("categories") else None,
        fps=listed_fps_from_entry(entry),
    )


def discover_trending_api(
    *,
    api_key: str,
    limit: int,
    region: str,
    category: str | None,
) -> list[VideoCandidate]:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is required for API trending. "
            "Install with: pip install -r scripts/requirements-youtube.txt"
        ) from exc

    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    params: dict[str, Any] = {
        "part": "snippet,contentDetails,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": min(max(limit, 50), 50),
    }
    if category:
        params["videoCategoryId"] = CATEGORY_IDS[category]

    response = youtube.videos().list(**params).execute()
    candidates: list[VideoCandidate] = []
    for item in response.get("items", []):
        vid = item["id"]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        duration_iso = item.get("contentDetails", {}).get("duration")
        candidates.append(
            VideoCandidate(
                video_id=vid,
                title=snippet.get("title", "(untitled)"),
                url=f"https://www.youtube.com/watch?v={vid}",
                channel=snippet.get("channelTitle", "unknown"),
                view_count=int(stats["viewCount"]) if stats.get("viewCount") else None,
                duration_seconds=_iso8601_duration_to_seconds(duration_iso),
                published_at=snippet.get("publishedAt"),
                source="youtube_api_trending",
                category_id=snippet.get("categoryId"),
            )
        )
    return candidates


def _iso8601_duration_to_seconds(duration: str | None) -> float | None:
    if not duration:
        return None
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration,
    )
    if not match:
        return None
    hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def discover_background_gameplay(*, limit: int) -> list[VideoCandidate]:
    per_query = max(limit // 2, 12)
    seen: set[str] = set()
    candidates: list[VideoCandidate] = []

    for query in BACKGROUND_SEARCH_QUERIES:
        batch = discover_search(query=query, limit=per_query)
        for candidate in batch:
            if candidate.video_id in seen:
                continue
            seen.add(candidate.video_id)
            candidate.source = f"background_search:{query}"
            candidates.append(candidate)

    return candidates


def discover_search(*, query: str, limit: int) -> list[VideoCandidate]:
    # ytsearchN:query returns up to N results; we re-sort by views when available.
    search_url = f"ytsearch{limit}:{query}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    candidates: list[VideoCandidate] = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
        for entry in info.get("entries") or []:
            if entry is None:
                continue
            candidate = _video_from_ytdlp_entry(entry, source=f"ytdlp_search:{query}")
            if candidate:
                candidates.append(candidate)

    candidates.sort(key=lambda v: v.view_count or 0, reverse=True)
    return candidates


def is_music_video(video: VideoCandidate) -> bool:
    if video.category_id == MUSIC_CATEGORY_ID:
        return True
    if MUSIC_TITLE_RE.search(video.title):
        return True
    if MUSIC_CHANNEL_RE.search(video.channel):
        return True
    return False


def is_trailer(video: VideoCandidate) -> bool:
    return bool(TRAILER_TITLE_RE.search(video.title))


def is_live_or_event(video: VideoCandidate) -> bool:
    return bool(LIVE_TITLE_RE.search(video.title))


def looks_like_background_gameplay(video: VideoCandidate) -> bool:
    return bool(BACKGROUND_GAMEPLAY_TITLE_RE.search(video.title))


def is_commentary_heavy(video: VideoCandidate) -> bool:
    return bool(COMMENTARY_HEAVY_RE.search(video.title))


def is_realestate_tour(video: VideoCandidate) -> bool:
    return bool(REALESTATE_TOUR_RE.search(video.title))


def is_sim_game_footage(video: VideoCandidate) -> bool:
    return bool(SIM_GAME_FOOTAGE_TITLE_RE.search(video.title))


def is_cabin_titled(video: VideoCandidate) -> bool:
    return bool(CABIN_TITLE_RE.search(video.title))


def is_sleep_ambiance(video: VideoCandidate) -> bool:
    return bool(SLEEP_AMBIENCE_RE.search(video.title))


def is_vlog_or_intro(video: VideoCandidate) -> bool:
    return bool(VLOG_OR_INTRO_RE.search(video.title))


def background_gameplay_score(video: VideoCandidate) -> int:
    title = video.title.lower()
    score = 0
    if looks_like_background_gameplay(video):
        score += 4
    if "no commentary" in title or "without commentary" in title:
        score += 6
    if "background" in title:
        score += 3
    for keyword in ("satisfying", "mobile", "parkour", "subway", "sandwich", "relaxing"):
        if keyword in title:
            score += 3
    if "walkthrough" in title and ("part " in title or "full game" in title):
        score -= 3
    if video.duration_seconds and 60 <= video.duration_seconds <= 1800:
        score += 2
    if video.duration_seconds and video.duration_seconds >= 600:
        score += 1
    if video.duration_seconds and video.duration_seconds > 10_800:
        score -= 2
    if video.view_count and video.view_count >= 500_000:
        score += 2
    if video.view_count and video.view_count >= 1_000_000:
        score += 3
    if is_commentary_heavy(video):
        score -= 12
    if is_live_or_event(video):
        score -= 8
    if is_trailer(video):
        score -= 8
    return score


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def max_parts_per_source_cap() -> int | None:
    """When splitting a full download, cap part count so hour-long uploads do not explode."""
    raw = os.environ.get("BROLL_MAX_PARTS_PER_SOURCE", "8").strip()
    if not raw or raw.lower() in {"0", "none", "unlimited"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return 36
    return value if value > 0 else None


def estimate_part_count(
    duration_seconds: float | None,
    *,
    clip_length: int,
    max_parts: int | None,
) -> int:
    if duration_seconds is None or duration_seconds <= 0:
        return 1
    if duration_seconds <= clip_length:
        return 1
    count = math.ceil(duration_seconds / clip_length)
    if max_parts is not None:
        count = min(count, max_parts)
    else:
        cap = max_parts_per_source_cap()
        if cap is not None:
            count = min(count, cap)
    return max(count, 1)


def _toolchain_opts() -> dict[str, str]:
    try:
        from toolchain_env import apply_to_os_environ, ytdlp_ffmpeg_opts

        apply_to_os_environ()
        return ytdlp_ffmpeg_opts()
    except ImportError:
        return {}


def _resolve_tool(name: str) -> str:
    try:
        from toolchain_env import resolve_tool

        return resolve_tool(name) or name
    except ImportError:
        return name


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            _resolve_tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _even(value: int) -> int:
    return value - (value % 2)


def aspect_output_size(aspect_ratio: str, max_height: int) -> tuple[int, int] | None:
    if aspect_ratio == "original":
        return None
    try:
        width_ratio, height_ratio = (int(x) for x in aspect_ratio.split(":", 1))
    except ValueError as exc:
        raise ValueError(f"Invalid aspect ratio: {aspect_ratio!r} (use e.g. 16:9)") from exc
    if width_ratio <= 0 or height_ratio <= 0:
        raise ValueError(f"Invalid aspect ratio: {aspect_ratio!r}")

    if width_ratio >= height_ratio:
        height = _even(max_height)
        width = _even(round(height * width_ratio / height_ratio))
    else:
        width = _even(max_height)
        height = _even(round(width * height_ratio / width_ratio))
    return width, height


def build_aspect_filter(aspect_ratio: str, max_height: int) -> list[str]:
    size = aspect_output_size(aspect_ratio, max_height)
    if size is None:
        return []
    width, height = size
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    return ["-vf", vf]


def export_clip(
    source: Path,
    output: Path,
    *,
    start: float,
    duration: float,
    aspect_ratio: str,
    max_height: int,
) -> None:
    cmd = [
        _resolve_tool("ffmpeg"),
        "-y",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-t",
        str(duration),
        *build_aspect_filter(aspect_ratio, max_height),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def split_into_parts(
    source: Path,
    *,
    output_dir: Path,
    video_id: str,
    clip_length: int,
    max_parts: int | None,
    keep_source: bool,
    aspect_ratio: str,
    max_height: int,
    start_offset: float = 0.0,
) -> list[dict[str, Any]]:
    try:
        source_fps = probe_fps(source)
    except (OSError, ValueError, subprocess.CalledProcessError):
        source_fps = None
    if source_fps is not None and not is_usable_fps(source_fps):
        print(f"    drop {source.name}: {source_fps:.1f} fps")
        if not keep_source and source.exists():
            source.unlink()
            print(f"    Removed source file: {source.name}")
        return []

    duration = probe_duration(source)
    usable = max(duration - start_offset, 0.0)
    part_count = estimate_part_count(usable, clip_length=clip_length, max_parts=max_parts)
    size = aspect_output_size(aspect_ratio, max_height)
    if size:
        print(f"    Cropping/scaling parts to {aspect_ratio} ({size[0]}x{size[1]})")

    parts: list[dict[str, Any]] = []
    for part_num in range(1, part_count + 1):
        start = start_offset + (part_num - 1) * clip_length
        segment_duration = min(float(clip_length), max(duration - start, 0))
        if segment_duration <= 0:
            break
        part_path = output_dir / f"{video_id}_part{part_num:02d}.mp4"
        export_clip(
            source,
            part_path,
            start=start,
            duration=segment_duration,
            aspect_ratio=aspect_ratio,
            max_height=max_height,
        )
        parts.append(
            {
                "part": part_num,
                "title_suffix": f"Part {part_num}",
                "file_path": str(part_path),
                "start_seconds": start,
                "duration_seconds": segment_duration,
                "aspect_ratio": aspect_ratio,
            }
        )
        print(f"    Part {part_num}: {part_path.name} ({_format_duration(segment_duration)})")

    if not keep_source and source.exists() and len(parts) > 0:
        source.unlink()
        print(f"    Removed source file: {source.name}")

    return parts


def filter_unwanted(
    candidates: list[VideoCandidate],
    *,
    limit: int,
    exclude_music: bool,
    exclude_trailers: bool,
    exclude_live: bool,
    exclude_realestate_tours: bool = False,
    exclude_sim_footage: bool = True,
    background_gameplay_only: bool,
    min_views: int,
    min_duration: float,
    max_duration: float | None = None,
    exclude_sleep: bool = True,
    quiet: bool = False,
) -> list[VideoCandidate]:
    kept: list[VideoCandidate] = []
    skipped_music = 0
    skipped_trailers = 0
    skipped_live = 0
    skipped_commentary = 0
    skipped_tours = 0
    skipped_sim = 0
    skipped_views = 0
    skipped_duration = 0
    skipped_sleep = 0
    skipped_long = 0
    skipped_vlog = 0
    skipped_other = 0
    for video in candidates:
        if exclude_music and is_music_video(video):
            skipped_music += 1
            continue
        if exclude_trailers and is_trailer(video):
            skipped_trailers += 1
            continue
        if exclude_live and is_live_or_event(video):
            skipped_live += 1
            continue
        if exclude_realestate_tours and is_realestate_tour(video):
            skipped_tours += 1
            continue
        if exclude_sim_footage and is_sim_game_footage(video):
            skipped_sim += 1
            continue
        if is_commentary_heavy(video):
            skipped_commentary += 1
            continue
        if exclude_sleep and is_sleep_ambiance(video):
            skipped_sleep += 1
            continue
        if is_vlog_or_intro(video):
            skipped_vlog += 1
            continue
        if video.view_count is not None and video.view_count < min_views:
            skipped_views += 1
            continue
        if video.duration_seconds is not None and video.duration_seconds < min_duration:
            skipped_duration += 1
            continue
        if (
            max_duration is not None
            and video.duration_seconds is not None
            and video.duration_seconds > max_duration
        ):
            skipped_long += 1
            continue
        if background_gameplay_only and background_gameplay_score(video) < 4:
            skipped_other += 1
            continue
        kept.append(video)
    kept.sort(
        key=lambda v: (background_gameplay_score(v), v.view_count or 0),
        reverse=True,
    )
    parts = []
    if skipped_music:
        parts.append(f"{skipped_music} music video(s)")
    if skipped_trailers:
        parts.append(f"{skipped_trailers} trailer(s)")
    if skipped_live:
        parts.append(f"{skipped_live} livestream/event(s)")
    if skipped_commentary:
        parts.append(f"{skipped_commentary} commentary-heavy")
    if skipped_tours:
        parts.append(f"{skipped_tours} real-estate tour(s)")
    if skipped_sim:
        parts.append(f"{skipped_sim} sim/game footage")
    if skipped_views:
        parts.append(f"{skipped_views} low-view")
    if skipped_duration:
        parts.append(f"{skipped_duration} too-short")
    if skipped_sleep:
        parts.append(f"{skipped_sleep} sleep/ambiance")
    if skipped_vlog:
        parts.append(f"{skipped_vlog} vlog/intro")
    if skipped_long:
        parts.append(f"{skipped_long} too-long")
    if skipped_other:
        parts.append(f"{skipped_other} non-background gameplay")
    if parts:
        _safe_print(f"Filtered out {' and '.join(parts)}.", quiet=quiet)
    return kept[:limit]


def discover_urls(lines: list[str]) -> list[VideoCandidate]:
    candidates: list[VideoCandidate] = []
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            info = ydl.extract_info(line, download=False)
            candidate = _video_from_ytdlp_entry(info, source="explicit_url")
            if candidate:
                candidates.append(candidate)
    return candidates


def download_videos(
    candidates: list[VideoCandidate],
    *,
    output_dir: Path,
    max_height: int,
    audio_only: bool,
    clip_length: int,
    max_parts: int | None,
    split_parts: bool,
    keep_source: bool,
    aspect_ratio: str,
    quiet: bool = False,
    id_only_filenames: bool = False,
    start_offset: float = 0.0,
) -> list[dict[str, Any]]:
    _configure_stdout()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    if audio_only:
        format_selector = "bestaudio/best"
        name_tpl = "%(id)s.%(ext)s" if id_only_filenames else "%(id)s_%(title)s.%(ext)s"
        outtmpl = str(output_dir / name_tpl)
        postprocessors = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        min_fps = int(MIN_USABLE_FPS)
        format_selector = (
            f"bestvideo[fps>={min_fps}][height<={max_height}]+bestaudio/"
            f"bestvideo[fps>={min_fps}]+bestaudio/"
            f"best[fps>={min_fps}][height<={max_height}]/"
            f"best[fps>={min_fps}]"
        )
        outtmpl = str(output_dir / "%(id)s_source.%(ext)s")
        postprocessors = []

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": format_selector,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "writethumbnail": not audio_only,
        "writeinfojson": True,
        "postprocessors": postprocessors,
        "overwrites": True,
        "retries": 0,
        "fragment_retries": 0,
        "extractor_retries": 0,
        "file_access_retries": 0,
        "socket_timeout": 15,
        "skip_unavailable_fragments": True,
        **_toolchain_opts(),
    }

    for candidate in candidates:
        _safe_print(f"\n--- Downloading: {candidate.title}", quiet=quiet)
        _safe_print(f"    {candidate.url}", quiet=quiet)
        record: dict[str, Any] = {
            **asdict(candidate),
            "status": "pending",
            "source_file": None,
            "parts": [],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(candidate.url, download=True)
                if not info:
                    raise RuntimeError("yt-dlp returned no video info")
                filepath = Path(ydl.prepare_filename(info))
                if audio_only:
                    filepath = filepath.with_suffix(".mp3")
                elif filepath.suffix.lower() != ".mp4":
                    merged = filepath.with_suffix(".mp4")
                    if merged.exists():
                        filepath = merged
                if not filepath.exists():
                    raise FileNotFoundError(f"Expected output missing: {filepath}")

                record["source_file"] = str(filepath)

                if audio_only or not split_parts:
                    if audio_only:
                        record["file_path"] = str(filepath)
                        _safe_print(f"    Saved: {filepath}", quiet=quiet)
                    else:
                        converted = output_dir / f"{candidate.video_id}_16x9.mp4"
                        duration = probe_duration(filepath)
                        size = aspect_output_size(aspect_ratio, max_height)
                        if size:
                            _safe_print(
                                f"    Converting to {aspect_ratio} ({size[0]}x{size[1]})...",
                                quiet=quiet,
                            )
                        export_clip(
                            filepath,
                            converted,
                            start=0,
                            duration=duration,
                            aspect_ratio=aspect_ratio,
                            max_height=max_height,
                        )
                        if not keep_source and filepath.exists():
                            filepath.unlink()
                        record["file_path"] = str(converted)
                        record["aspect_ratio"] = aspect_ratio
                        _safe_print(f"    Saved: {converted}", quiet=quiet)
                    record["status"] = "ok"
                else:
                    try:
                        source_duration = probe_duration(filepath)
                    except (OSError, ValueError, subprocess.CalledProcessError):
                        source_duration = candidate.duration_seconds
                        if source_duration is None:
                            source_duration = info.get("duration")
                    source_label = _format_duration(
                        float(source_duration) if source_duration is not None else None
                    )
                    part_label = _format_duration(float(clip_length))
                    if max_parts is None:
                        _safe_print(
                            f"    Splitting full source {source_label} into ~{part_label} parts...",
                            quiet=quiet,
                        )
                    else:
                        _safe_print(
                            f"    Splitting {source_label} into ~{part_label} parts...",
                            quiet=quiet,
                        )
                    parts = split_into_parts(
                        filepath,
                        output_dir=output_dir,
                        video_id=candidate.video_id,
                        clip_length=clip_length,
                        max_parts=max_parts,
                        keep_source=keep_source,
                        aspect_ratio=aspect_ratio,
                        max_height=max_height,
                        start_offset=start_offset,
                    )
                    record["parts"] = parts
                    record["status"] = "ok" if parts else "error"
                    if not parts:
                        record["error"] = "No parts were created"
        except Exception as exc:  # noqa: BLE001 — collect per-video failures
            record["status"] = "error"
            record["error"] = str(exc)
            err = str(exc)
            if "403" in err or "Forbidden" in err:
                _safe_print(f"    Skip 403: {candidate.video_id} — next source", file=sys.stderr, quiet=quiet)
            else:
                _safe_print(f"    Failed: {exc}", file=sys.stderr, quiet=quiet)
            continue
        results.append(record)

    return results


def write_manifest(output_dir: Path, mode: str, args: argparse.Namespace, results: list[dict[str, Any]]) -> Path:
    def _json_safe(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        return value

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "args": {k: _json_safe(v) for k, v in vars(args).items() if k != "func"},
        "videos": results,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find popular YouTube videos and download them locally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output",
        type=Path,
        default=_default_output_dir(),
        help=f"Download directory (default: {_default_output_dir()})",
    )
    common.add_argument("--limit", type=int, default=5, help="Max videos to fetch/download")
    common.add_argument(
        "--max-height",
        type=int,
        default=1080,
        help="Max video height in pixels (default: 1080)",
    )
    common.add_argument("--audio-only", action="store_true", help="Download audio as MP3 only")
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates without downloading",
    )
    common.add_argument(
        "--include-music",
        action="store_true",
        help="Keep music videos (excluded by default)",
    )
    common.add_argument(
        "--include-trailers",
        action="store_true",
        help="Keep trailers and teasers (excluded by default)",
    )
    common.add_argument(
        "--include-live",
        action="store_true",
        help="Keep livestreams and showcases (excluded by default)",
    )
    common.add_argument(
        "--min-views",
        type=int,
        default=100_000,
        help="Minimum view count (default: 100000)",
    )
    common.add_argument(
        "--min-duration",
        type=int,
        default=60,
        help="Minimum source video length in seconds (default: 60)",
    )
    common.add_argument(
        "--clip-length",
        type=int,
        default=120,
        help="Max length per output clip in seconds (default: 120 = 2 minutes)",
    )
    common.add_argument(
        "--max-parts",
        type=int,
        default=None,
        help="Max parts to export per source video (default: unlimited)",
    )
    common.add_argument(
        "--no-split",
        action="store_true",
        help="Download full source video without splitting into parts",
    )
    common.add_argument(
        "--keep-source",
        action="store_true",
        help="Keep the full downloaded source after splitting",
    )
    common.add_argument(
        "--aspect-ratio",
        default="9:16",
        help="Output aspect ratio: 9:16 (default, Shorts/Reels), 16:9, or original",
    )
    common.add_argument(
        "--voiceover",
        action="store_true",
        help="After download, run AI story + TTS + captions (waits for Cursor story.json)",
    )
    common.add_argument(
        "--no-wait-for-story",
        action="store_true",
        help="With --voiceover: write story prompt and exit instead of waiting for story.json",
    )
    common.add_argument(
        "--story-theme",
        default="a shocking secret that ruined everything",
        help="Theme for AI story when --voiceover is used",
    )
    common.add_argument(
        "--voice",
        default="en-US-ChristopherNeural",
        help="edge-tts voice name for narration",
    )
    common.add_argument(
        "--require-unused",
        action="store_true",
        help="Only download YouTube IDs not in content/used.json (default: reuse allowed)",
    )
    common.add_argument(
        "--allow-reuse",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    common.add_argument(
        "--any-topic",
        action="store_true",
        help="Skip background-gameplay title filter (car B-roll, nature, etc.)",
    )

    trending = sub.add_parser(
        "trending",
        parents=[common],
        help="Fetch popular background gameplay for voiceover repurposing",
    )
    trending.add_argument("--region", default="US", help="Region code for API trending (default: US)")
    trending.add_argument(
        "--category",
        choices=sorted(CATEGORY_IDS),
        default="gaming",
        help="Optional API category supplement (default: gaming)",
    )
    trending.add_argument(
        "--api-key",
        default=os.environ.get("YOUTUBE_API_KEY"),
        help="YouTube Data API key (or set YOUTUBE_API_KEY env var)",
    )

    search = sub.add_parser("search", parents=[common], help="Search YouTube by keyword")
    search.add_argument("--query", required=True, help='Search query, e.g. "viral moments"')

    urls = sub.add_parser("urls", parents=[common], help="Download URLs from a text file")
    urls.add_argument("--file", type=Path, required=True, help="Text file with one URL per line")

    return parser


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _safe_print(message: str, *, file=None, quiet: bool = False) -> None:
    if quiet:
        return
    stream = file or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe, file=stream, flush=True)


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    _configure_stdout()
    _load_local_env()
    parser = build_parser()
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.clip_length < 1:
        parser.error("--clip-length must be at least 1")
    if args.max_parts is not None and args.max_parts < 1:
        parser.error("--max-parts must be at least 1")
    if args.aspect_ratio not in {"original", "16:9", "9:16"}:
        parser.error("--aspect-ratio must be original, 16:9, or 9:16")

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[VideoCandidate] = []
    if args.mode == "trending":
        print("Searching for popular background gameplay (no commentary)...")
        candidates = discover_background_gameplay(limit=max(args.limit * 4, 40))
        if args.api_key:
            print(f"Also checking YouTube gaming chart (region={args.region})...")
            try:
                api_candidates = discover_trending_api(
                    api_key=args.api_key,
                    limit=args.limit,
                    region=args.region,
                    category=args.category,
                )
                seen = {video.video_id for video in candidates}
                for video in api_candidates:
                    if video.video_id not in seen:
                        candidates.append(video)
                        seen.add(video.video_id)
            except Exception as exc:  # noqa: BLE001
                print(f"API supplement skipped ({exc}).", file=sys.stderr)

    elif args.mode == "search":
        print(f'Searching YouTube for "{args.query}"...')
        candidates = discover_search(query=args.query, limit=max(args.limit * 4, 20))

    elif args.mode == "urls":
        if not args.file.is_file():
            parser.error(f"URL file not found: {args.file}")
        lines = args.file.read_text(encoding="utf-8").splitlines()
        print(f"Loading {len(lines)} URL(s) from {args.file}...")
        candidates = discover_urls(lines)

    include_music = args.include_music or (
        args.mode == "trending" and getattr(args, "category", None) == "music"
    )
    background_only = args.mode != "urls" and not args.any_topic
    if args.mode != "urls":
        candidates = filter_unwanted(
            candidates,
            limit=args.limit,
            exclude_music=not include_music,
            exclude_trailers=not args.include_trailers,
            exclude_live=not args.include_live,
            background_gameplay_only=background_only,
            min_views=args.min_views,
            min_duration=float(args.min_duration),
        )
    else:
        candidates = candidates[: args.limit]

    if args.require_unused and not args.allow_reuse:
        used_ids = content_reuse.used_youtube_ids()
        if used_ids:
            before = len(candidates)
            reused = [video for video in candidates if video.video_id in used_ids]
            candidates = [video for video in candidates if video.video_id not in used_ids]
            skipped_used = before - len(candidates)
            if skipped_used:
                print(f"Skipped {skipped_used} already-used source video(s) (--require-unused).")
                for video in reused[:8]:
                    print(f"  prior use: {video.title} ({video.video_id})")
            candidates = candidates[: args.limit]
    elif used_hint := content_reuse.used_youtube_ids():
        reused = [video for video in candidates if video.video_id in used_hint]
        if reused:
            print(f"Note: {len(reused)} candidate(s) appear in content/used.json (reuse allowed).")
            for video in reused[:5]:
                print(f"  prior use: {video.title} ({video.video_id})")

    if not candidates:
        print("No videos found.", file=sys.stderr)
        print(
            "Try lowering --min-views, lowering --min-duration, or search explicitly, e.g.\n"
            '  python scripts/youtube_popular_downloader.py search '
            '--query "minecraft parkour no commentary" --limit 5 --dry-run',
            file=sys.stderr,
        )
        return 1

    split_parts = not args.no_split and not args.audio_only
    clip_length = args.clip_length
    max_parts = args.max_parts

    print(f"\nFound {len(candidates)} background gameplay video(s):\n")
    for i, v in enumerate(candidates, 1):
        views = f"{v.view_count:,}" if v.view_count else "?"
        duration = _format_duration(v.duration_seconds)
        score = background_gameplay_score(v)
        parts_note = ""
        if split_parts:
            part_count = estimate_part_count(
                v.duration_seconds,
                clip_length=clip_length,
                max_parts=max_parts,
            )
            parts_note = f" -> {part_count} clip(s) @ {_format_duration(float(clip_length))} each"
        print(f"  {i}. [{views} views | {duration}] score={score}{parts_note}")
        print(f"     {v.title}")
        print(f"     {v.channel} — {v.url}")

    if args.dry_run:
        manifest_rows = []
        for c in candidates:
            row = asdict(c)
            if split_parts:
                row["estimated_parts"] = estimate_part_count(
                    c.duration_seconds,
                    clip_length=clip_length,
                    max_parts=max_parts,
                )
                row["clip_length_seconds"] = clip_length
            manifest_rows.append(row)
        manifest_path = write_manifest(output_dir, args.mode, args, manifest_rows)
        print(f"\nDry run complete. Manifest: {manifest_path}")
        if split_parts:
            total_parts = sum(
                estimate_part_count(c.duration_seconds, clip_length=clip_length, max_parts=max_parts)
                for c in candidates
            )
            print(f"Would create {total_parts} part file(s) total (max {_format_duration(float(clip_length))} each).")
        return 0

    print(f"\nDownloading to {output_dir} ...")
    if split_parts:
        size = aspect_output_size(args.aspect_ratio, args.max_height)
        ratio_note = f", output {args.aspect_ratio}"
        if size:
            ratio_note += f" ({size[0]}x{size[1]})"
        print(
            f"Each source will be split into {_format_duration(float(clip_length))} parts "
            f"(Part 1, Part 2, ...){ratio_note}."
        )
    results = download_videos(
        candidates,
        output_dir=output_dir,
        max_height=args.max_height,
        audio_only=args.audio_only,
        clip_length=clip_length,
        max_parts=max_parts,
        split_parts=split_parts,
        keep_source=args.keep_source,
        aspect_ratio=args.aspect_ratio,
    )
    manifest_path = write_manifest(output_dir, args.mode, args, results)
    for record in results:
        if record.get("status") != "ok":
            continue
        content_reuse.register_video(
            youtube_id=str(record.get("video_id") or ""),
            title=str(record.get("title") or ""),
        )

    ok = sum(1 for r in results if r.get("status") == "ok")
    total_parts = sum(len(r.get("parts") or []) for r in results)
    print(f"\nDone: {ok}/{len(results)} source video(s) processed.")
    if split_parts:
        print(f"Created {total_parts} part file(s).")
    print(f"Manifest: {manifest_path}")

    if getattr(args, "voiceover", False):
        if args.dry_run:
            print("\n--voiceover skipped during dry-run.")
        elif ok == 0:
            print("\n--voiceover skipped: no videos downloaded.", file=sys.stderr)
        else:
            pipeline = Path(__file__).resolve().parent / "story_voiceover_pipeline.py"
            print("\nRunning story + voiceover pipeline (Kinocut)...")
            voiceover_cmd = [
                sys.executable,
                str(pipeline),
                str(manifest_path),
                "--output",
                str(output_dir / "final"),
                "--theme",
                args.story_theme,
                "--voice",
                args.voice,
                "--story-mode",
                "cursor",
            ]
            if args.no_wait_for_story:
                voiceover_cmd.append("--no-wait-for-story")
            voiceover_result = subprocess.run(voiceover_cmd, check=False)
            if voiceover_result.returncode == 2:
                print(
                    "\nClips downloaded. Ask Cursor to write story.json using "
                    f"{output_dir / 'final' / 'CURSOR_STORY_PROMPT.md'}, then re-run voiceover."
                )
            elif voiceover_result.returncode != 0:
                print("Voiceover pipeline failed.", file=sys.stderr)
                return voiceover_result.returncode
            else:
                print(f"Final videos: {output_dir / 'final'}")

    print("\nPost Part 1, then Part 2, etc. Final files end with _final.mp4")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
