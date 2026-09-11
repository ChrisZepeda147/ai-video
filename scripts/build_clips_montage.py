#!/usr/bin/env python3
"""Build a 9:16 montage from shuffled video clips + audio, with optional dark-luxury grade."""

from __future__ import annotations

import argparse
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from broll_frame_gate import clean_spans, longest_clean_span, scan_clip_local, score_window
from build_stills_slideshow import burn_captions

FPS = 30
DEFAULT_PLAYBACK_SPEED = 0.80
BASELINE_AUDIO_SECONDS = 60.0
BASELINE_SEGMENT_SECONDS = 12.0
MIN_SEGMENT_SECONDS = 8.0
MAX_SEGMENT_SECONDS = 18.0


def segment_length_for_duration(duration: float) -> float:
    """Scale montage beat length with speech duration (60s -> 12s, 90s -> 18s)."""
    if duration <= 0:
        return BASELINE_SEGMENT_SECONDS
    scaled = BASELINE_SEGMENT_SECONDS * (duration / BASELINE_AUDIO_SECONDS)
    return max(MIN_SEGMENT_SECONDS, min(MAX_SEGMENT_SECONDS, scaled))


def montage_beats_needed(*, duration: float, segment_length: float, layout: str) -> int:
    per_beat = max(segment_length, 0.1)
    beats = max(1, math.ceil(duration / per_beat))
    if layout != "single":
        beats *= 2
    return beats


def min_unique_clips_needed(*, duration: float, segment_length: float, layout: str) -> int:
    return montage_beats_needed(duration=duration, segment_length=segment_length, layout=layout)


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


def _source_id(clip: Path) -> str:
    stem = clip.stem
    if "_part" in stem:
        return stem.rsplit("_part", 1)[0]
    return stem


def _group_clips_by_source(clips: list[Path]) -> dict[str, list[Path]]:
    pools: dict[str, list[Path]] = {}
    for clip in clips:
        pools.setdefault(_source_id(clip), []).append(clip)
    return pools


class _ClipPicker:
    """Pick montage clips once each — no file repeats within one render."""

    def __init__(self, clips: list[Path], rng: random.Random) -> None:
        self.rng = rng
        self.all_clips = list(clips)
        self.pools = _group_clips_by_source(clips)
        self.unused_files = set(clips)
        self._unused_sources = list(self.pools.keys())
        rng.shuffle(self._unused_sources)

    def _reshuffle_sources(self) -> None:
        self._unused_sources = [
            source_id
            for source_id, parts in self.pools.items()
            if any(part in self.unused_files for part in parts)
        ]
        self.rng.shuffle(self._unused_sources)

    def pick(self, *, exclude: set[Path] | None = None) -> Path:
        exclude = exclude or set()
        available_files = [clip for clip in self.unused_files if clip not in exclude]
        if not available_files:
            raise RuntimeError(
                "Not enough unique B-roll clips for this video length. "
                "Download more sources or use a shorter speech."
            )

        excluded_sources = {_source_id(item) for item in exclude}
        unused_sources = {
            _source_id(clip)
            for clip in available_files
            if _source_id(clip) not in excluded_sources
        }
        if unused_sources:
            if not self._unused_sources or not unused_sources.intersection(self._unused_sources):
                self._reshuffle_sources()
            source_id = next(sid for sid in self._unused_sources if sid in unused_sources)
            self._unused_sources.remove(source_id)
            parts = [
                part
                for part in self.pools[source_id]
                if part in self.unused_files and part not in exclude
            ]
            if parts:
                clip = self.rng.choice(parts)
                self.unused_files.discard(clip)
                return clip

        clip = self.rng.choice(available_files)
        self.unused_files.discard(clip)
        return clip

    def used_clips(self) -> set[Path]:
        return {clip for clip in self.all_clips if clip not in self.unused_files}


def _window_in_span(
    span: tuple[float, float],
    needed: float,
    rng: random.Random,
) -> tuple[float, float]:
    start, end = span
    span_len = max(end - start, 0.0)
    if span_len <= needed + 0.05:
        return start, span_len
    slack = span_len - needed
    return start + rng.uniform(0.0, slack), needed


