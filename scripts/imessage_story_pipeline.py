#!/usr/bin/env python3
"""
Generate a vertical fake-story video told through an iPhone iMessage thread.

No downloaded gameplay. The video IS the conversation: typing dots, bubbles,
and the iMessage composer bar, assembled into 9:16 parts.

Examples:
  python scripts/imessage_story_pipeline.py --theme "don't come home yet"
  python scripts/imessage_story_pipeline.py --story-mode template --voiceover
  python scripts/imessage_story_pipeline.py --story-file downloads/imessage/story.json
  python scripts/imessage_story_pipeline.py --appearance light --parts 2 --duration 40
  python scripts/imessage_story_pipeline.py --no-voiceover
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import content_reuse
from imessage_ui import HEIGHT, WIDTH, ChatMessage, PhoneUI, theme_for

DEFAULT_PARTS = 2
DEFAULT_DURATION = 38.0
DEFAULT_APPEARANCE = "dark"
DEFAULT_VOICE = "en-US-ChristopherNeural"
WORDS_PER_SECOND = 2.35


@dataclass
class FrameEvent:
    messages: list[ChatMessage]
    duration: float
    typing: str | None = None  # "them"
    composer: str = ""
    sound: str | None = None  # "send" | "receive"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


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
    result = subprocess.run(cmd, capture_output=quiet, text=True, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{stderr or stdout or result.returncode}")


def typing_seconds(text: str, sender: str) -> float:
    chars = max(1, len(text))
    if sender == "me":
        return min(2.1, max(0.65, chars * 0.032 + 0.4))
    return min(2.3, max(0.8, chars * 0.038 + 0.5))


def hold_seconds(text: str) -> float:
    words = max(1, len(text.split()))
    return min(3.0, max(0.85, words * 0.26 + 0.55))


def parse_messages(raw_part: dict[str, Any]) -> list[ChatMessage]:
    items = raw_part.get("messages")
    if not isinstance(items, list) or not items:
        raise ValueError(f"Part {raw_part.get('part')} needs a non-empty messages array")
    out: list[ChatMessage] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each message must be an object")
        kind = str(item.get("kind") or item.get("type") or "text").lower()
        text = str(item.get("text") or "").strip()
        if kind in {"time", "timestamp"}:
            out.append(ChatMessage(sender="time", text=text or "Today"))
            continue
        sender = str(item.get("from") or item.get("sender") or "").lower()
        if sender in {"them", "other", "contact", "left"}:
            sender = "them"
        elif sender in {"me", "self", "you", "right"}:
            sender = "me"
        else:
            raise ValueError(f"Message is missing from=me|them: {item}")
        if not text:
            raise ValueError("Text messages need a non-empty text field")
        out.append(ChatMessage(sender=sender, text=text, status=str(item.get("status") or "")))
    return out


def validate_story(story: dict[str, Any], parts: int) -> dict[str, Any]:
    raw_parts = story.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("Story JSON must include a non-empty parts array")
    by_part = {}
    for part in raw_parts:
        number = int(part["part"])
        by_part[number] = parse_messages(part)
    missing = [n for n in range(1, parts + 1) if n not in by_part]
    if missing:
        raise ValueError(f"Story missing part(s): {missing}")
    story["_parsed"] = by_part
    return story


def built_in_story() -> dict[str, Any]:
    return {
        "title": "Don't Come Home Yet",
        "hook": "Don't come home yet.",
        "contact_name": "Mom",
        "time": "2:14",
        "appearance": "dark",
        "source": "template",
        "parts": [
            {
                "part": 1,
                "narration": (
                    "I was still at work when my mom texted me not to come home. "
                    "At first I thought she was overreacting. Then she said my dad's car was in the driveway, "
                    "even though he did not have a key anymore. I told her to call the police, and she said she already had. "
                    "Then she wrote the line that made my stomach drop: he was inside the house, and she could not leave."
                ),
                "messages": [
                    {"kind": "time", "text": "Today 2:14 AM"},
                    {"from": "them", "text": "Are you still at work?"},
                    {"from": "me", "text": "Yeah just leaving. Why."},
                    {"from": "them", "text": "Don't come home yet."},
                    {"from": "me", "text": "Mom what happened"},
                    {"from": "them", "text": "Just stay where you are."},
                    {"from": "me", "text": "You're scaring me"},
                    {"from": "them", "text": "Your dad's car is in the driveway."},
                    {"from": "me", "text": "He doesn't have a key anymore"},
                    {"from": "them", "text": "I know."},
                    {"from": "me", "text": "Call the police"},
                    {"from": "them", "text": "I already did."},
                    {"from": "them", "text": "He's inside the house."},
                    {"from": "me", "text": "GET OUT"},
                    {"from": "them", "text": "I can't."},
                    {"from": "them", "text": "He's in the hallway."},
                ],
            },
            {
                "part": 2,
                "narration": (
                    "I kept texting, but the replies stopped sounding like my mom. "
                    "Someone else had her phone. They told me to come home so we could talk, "
                    "then switched back to her voice and said he had been arrested. "
                    "Even then, I did not feel safe until I was in the car and on my way."
                ),
                "messages": [
                    {"kind": "time", "text": "Today 2:17 AM"},
                    {"from": "me", "text": "Mom??"},
                    {"from": "me", "text": "Answer me"},
                    {"from": "them", "text": "She can't come to the phone."},
                    {"from": "me", "text": "Who is this."},
                    {"from": "them", "text": "Come home. We should talk."},
                    {"from": "me", "text": "I'm calling the cops right now"},
                    {"from": "them", "text": "It's me. I'm okay."},
                    {"from": "me", "text": "Don't play with me"},
                    {"from": "them", "text": "They arrested him."},
                    {"from": "me", "text": "Then who just texted me"},
                    {"from": "them", "text": "He had my phone for a minute."},
                    {"from": "them", "text": "It's over. Come home."},
                    {"from": "me", "text": "I'm on my way. Do not open the door until you see me."},
                    {"from": "them", "text": "I won't. I love you."},
                ],
            },
        ],
    }


def as_history(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Copy prior-part messages onto the next part's screen.

    iOS only keeps a receipt under the latest outgoing bubble, and only if they
    have not replied yet. Older sent texts stay unmarked.
    """
    last_text = -1
    for index, message in enumerate(messages):
        if message.sender in {"me", "them"}:
            last_text = index
    out: list[ChatMessage] = []
    for index, message in enumerate(messages):
        status = ""
        if message.sender == "me" and index == last_text:
            status = message.status or "Delivered"
        out.append(ChatMessage(sender=message.sender, text=message.text, status=status))
    return out


