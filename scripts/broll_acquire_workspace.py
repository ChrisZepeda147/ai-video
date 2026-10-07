"""Per-source temp workspace for parallel B-roll acquisition."""

from __future__ import annotations

import shutil
from pathlib import Path


def source_workspace(job_dir: Path, video_id: str) -> Path:
    safe = (video_id or "unknown").strip()
    return job_dir / "tmp" / "broll" / safe


def cleanup_workspace(workspace: Path) -> None:
    if workspace.is_dir():
        shutil.rmtree(workspace, ignore_errors=True)


def finalize_parts(workspace: Path, clips_dir: Path, video_id: str) -> list[Path]:
    """Move completed part files into the shared job clips dir (atomic replace)."""
    clips_dir.mkdir(parents=True, exist_ok=True)
    finalized: list[Path] = []
    for part in sorted(workspace.glob(f"{video_id}_part*.mp4")):
        dest = clips_dir / part.name
        if dest.exists():
            dest.unlink(missing_ok=True)
        part.replace(dest)
        finalized.append(dest)
    cleanup_workspace(workspace)
    return finalized
