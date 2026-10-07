"""Cheap pre-render verification of gated B-roll from ensure_broll."""

from __future__ import annotations

import json
from pathlib import Path


MANIFEST_NAME = "broll_usable_manifest.json"


def manifest_path(job_dir: Path) -> Path:
    return job_dir / MANIFEST_NAME


def write_manifest(job_dir: Path, *, clip_names: list[str], required: int) -> None:
    payload = {
        "version": 1,
        "required": required,
        "clip_names": sorted(set(clip_names)),
    }
    manifest_path(job_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def verify_manifest(job_dir: Path, clips_dir: Path) -> tuple[bool, int, int]:
    """Return ok, usable_count, required without re-running frame gate."""
    path = manifest_path(job_dir)
    if not path.is_file():
        return False, 0, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, 0, 0
    required = int(data.get("required") or 0)
    names = [str(n) for n in (data.get("clip_names") or []) if n]
    present = sum(1 for name in names if (clips_dir / name).is_file())
    ok = present >= required and required > 0
    return ok, present, required
