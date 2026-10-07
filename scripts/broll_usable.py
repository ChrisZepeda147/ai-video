"""Single source of truth for usable B-roll clip counts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from montage_telemetry import emit_stage_line


@dataclass(frozen=True)
class BrollInventory:
    raw: int
    usable: list[Path]
    required: int

    @property
    def usable_count(self) -> int:
        return len(self.usable)

    @property
    def distinct_sources(self) -> int:
        from broll_pool import _youtube_id_from_clip_name

        ids = {
            _youtube_id_from_clip_name(clip.name) or clip.stem
            for clip in self.usable
        }
        return len(ids)

    def satisfies_count(self) -> bool:
        return self.usable_count >= self.required


def raw_clip_paths(clips_dir: Path) -> list[Path]:
    return sorted(clips_dir.glob("*_part*.mp4"))


def measure_usable_broll(
    clips_dir: Path,
    *,
    required: int,
    gate_fn: Callable[[list[Path]], list[Path]],
) -> BrollInventory:
    raw = raw_clip_paths(clips_dir)
    usable = gate_fn(raw) if raw else []
    return BrollInventory(raw=len(raw), usable=usable, required=required)


def log_broll_progress(
    stage: str,
    inv: BrollInventory,
    *,
    status: str = "progress",
    extra: dict[str, str | int] | None = None,
) -> None:
    payload: dict[str, str | int] = {
        "raw": inv.raw,
        "usable": inv.usable_count,
        "sources": inv.distinct_sources,
        "required": inv.required,
    }
    if extra:
        payload.update(extra)
    emit_stage_line(stage, status, **payload)
