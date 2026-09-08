#!/usr/bin/env python3
"""
Add AI story narration, voiceover, and burned captions to downloaded part clips.

Reads a manifest.json from the YouTube downloader (or a folder of *_partNN.mp4 files),
generates a multi-part story sized to each clip, synthesizes speech with edge-tts,
then runs Kinocut to replace gameplay audio and burn subtitles.

Examples:
  python scripts/story_voiceover_pipeline.py downloads/youtube/manifest.json
  python scripts/story_voiceover_pipeline.py downloads/youtube --theme "workplace betrayal"
  python scripts/story_voiceover_pipeline.py downloads/youtube/manifest.json --dry-run

Optional story sources (pick one):
  --cursor-story     Default. Uses story.json if present; otherwise writes a prompt
                     for Cursor chat and waits for story.json (auto-continues).
  --story-file PATH  Use a story JSON you or Cursor already wrote.
  --no-wait-for-story  Write the Cursor prompt and exit instead of waiting.
  OPENAI_API_KEY     Set in scripts/.env to use GPT instead (optional).
  --template-story   Last-resort built-in filler (not recommended).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import content_reuse

WORDS_PER_SECOND = 2.35
DEFAULT_VOICE = "en-US-ChristopherNeural"


@dataclass
class PartClip:
    video_id: str
    part: int
    file_path: Path
    duration_seconds: float
    title: str = ""


@dataclass
class StoryPart:
    part: int
    narration: str


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _kino_exe() -> Path:
    return _project_root() / "tools" / "kinocut" / ".venv" / "Scripts" / "kino.exe"


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _run(cmd: list[str], *, quiet: bool = False) -> None:
    result = subprocess.run(
        cmd,
        capture_output=quiet,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""
        detail = stderr or stdout or f"exit {result.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{detail}")


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


def target_words(duration_seconds: float) -> int:
    return max(40, int(duration_seconds * WORDS_PER_SECOND * 0.92))


def load_parts_from_manifest(manifest_path: Path) -> tuple[str, list[PartClip]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    clips: list[PartClip] = []
    series_title = "Untitled story"
    for video in data.get("videos", []):
        series_title = video.get("title") or series_title
        video_id = video.get("video_id", "video")
        for part in video.get("parts") or []:
            file_path = Path(part["file_path"])
            if not file_path.is_file():
                raise FileNotFoundError(f"Missing part file: {file_path}")
            duration = float(part.get("duration_seconds") or probe_duration(file_path))
            clips.append(
                PartClip(
                    video_id=video_id,
                    part=int(part["part"]),
                    file_path=file_path,
                    duration_seconds=duration,
                    title=series_title,
                )
            )
    clips.sort(key=lambda c: (c.video_id, c.part))
    if not clips:
        raise ValueError(f"No parts found in manifest: {manifest_path}")
    return series_title, clips


def discover_parts_in_dir(folder: Path) -> list[PartClip]:
    pattern = re.compile(r"^(?P<id>.+)_part(?P<num>\d+)\.mp4$", re.IGNORECASE)
    clips: list[PartClip] = []
    for path in sorted(folder.glob("*_part*.mp4")):
        if path.name.endswith("_final.mp4"):
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        clips.append(
            PartClip(
                video_id=match.group("id"),
                part=int(match.group("num")),
                file_path=path,
                duration_seconds=probe_duration(path),
            )
        )
    clips.sort(key=lambda c: (c.video_id, c.part))
    if not clips:
        raise ValueError(f"No *_partNN.mp4 files found in {folder}")
    return clips


def generate_story_openai(
    *,
    clips: list[PartClip],
    theme: str,
    model: str,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    part_specs = [
        {
            "part": clip.part,
            "target_words": target_words(clip.duration_seconds),
            "duration_seconds": clip.duration_seconds,
        }
        for clip in clips
    ]
    used = content_reuse.used_prompt_block()
    prompt = f"""Write a dramatic first-person story for short-form video narration over background gameplay.

Theme: {theme}
Number of parts: {len(clips)}

Each part must fit its spoken duration. Use about the target word count for each part.
End every part except the last on a mini-cliffhanger. Part 1 must hook immediately.
The last part must resolve the story: we learn what happened, the danger ends or the twist lands, and it does not stop on another hook.
Do not reuse a title, hook, or plot from stories already made.

{used}

Parts specification (JSON):
{json.dumps(part_specs, indent=2)}

