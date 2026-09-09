"""Caption presets and ASS generation for vertical Shorts."""

from __future__ import annotations

from typing import Any

from discovery.transcription.base import TranscriptSegment

PRESETS: dict[str, dict[str, Any]] = {
    "viral_bold": {
        "font": "Arial Black",
        "font_size": 72,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 4,
        "bold": True,
        "margin_v": 280,
        "alignment": 2,
    },
    "clean": {
        "font": "Arial",
        "font_size": 56,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00404040",
        "outline": 2,
        "bold": False,
        "margin_v": 300,
        "alignment": 2,
    },
    "minimal": {
        "font": "Helvetica",
        "font_size": 48,
        "primary_color": "&H00E0E0E0",
        "outline_color": "&H00202020",
        "outline": 1,
        "bold": False,
        "margin_v": 320,
        "alignment": 2,
    },
    "story": {
        "font": "Georgia",
        "font_size": 52,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3,
        "bold": False,
        "margin_v": 260,
        "alignment": 2,
    },
}


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_ass_captions(
    segments: list[TranscriptSegment],
    *,
    preset: str = "viral_bold",
    hook_text: str | None = None,
    hook_duration: float = 2.5,
    width: int = 1080,
    height: int = 1920,
) -> str:
    cfg = PRESETS.get(preset, PRESETS["viral_bold"])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{cfg["font"]},{cfg["font_size"]},{cfg["primary_color"]},&H000000FF,{cfg["outline_color"]},&H80000000,{1 if cfg["bold"] else 0},0,0,0,100,100,0,0,1,{cfg["outline"]},0,{cfg["alignment"]},40,40,{cfg["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if hook_text:
        lines.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(hook_duration)},Default,,0,0,0,,{hook_text.upper()}"
        )
    offset = hook_duration if hook_text else 0.0
    for seg in segments:
        start = seg.start + offset
        end = seg.end + offset
        text = seg.text.replace("\n", " ").strip()
        if not text:
            continue
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
