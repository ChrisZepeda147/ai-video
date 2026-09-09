"""
YouTube metadata-only reference discovery.

REFERENCE VIDEO != PRODUCTION ASSET

This module never downloads video files and never calls production pipelines.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from discovery.config import YOUTUBE_DETAILS_BATCH_SIZE, youtube_api_key
from discovery.models import ReferenceVideo

YOUTUBE_PLATFORM = "youtube"
SHORTS_MAX_DURATION_SEC = 60.0
ISO8601_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


class YouTubeClient(Protocol):
    def search_video_ids(
        self,
        *,
        query: str,
        limit: int,
        shorts_only: bool,
    ) -> list[str]: ...

    def fetch_video_details(self, video_ids: list[str]) -> list[ReferenceVideo]: ...


def iso8601_duration_to_seconds(duration: str | None) -> float | None:
    if not duration:
        return None
    match = ISO8601_DURATION_RE.fullmatch(duration)
    if not match:
        return None
    hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def parse_int_stat(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def best_thumbnail(snippet: dict[str, Any]) -> str | None:
    thumbs = snippet.get("thumbnails") or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbs.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return None


def item_to_reference(
    item: dict[str, Any],
    *,
    source_query: str | None,
) -> ReferenceVideo | None:
    video_id = item.get("id")
    if not video_id:
        return None
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    content = item.get("contentDetails") or {}
    duration = iso8601_duration_to_seconds(content.get("duration"))
    return ReferenceVideo(
        platform=YOUTUBE_PLATFORM,
        external_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=snippet.get("title") or "(untitled)",
        channel=snippet.get("channelTitle"),
        channel_id=snippet.get("channelId"),
        description=snippet.get("description"),
        duration_sec=duration,
        view_count=parse_int_stat(stats.get("viewCount")),
        like_count=parse_int_stat(stats.get("likeCount")),
        comment_count=parse_int_stat(stats.get("commentCount")),
        published_at=snippet.get("publishedAt"),
        thumbnail_url=best_thumbnail(snippet),
        source_query=source_query,
        production_asset=False,
    )


def is_short_duration(duration_sec: float | None) -> bool:
    return duration_sec is not None and duration_sec <= SHORTS_MAX_DURATION_SEC


class YouTubeApiClient:
    """YouTube Data API v3 client — search once, details in batches."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._youtube = None

    def _service(self) -> Any:
        if self._youtube is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError(
                    "google-api-python-client is required for YouTube API discovery. "
                    "Install with: pip install -r scripts/requirements-youtube.txt"
                ) from exc
            self._youtube = build("youtube", "v3", developerKey=self.api_key, cache_discovery=False)
        return self._youtube

    def search_video_ids(
        self,
        *,
        query: str,
        limit: int,
        shorts_only: bool,
    ) -> list[str]:
        youtube = self._service()
        search_query = query
        if shorts_only and "#shorts" not in query.lower():
            search_query = f"{query} #shorts"

        collected: list[str] = []
        seen: set[str] = set()
        page_token: str | None = None

        while len(collected) < limit:
            page_size = min(50, limit - len(collected))
            params: dict[str, Any] = {
                "part": "id",
                "q": search_query,
                "type": "video",
                "maxResults": page_size,
                "order": "viewCount",
            }
            if shorts_only:
                params["videoDuration"] = "short"
            if page_token:
                params["pageToken"] = page_token

            response = youtube.search().list(**params).execute()
            for item in response.get("items") or []:
                video_id = (item.get("id") or {}).get("videoId")
                if not video_id or video_id in seen:
                    continue
                seen.add(video_id)
                collected.append(video_id)
                if len(collected) >= limit:
                    break

            page_token = response.get("nextPageToken")
            if not page_token or not response.get("items"):
                break

        return collected[:limit]

    def fetch_video_details(self, video_ids: list[str]) -> list[ReferenceVideo]:
        if not video_ids:
            return []
        youtube = self._service()
        refs: list[ReferenceVideo] = []
        for offset in range(0, len(video_ids), YOUTUBE_DETAILS_BATCH_SIZE):
            batch = video_ids[offset : offset + YOUTUBE_DETAILS_BATCH_SIZE]
            response = youtube.videos().list(
                part="snippet,contentDetails,statistics",
                id=",".join(batch),
            ).execute()
            for item in response.get("items") or []:
                ref = item_to_reference(item, source_query=None)
                if ref:
                    refs.append(ref)
        return refs


class YtDlpClient:
    """Metadata-only fallback when YouTube Data API is unavailable."""

    def search_video_ids(
        self,
        *,
        query: str,
        limit: int,
        shorts_only: bool,
    ) -> list[str]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "yt-dlp is required when YOUTUBE_API_KEY is not set. "
                "Install with: pip install -r scripts/requirements-youtube.txt"
            ) from exc

        search_query = query
        if shorts_only and "#shorts" not in query.lower():
            search_query = f"{query} #shorts"

        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        ids: list[str] = []
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{search_query}", download=False)
            for entry in info.get("entries") or []:
                if entry is None:
                    continue
                video_id = entry.get("id")
                if video_id:
                    ids.append(video_id)
        return ids[:limit]

    def fetch_video_details(self, video_ids: list[str]) -> list[ReferenceVideo]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "yt-dlp is required when YOUTUBE_API_KEY is not set. "
                "Install with: pip install -r scripts/requirements-youtube.txt"
            ) from exc

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        refs: list[ReferenceVideo] = []
        with yt_dlp.YoutubeDL(opts) as ydl:
            for video_id in video_ids:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = ydl.extract_info(url, download=False)
                if not info:
                    continue
                refs.append(
                    ReferenceVideo(
                        platform=YOUTUBE_PLATFORM,
                        external_id=video_id,
                        url=url,
                        title=info.get("title") or "(untitled)",
                        channel=info.get("uploader") or info.get("channel"),
                        channel_id=info.get("channel_id"),
                        description=info.get("description"),
                        duration_sec=info.get("duration"),
                        view_count=parse_int_stat(info.get("view_count")),
                        like_count=parse_int_stat(info.get("like_count")),
                        comment_count=parse_int_stat(info.get("comment_count")),
                        published_at=info.get("upload_date"),
                        thumbnail_url=info.get("thumbnail"),
                        source_query=None,
                        production_asset=False,
                    )
                )
        return refs


def build_youtube_client() -> YouTubeClient:
    key = youtube_api_key()
    if key:
        return YouTubeApiClient(key)
    return YtDlpClient()