def plan_timeline(messages: list[ChatMessage], history: list[ChatMessage] | None = None) -> list[FrameEvent]:
    events: list[FrameEvent] = []
    visible: list[ChatMessage] = list(history or [])
    if visible:
        events.append(FrameEvent(messages=list(visible), duration=0.9))
    for index, message in enumerate(messages):
        if message.sender == "time":
            visible.append(message)
            events.append(FrameEvent(messages=list(visible), duration=0.7))
            continue
        events.append(
            FrameEvent(
                messages=list(visible),
                duration=typing_seconds(message.text, message.sender),
                # iOS only shows the animated dots for the other person.
                typing="them" if message.sender == "them" else None,
            )
        )
        visible.append(message)
        sound = "receive" if message.sender == "them" else "send"
        is_last = index == len(messages) - 1
        shown = list(visible)
        if message.sender == "me":
            shown[-1] = ChatMessage(sender="me", text=message.text, status=message.status or "Delivered")
        events.append(
            FrameEvent(
                messages=shown,
                duration=hold_seconds(message.text) + (1.15 if is_last else 0),
                sound=sound,
            )
        )
    if not events:
        raise ValueError("No timeline events")
    return events


def expand_events(events: list[FrameEvent]) -> list[tuple[FrameEvent, int, float]]:
    """Each item is (event, animation_phase, slice_duration)."""
    slices: list[tuple[FrameEvent, int, float]] = []
    for event in events:
        if event.typing:
            steps = max(3, int(round(event.duration * 5)))
            step = event.duration / steps
            for i in range(steps):
                slices.append((event, i, step))
        elif event.composer:
            steps = max(3, int(round(event.duration * 5)))
            step = event.duration / steps
            text = event.composer
            for i in range(steps):
                chars = max(1, int(len(text) * (i + 1) / steps))
                partial = FrameEvent(
                    messages=event.messages,
                    duration=step,
                    composer=text[:chars],
                    sound=event.sound if i == steps - 1 else None,
                )
                slices.append((partial, i, step))
        else:
            slices.append((event, 0, event.duration))
    return slices