def _pick_segment(
    clip: Path,
    *,
    segment_length: float,
    rng: random.Random,
    subject: str = "",
    source_needed: float | None = None,
    strict: bool = False,
    use_vision: bool = False,
) -> tuple[float, float] | None:
    duration = probe_duration(clip)
    needed = source_needed if source_needed is not None else segment_length
    samples = scan_clip_local(clip, duration=duration)
    min_length = min(needed, duration, 2.5)
    spans = clean_spans(samples, min_length=min_length)
    if not spans:
        return None

    fit = [span for span in spans if span[1] - span[0] >= min(needed, duration) - 0.05]
    if fit:
        window_start, window_len = _window_in_span(rng.choice(fit), min(needed, duration), rng)
    else:
        longest = longest_clean_span(samples, min_length=min_length)
        if longest is None:
            return None
        window_start, window_len = _window_in_span(longest, min(needed, duration), rng)

    report = score_window(
        clip,
        start=window_start,
        duration=window_len,
        clip_duration=duration,
        subject=subject,
        strict=strict,
        use_vision=use_vision,
    )
    if not report["ok"]:
        return None
    return window_start, window_len


def _playback_chain(playback_speed: float) -> str:
    if abs(playback_speed - 1.0) < 0.01:
        return ""
    return f"setpts=PTS/{playback_speed},"


def _export_segment(
    source: Path,
    output: Path,
    *,
    start: float,
    duration: float,
    width: int,
    height: int,
    grade: bool,
    playback_speed: float = 1.0,
    output_duration: float | None = None,
) -> None:
    vf = _playback_chain(playback_speed) + _scale_crop_filter(width=width, height=height, grade=grade)
    frames = _duration_to_frames(output_duration if output_duration is not None else duration)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-t",
        str(duration),
        "-frames:v",
        str(frames),
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


def _source_needed(output_duration: float, playback_speed: float) -> float:
    return max(0.4, output_duration * playback_speed)


def _pick_passing_window(
    picker: _ClipPicker,
    *,
    segment_length: float,
    rng: random.Random,
    subject: str,
    source_needed: float,
    strict: bool,
    use_vision: bool,
    exclude: set[Path] | None = None,
) -> tuple[Path, float, float]:
    tried: set[Path] = set(exclude or ())
    attempts = 0
    limit = max(len(picker.all_clips) * 2, 6)
    while attempts < limit:
        clip = picker.pick(exclude=tried)
        picked = _pick_segment(
            clip,
            segment_length=segment_length,
            rng=rng,
            subject=subject,
            source_needed=source_needed,
            strict=strict,
            use_vision=use_vision,
        )
        attempts += 1
        if picked:
            return clip, picked[0], picked[1]
        tried.add(clip)
        if len(tried) >= len(picker.all_clips):
            break
    raise RuntimeError("No B-roll window passed the subject/frame gate.")


