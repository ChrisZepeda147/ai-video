"""Layout helpers for downloads/motivational job folders."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Top-level dirs under downloads/motivational that are not per-job folders.
RESERVED_DIR_NAMES = frozenset(
    {
        "broll-pool",
        "speech-pool",
        "pool",
        "_speech-source",
    }
)


def motivation_jobs_root(root: Path) -> Path:
    return root / "downloads" / "motivational"


def is_date_folder(name: str) -> bool:
    return bool(DATE_DIR_RE.match(name))


def is_reserved_motivation_dir(name: str) -> bool:
    return name in RESERVED_DIR_NAMES


def default_job_date(*, when: datetime | None = None) -> str:
    """Calendar day for new job folders (local timezone)."""
    moment = when or datetime.now().astimezone()
    return moment.date().isoformat()


def job_date_from_iso(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone().date().isoformat()


def legacy_job_dir(slug: str, jobs_root: Path) -> Path:
    return jobs_root / slug


def job_dir_for(slug: str, jobs_root: Path, *, job_date: str | None = None) -> Path:
    day = job_date or default_job_date()
    return jobs_root / day / slug


def _job_dir_has_markers(path: Path) -> bool:
    return (
        (path / "job.json").is_file()
        or (path / "output").is_dir()
        or (path / "audio").is_dir()
    )


def resolve_job_dir(slug: str, jobs_root: Path) -> Path | None:
    """Find an existing job folder (dated layout first, then legacy flat)."""
    if not jobs_root.is_dir():
        return None
    legacy = legacy_job_dir(slug, jobs_root)
    dated_matches: list[Path] = []
    for child in jobs_root.iterdir():
        if not child.is_dir() or is_reserved_motivation_dir(child.name):
            continue
        if is_date_folder(child.name):
            candidate = child / slug
            if candidate.is_dir() and _job_dir_has_markers(candidate):
                dated_matches.append(candidate)
    if dated_matches:
        return max(dated_matches, key=lambda p: p.stat().st_mtime)
    if legacy.is_dir() and _job_dir_has_markers(legacy):
        return legacy
    return None


def iter_legacy_motivation_job_dirs(jobs_root: Path) -> Iterator[Path]:
    """Job folders still sitting directly under downloads/motivational/."""
    if not jobs_root.is_dir():
        return
    for child in sorted(jobs_root.iterdir()):
        if not child.is_dir() or is_reserved_motivation_dir(child.name) or is_date_folder(child.name):
            continue
        if _job_dir_has_markers(child):
            yield child


def infer_job_folder_date(job_dir: Path) -> str:
    """Best calendar day for sorting a job (output mtime, then job.json, then folder mtime)."""
    job_json = job_dir / "job.json"
    if job_json.is_file():
        try:
            payload = json.loads(job_json.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                stored = str(payload.get("job_date") or "").strip()
                if is_date_folder(stored):
                    return stored
                for key in ("created_at", "rendered_at", "exported_at"):
                    parsed = job_date_from_iso(str(payload.get(key) or ""))
                    if parsed:
                        return parsed
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    output_dir = job_dir / "output"
    if output_dir.is_dir():
        mp4s = list(output_dir.glob("*.mp4"))
        if mp4s:
            newest = max(mp4s, key=lambda p: p.stat().st_mtime)
            return datetime.fromtimestamp(newest.stat().st_mtime).astimezone().date().isoformat()
    stamp = datetime.fromtimestamp(job_dir.stat().st_mtime).astimezone()
    return default_job_date(when=stamp)


def motivation_job_rel_prefix(slug: str, job_date: str) -> str:
    return f"downloads/motivational/{job_date}/{slug}"


def legacy_motivation_job_rel_prefix(slug: str) -> str:
    return f"downloads/motivational/{slug}"


def iter_motivation_job_dirs(jobs_root: Path) -> Iterator[Path]:
    if not jobs_root.is_dir():
        return
    for child in sorted(jobs_root.iterdir()):
        if not child.is_dir() or is_reserved_motivation_dir(child.name):
            continue
        if is_date_folder(child.name):
            for job_dir in sorted(child.iterdir()):
                if job_dir.is_dir() and not is_reserved_motivation_dir(job_dir.name):
                    yield job_dir
        elif _job_dir_has_markers(child):
            yield child


def motivation_output_path(job_dir: Path, slug: str) -> Path:
    return job_dir / "output" / f"{slug}-motivation.mp4"


def motivation_output_rel(root: Path, job_dir: Path, slug: str) -> str:
    return motivation_output_path(job_dir, slug).relative_to(root).as_posix()


def motivation_job_slug_from_rel(rel_path: str | None) -> str | None:
    """Job slug from downloads/motivational/…/output/… paths."""
    if not rel_path:
        return None
    normalized = str(rel_path).replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    try:
        idx = parts.index("motivational")
    except ValueError:
        return None
    tail = parts[idx + 1 :]
    if len(tail) >= 3 and is_date_folder(tail[0]) and tail[2] == "output":
        return tail[1]
    if len(tail) >= 2 and tail[1] == "output":
        return tail[0]
    return None