def write_tone_samples(kind: str, sample_rate: int = 44100) -> list[int]:
    if kind == "send":
        freqs = (1180, 1560)
        ms = 70
    else:
        freqs = (880, 1240)
        ms = 90
    n = int(sample_rate * ms / 1000)
    out = []
    for i in range(n):
        t = i / sample_rate
        env = (1 - i / max(1, n - 1)) ** 1.6
        val = 0.0
        for freq in freqs:
            val += math.sin(2 * math.pi * freq * t)
        val = val / len(freqs) * env * 0.28
        out.append(int(max(-1.0, min(1.0, val)) * 32767))
    return out


def write_mix_wav(events: list[FrameEvent], path: Path) -> float:
    sample_rate = 44100
    total = sum(e.duration for e in events)
    samples = [0] * int(sample_rate * (total + 0.15))
    tones = {name: write_tone_samples(name, sample_rate) for name in ("send", "receive")}
    cursor = 0.0
    for event in events:
        if event.sound:
            start = int(cursor * sample_rate)
            tone = tones[event.sound]
            for i, value in enumerate(tone):
                idx = start + i
                if idx < len(samples):
                    mixed = samples[idx] + value
                    samples[idx] = max(-32767, min(32767, mixed))
        cursor += event.duration
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return total


def probe_media_duration(path: Path) -> float:
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
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {(result.stderr or '').strip()}")
    return float(result.stdout.strip())


def atempo_chain(factor: float) -> str:
    if factor <= 0:
        raise ValueError(f"atempo factor must be positive, got {factor}")
    parts: list[float] = []
    remaining = factor
    while remaining < 0.5:
        parts.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        parts.append(2.0)
        remaining /= 2.0
    parts.append(remaining)
    return ",".join(f"atempo={value:.6f}" for value in parts)


def edge_tts_rate_for_duration(text: str, target_duration: float) -> str:
    words = max(1, len(text.split()))
    estimated = words / WORDS_PER_SECOND
    pct = int(round((target_duration / estimated - 1.0) * 100))
    pct = max(-45, min(45, pct))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def fit_voiceover_to_duration(voice_path: Path, target_duration: float, output_path: Path) -> float:
    actual = probe_media_duration(voice_path)
    if abs(actual - target_duration) <= 0.12:
        if output_path.resolve() != voice_path.resolve():
            output_path.write_bytes(voice_path.read_bytes())
        return actual

    tempo = actual / target_duration
    if tempo < 0.65 or tempo > 1.5:
        print(
            f"  Voiceover pacing: {actual:.1f}s speech for {target_duration:.1f}s video "
            f"({tempo:.2f}x tempo — narration may be too short/long)"
        )
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_path),
            "-filter:a",
            atempo_chain(tempo),
            "-t",
            f"{target_duration:.3f}",
            str(output_path),
        ],
        quiet=True,
    )
    fitted = probe_media_duration(output_path)
    print(f"  Voiceover fit: {actual:.1f}s -> {fitted:.1f}s (target {target_duration:.1f}s)")
    return fitted


def target_narration_words(duration: float) -> int:
    return max(40, int(duration * WORDS_PER_SECOND * 0.92))


def part_narration(story: dict[str, Any], part: int, messages: list[ChatMessage], duration: float) -> str:
    for raw in story.get("parts") or []:
        if int(raw.get("part", 0)) == part:
            narration = str(raw.get("narration") or "").strip()
            if narration:
                return narration
    hook = str(story.get("hook") or story.get("title") or "This story still haunts me.")
    texts = [m.text for m in messages if m.sender in {"me", "them"}]
    preview = " ".join(texts[:8])
    return f"{hook} It started with a text thread I will never forget. {preview}"


def synthesize_voiceover(text: str, *, voice: str, audio_path: Path, rate: str = "+5%") -> None:
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
            "--rate",
            rate,
        ]
    )


def write_silent_wav(duration: float, path: Path) -> None:
    sample_rate = 44100
    samples = [0] * max(1, int(sample_rate * max(duration, 0.1)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def mux_voiceover(video_path: Path, audio_path: Path, output_path: Path, duration: float) -> None:
    # The timeline holds its final frame for a beat, but that hold only exists as a
    # container duration -- the last packet's timestamp is earlier. Pin the length and
    # clone-pad the tail frame if the encoded video stream ends early.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_duration = probe_media_duration(video_path)
    pad = max(0.0, duration - video_duration)
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path)]
    if pad > 0.05:
        cmd += [
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.3f}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
        ]
    else:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration:.3f}",
        str(output_path),
    ]
    _run(cmd, quiet=True)


