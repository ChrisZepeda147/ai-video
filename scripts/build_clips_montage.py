#!/usr/bin/env python3
"""Build a 9:16 montage from shuffled video clips + audio, with optional dark-luxury grade."""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from build_stills_slideshow import burn_captions

FPS = 30


def _even(value: int) -> int:
    return value - (value % 2)


def probe_duration(path: Path) -> float:
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


# Charcoal + light plum cast — matches prompts/dark-luxury-still.md
# Saturation stays high enough that paint and sky do not go grey.
DARK_LUXURY_GRADE = (
    "eq=brightness=-0.08:saturation=0.62:contrast=1.10,"
    "colorbalance=rs=0.04:gs=-0.01:bs=0.05,"
    "curves=all='0/0 0.45/0.38 1/0.94'"
)


def _duration_to_frames(seconds: float) -> int:
    return max(1, int(round(seconds * FPS)))


def _scale_crop_filter(*, width: int, height: int, grade: bool) -> str:
    chain = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps=30"
    )
    if grade:
        chain += f",{DARK_LUXURY_GRADE}"
    return chain + ",format=yuv420p"


def _pick_segment(
    clip: Path,
    *,
    segment_length: float,
    rng: random.Random,
) -> tuple[float, float]:
    duration = probe_duration(clip)
    if duration <= segment_length + 0.25:
        return 0.0, min(segment_length, duration)
    max_start = max(duration - segment_length - 0.1, 0.0)
    start = rng.uniform(0.0, max_start)
    return start, segment_length


def _export_segment(
    source: Path,
    output: Path,
    *,
    start: float,
    duration: float,
    width: int,
    height: int,
    grade: bool,
) -> None:
    vf = _scale_crop_filter(width=width, height=height, grade=grade)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-frames:v",
        str(_duration_to_frames(duration)),
        "-an",
        "-vf",
        vf,
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


def _export_split_segment(
    left: Path,
    right: Path,
    output: Path,
    *,
    left_start: float,
    right_start: float,
    duration: float,
    width: int,
    height: int,
    layout: str,
    grade: bool,
) -> None:
    if layout == "split-v":
        panel_w, panel_h = width, _even(height // 2)
    else:
        panel_w, panel_h = _even(width // 2), height
    panel_vf = _scale_crop_filter(width=panel_w, height=panel_h, grade=grade)
    stack = "vstack=inputs=2" if layout == "split-v" else "hstack=inputs=2"
    filter_complex = (
        f"[0:v]trim=start={left_start}:duration={duration},setpts=PTS-STARTPTS,{panel_vf}[a];"
        f"[1:v]trim=start={right_start}:duration={duration},setpts=PTS-STARTPTS,{panel_vf}[b];"
        f"[a][b]{stack}[vout]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(left),
        "-i",
        str(right),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-t",
        str(duration),
        "-an",
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


def _pad_video_to_duration(source: Path, output: Path, *, target_duration: float) -> None:
    current = probe_duration(source)
    if current >= target_duration - 0.02:
        if source.resolve() != output.resolve():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(output)],
                check=True,
                capture_output=True,
            )
        return
    pad = target_duration - current
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={pad:.3f}",
        "-t",
        str(target_duration),
        "-an",
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


def _concat_segments(segments: list[Path], output: Path) -> None:
    list_path = output.with_suffix(".concat.txt")
    lines = [f"file '{segment.resolve().as_posix()}'" for segment in segments]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    list_path.unlink(missing_ok=True)


def _mux_audio(
    video: Path,
    audio: Path,
    output: Path,
    *,
    audio_start: float,
    audio_duration: float | None,
) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-ss",
        str(audio_start),
        "-i",
        str(audio),
    ]
    cmd.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    )
    if audio_duration is not None:
        cmd.extend(["-t", str(audio_duration)])
    cmd.extend(["-movflags", "+faststart", str(output)])
    subprocess.run(cmd, check=True, capture_output=True)


