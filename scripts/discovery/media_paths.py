"""Shared helpers for local media paths in the dashboard."""

from __future__ import annotations

from pathlib import Path


AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv"})
VIDEO_MEDIA_KINDS = frozenset({"audio", "video", "video_audio", "other"})
MIN_PLAYABLE_BYTES = 100_000
MIN_AUDIO_BYTES = 4_096


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


def is_playable_file(path: Path, *, min_bytes: int | None = None) -> bool:
    """True when file exists and is above stub size."""
    if not path.is_file():
        return False
    if min_bytes is None:
        min_bytes = MIN_AUDIO_BYTES if path.suffix.lower() in AUDIO_EXTENSIONS else MIN_PLAYABLE_BYTES
    try:
        return path.stat().st_size >= min_bytes
    except OSError:
        return False


def is_playable_media(root: Path, rel_path: str | None, *, role: str | None = None) -> bool:
    """True when repo-relative media exists and is large enough to preview."""
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return False
    path = root / normalized
    if not path.is_file():
        return False
    kind = infer_media_kind(normalized, role=role)
    floor = MIN_AUDIO_BYTES if kind == "audio" else MIN_PLAYABLE_BYTES
    return is_playable_file(path, min_bytes=floor)


def motivation_job_slug_from_rel(rel_path: str | None) -> str | None:
    from discovery.motivation_paths import motivation_job_slug_from_rel as _slug_from_rel

    return _slug_from_rel(normalize_rel_path(rel_path))


def is_complete_motivation_job(
    root: Path,
    job_slug: str,
    *,
    output_path: Path | None = None,
) -> bool:
    """Motivation/combo job must have speech, visual clips, and a real output."""
    from discovery.motivation_paths import motivation_jobs_root, resolve_job_dir

    job_dir = resolve_job_dir(job_slug, motivation_jobs_root(root))
    if not job_dir:
        return False
    speech = job_dir / "audio" / "speech.mp3"
    if not is_playable_file(speech, min_bytes=MIN_AUDIO_BYTES):
        return False
    clips_dir = job_dir / "clips"
    if not clips_dir.is_dir():
        return False
    if not any(is_playable_file(clip) for clip in clips_dir.glob("*.mp4")):
        return False
    if output_path is None:
        out_dir = job_dir / "output"
        candidates: list[Path] = []
        if out_dir.is_dir():
            candidates.extend(sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True))
        default = out_dir / f"{job_slug}-motivation.mp4"
        if default.is_file():
            candidates.insert(0, default)
        output_path = candidates[0] if candidates else None
    if not output_path or not is_playable_file(output_path):
        return False
    return True


def is_previewable_output(root: Path, rel_path: str | None, *, role: str | None = None) -> bool:
    """Videos tab preview gate — rejects stubs and incomplete motivation/combo jobs."""
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return False
    job_slug = motivation_job_slug_from_rel(normalized)
    if job_slug:
        return is_complete_motivation_job(root, job_slug, output_path=root / normalized)
    return is_playable_media(root, normalized, role=role)


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
