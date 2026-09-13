"""Pre-ship quality checks for DrivenVisuals renders."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from discovery.driven_visuals import load_defaults


@dataclass
class QualityReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ffprobe_duration(path: Path) -> float:
    _ensure_scripts_path()
    from toolchain_env import resolve_tool, subprocess_env

    ffprobe = resolve_tool("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=subprocess_env(),
    )
    return float(result.stdout.strip().split(",")[0].strip())


def _leading_silence_sec(path: Path) -> float | None:
    _ensure_scripts_path()
    from toolchain_env import resolve_tool, subprocess_env

    ffmpeg = resolve_tool("ffmpeg")
    if not ffmpeg:
        return None
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "silencedetect=noise=-35dB:d=0.25",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=subprocess_env())
    log = (result.stderr or "") + (result.stdout or "")
    start_match = re.search(r"silence_start:\s*([0-9.]+)", log)
    if not start_match:
        return 0.0
    try:
        silence_start = float(start_match.group(1))
    except ValueError:
        return None
    if silence_start > 0.2:
        return 0.0
    match = re.search(r"silence_end:\s*([0-9.]+)", log)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _ensure_scripts_path() -> None:
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def _vehicle_missing_at_sample(video_path: Path, subject: str, duration: float) -> float | None:
    from broll_frame_gate import (
        extract_preview_frame,
        frame_fail_reasons,
        vision_subject_present,
    )

    step = 3.0
    stamp = 5.0
    while stamp < duration - 0.4:
        frame = extract_preview_frame(video_path, stamp)
        if frame:
            fails = frame_fail_reasons(frame, subject=subject)
            if any(
                reason in fails
                for reason in ("talking-head", "missing-subject", "cabin", "title-card", "empty")
            ):
                return stamp
            present = vision_subject_present(frame, subject, opener=False)
            if present is False:
                return stamp
        stamp += step
    return None


def _opener_is_full_exterior(video_path: Path, subject: str) -> bool | None:
    from broll_frame_gate import (
        cabin_interior_reasons,
        extract_preview_frame,
        vision_subject_present,
        wants_vehicle,
    )

    if not wants_vehicle(subject):
        return None
    first = extract_preview_frame(video_path, 0.0)
    if not first:
        return False

    for stamp in (0.0, 2.5, 5.0):
        frame = extract_preview_frame(video_path, stamp) or first
        if cabin_interior_reasons(frame):
            return False
    present = vision_subject_present(first, subject, opener=True)
    if present is False:
        return False
    return True


def check_render_quality(
    video_path: Path,
    *,
    expected_duration: float | None = None,
    subject: str = "",
) -> QualityReport:
    preset = load_defaults()
    gate = preset.get("quality_gate") or {}
    report = QualityReport(ok=True)

    if not video_path.is_file():
        report.ok = False
        report.errors.append("output file missing")
        return report

    size = video_path.stat().st_size
    if size < 100_000:
        report.ok = False
        report.errors.append("output file too small (likely broken render)")

    try:
        duration = _ffprobe_duration(video_path)
    except (subprocess.CalledProcessError, ValueError, RuntimeError) as exc:
        report.ok = False
        report.errors.append(f"could not probe duration: {exc}")
        return report

    min_duration = float(gate.get("min_output_duration_sec") or 8.0)
    if duration < min_duration:
        report.warnings.append(f"duration {duration:.1f}s is shorter than {min_duration:.0f}s minimum")

    if expected_duration and abs(duration - expected_duration) > max(2.0, expected_duration * 0.15):
        report.warnings.append(
            f"duration {duration:.1f}s differs from expected {expected_duration:.1f}s"
        )

    max_leading = float(gate.get("max_leading_silence_sec") or 0.35)
    leading = _leading_silence_sec(video_path)
    if leading is not None and leading > max_leading:
        report.warnings.append(f"speech starts late (~{leading:.2f}s leading silence)")

    if subject and gate.get("require_full_exterior_opener", True):
        from broll_frame_gate import wants_vehicle

        if wants_vehicle(subject):
            opener = _opener_is_full_exterior(video_path, subject)
            if opener is False:
                report.errors.append("opener is not a full exterior view of the car")
            elif opener is None:
                report.warnings.append("could not vision-check opener frame")
            bad_at = _vehicle_missing_at_sample(video_path, subject, duration)
            if bad_at is not None:
                report.errors.append(f"non-vehicle or off-subject frame around {bad_at:.0f}s")

    if report.errors:
        report.ok = False
    return report
