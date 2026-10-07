"""Preflight YouTube formats before expensive B-roll downloads."""

from __future__ import annotations

from typing import Any

try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # type: ignore[assignment]

from build_clips_montage import MIN_USABLE_FPS

MAX_HEIGHT = 2160  # no 8K acquisition


def _height_score(height: int) -> int:
    if height <= 1440:
        return 300 - abs(height - 1440)
    if height <= 1080:
        return 250 - abs(height - 1080)
    if height <= 2160:
        return 200 - abs(height - 2160) // 4
    return -1000


def inspect_usable_formats(url: str) -> tuple[bool, str | None, dict[str, Any]]:
    if yt_dlp is None:
        return True, None, {}
    opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        from toolchain_env import ytdlp_ffmpeg_opts

        opts.update(ytdlp_ffmpeg_opts())
    except ImportError:
        pass
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return True, None, {}
    if not isinstance(info, dict):
        return True, None, {}
    formats = info.get("formats") or []
    best: dict[str, Any] | None = None
    best_score = -10_000
    min_fps = float(MIN_USABLE_FPS)
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("vcodec") in (None, "none"):
            continue
        height = int(fmt.get("height") or 0)
        if height <= 0 or height > MAX_HEIGHT:
            continue
        fps = float(fmt.get("fps") or 0)
        if fps < min_fps:
            continue
        score = _height_score(height) + min(fps, 120.0)
        if score > best_score:
            best_score = score
            best = {
                "height": height,
                "fps": fps,
                "format_id": fmt.get("format_id"),
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
            }
    if best is None:
        return False, "no_50fps_format", {}
    return True, None, best


def log_candidate_skip(video_id: str, reason: str) -> None:
    print(f"BROLL_CANDIDATE_SKIP id={video_id} reason={reason}")