def write_concat_list(entries: list[tuple[Path, float]], list_path: Path) -> None:
    lines: list[str] = []
    last = ""
    for path, duration in entries:
        posix = path.resolve().as_posix().replace("'", "'\\''")
        last = posix
        lines.append(f"file '{posix}'")
        lines.append(f"duration {duration:.3f}")
    if last:
        lines.append(f"file '{last}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_video(list_path: Path, audio_path: Path, output_path: Path, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-i",
            str(audio_path),
            "-vsync",
            "vfr",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-t",
            f"{duration:.3f}",
            str(output_path),
        ],
        quiet=True,
    )


def write_cursor_prompt(
    *,
    theme: str,
    parts: int,
    duration: float,
    contact: str,
    output_dir: Path,
    voiceover: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    target_messages = max(10, int(duration / 2.45))
    target_words = target_narration_words(duration)
    request = {
        "theme": theme,
        "total_parts": parts,
        "seconds_per_part": duration,
        "target_messages_per_part": target_messages,
        "target_narration_words_per_part": target_words,
        "voiceover": voiceover,
        "default_contact_name": contact,
        "output_story_file": str(output_dir / "story.json"),
    }
    request_path = output_dir / "story_request.json"
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    prompt_path = output_dir / "CURSOR_STORY_PROMPT.md"
    prompt_path.write_text(
        f"""# Cursor iMessage story request

Write a fake story told through iPhone text messages. This will be rendered as a vertical iMessage video.
{"A voiceover narrator plays over the chat (no on-screen captions)." if voiceover else ""}

## Theme
{theme}

## Format
- {parts} part(s)
- About {duration:.0f} seconds per part
- About {target_messages} bubbles per part (short texts, not paragraphs)
- Default contact name if none fits better: {contact}
{"- About " + str(target_words) + " words of first-person narration per part (voiceover, not shown as captions). Narration must fill the full clip (~2.35 words/sec); a busy thread often runs longer than the target duration." if voiceover else ""}

## Rules
- The chat is the visual story. {"The narration retells it dramatically in first person." if voiceover else "No narrator."}
- Texts must sound like real phones: short, uneven, a little messy.
- Part 1 must hook in the first 2-3 bubbles.
- End every part except the last on a cliffhanger last message.
- The last part must actually end: name who or what it was, get the narrator somewhere safe, and close in the last 2-3 bubbles. Do not finish on RUN, don't open the door, or another hook.
- Alternate me/them enough that it feels like a real back-and-forth.
- First item in each part should be a timestamp: {{"kind": "time", "text": "Today 2:14 AM"}}
- Do not pad with filler like "ok" "lol" unless it serves the story.
- Do not reuse a title, hook, or plot from stories already made.

{content_reuse.used_prompt_block()}

## Output
Save **only** this JSON to `{output_dir / "story.json"}`:

```json
{{
  "title": "short catchy title",
  "hook": "the line that makes someone stop scrolling",
  "contact_name": "Mom",
  "time": "2:14",
  "appearance": "dark",
  "parts": [
    {{
      "part": 1,
      {"\"narration\": \"first-person voiceover for this part (~" + str(target_words) + " words)\"," if voiceover else ""}
      "messages": [
        {{"kind": "time", "text": "Today 2:14 AM"}},
        {{"from": "them", "text": "Are you awake?"}},
        {{"from": "me", "text": "Yeah what's wrong"}}
      ]
    }}
  ]
}}
```

`from` must be `me` or `them`. When this file is saved, the pipeline continues automatically.
""",
        encoding="utf-8",
    )
    return prompt_path, request_path


def generate_story_openai(*, theme: str, parts: int, duration: float, contact: str, model: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    target_messages = max(10, int(duration / 2.45))
    used = content_reuse.used_prompt_block()
    prompt = f"""Write a viral fake story told only through iPhone texts.

Theme: {theme}
Parts: {parts}
Seconds per part: {duration}
Target bubbles per part: {target_messages}
Suggested contact name: {contact}

Do not reuse a title, hook, or plot from stories already made.

{used}
Rules:
- Short real-looking texts, not narration.
- Part 1 hooks immediately.
- Cliffhanger at the end of every part except the last.
- The last part must resolve: we learn who or what it was, the narrator is safe, and the last 2-3 bubbles close the story. No final-part hook.
- First message of each part is kind=time.

Return ONLY JSON:
{{
  "title": "...",
  "hook": "...",
  "contact_name": "...",
  "time": "2:14",
  "appearance": "dark",
  "parts": [
    {{"part": 1, "messages": [{{"kind": "time", "text": "Today 2:14 AM"}}, {{"from": "them", "text": "..."}}]}}
  ]
}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You write viral iMessage story scripts. Output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")


def wait_for_story(
    *,
    story_path: Path,
    parts: int,
    poll_interval: float,
    timeout: float | None,
) -> dict[str, Any]:
    print(f"\nWaiting for {story_path.name} ...")
    print("Ask Cursor chat:")
    print('  "Read CURSOR_STORY_PROMPT.md and write story.json"')
    print("\nThe pipeline continues automatically once the file is valid.\n")
    start = time.monotonic()
    last_error = ""
    while True:
        if story_path.is_file():
            try:
                story = json.loads(story_path.read_text(encoding="utf-8"))
                story = validate_story(story, parts)
                hits = content_reuse.find_story_reuse(story, ignore_paths=[str(story_path)])
                if hits:
                    print(f"  {story_path.name} reuses existing content:")
                    print(content_reuse.format_hits(hits))
                    print("  Rewrite story.json with a new plot, then save again.")
                    last_error = "story reuses existing content"
                else:
                    return story
            except (ValueError, json.JSONDecodeError, KeyError) as exc:
                last_error = str(exc)
                print(f"  {story_path.name} not ready yet ({exc})")
        if timeout is not None and timeout > 0 and (time.monotonic() - start) >= timeout:
            raise SystemExit(f"Timed out waiting for {story_path}. Last error: {last_error}")
        time.sleep(poll_interval)


def resolve_story(
    *,
    theme: str,
    parts: int,
    duration: float,
    contact: str,
    output_dir: Path,
    story_file: Path | None,
    story_mode: str,
    model: str,
    wait_for_story_file: bool,
    wait_timeout: float | None,
    poll_interval: float,
    voiceover: bool,
) -> dict[str, Any]:
    if story_file is not None:
        story = json.loads(story_file.read_text(encoding="utf-8"))
        story["source"] = f"file:{story_file}"
        return validate_story(story, parts)

    default_story = output_dir / "story.json"
    if story_mode == "cursor" and default_story.is_file():
        story = json.loads(default_story.read_text(encoding="utf-8"))
        story["source"] = f"file:{default_story}"
        return validate_story(story, parts)

    if story_mode == "openai" or (story_mode == "auto" and os.environ.get("OPENAI_API_KEY")):
        print(f"Generating iMessage story with OpenAI ({model})...")
        story = generate_story_openai(theme=theme, parts=parts, duration=duration, contact=contact, model=model)
        story["source"] = f"openai:{model}"
        return validate_story(story, parts)

    if story_mode == "template":
        print("Using built-in iMessage story.")
        return validate_story(built_in_story(), parts)

    prompt_path, request_path = write_cursor_prompt(
        theme=theme,
        parts=parts,
        duration=duration,
        contact=contact,
        output_dir=output_dir,
        voiceover=voiceover,
    )
    print("\nCursor story mode: no story.json found yet.")
    print(f"  Prompt:  {prompt_path}")
    print(f"  Request: {request_path}")
    if wait_for_story_file:
        return wait_for_story(
            story_path=default_story,
            parts=parts,
            poll_interval=poll_interval,
            timeout=wait_timeout,
        )
    print("\nAsk Cursor chat:")
    print('  "Read CURSOR_STORY_PROMPT.md and write story.json"')
    raise SystemExit(2)


def render_part(
    *,
    part: int,
    messages: list[ChatMessage],
    story: dict[str, Any],
    output_dir: Path,
    appearance: str,
    dry_run: bool,
    voiceover: bool,
    voice: str,
    history: list[ChatMessage] | None = None,
) -> dict[str, Any]:
    contact = str(story.get("contact_name") or "Mom")
    clock = str(story.get("time") or "2:14")
    theme = theme_for(story.get("appearance") or appearance)
    badge_raw = story.get("unread_badge")
    unread_badge = int(badge_raw) if badge_raw not in (None, "") else None
    ui = PhoneUI(
        theme,
        contact,
        clock,
        story.get("contact_color"),
        unread_badge,
    )
    prior = list(history or [])
    events = plan_timeline(messages, prior)
    duration = sum(e.duration for e in events)
    final_path = output_dir / f"part{part:02d}_final.mp4"
    record = {
        "part": part,
        "messages": len(messages),
        "history_messages": len(prior),
        "duration_seconds": round(duration, 2),
        "final_path": str(final_path),
        "status": "pending",
    }
    prior_note = f", {len(prior)} prior on screen" if prior else ""
    print(f"\nPart {part}: {len(messages)} bubbles{prior_note}, ~{duration:.1f}s")
    print(f"  Contact: {contact}")
    if dry_run:
        record["status"] = "dry_run"
        return record

    frames_dir = output_dir / "frames" / f"part{part:02d}"
    if frames_dir.exists():
        for old in frames_dir.glob("*.png"):
            old.unlink()
    frames_dir.mkdir(parents=True, exist_ok=True)
    slices = expand_events(events)
    concat_entries: list[tuple[Path, float]] = []
    cache: dict[tuple[int, str, str, int], Path] = {}
    for i, (event, phase, slice_dur) in enumerate(slices):
        key = (len(event.messages), event.typing or "", event.composer, phase)
        if key not in cache:
            frame = ui.render(event.messages, typing=event.typing, composer=event.composer, phase=phase)
            path = frames_dir / f"f{i:04d}.png"
            frame.save(path, "PNG")
            cache[key] = path
        concat_entries.append((cache[key], slice_dur))

    audio_path = output_dir / "audio" / f"part{part:02d}.wav"
    list_path = frames_dir / "concat.txt"
    write_concat_list(concat_entries, list_path)
    print("  Assembling video...")
    if voiceover:
        work_mp4 = output_dir / f"part{part:02d}_work.mp4"
        write_silent_wav(duration, audio_path)
        assemble_video(list_path, audio_path, work_mp4, duration)
        narration = part_narration(story, part, messages, duration)
        narration_path = output_dir / "audio" / f"part{part:02d}_narration.txt"
        narration_path.write_text(narration, encoding="utf-8")
        voice_path = output_dir / "audio" / f"part{part:02d}_voice.mp3"
        fitted_path = output_dir / "audio" / f"part{part:02d}_voice_fit.mp3"
        words = len(narration.split())
        needed = target_narration_words(duration)
        if words < int(needed * 0.75):
            print(f"  Warning: narration is {words} words but ~{needed} words fit {duration:.0f}s")
        print("  Synthesizing voiceover...")
        rate = edge_tts_rate_for_duration(narration, duration)
        synthesize_voiceover(narration, voice=voice, audio_path=voice_path, rate=rate)
        fit_voiceover_to_duration(voice_path, duration, fitted_path)
        mux_voiceover(work_mp4, fitted_path, final_path, duration)
        record["narration_file"] = str(narration_path)
        record["voice_path"] = str(fitted_path)
        if work_mp4.exists():
            work_mp4.unlink()
    else:
        write_mix_wav(events, audio_path)
        assemble_video(list_path, audio_path, final_path, duration)
        record["audio_path"] = str(audio_path)
    record["status"] = "ok"
    record["voiceover"] = voiceover
    print(f"  Done: {final_path}")
    return record


SCRATCH_DIRS = ("frames", "audio")
SCRATCH_FILES = ("manifest.json", "story_request.json", "CURSOR_STORY_PROMPT.md")


def cleanup_scratch(output_dir: Path) -> None:
    """Drop render leftovers. Keep story.json and the finished part videos."""
    removed = 0
    for name in SCRATCH_DIRS:
        path = output_dir / name
        if path.is_dir():
            shutil.rmtree(path)
            removed += 1
    for name in SCRATCH_FILES:
        path = output_dir / name
        if path.is_file():
            path.unlink()
            removed += 1
    for path in output_dir.glob("part*_work.mp4"):
        path.unlink()
        removed += 1
    for path in output_dir.glob("strip_part*.png"):
        path.unlink()
        removed += 1
    if removed:
        print("Cleaned scratch files. Kept story.json and *_final.mp4.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a fake iMessage story video.")
    parser.add_argument("--output", type=Path, default=None, help="Output folder (default: downloads/imessage)")
    parser.add_argument("--theme", default="don't come home yet", help="Story theme / prompt")
    parser.add_argument("--contact", default="Mom", help="Default contact name if the story does not set one")
    parser.add_argument("--parts", type=int, default=DEFAULT_PARTS, help="How many video parts (default: 2)")
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION,
        help="Target seconds per part, used for story sizing (default: 38)",
    )
    parser.add_argument(
        "--appearance",
        choices=("dark", "light"),
        default=DEFAULT_APPEARANCE,
        help="iMessage look (story.json can override)",
    )
    parser.add_argument("--story-file", type=Path, default=None, help="Use an existing conversation JSON")
    parser.add_argument(
        "--story-mode",
        choices=("cursor", "openai", "template", "auto"),
        default="cursor",
        help="Story source: cursor (default), openai, template, or auto",
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model when --story-mode openai")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, skip render")
    parser.add_argument(
        "--wait-for-story",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wait for story.json after writing Cursor prompt (default: on)",
    )
    parser.add_argument("--wait-timeout", type=float, default=0, help="Seconds to wait for story.json (0 = no limit)")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between story.json checks")
    parser.add_argument(
        "--voiceover",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add first-person voiceover narration (no captions, default: on)",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help=f"edge-tts voice for voiceover (default: {DEFAULT_VOICE})",
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
    output_dir = args.output or (_project_root() / "downloads" / "imessage")
    output_dir.mkdir(parents=True, exist_ok=True)
    parts = max(1, args.parts)
    wait_timeout = args.wait_timeout if args.wait_timeout > 0 else None

    story = resolve_story(
        theme=args.theme,
        parts=parts,
        duration=args.duration,
        contact=args.contact,
        output_dir=output_dir,
        story_file=args.story_file,
        story_mode=args.story_mode,
        model=args.model,
        wait_for_story_file=args.wait_for_story,
        wait_timeout=wait_timeout,
        poll_interval=max(0.5, args.poll_interval),
        voiceover=args.voiceover,
    )
    story_path = output_dir / "story.json"
    to_save = {k: v for k, v in story.items() if k != "_parsed"}
    if "appearance" not in to_save:
        to_save["appearance"] = args.appearance
    if "contact_name" not in to_save:
        to_save["contact_name"] = args.contact
    story_path.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
    print(f"\nStory title: {story.get('title', '(untitled)')}")
    print(f"Story saved: {story_path}")
    ignore_story = [str(story_path)]
    if args.story_file is not None:
        ignore_story.append(str(args.story_file))
    try:
        hits = content_reuse.enforce_story_unused(
            to_save,
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

    parsed: dict[int, list[ChatMessage]] = story["_parsed"]
    results = []
    history: list[ChatMessage] = []
    for part in range(1, parts + 1):
        results.append(
            render_part(
                part=part,
                messages=parsed[part],
                story=to_save,
                output_dir=output_dir,
                appearance=args.appearance,
                dry_run=args.dry_run,
                voiceover=args.voiceover,
                voice=args.voice,
                history=history,
            )
        )
        history.extend(as_history(parsed[part]))

    ok = sum(1 for r in results if r.get("status") == "ok")
    if args.dry_run:
        print(f"\nDry run complete. {len(results)} part(s) planned.")
        return 0
    print(f"\n iMessage story complete: {ok}/{len(results)} part(s) rendered.")
    if ok == len(results):
        cleanup_scratch(output_dir)
        content_reuse.register_story(to_save, path=story_path)
        for record in results:
            final = Path(str(record.get("final_path") or ""))
            if final.is_file():
                content_reuse.register_video(file_path=final, title=str(to_save.get("title") or final.stem))
        print(f"Recorded in {content_reuse.catalog_path()}")
        try:
            from discovery.auto_register import sync_register_best_effort
            from discovery.site_videos import sync_legacy_renders_to_site

            for record in results:
                final = Path(str(record.get("final_path") or ""))
                if final.is_file():
                    sync_register_best_effort(
                        final_path=final,
                        slug=story_path.parent.name,
                        title=str(to_save.get("title") or final.stem),
                        hook=str(to_save.get("hook") or ""),
                        job_dir=output_dir,
                        pipeline="imessage_story_pipeline",
                    )
            sync_legacy_renders_to_site(slugs=[story_path.parent.name])
        except ImportError:
            pass
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
