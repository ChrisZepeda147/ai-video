#!/usr/bin/env python3
"""Burn static centered text onto video via ASS subtitles."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

VALID_PLACES = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "mid-left",
        "mid-center",
        "mid-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
)

# ASS numpad alignment: 7 8 9 / 4 5 6 / 1 2 3
_PLACE_ALIGNMENT = {
    "top-left": 7,
    "top-center": 8,
    "top-right": 9,
    "mid-left": 4,
    "mid-center": 5,
    "mid-right": 6,
    "bottom-left": 1,
    "bottom-center": 2,
    "bottom-right": 3,
}


def _ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:d}:{minutes:02d}:{secs:05.2f}"


def _escape_ass(text: str) -> str:
    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.replace("{", r"\{").replace("}", r"\}")


def wrap_text(text: str, *, max_chars: int = 28) -> str:
    words = text.split()
    if not words:
        return ""
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        if current and len(trial) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return r"\N".join(lines)


def default_font_size(height: int) -> int:
    return max(36, round(height * 72 / 1920))


def default_margin_v(height: int, place: str) -> int:
    edge = max(40, round(height * 0.10))
    if place.startswith("top"):
        return edge
    if place.startswith("mid"):
        return 0
    return edge


def build_static_ass(
    text: str,
    *,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    place: str = "mid-center",
    font_size: int | None = None,
) -> str:
    if place not in VALID_PLACES:
        raise ValueError(f"Unknown text place: {place}. Use one of: {', '.join(sorted(VALID_PLACES))}")
    size = font_size or default_font_size(height)
    alignment = _PLACE_ALIGNMENT[place]
    margin_v = default_margin_v(height, place)
    wrapped = wrap_text(_escape_ass(text))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,0,{alignment},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    line = f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Default,,0,0,0,,{wrapped}\n"
    return header + line


def burn_ass_on_video(video: Path, ass_path: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ass_escaped = ass_path.resolve().as_posix().replace(":", "\\:")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"ass='{ass_escaped}'",
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
