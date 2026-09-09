"""FFmpeg Short renderer — consumes timeline + source + approved visuals."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discovery.captions import build_ass_captions
from discovery.config import project_root
from discovery.transcription.base import TranscriptSegment

def _probe_duration(path: Path) -> float:
    import subprocess

    result = subprocess.run(
        [
            "ffprobe",
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
    )
    return float(result.stdout.strip())


OUTPUT_ROOT = project_root() / "downloads" / "production"
WIDTH = 1080
HEIGHT = 1920


@dataclass
class RenderResult:
    output_path: str
    duration_sec: float
    ffmpeg_command: str


def production_output_dir(slug: str) -> Path:
    path = OUTPUT_ROOT / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def _motion_filter(motion: str, duration: float, fps: int = 30) -> str:
    frames = max(1, int(duration * fps))
    if motion == "zoom_out":
        return (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"zoompan=z='max(1.5-0.0015*on,1)':d={frames}:s={WIDTH}x{HEIGHT}:fps={fps}"
        )
    if motion == "pan":
        return (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"zoompan=z=1.2:x='iw/2-(iw/zoom/2)+50*sin(on/25)':y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={fps}"
        )
    # default zoom_in
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='min(zoom+0.0015,1.35)':d={frames}:s={WIDTH}x{HEIGHT}:fps={fps}"
    )


def _render_segment_clip(seg: dict[str, Any], work_dir: Path, index: int) -> Path:
    out = work_dir / f"seg_{index:03d}.mp4"
    duration = max(0.1, float(seg["end"]) - float(seg["start"]))
    seg_type = seg.get("type", "image")
    path = Path(seg["path"])
    if not path.is_file():
        raise FileNotFoundError(f"Timeline segment missing file: {path}")

    if seg_type == "image":
        vf = _motion_filter(seg.get("motion", "zoom_in"), duration)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(path),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ]
    elif seg_type in {"source_video", "ai_video"}:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-t", str(duration),
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ]
    else:
        raise ValueError(f"Unknown segment type: {seg_type}")

    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _concat_clips(clips: list[Path], output: Path) -> None:
    list_file = output.parent / "concat.txt"
    list_file.write_text("\n".join(f"file '{c.resolve().as_posix()}'" for c in clips), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _mux_audio(video: Path, audio: Path, output: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _burn_subtitles(video: Path, ass_path: Path, output: Path) -> None:
    ass_escaped = ass_path.resolve().as_posix().replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", f"ass='{ass_escaped}'",
        "-c:a", "copy",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def render_short(
    *,
    slug: str,
    timeline: dict[str, Any],
    audio_path: str | None = None,
    caption_preset: str = "viral_bold",
    hook_text: str | None = None,
    transcript_segments: list[dict[str, Any]] | None = None,
    burn_captions: bool = True,
) -> RenderResult:
    work_dir = production_output_dir(slug) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    for i, seg in enumerate(timeline.get("segments", [])):
        clips.append(_render_segment_clip(seg, work_dir, i))

    if not clips:
        raise ValueError("Timeline has no renderable segments")

    concat_out = work_dir / "concat.mp4"
    _concat_clips(clips, concat_out)

    current = concat_out
    if audio_path and Path(audio_path).is_file():
        muxed = work_dir / "with_audio.mp4"
        _mux_audio(current, Path(audio_path), muxed)
        current = muxed

    if burn_captions and transcript_segments:
        segs = [
            TranscriptSegment(
                text=s.get("text", ""),
                start=float(s.get("start", 0)),
                end=float(s.get("end", 0)),
                confidence=s.get("confidence"),
            )
            for s in transcript_segments
        ]
        ass_path = work_dir / "captions.ass"
        ass_path.write_text(
            build_ass_captions(segs, preset=caption_preset, hook_text=hook_text),
            encoding="utf-8",
        )
        captioned = work_dir / "captioned.mp4"
        _burn_subtitles(current, ass_path, captioned)
        current = captioned

    final = production_output_dir(slug) / "final.mp4"
    if current != final:
        final.write_bytes(current.read_bytes())

    duration = _probe_duration(final)
    cmd_log = work_dir / "render_command.json"
    cmd_log.write_text(json.dumps({"output": str(final), "segments": len(clips)}, indent=2), encoding="utf-8")

    return RenderResult(
        output_path=str(final),
        duration_sec=duration,
        ffmpeg_command=str(cmd_log),
    )