Return ONLY valid JSON in this shape:
{{
  "title": "short catchy title",
  "hook": "one-line hook for part 1 opening",
  "parts": [
    {{"part": 1, "narration": "spoken text for part 1 only"}},
    {{"part": 2, "narration": "spoken text for part 2 only"}}
  ]
}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You write viral short-form story scripts. Output strict JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def generate_story_fallback(*, clips: list[PartClip], theme: str) -> dict[str, Any]:
    """Template story when no OpenAI key is configured."""
    templates = [
        "I never thought a normal day would change everything. {detail} But then I noticed something that didn't add up.",
        "That's when it got worse. {detail} I tried to keep calm, but every instinct told me I was running out of time.",
        "By the end, I finally understood the truth. {detail} And honestly, I still can't believe how it ended.",
        "Looking back, the signs were always there. {detail} I just wasn't ready to see them until it was too late.",
        "What happened next still feels unreal. {detail} If you're watching this, learn from my mistake.",
    ]
    parts_out: list[dict[str, Any]] = []
    for i, clip in enumerate(clips):
        template = templates[i % len(templates)]
        words_needed = target_words(clip.duration_seconds)
        detail = f"This is part {clip.part} of a story about {theme}."
        narration = template.format(detail=detail)
        while len(narration.split()) < words_needed - 20:
            narration += (
                " I kept replaying the moment in my head, wondering who I could even trust. "
                "Every second felt louder than the last."
            )
        words = narration.split()
        if len(words) > words_needed:
            narration = " ".join(words[:words_needed])
        parts_out.append({"part": clip.part, "narration": narration})
    return {
        "title": f"{theme.title()} Story",
        "hook": "You won't believe how this started.",
        "parts": parts_out,
        "source": "template_fallback",
    }


def validate_story(story: dict[str, Any], clips: list[PartClip]) -> dict[str, Any]:
    parts = story.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Story JSON must include a non-empty 'parts' array")
    by_part = {int(p["part"]): str(p["narration"]).strip() for p in parts if "part" in p and "narration" in p}
    missing = [clip.part for clip in clips if clip.part not in by_part]
    if missing:
        raise ValueError(f"Story missing narration for part(s): {missing}")
    return story


def load_story_file(path: Path, clips: list[PartClip]) -> dict[str, Any]:
    story = json.loads(path.read_text(encoding="utf-8"))
    story = validate_story(story, clips)
    story["source"] = f"file:{path}"
    return story


def write_cursor_story_prompt(
    *,
    clips: list[PartClip],
    theme: str,
    series_title: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    part_specs = [
        {
            "part": clip.part,
            "duration_seconds": clip.duration_seconds,
            "target_words": target_words(clip.duration_seconds),
        }
        for clip in clips
    ]
    request = {
        "theme": theme,
        "series_title": series_title,
        "total_parts": len(clips),
        "total_runtime_seconds": sum(c.duration_seconds for c in clips),
        "parts": part_specs,
        "output_story_file": str(output_dir / "story.json"),
    }
    request_path = output_dir / "story_request.json"
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

    prompt_path = output_dir / "CURSOR_STORY_PROMPT.md"
    prompt_path.write_text(
        f"""# Cursor story request

Write a dramatic first-person story for short-form video narration over background gameplay.

## Theme
{theme}

## Source video
{series_title}

## Parts (write one narration block per part)
{json.dumps(part_specs, indent=2)}

## Rules
- Part 1 must hook in the first sentence.
- Each part must stay near its target word count (spoken at ~2.35 words/sec).
- End each part except the last on a mini-cliffhanger.
- The last part must resolve the story: we learn what happened, the danger ends or the twist lands, and it does not stop on another hook.
- Write for voiceover: short sentences, natural speech, no stage directions.
- Do NOT repeat filler lines to pad length.
- Do not reuse a title, hook, or plot from stories already made.

{content_reuse.used_prompt_block()}

## Output
Save **only** this JSON to `{request_path.parent / "story.json"}`:

```json
{{
  "title": "short catchy title",
  "hook": "one-line hook",
  "parts": [
    {{"part": 1, "narration": "..."}},
    {{"part": 2, "narration": "..."}}
  ]
}}
```

When `{request_path.parent / "story.json"}` is saved, the voiceover pipeline continues automatically
(TTS + captions). No need to re-run the command if you started with `--wait-for-story`.
""",
        encoding="utf-8",
    )
    return prompt_path, request_path


def wait_for_story_file(
    *,
    story_path: Path,
    clips: list[PartClip],
    poll_interval: float,
    timeout: float | None,
) -> dict[str, Any]:
    print(f"\nWaiting for {story_path.name} ...")
    print("Ask Cursor chat:")
    print('  "Read CURSOR_STORY_PROMPT.md and write story.json"')
    print("\nThe pipeline will continue automatically once the file is saved.\n")

    start = time.monotonic()
    last_error = ""
    while True:
        if story_path.is_file():
            try:
                story = load_story_file(story_path, clips)
                hits = content_reuse.find_story_reuse(story, ignore_paths=[str(story_path)])
                if hits:
                    print(f"  {story_path.name} reuses existing content:")
                    print(content_reuse.format_hits(hits))
                    print("  Rewrite story.json with a new plot, then save again.")
                    last_error = "story reuses existing content"
                else:
                    print(f"Found valid {story_path.name} — continuing voiceover...")
                    return story
            except (ValueError, json.JSONDecodeError, KeyError) as exc:
                last_error = str(exc)
                print(f"  {story_path.name} not ready yet ({exc})")

        if timeout is not None and timeout > 0 and (time.monotonic() - start) >= timeout:
            hint = f" Last error: {last_error}" if last_error else ""
            raise SystemExit(
                f"Timed out after {timeout:.0f}s waiting for {story_path}.{hint}"
            )

        time.sleep(poll_interval)


def resolve_story(
    *,
    clips: list[PartClip],
    theme: str,
    series_title: str,
    output_dir: Path,
    story_file: Path | None,
    story_mode: str,
    model: str,
    wait_for_story: bool,
    wait_timeout: float | None,
    poll_interval: float,
) -> dict[str, Any]:
    if story_file is not None:
        print(f"Loading story from {story_file}...")
        return load_story_file(story_file, clips)

    default_story = output_dir / "story.json"
    if story_mode == "cursor" and default_story.is_file():
        print(f"Loading Cursor story from {default_story}...")
        return load_story_file(default_story, clips)

    if story_mode == "openai" or (story_mode == "auto" and os.environ.get("OPENAI_API_KEY")):
        print(f"Generating story with OpenAI ({model})...")
        try:
            story = generate_story_openai(clips=clips, theme=theme, model=model)
            story["source"] = f"openai:{model}"
            return validate_story(story, clips)
        except Exception as exc:  # noqa: BLE001
            print(f"OpenAI story failed ({exc}).", file=sys.stderr)
            if story_mode == "openai":
                raise

    if story_mode == "template":
        print("Using built-in template story.")
        return generate_story_fallback(clips=clips, theme=theme)

    prompt_path, request_path = write_cursor_story_prompt(
        clips=clips,
        theme=theme,
        series_title=series_title,
        output_dir=output_dir,
    )
    print("\nCursor story mode: no story.json found yet.")
    print(f"  Prompt:  {prompt_path}")
    print(f"  Request: {request_path}")

    if wait_for_story:
        return wait_for_story_file(
            story_path=default_story,
            clips=clips,
            poll_interval=poll_interval,
            timeout=wait_timeout,
        )

    print("\nAsk Cursor chat:")
    print('  "Read CURSOR_STORY_PROMPT.md and write story.json"')
    print("\nThen re-run with --wait-for-story or pass --story-file story.json")
    raise SystemExit(2)


def synthesize_narration(
    text: str,
    *,
    voice: str,
    audio_path: Path,
    srt_path: Path,
) -> None:
    text_file = audio_path.with_suffix(".txt")
    text_file.write_text(text.strip(), encoding="utf-8")
    _run(
        [
            sys.executable,
            "-m",
            "edge_tts",
            "-f",
            str(text_file),
            "-v",
            voice,
            "--write-media",
            str(audio_path),
            "--write-subtitles",
            str(srt_path),
            "--rate",
            "+5%",
        ]
    )


def kinocut_replace_audio(video: Path, audio: Path, output: Path) -> None:
    kino = _kino_exe()
    if not kino.is_file():
        raise FileNotFoundError(f"Kinocut CLI not found: {kino}")
    _run(
        [
            str(kino),
            "--format",
            "json",
            "add-audio",
            str(video),
            str(audio),
            "-o",
            str(output),
        ],
        quiet=True,
    )


def probe_video_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    width, height = (int(x) for x in result.stdout.strip().split(",", 1))
    return width, height


def _srt_timestamp_to_ass(timestamp: str) -> str:
    hours, minutes, rest = timestamp.strip().split(":", 2)
    seconds, millis = rest.split(",", 1)
    cs = millis[:2].ljust(2, "0")
    return f"{int(hours)}:{minutes}:{seconds}.{cs}"


def _parse_srt_blocks(srt_path: Path) -> list[tuple[str, str, str]]:
    content = srt_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", content)
    events: list[tuple[str, str, str]] = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        timing = lines[1]
        if "-->" not in timing:
            continue
        start_raw, end_raw = (part.strip() for part in timing.split("-->", 1))
        text = "\\N".join(line.strip() for line in lines[2:] if line.strip())
        if not text:
            continue
        events.append((_srt_timestamp_to_ass(start_raw), _srt_timestamp_to_ass(end_raw), text))
    return events


def build_centered_ass(srt_path: Path, *, width: int, height: int, ass_path: Path) -> None:
    """Build a minimal authored ASS file with captions centered on the frame."""
    events = _parse_srt_blocks(srt_path)
    dialogue_lines = [
        f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}" for start, end, text in events
    ]
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,36,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,8,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(dialogue_lines)}
"""
    ass_path.write_text(ass_content, encoding="utf-8")


def caption_style_for_landscape() -> str:
    return (
        "FontSize=30,PrimaryColour=&H00FFFFFF,BackColour=&H00000000,"
        "BorderStyle=3,Outline=8,Alignment=2,MarginV=40"
    )


def kinocut_burn_captions(video: Path, srt: Path, output: Path) -> None:
    kino = _kino_exe()
    width, height = probe_video_size(video)

    if height > width:
        ass_path = srt.with_suffix(".center.ass")
        build_centered_ass(srt, width=width, height=height, ass_path=ass_path)
        subtitle_file = ass_path
        extra: list[str] = []
    else:
        subtitle_file = srt
        extra = ["--style", caption_style_for_landscape()]

    _run(
        [
            str(kino),
            "--format",
            "json",
            "subtitles",
            str(video),
            str(subtitle_file),
            *extra,
            "-o",
            str(output),
        ],
        quiet=True,
    )


def process_parts(
    clips: list[PartClip],
    *,
    story: dict[str, Any],
    output_dir: Path,
    voice: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    story_parts = {int(p["part"]): p["narration"] for p in story.get("parts", [])}
    results: list[dict[str, Any]] = []

    for clip in clips:
        narration = story_parts.get(clip.part)
        if not narration:
            raise ValueError(f"Story missing narration for part {clip.part}")

        work_dir = output_dir / clip.video_id / f"part{clip.part:02d}"
        work_dir.mkdir(parents=True, exist_ok=True)
        narration_txt = work_dir / "narration.txt"
        narration_txt.write_text(narration, encoding="utf-8")
        audio_path = work_dir / "narration.mp3"
        srt_path = work_dir / "narration.srt"
        voiced_path = work_dir / "voiced.mp4"
        final_path = output_dir / f"{clip.video_id}_part{clip.part:02d}_final.mp4"

        print(f"\n[Part {clip.part}] {clip.file_path.name} ({clip.duration_seconds:.0f}s)")
        print(f"  Words target: ~{target_words(clip.duration_seconds)}")
        print(f"  Narration preview: {narration[:120]}...")

        record: dict[str, Any] = {
            "part": clip.part,
            "input": str(clip.file_path),
            "narration_file": str(narration_txt),
            "final_path": str(final_path),
            "status": "pending",
        }

        if dry_run:
            record["status"] = "dry_run"
            results.append(record)
            continue

        print("  Synthesizing voice...")
        synthesize_narration(narration, voice=voice, audio_path=audio_path, srt_path=srt_path)

        print("  Kinocut: replace gameplay audio...")
        kinocut_replace_audio(clip.file_path, audio_path, voiced_path)

        print("  Kinocut: burn captions...")
        kinocut_burn_captions(voiced_path, srt_path, final_path)

        record["status"] = "ok"
        record["audio_path"] = str(audio_path)
        record["srt_path"] = str(srt_path)
        print(f"  Done: {final_path}")
        results.append(record)

    return results


def cleanup_scratch(output_dir: Path, video_ids: list[str]) -> None:
    """Drop render leftovers. Keep story.json and the finished part videos."""
    removed = 0
    for name in ("voiceover_manifest.json", "story_request.json", "CURSOR_STORY_PROMPT.md"):
        path = output_dir / name
        if path.is_file():
            path.unlink()
            removed += 1
    for video_id in dict.fromkeys(video_ids):
        path = output_dir / video_id
        if path.is_dir():
            shutil.rmtree(path)
            removed += 1
    if removed:
        print("Cleaned scratch files. Kept story.json and *_final.mp4.")


def cleanup_download_leftovers(source_dir: Path) -> None:
    """Drop source clips and sidecars after finals exist. Leave final/ alone."""
    removed = 0
    manifest = source_dir / "manifest.json"
    if manifest.is_file():
        manifest.unlink()
        removed += 1
    for path in source_dir.glob("*_source.*"):
        if path.is_file():
            path.unlink()
            removed += 1
    for path in source_dir.glob("*_part*.mp4"):
        if path.name.endswith("_final.mp4"):
            continue
        if path.is_file():
            path.unlink()
            removed += 1
    if removed:
        print("Cleaned source downloads. Kept story.json and *_final.mp4.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI story + voiceover + captions for part clips.")
    parser.add_argument(
        "source",
        type=Path,
        help="manifest.json path or folder containing *_partNN.mp4 files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder for final videos (default: <source>/final)",
    )
    parser.add_argument(
        "--theme",
        default="a shocking secret that ruined everything",
        help="Story theme / prompt",
    )
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"TTS voice (default: {DEFAULT_VOICE})")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model when --story-mode openai")
    parser.add_argument(
        "--story-file",
        type=Path,
        default=None,
        help="Use an existing story JSON (e.g. written by Cursor)",
    )
    parser.add_argument(
        "--story-mode",
        choices=("cursor", "openai", "template", "auto"),
        default="cursor",
        help="Story source: cursor (default), openai, template, or auto",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan render only, skip TTS/video")
    parser.add_argument(
        "--wait-for-story",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wait for story.json after writing Cursor prompt (default: on)",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=0,
        help="Seconds to wait for story.json (0 = no limit, default)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between story.json checks while waiting (default: 2)",
    )
    parser.add_argument(
        "--allow-reuse",
        action="store_true",
        help="Allow a story that matches one you already made",
    )
    return parser


def main() -> int:
    _load_env()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = build_parser().parse_args()
    source: Path = args.source

    if source.is_file() and source.name == "manifest.json":
        series_title, clips = load_parts_from_manifest(source)
        default_out = source.parent / "final"
    elif source.is_dir():
        clips = discover_parts_in_dir(source)
        series_title = clips[0].video_id
        default_out = source / "final"
    else:
        print(f"Source not found or unsupported: {source}", file=sys.stderr)
        return 1

    output_dir = args.output or default_out
    total_seconds = sum(c.duration_seconds for c in clips)
    print(f"Loaded {len(clips)} part(s), total runtime {total_seconds:.0f}s")
    print(f"Series: {series_title}")

    wait_timeout = args.wait_timeout if args.wait_timeout > 0 else None
    story = resolve_story(
        clips=clips,
        theme=args.theme,
        series_title=series_title,
        output_dir=output_dir,
        story_file=args.story_file,
        story_mode=args.story_mode,
        model=args.model,
        wait_for_story=args.wait_for_story,
        wait_timeout=wait_timeout,
        poll_interval=max(0.5, args.poll_interval),
    )
    story_path = output_dir / "story.json"
    ignore_story = [str(story_path)]
    if args.story_file is not None:
        ignore_story.append(str(args.story_file))
    try:
        hits = content_reuse.enforce_story_unused(
            story,
            ignore_paths=ignore_story,
            allow_reuse=args.allow_reuse,
        )
    except content_reuse.StoryReuseError as exc:
        print(str(exc), file=sys.stderr)
        print("Write a new plot, or pass --allow-reuse to keep this story.", file=sys.stderr)
        return 2
    if hits and args.allow_reuse:
        print(content_reuse.format_hits(hits))
        print("Allowed by --allow-reuse.")
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.story_file is None and not story_path.exists():
        story_path.write_text(json.dumps(story, indent=2), encoding="utf-8")
    elif args.story_file is None:
        story_path.write_text(json.dumps(story, indent=2), encoding="utf-8")
    print(f"\nStory title: {story.get('title', '(untitled)')}")
    print(f"Story saved: {story_path}")

    results = process_parts(
        clips,
        story=story,
        output_dir=output_dir,
        voice=args.voice,
        dry_run=args.dry_run,
    )

    ok = sum(1 for r in results if r.get("status") == "ok")
    if args.dry_run:
        print(f"\nDry run complete. {len(results)} part(s) planned.")
        return 0
    print(f"\nVoiceover complete: {ok}/{len(results)} part(s) rendered.")
    if ok == len(results):
        cleanup_scratch(output_dir, [clip.video_id for clip in clips])
        source_dir = source.parent if source.is_file() else source
        if source_dir.resolve() != output_dir.resolve():
            cleanup_download_leftovers(source_dir)
        content_reuse.register_story(story, path=story_path)
        for clip in clips:
            final_path = output_dir / f"{clip.video_id}_part{clip.part:02d}_final.mp4"
            content_reuse.register_video(
                youtube_id=content_reuse.youtube_id_from_name(final_path.name) or clip.video_id,
                file_path=final_path if final_path.is_file() else None,
                title=series_title,
            )
        print(f"Recorded in {content_reuse.catalog_path()}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
