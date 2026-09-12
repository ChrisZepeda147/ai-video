#!/usr/bin/env python3
"""Reorder timed video segments, remux audio, optionally strip + reburn captions.

Keeps each segment's exact duration. Used for shot-order changes on finished
montages without re-downloading B-roll.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from build_clips_montage import _mux_audio, probe_duration
from build_stills_slideshow import burn_captions
from toolchain_env import apply_to_os_environ, resolve_tool


def _ffmpeg() -> str:
    apply_to_os_environ()
    return resolve_tool("ffmpeg") or "ffmpeg"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _cut_segment(
    src: Path,
    dest: Path,
    *,
    start: float,
    duration: float,
    strip_caption_box: str | None,
) -> None:
    vf_parts: list[str] = []
    if strip_caption_box:
        vf_parts.append(f"delogo={strip_caption_box}")
    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.6f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.6f}",
        "-an",
    ]
    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
    cmd.append(str(dest))
    _run(cmd)


def _concat(segments: list[Path], dest: Path) -> None:
    list_file = dest.with_suffix(".concat.txt")
    list_file.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in segments),
        encoding="utf-8",
    )
    try:
        _run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(dest),
            ]
        )
    finally:
        list_file.unlink(missing_ok=True)


def reorder_segments(
    *,
    video: Path,
    audio: Path,
    output: Path,
    segments: list[tuple[float, float]],
    captions: Path | None,
    strip_caption_box: str | None,
    width: int,
    height: int,
    audio_start: float,
) -> None:
    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")
    if not audio.is_file():
        raise FileNotFoundError(f"Audio not found: {audio}")
    if not segments:
        raise ValueError("Need at least one segment start,end")

    total = probe_duration(video)
    audio_duration = probe_duration(audio) - audio_start
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="reorder_segs_") as tmp:
        tmp_dir = Path(tmp)
        cut_paths: list[Path] = []
        for i, (start, end) in enumerate(segments):
            if end <= start:
                raise ValueError(f"Bad segment {i}: end ({end}) <= start ({start})")
            if start < -1e-6 or end > total + 0.05:
                raise ValueError(f"Segment {i} [{start},{end}] outside video ({total:.3f}s)")
            duration = min(end, total) - max(0.0, start)
            cut = tmp_dir / f"seg_{i:02d}.mp4"
            _cut_segment(
                video,
                cut,
                start=max(0.0, start),
                duration=duration,
                strip_caption_box=strip_caption_box,
            )
            cut_paths.append(cut)

        silent = tmp_dir / "silent.mp4"
        _concat(cut_paths, silent)
        muxed = tmp_dir / "muxed.mp4"
        _mux_audio(
            silent,
            audio,
            muxed,
            audio_start=audio_start,
            audio_duration=audio_duration,
        )

        if captions is not None:
            if not captions.is_file():
                raise FileNotFoundError(f"Captions not found: {captions}")
            burn_captions(
                muxed,
                captions,
                output,
                width=width,
                height=height,
                audio_start=audio_start,
                audio_duration=audio_duration,
                word_by_word=captions.suffix.lower() == ".json3",
            )
        else:
            output.write_bytes(muxed.read_bytes())

    print(f"Saved: {output} ({probe_duration(output):.2f}s)")


def _parse_segments(raw: list[str]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for item in raw:
        if "," not in item:
            raise ValueError(f"Segment must be start,end — got {item!r}")
        a, b = item.split(",", 1)
        out.append((float(a), float(b)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--segment",
        action="append",
        required=True,
        help="Segment as start,end seconds. Repeat in desired play order.",
    )
    parser.add_argument("--captions", type=Path, default=None)
    parser.add_argument(
        "--strip-caption-box",
        default=None,
        help="ffmpeg delogo params, e.g. x=140:y=880:w=800:h=160 (for burned-in text)",
    )
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--audio-start", type=float, default=0.0)
    args = parser.parse_args()

    try:
        reorder_segments(
            video=args.video,
            audio=args.audio,
            output=args.output,
            segments=_parse_segments(args.segment),
            captions=args.captions,
            strip_caption_box=args.strip_caption_box,
            width=args.width,
            height=args.height,
            audio_start=args.audio_start,
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            sys.stderr.buffer.write(exc.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
