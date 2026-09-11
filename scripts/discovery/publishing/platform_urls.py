"""Parse platform post URLs into platform + post id."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TIKTOK_ID_RE = re.compile(r"^\d{8,}$")
INSTAGRAM_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_platform_post_url(url: str) -> tuple[str, str, str]:
    """Return (platform, platform_post_id, normalized_url)."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("platform_url is required")
    if not raw.startswith("http"):
        raw = f"https://{raw.lstrip('/')}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if "youtube.com" in host or "youtu.be" in host:
        post_id = _youtube_id(parsed)
        if not post_id:
            raise ValueError("Could not parse YouTube video id from URL")
        normalized = f"https://www.youtube.com/watch?v={post_id}"
        return "youtube", post_id, normalized

    if "tiktok.com" in host:
        post_id = _tiktok_id(path)
        if not post_id:
            raise ValueError("Could not parse TikTok video id from URL")
        normalized = raw.split("?")[0]
        return "tiktok", post_id, normalized

    if "instagram.com" in host:
        post_id = _instagram_code(path)
        if not post_id:
            raise ValueError("Could not parse Instagram post code from URL")
        normalized = raw.split("?")[0]
        return "instagram", post_id, normalized

    if "facebook.com" in host or "fb.watch" in host:
        post_id = _facebook_id(path, parsed)
        if not post_id:
            raise ValueError("Could not parse Facebook post id from URL")
        normalized = raw.split("?")[0]
        return "facebook", post_id, normalized

    raise ValueError(f"Unsupported platform URL host: {host or raw}")


def _youtube_id(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if "youtu.be" in host:
        parts = [p for p in path.split("/") if p]
        if parts and YOUTUBE_ID_RE.match(parts[0]):
            return parts[0]
    if "/shorts/" in path:
        parts = [p for p in path.split("/") if p]
        idx = parts.index("shorts") if "shorts" in parts else -1
        if idx >= 0 and idx + 1 < len(parts) and YOUTUBE_ID_RE.match(parts[idx + 1]):
            return parts[idx + 1]
    query = parse_qs(parsed.query or "")
    vid = (query.get("v") or [None])[0]
    if vid and YOUTUBE_ID_RE.match(vid):
        return vid
    return None


def _tiktok_id(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    for part in reversed(parts):
        if TIKTOK_ID_RE.match(part):
            return part
    return None


def _facebook_id(path: str, parsed) -> str | None:
    parts = [p for p in path.split("/") if p]
    for marker in ("posts", "videos", "reel", "watch"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    query = parse_qs(parsed.query or "")
    story = (query.get("story_fbid") or [None])[0]
    if story:
        return str(story)
    if parts and parts[-1].isdigit():
        return parts[-1]
    return None


def _instagram_code(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    for marker in ("p", "reel", "reels", "tv"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                code = parts[idx + 1]
                if INSTAGRAM_CODE_RE.match(code):
                    return code
    return None
