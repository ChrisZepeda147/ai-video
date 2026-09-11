"""Shared helpers for local media paths in the dashboard."""

from __future__ import annotations

from pathlib import Path


AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv"})


def normalize_rel_path(path: str | None) -> str:
    if not path:
        return ""
    return str(path).replace("\\", "/").lstrip("/")


def file_exists_rel(root: Path, rel_path: str | None) -> bool:
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return False
    return (root / normalized).is_file()


def display_media_path(rel_path: str | None) -> str | None:
    """Short repo-relative path for UI (strip noisy prefixes when possible)."""
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return None
    for marker in ("downloads/", "shared_library/", "prompts/"):
        idx = normalized.find(marker)
        if idx >= 0:
            return normalized[idx:]
    return normalized


def infer_media_kind(rel_path: str | None, *, role: str | None = None) -> str:
    """Return audio | video | other for catalog filtering."""
    if role == "speech":
        return "audio"
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return "other"
    suffix = Path(normalized).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if normalized.endswith(".json3") or normalized.endswith(".json"):
        return "audio"
    return "other"