def build_silent_montage(
    *,
    clips_dir: Path,
    output: Path,
    target_duration: float,
    segment_length: float,
    layout: str = "single",
    grade: bool,
    seed: int | None,
    width: int,
    height: int,
    subject: str = "",
    playback_speed: float = 1.0,
    use_vision: bool = True,
) -> set[Path]:
    """Stitch shuffled B-roll into a fixed-length silent video."""
    clips = sorted(clips_dir.glob("*.mp4"))
    if not clips:
        raise FileNotFoundError(f"No .mp4 clips in {clips_dir}")
    if target_duration <= 0:
        raise ValueError("target_duration must be positive")

    needed_clips = min_unique_clips_needed(
        duration=target_duration,
        segment_length=segment_length,
        layout=layout,
    )
    if len(clips) < needed_clips:
        raise RuntimeError(
            f"Need at least {needed_clips} unique B-roll clips for "
            f"{target_duration:.0f}s at {segment_length:.1f}s beats, have {len(clips)}."
        )

    rng = random.Random(seed)
    picker = _ClipPicker(clips, rng)
    output.parent.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    accumulated = 0.0
    segment_index = 0

    with tempfile.TemporaryDirectory(prefix="clips_silent_") as tmp:
        tmp_dir = Path(tmp)
        while accumulated < target_duration - 0.02:
            remaining = target_duration - accumulated
            this_duration = min(segment_length, remaining)
            needed = _source_needed(this_duration, playback_speed)
            strict = segment_index == 0
            vision = use_vision and segment_index < 2

            if layout == "single":
                clip, start, source_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                )
                out_len = min(this_duration, source_len / max(playback_speed, 0.05))
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_segment(
                    clip,
                    segment_path,
                    start=start,
                    duration=source_len,
                    width=width,
                    height=height,
                    grade=grade,
                    playback_speed=playback_speed,
                    output_duration=out_len,
                )
            else:
                left, left_start, left_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                )
                right, right_start, right_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                    exclude={left},
                )
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_split_segment(
                    left,
                    right,
                    segment_path,
                    left_start=left_start,
                    right_start=right_start,
                    duration=min(left_len, right_len),
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
        _pad_video_to_duration(silent_video, output, target_duration=target_duration)
    return picker.used_clips()


def build_montage(
    *,
    clips_dir: Path,
    audio: Path | None,
    output: Path,
    segment_length: float,
    layout: str,
    grade: bool,
    seed: int | None,
    width: int,
    height: int,
    audio_start: float,
    audio_duration: float | None,
    subject: str = "",
    playback_speed: float = DEFAULT_PLAYBACK_SPEED,
    use_vision: bool = True,
    include_audio: bool = True,
) -> set[Path]:
    clips = sorted(clips_dir.glob("*.mp4"))
    if not clips:
        raise FileNotFoundError(f"No .mp4 clips in {clips_dir}")
    if include_audio and (audio is None or not audio.is_file()):
        raise FileNotFoundError(f"Audio not found: {audio}")

    target_duration = audio_duration
    if target_duration is None:
        if audio is None or not audio.is_file():
            raise ValueError("audio_duration is required when audio file is missing")
        target_duration = probe_duration(audio) - audio_start
    if target_duration <= 0:
        raise ValueError("audio_duration must be positive")

    needed_clips = min_unique_clips_needed(
        duration=target_duration,
        segment_length=segment_length,
        layout=layout,
    )
    if len(clips) < needed_clips:
        raise RuntimeError(
            f"Need at least {needed_clips} unique B-roll clips for "
            f"{target_duration:.0f}s at {segment_length:.1f}s beats, have {len(clips)}."
        )

    rng = random.Random(seed)
    picker = _ClipPicker(clips, rng)
    output.parent.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    accumulated = 0.0
    segment_index = 0

    with tempfile.TemporaryDirectory(prefix="clips_montage_") as tmp:
        tmp_dir = Path(tmp)
        while accumulated < target_duration - 0.02:
            remaining = target_duration - accumulated
            this_duration = min(segment_length, remaining)
            needed = _source_needed(this_duration, playback_speed)
            strict = segment_index == 0
            vision = use_vision and segment_index < 2

            if layout == "single":
                clip, start, source_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                )
                out_len = min(this_duration, source_len / max(playback_speed, 0.05))
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_segment(
                    clip,
                    segment_path,
                    start=start,
                    duration=source_len,
                    width=width,
                    height=height,
                    grade=grade,
                    playback_speed=playback_speed,
                    output_duration=out_len,
                )
            else:
                left, left_start, left_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                )
                right, right_start, right_len = _pick_passing_window(
                    picker,
                    segment_length=this_duration,
                    rng=rng,
                    subject=subject,
                    source_needed=needed,
                    strict=strict,
                    use_vision=vision,
                    exclude={left},
                )
                segment_path = tmp_dir / f"seg_{segment_index:04d}.mp4"
                _export_split_segment(
                    left,
                    right,
                    segment_path,
                    left_start=left_start,
                    right_start=right_start,
                    duration=min(left_len, right_len),
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
        if include_audio:
            assert audio is not None
            _mux_audio(
                fitted_video,
                audio,
                output,
                audio_start=audio_start,
                audio_duration=target_duration,
            )
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(fitted_video), "-c", "copy", "-an", str(output)],
                check=True,
                capture_output=True,
            )
    return picker.used_clips()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips", type=Path, required=True, help="Directory of source .mp4 clips")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--segment-length",
        type=float,
        default=None,
        help="Seconds per montage beat (default: scales with audio length)",
    )
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=DEFAULT_PLAYBACK_SPEED,
        help="Clip playback rate. 0.80 = slower motion",
    )
    parser.add_argument("--subject", default="", help="Required on-screen subject, e.g. porsche gt3rs")
    parser.add_argument("--no-vision", action="store_true", help="Skip optional vision subject check")
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
    segment_length = (
        args.segment_length
        if args.segment_length is not None
        else segment_length_for_duration(audio_duration)
    )

    try:
        temp_output = args.output
        if args.captions:
            temp_output = args.output.with_suffix(".nocap.mp4")
        build_montage(
            clips_dir=args.clips,
            audio=args.audio,
            output=temp_output,
            segment_length=segment_length,
            layout=args.layout,
            grade=not args.no_grade,
            seed=args.seed,
            width=args.width,
            height=args.height,
            audio_start=args.audio_start,
            audio_duration=audio_duration,
            subject=args.subject,
            playback_speed=args.playback_speed,
            use_vision=not args.no_vision,
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
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
