"""Cache YouTube B-roll search candidate lists."""

from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any

SEARCH_CACHE_VERSION = "broll_search_v1"
DEFAULT_TTL_SEC = 86400 * 3


def _cache_path(jobs_root: Path) -> Path:
    return jobs_root / "broll-pool" / "search_cache.json"


def _normalize_query(query: str) -> str:
    return " ".join((query or "").lower().split())


def _query_key(query: str, *, min_views: int, min_duration: int) -> str:
    raw = f"{SEARCH_CACHE_VERSION}|{_normalize_query(query)}|{min_views}|{min_duration}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": SEARCH_CACHE_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": SEARCH_CACHE_VERSION, "entries": {}}
    if data.get("version") != SEARCH_CACHE_VERSION:
        return {"version": SEARCH_CACHE_VERSION, "entries": {}}
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_cached_candidates(
    jobs_root: Path | None,
    *,
    query: str,
    min_views: int,
    min_duration: int,
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> list[dict[str, Any]] | None:
    if jobs_root is None:
        return None
    path = _cache_path(jobs_root)
    data = _load(path)
    key = _query_key(query, min_views=min_views, min_duration=min_duration)
    entry = data.get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return None
    ts = float(entry.get("cached_at") or 0)
    if time.time() - ts > ttl_sec:
        return None
    items = entry.get("candidates")
    if not isinstance(items, list):
        return None
    return list(items)


def store_cached_candidates(
    jobs_root: Path | None,
    *,
    query: str,
    min_views: int,
    min_duration: int,
    candidates: list[dict[str, Any]],
) -> None:
    if jobs_root is None:
        return
    path = _cache_path(jobs_root)
    data = _load(path)
    key = _query_key(query, min_views=min_views, min_duration=min_duration)
    data.setdefault("entries", {})[key] = {
        "query": query,
        "cached_at": time.time(),
        "candidates": candidates,
    }
    _save(path, data)