def build_montage(
    *,
    clips_dir: Path,
    audio: Path,
    output: Path,
    segment_length: float,
    layout: str,
    grade: bool,
    seed: int | None,
    width: int,
    height: int,
    audio_start: float,
    audio_duration: float | None,
) -> None:
    clips = sorted(clips_dir.glob("*.mp4"))
    if not clips:
        raise FileNotFoundError(f"No .mp4 clips in {clips_dir}")
    if not audio.is_file():
        raise FileNotFoundError(f"Audio not found: {audio}")

    target_duration = audio_duration
    if target_duration is None:
        target_duration = probe_duration(audio) - audio_start
    if target_duration <= 0:
        raise ValueError("audio_duration must be positive")

    rng = random.Random(seed)
    output.parent.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    accumulated = 0.0
    segment_index = 0

    with tempfile.TemporaryDirectory(prefix="clips_montage_") as tmp:
        tmp_dir = Path(tmp)
        while accumulated < target_duration - 0.02:
            remaining = target_duration - accumulated
            this_duration = min(segment_length, remaining)

            if layout == "single":
                clip = rng.choice(clips)
                start, _ = _pick_segment(clip, segment_length=this_duration, rng=rng)
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_segment(
                    clip,
                    segment_path,
                    start=start,
                    duration=this_duration,
                    width=width,
                    height=height,
                    grade=grade,
                )
            else:
                left = rng.choice(clips)
                right = rng.choice(clips)
                left_start, _ = _pick_segment(left, segment_length=this_duration, rng=rng)
                right_start, _ = _pick_segment(right, segment_length=this_duration, rng=rng)
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_split_segment(
                    left,
                    right,
                    segment_path,
                    left_start=left_start,
                    right_start=right_start,
                    duration=this_duration,
                    width=width,
                    height=height,
                    layout=layout,
                    grade=grade,
                )

            segments.append(segment_path)
            accumulated += probe_duration(segment_path)
            segment_index += 1

        silent_video = tmp_dir / "montage_silent.mp4"
        _concat_segments(segments, silent_video)
        fitted_video = tmp_dir / "montage_fitted.mp4"
        _pad_video_to_duration(silent_video, fitted_video, target_duration=target_duration)
        _mux_audio(
            fitted_video,
            audio,
            output,
            audio_start=audio_start,
            audio_duration=target_duration,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips", type=Path, required=True, help="Directory of source .mp4 clips")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segment-length", type=float, default=4.0, help="Seconds per montage beat")
    parser.add_argument(
        "--layout",
        choices=("single", "split-v", "split-h"),
        default="single",
        help="single = full frame; split-v = stacked pair (9:16); split-h = side-by-side pair",
    )
    parser.add_argument("--no-grade", action="store_true", help="Skip dark-luxury color grade")
    parser.add_argument("--seed", type=int, default=None, help="Shuffle seed for reproducible cuts")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--audio-start", type=float, default=0.0)
    parser.add_argument("--audio-duration", type=float, default=None)
    parser.add_argument(
        "--captions",
        type=Path,
        default=None,
        help="Burn in captions (.json3 = word-by-word, .srt = line captions)",
    )
    args = parser.parse_args()
    if not args.audio.is_file():
        print(f"Audio not found: {args.audio}", file=sys.stderr)
        return 1
    if args.audio_duration is None:
        audio_duration = probe_duration(args.audio) - args.audio_start
    else:
        audio_duration = args.audio_duration

    try:
        temp_output = args.output
        if args.captions:
            temp_output = args.output.with_suffix(".nocap.mp4")
        build_montage(
            clips_dir=args.clips,
            audio=args.audio,
            output=temp_output,
            segment_length=args.segment_length,
            layout=args.layout,
            grade=not args.no_grade,
            seed=args.seed,
            width=args.width,
            height=args.height,
            audio_start=args.audio_start,
            audio_duration=audio_duration,
        )
        if args.captions:
            if not args.captions.is_file():
                raise FileNotFoundError(f"Captions not found: {args.captions}")
            word_by_word = args.captions.suffix.lower() == ".json3"
            burn_captions(
                temp_output,
                args.captions,
                args.output,
                width=args.width,
                height=args.height,
                audio_start=args.audio_start,
                audio_duration=audio_duration,
                word_by_word=word_by_word,
            )
            temp_output.unlink(missing_ok=True)
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
