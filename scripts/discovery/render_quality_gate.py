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


def check_render_quality(
    video_path: Path,
    *,
    expected_duration: float | None = None,
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

    if report.errors:
        report.ok = False
    return report
