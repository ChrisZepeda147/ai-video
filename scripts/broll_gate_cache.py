"""Cache frame/subject gate results for B-roll parts (avoid repeat vision scans)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

GATE_VERSION = "broll_gate_v2"


def _clip_identity(clip: Path) -> str:
    stat = clip.stat()
    raw = f"{clip.name}|{stat.st_size}|{int(stat.st_mtime_ns)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cache_path_for_jobs_root(jobs_root: Path) -> Path:
    return jobs_root / "broll-pool" / "gate_cache.json"


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": GATE_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": GATE_VERSION, "entries": {}}
    if data.get("version") != GATE_VERSION:
        return {"version": GATE_VERSION, "entries": {}}
    entries = data.get("entries")
    return {"version": GATE_VERSION, "entries": entries if isinstance(entries, dict) else {}}


def _save_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def lookup_gate_result(
    jobs_root: Path | None,
    clip: Path,
    *,
    subject_slug: str,
) -> dict[str, Any] | None:
    if jobs_root is None or not clip.is_file():
        return None
    path = cache_path_for_jobs_root(jobs_root)
    cache = _load_cache(path)
    key = _clip_identity(clip)
    entry = cache["entries"].get(key)
    if not isinstance(entry, dict):
        return None
    if entry.get("gate_version") != GATE_VERSION:
        return None
    cached_slug = str(entry.get("subject_slug") or "")
    if subject_slug and cached_slug and cached_slug != subject_slug:
        return None
    return entry


def store_gate_result(
    jobs_root: Path | None,
    clip: Path,
    *,
    subject_slug: str,
    passed: bool,
    reason: str = "",
    fps: float = 0.0,
    source_id: str = "",
) -> None:
    if jobs_root is None or not clip.is_file():
        return
    path = cache_path_for_jobs_root(jobs_root)
    cache = _load_cache(path)
    key = _clip_identity(clip)
    cache["entries"][key] = {
        "gate_version": GATE_VERSION,
        "clip_name": clip.name,
        "subject_slug": subject_slug,
        "pass": passed,
        "reason": reason,
        "fps": fps,
        "source_id": source_id,
    }
    _save_cache(path, cache)
