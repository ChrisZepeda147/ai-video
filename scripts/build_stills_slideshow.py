#!/usr/bin/env python3
"""Build a 9:16 slideshow MP4 from still images + audio, optional burned-in captions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess

from toolchain_env import resolve_tool
import sys
from pathlib import Path


def build_slideshow(
    *,
    stills_dir: Path,
    audio: Path,
    output: Path,
    seconds_per_still: float,
    audio_start: float,
    audio_duration: float | None,
    width: int,
    height: int,
) -> None:
    images = sorted(stills_dir.glob("*.png")) + sorted(stills_dir.glob("*.jpg"))
    if not images:
        raise FileNotFoundError(f"No stills in {stills_dir}")
    if not audio.is_file():
        raise FileNotFoundError(f"Audio not found: {audio}")

    output.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    for img in images:
        inputs.extend(["-loop", "1", "-t", str(seconds_per_still), "-i", str(img)])

    audio_idx = len(images)
    inputs.extend(["-ss", str(audio_start), "-i", str(audio)])
    if audio_duration is not None:
        inputs.extend(["-t", str(audio_duration)])

    filters: list[str] = []
    for i in range(len(images)):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=30,format=yuv420p[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(len(images)))
    filters.append(f"{concat_in}concat=n={len(images)}:v=1:a=0[vout]")

    ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        f"{audio_idx}:a",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _srt_to_seconds(timestamp: str) -> float:
    hours, minutes, rest = timestamp.strip().split(":", 2)
    seconds, millis = rest.split(",", 1)
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def _seconds_to_srt(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def trim_srt(srt_path: Path, *, start: float, duration: float, out_path: Path) -> None:
    content = srt_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", content)
    end = start + duration
    kept: list[str] = []
    index = 1
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = (part.strip() for part in lines[1].split("-->", 1))
        block_start = _srt_to_seconds(start_raw)
        block_end = _srt_to_seconds(end_raw)
        if block_end <= start or block_start >= end:
            continue
        clipped_start = max(block_start, start) - start
        clipped_end = min(block_end, end) - start
        text = "\n".join(lines[2:])
        kept.append(
            f"{index}\n{_seconds_to_srt(clipped_start)} --> {_seconds_to_srt(clipped_end)}\n{text}"
        )
        index += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def _srt_timestamp_to_ass(timestamp: str) -> str:
    hours, minutes, rest = timestamp.strip().split(":", 2)
    seconds, millis = rest.split(",", 1)
    cs = millis[:2].ljust(2, "0")
    return f"{int(hours)}:{minutes}:{seconds}.{cs}"


def _seconds_to_ass(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return escaped.replace(" ", r"\h")


def _ass_header(*, width: int, height: int, phrase_size: int = 46, hook_size: int = 64) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Bold,{phrase_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,0,2,80,80,120,1
Style: Hook,Arial Bold,{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,5,0,2,80,80,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def parse_json3_words(json3_path: Path, *, start: float, duration: float) -> list[tuple[float, float, str]]:
    data = json.loads(json3_path.read_text(encoding="utf-8"))
    raw: list[tuple[float, str]] = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue
        base = float(event.get("tStartMs") or 0) / 1000.0
        for seg in segs:
            text = str(seg.get("utf8") or "").strip()
            if not text or text == "\n":
                continue
            offset = float(seg.get("tOffsetMs") or 0) / 1000.0
            raw.append((base + offset, text))

    raw.sort(key=lambda item: item[0])
    end = start + duration
    words: list[tuple[float, float, str]] = []
    for i, (word_start, word) in enumerate(raw):
        if word_start < start or word_start >= end:
            continue
        rel_start = word_start - start
        next_start = raw[i + 1][0] if i + 1 < len(raw) else end
        rel_end = min(next_start - start, duration)
        if rel_end <= rel_start:
            rel_end = min(rel_start + 0.25, duration)
        words.append((rel_start, rel_end, word))
    return words


def build_word_ass(
    words: list[tuple[float, float, str]], *, width: int, height: int, ass_path: Path
) -> None:
    dialogue_lines = [
        f"Dialogue: 0,{_seconds_to_ass(start)},{_seconds_to_ass(end)},Default,,0,0,0,,{_ass_escape(word)}"
        for start, end, word in words
    ]
    ass_path.write_text(_ass_header(width=width, height=height) + "\n".join(dialogue_lines) + "\n", encoding="utf-8")


def group_words_into_phrases(
    words: list[tuple[float, float, str]],
    *,
    min_words: int = 2,
    max_words: int = 5,
) -> list[tuple[float, float, str]]:
    """Merge word-level captions into 2–5 word phrase blocks."""
    if not words:
        return []
    phrases: list[tuple[float, float, str]] = []
    buffer: list[tuple[float, float, str]] = []

    def flush() -> None:
        if not buffer:
            return
        text = " ".join(item[2] for item in buffer).strip()
        if not text:
            buffer.clear()
            return
        phrases.append((buffer[0][0], buffer[-1][1], text.upper()))
        buffer.clear()

    for start, end, word in words:
        buffer.append((start, end, word.strip()))
        last = buffer[-1][2]
        ends_clause = last.endswith((".", "!", "?", ","))
        if len(buffer) >= max_words or (len(buffer) >= min_words and ends_clause):
            flush()
    if len(buffer) >= min_words:
        flush()
    elif buffer and not phrases:
        text = " ".join(item[2] for item in buffer).strip()
        if text:
            phrases.append((buffer[0][0], buffer[-1][1], text.upper()))
    elif buffer and phrases:
        prev_start, prev_end, prev_text = phrases[-1]
        extra = " ".join(item[2] for item in buffer).strip()
        phrases[-1] = (prev_start, buffer[-1][1], f"{prev_text} {extra}".strip().upper())
    return phrases


def build_phrase_ass(
    phrases: list[tuple[float, float, str]],
    *,
    width: int,
    height: int,
    ass_path: Path,
    hook_text: str | None = None,
    phrase_size: int = 46,
    hook_size: int = 64,
) -> None:
    hook_norm = " ".join((hook_text or "").upper().split())
    dialogue_lines: list[str] = []
    for index, (start, end, text) in enumerate(phrases):
        style = "Default"
        if index == 0 and start <= 1.0:
            if hook_norm and hook_norm in text:
                style = "Hook"
            elif hook_norm and text.startswith(hook_norm.split()[0]):
                style = "Hook"
            elif not hook_norm:
                style = "Hook"
        dialogue_lines.append(
            f"Dialogue: 0,{_seconds_to_ass(start)},{_seconds_to_ass(end)},{style},,0,0,0,,{_ass_escape(text)}"
        )
    ass_path.write_text(
        _ass_header(width=width, height=height, phrase_size=phrase_size, hook_size=hook_size)
        + "\n".join(dialogue_lines)
        + "\n",
        encoding="utf-8",
    )


def build_centered_ass(srt_path: Path, *, width: int, height: int, ass_path: Path) -> None:
    content = srt_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", content)
    dialogue_lines: list[str] = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = (part.strip() for part in lines[1].split("-->", 1))
        text = "\\N".join(line.strip() for line in lines[2:] if line.strip())
        if not text:
            continue
        dialogue_lines.append(
            f"Dialogue: 0,{_srt_timestamp_to_ass(start_raw)},{_srt_timestamp_to_ass(end_raw)},Default,,0,0,0,,{_ass_escape(text)}"
        )
    ass_path.write_text(
        _ass_header(width=width, height=height) + "\n".join(dialogue_lines) + "\n",
        encoding="utf-8",
    )


def burn_captions(
    video: Path,
    captions: Path,
    output: Path,
    *,
    width: int,
    height: int,
    audio_start: float,
    audio_duration: float,
    word_by_word: bool = False,
    caption_mode: str | None = None,
    hook_text: str | None = None,
    phrase_min_words: int = 2,
    phrase_max_words: int = 5,
) -> None:
    ass_path = captions.with_suffix(".burn.ass")
    mode = caption_mode or ("word" if word_by_word else "phrase")
    if mode == "word":
        words = parse_json3_words(captions, start=audio_start, duration=audio_duration)
        if not words:
            raise RuntimeError(f"No words found in {captions} for the selected audio window")
        build_word_ass(words, width=width, height=height, ass_path=ass_path)
    elif mode == "phrase" and captions.suffix.lower() == ".json3":
        words = parse_json3_words(captions, start=audio_start, duration=audio_duration)
        if not words:
            raise RuntimeError(f"No words found in {captions} for the selected audio window")
        phrases = group_words_into_phrases(
            words,
            min_words=max(1, phrase_min_words),
            max_words=max(phrase_min_words, phrase_max_words),
        )
        build_phrase_ass(
            phrases,
            width=width,
            height=height,
            ass_path=ass_path,
            hook_text=hook_text,
        )
    else:
        trimmed = captions.with_suffix(".trim.srt")
        trim_srt(captions, start=audio_start, duration=audio_duration, out_path=trimmed)
        build_centered_ass(trimmed, width=width, height=height, ass_path=ass_path)
    escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"ass='{escaped}'",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds-per-still", type=float, default=6.0)
    parser.add_argument("--audio-start", type=float, default=0.0)
    parser.add_argument("--audio-duration", type=float, default=None)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument(
        "--captions",
        type=Path,
        default=None,
        help="Burn in captions (.json3 = one word at a time, .srt = line captions)",
    )
    parser.add_argument("--srt", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    captions = args.captions or args.srt
    audio_duration = args.audio_duration or 60.0

    try:
        temp_output = args.output
        if captions:
            temp_output = args.output.with_suffix(".nocap.mp4")
        build_slideshow(
            stills_dir=args.stills,
            audio=args.audio,
            output=temp_output,
            seconds_per_still=args.seconds_per_still,
            audio_start=args.audio_start,
            audio_duration=args.audio_duration,
            width=args.width,
            height=args.height,
        )
        if captions:
            if not captions.is_file():
                raise FileNotFoundError(f"Captions not found: {captions}")
            word_by_word = captions.suffix.lower() == ".json3"
            burn_captions(
                temp_output,
                captions,
                args.output,
                width=args.width,
                height=args.height,
                audio_start=args.audio_start,
                audio_duration=audio_duration,
                word_by_word=word_by_word,
            )
            if temp_output.exists():
                temp_output.unlink()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Saved: {args.output}")
    try:
        scripts = Path(__file__).resolve().parent
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import content_reuse

        content_reuse.register_video(file_path=args.output, title=args.output.stem)
        from discovery.auto_register import sync_register_best_effort
        from discovery.site_videos import sync_legacy_renders_to_site

        sync_register_best_effort(
            final_path=args.output,
            slug=args.output.stem,
            title=args.output.stem.replace("-", " "),
            job_dir=args.output.parent,
            pipeline="build_stills_slideshow",
        )
        sync_legacy_renders_to_site(slugs=[args.output.stem])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
