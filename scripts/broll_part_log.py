"""Per-part FPS diagnostics for B-roll acquisition."""

from __future__ import annotations

from pathlib import Path

from build_clips_montage import is_usable_fps, probe_fps


def log_broll_part(
    *,
    video_id: str,
    part: int,
    source_fps: float | None,
    output_fps: float | None,
    duration: float | None,
    usable: bool,
    reason: str = "",
) -> None:
    sf = f"{source_fps:.1f}" if source_fps is not None else "?"
    of = f"{output_fps:.1f}" if output_fps is not None else "?"
    dur = f"{duration:.1f}" if duration is not None else "?"
    flag = 1 if usable else 0
    extra = f" reason={reason}" if reason else ""
    print(
        f"BROLL_PART video_id={video_id} part={part:02d} "
        f"source_fps={sf} output_fps={of} duration={dur} usable={flag}{extra}"
    )


def probe_part_usable(path: Path, *, source_fps: float | None = None) -> tuple[float, bool, str]:
    try:
        out_fps = probe_fps(path)
    except (OSError, ValueError):
        return 0.0, False, "probe_failed"
    if not is_usable_fps(out_fps):
        return out_fps, False, "low_output_fps"
    if source_fps is not None and source_fps >= 50 and out_fps < 50:
        return out_fps, False, "fps_lost_in_export"
    return out_fps, True, ""
