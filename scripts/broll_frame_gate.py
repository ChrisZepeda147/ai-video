#!/usr/bin/env python3
"""Local B-roll frame gate: talking-head, title-card, empty, optional subject check."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image

WORD_RE = re.compile(r"[a-z0-9]+")
ALNUM_RE = re.compile(r"[^a-z0-9]+")

BROLL_STOP = {
    "4k",
    "8k",
    "asmr",
    "broll",
    "cinematic",
    "clip",
    "clips",
    "dark",
    "drive",
    "driving",
    "footage",
    "free",
    "hd",
    "luxury",
    "motivation",
    "motivational",
    "music",
    "night",
    "no",
    "raw",
    "reel",
    "reels",
    "short",
    "shorts",
    "stock",
    "tour",
    "uhd",
    "video",
    "videos",
}

SUBJECT_ALIASES = {
    "porsche": ("porsche", "gt3", "gt3rs", "911", "carrera", "gt2"),
    "gt3rs": ("gt3rs", "gt3", "porsche"),
    "gt3": ("gt3", "gt3rs", "porsche"),
    "lambo": ("lambo", "lamborghini", "aventador", "huracan", "urus", "revuelto"),
    "lamborghini": ("lambo", "lamborghini", "aventador", "huracan", "urus", "revuelto"),
    "ferrari": ("ferrari", "sf90", "pista", "roma", "812", "488"),
    "yacht": ("yacht", "superyacht", "megayacht"),
    "mansion": ("mansion", "estate", "villa"),
    "villa": ("villa", "estate"),
}

TALKING_HEAD_LIMIT = 0.10
TITLE_CARD_LIMIT = 0.58
EMPTY_LIMIT = 0.86
PASS_RATIO = 0.8
SCAN_STEP = 1.0
MIN_CLEAN_SPAN = 3.0
VEHICLE_MID_VAR_MIN = 1800.0
OPENER_MID_VAR_MIN = 2000.0
OPENER_JUMP_MEAN_DIFF = 42.0
VEHICLE_WORDS = frozenset(
    {
        "911",
        "aventador",
        "car",
        "carrera",
        "coupe",
        "ferrari",
        "gt2",
        "gt3",
        "gt3rs",
        "huracan",
        "lambo",
        "lamborghini",
        "pista",
        "porsche",
        "revuelto",
        "roma",
        "sf90",
        "supercar",
        "urus",
        "vehicle",
    }
)
OPENER_VIEWS = frozenset({"front", "three_quarter", "side"})
NON_CAR_OBJECTS = frozenset(
    {
        "coffee",
        "tamper",
        "espresso",
        "person",
        "people",
        "man",
        "woman",
        "host",
        "face",
        "kitchen",
        "watch",
        "phone",
        "logo",
        "text",
        "mansion",
        "house",
    }
)


def subject_tokens(*parts: str) -> list[str]:
    raw = " ".join(part.replace("-", " ").replace("_", " ") for part in parts if part)
    found: list[str] = []
    seen: set[str] = set()
    for word in WORD_RE.findall(raw.lower()):
        if word in BROLL_STOP or len(word) < 3:
            continue
        if word not in seen:
            seen.add(word)
            found.append(word)
    if found:
        return found
    fallback = [word for word in WORD_RE.findall(raw.lower()) if len(word) > 2]
    return list(dict.fromkeys(fallback))


def _normalized(text: str) -> str:
    return ALNUM_RE.sub("", (text or "").lower())


def title_matches_subject(title: str, subjects: Iterable[str]) -> bool:
    tokens = [item for item in subjects if item]
    if not tokens:
        return True
    hay = (title or "").lower()
    compact = _normalized(title)
    for token in tokens:
        aliases = SUBJECT_ALIASES.get(token, (token,))
        for alias in aliases:
            if alias in hay.split() or alias in hay or _normalized(alias) in compact:
                return True
    return False


def _is_skin_pixel(r: int, g: int, b: int) -> bool:
    if r < 60 or g < 40 or b < 20:
        return False
    if max(r, g, b) - min(r, g, b) < 15:
        return False
    if r <= g or r <= b:
        return False
    return (r - g) >= 15 and (r - b) >= 15


def talking_head_score(png_bytes: bytes) -> float:
    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    width, height = img.size
    regions = (
        (int(width * 0.20), int(width * 0.80), int(height * 0.08), int(height * 0.62)),
        (int(width * 0.28), int(width * 0.72), int(height * 0.55), int(height * 0.92)),
    )
    skin_hits = 0
    total = 0
    for x0, x1, y0, y1 in regions:
        for x in range(x0, x1, 2):
            for y in range(y0, y1, 2):
                r, g, b = img.getpixel((x, y))
                if _is_skin_pixel(r, g, b):
                    skin_hits += 1
                total += 1
    return skin_hits / max(total, 1)


def title_card_score(png_bytes: bytes) -> float:
    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    width, height = img.size
    dark = 0
    bright = 0
    colors: set[tuple[int, int, int]] = set()
    total = 0
    for x in range(0, width, 4):
        for y in range(0, height, 4):
            r, g, b = img.getpixel((x, y))
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luma < 28:
                dark += 1
            if luma > 230:
                bright += 1
            colors.add((r // 32, g // 32, b // 32))
            total += 1
    if total == 0:
        return 1.0
    extreme = (dark + bright) / total
    variety = 1.0 - min(len(colors) / 40.0, 1.0)
    return extreme * variety


def empty_score(png_bytes: bytes) -> float:
    img = Image.open(BytesIO(png_bytes)).convert("L")
    width, height = img.size
    values: list[int] = []
    for x in range(0, width, 4):
        for y in range(0, height, 4):
            values.append(img.getpixel((x, y)))
    if not values:
        return 1.0
    mean = sum(values) / len(values)
    var = sum((value - mean) ** 2 for value in values) / len(values)
    return max(0.0, 1.0 - (var / 1800.0))


def wants_vehicle(subject: str) -> bool:
    tokens = set(subject_tokens(subject))
    for token in list(tokens):
        tokens.update(SUBJECT_ALIASES.get(token, ()))
    return bool(tokens & VEHICLE_WORDS)


def _luma_var(png_bytes: bytes, *, x0: float, x1: float, y0: float, y1: float) -> float:
    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    width, height = img.size
    values: list[float] = []
    for x in range(int(width * x0), max(int(width * x1), int(width * x0) + 1), 3):
        for y in range(int(height * y0), max(int(height * y1), int(height * y0) + 1), 3):
            r, g, b = img.getpixel((min(x, width - 1), min(y, height - 1)))
            values.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def vehicle_missing(png_bytes: bytes) -> bool:
    mid_var = _luma_var(png_bytes, x0=0.20, x1=0.80, y0=0.35, y1=0.75)
    return mid_var < VEHICLE_MID_VAR_MIN


def cabin_interior_reasons(png_bytes: bytes) -> list[str]:
    """Local cabin / windshield-from-inside / gauge check. No API."""
    img = Image.open(BytesIO(png_bytes)).convert("RGB").resize((80, 140))
    width, height = img.size
    luma: list[float] = []
    outdoor = 0
    for y in range(height):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            luma.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
            if g > r + 8 and g > b + 5:
                outdoor += 1
    total = width * height
    outdoor_frac = outdoor / total if total else 0.0
    row_means = [
        sum(luma[y * width : (y + 1) * width]) / width
        for y in range(height)
    ]
    max_drop = 0.0
    for y in range(int(height * 0.40), int(height * 0.82)):
        drop = row_means[y - 1] - row_means[y]
        if drop > max_drop:
            max_drop = drop
    lower = luma[int(height * 0.70) * width :]
    upper = luma[: int(height * 0.38) * width]
    if lower and upper:
        lower_mean = sum(lower) / len(lower)
        upper_mean = sum(upper) / len(upper)
        if max_drop >= 30 and upper_mean > lower_mean + 25:
            return ["cabin"]
    mid = luma[int(height * 0.30) * width : int(height * 0.72) * width]
    if mid and outdoor_frac < 0.01:
        mid_mean = sum(mid) / len(mid)
        dark_frac = sum(1 for value in luma if value < 32) / total
        if mid_mean > 90 and dark_frac > 0.18:
            return ["cabin"]
    return []


def opener_fail_reasons(png_bytes: bytes) -> list[str]:
    """Local full-car opener check. No API. Rejects cabin, windshield, tiny-car establishing shots."""
    reasons: list[str] = []
    if talking_head_score(png_bytes) >= TALKING_HEAD_LIMIT:
        reasons.append("talking-head")
    mid_var = _luma_var(png_bytes, x0=0.18, x1=0.82, y0=0.28, y1=0.72)
    if mid_var < OPENER_MID_VAR_MIN:
        reasons.append("weak-opener")
    reasons.extend(cabin_interior_reasons(png_bytes))
    return reasons


def ffmpeg_accurate_input(source: Path, timestamp: float) -> list[str]:
    """Coarse input seek, then accurate output seek. Avoids keyframe-skip lies."""
    ts = max(0.0, float(timestamp))
    pad = min(ts, 3.0)
    args = ["-ss", f"{ts - pad:.6f}", "-i", str(source)]
    if pad >= 0.001:
        args.extend(["-ss", f"{pad:.6f}"])
    return args


def opener_has_jump_cut(frames: list[bytes], *, threshold: float = OPENER_JUMP_MEAN_DIFF) -> bool:
    """True when consecutive opener frames look like different shots."""
    if len(frames) < 3:
        return False
    prev = Image.open(BytesIO(frames[0])).convert("RGB").resize((48, 48))
    prev_bytes = prev.tobytes()
    n = len(prev_bytes)
    if n == 0:
        return False
    for raw in frames[1:]:
        img = Image.open(BytesIO(raw)).convert("RGB").resize((48, 48))
        data = img.tobytes()
        diff = sum(abs(a - b) for a, b in zip(prev_bytes, data)) / n
        if diff >= threshold:
            return True
        prev_bytes = data
    return False


def frame_fail_reasons(png_bytes: bytes, subject: str = "") -> list[str]:
    reasons: list[str] = []
    if talking_head_score(png_bytes) >= TALKING_HEAD_LIMIT:
        reasons.append("talking-head")
    if title_card_score(png_bytes) >= TITLE_CARD_LIMIT:
        reasons.append("title-card")
    if empty_score(png_bytes) >= EMPTY_LIMIT:
        reasons.append("empty")
    if wants_vehicle(subject) and vehicle_missing(png_bytes):
        reasons.append("missing-subject")
    if wants_vehicle(subject):
        reasons.extend(cabin_interior_reasons(png_bytes))
    return reasons


def extract_preview_frame(source: Path, timestamp: float) -> bytes | None:
    ffmpeg = "ffmpeg"
    try:
        from toolchain_env import resolve_tool

        ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
    except Exception:
        pass
    cmd = [
        ffmpeg,
        "-y",
        *ffmpeg_accurate_input(source, timestamp),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError:
        return None
    return result.stdout or None


def sample_timestamps(duration: float, start: float, length: float, *, count: int = 5) -> list[float]:
    if duration <= 0 or length <= 0:
        return [max(start, 0.0)]
    end = min(start + length, duration) - 0.12
    begin = min(max(start + 0.35, 0.0), max(end, 0.0))
    if end <= begin + 0.05:
        return [begin]
    if count <= 1:
        return [begin]
    span = end - begin
    return [begin + span * (index / (count - 1)) for index in range(count)]


def window_report(
    frames: list[bytes],
    *,
    strict: bool = False,
    subject: str = "",
) -> dict[str, object]:
    if not frames:
        return {"ok": False, "pass_ratio": 0.0, "reasons": ["no-frames"]}
    failed = 0
    reasons: list[str] = []
    for frame in frames:
        frame_reasons = frame_fail_reasons(frame, subject)
        if frame_reasons:
            failed += 1
            reasons.extend(frame_reasons)
        elif strict and talking_head_score(frame) >= TALKING_HEAD_LIMIT * 0.7:
            failed += 1
            reasons.append("talking-head")
    ratio = (len(frames) - failed) / len(frames)
    first_bad = bool(frames) and bool(frame_fail_reasons(frames[0], subject))
    needed = 1.0 if strict else PASS_RATIO
    ok = ratio >= needed and not first_bad
    return {
        "ok": ok,
        "pass_ratio": ratio,
        "reasons": sorted(set(reasons)),
        "first_bad": first_bad,
    }


def _load_env_files() -> None:
    roots = (
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    )
    for path in roots:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def vision_prompt(subject: str, *, opener: bool = False) -> str:
    """Ask vision whether the subject is in frame. Opener is stricter for cars."""
    subject = subject.strip()
    if opener and wants_vehicle(subject):
        return (
            f'Intended subject: "{subject}". Reply with JSON only, no extra text: '
            '{"object":"2-4 word main object","view":"front|three_quarter|side|rear|cabin|other",'
            '"full_exterior":true_or_false}. '
            "full_exterior is true ONLY if a car is seen from outside and most of the body "
            "is visible from the front, three-quarter, or side. "
            "full_exterior is false for rear-only, taillights, cabin, dashboard, "
            "a wheel close-up, a person standing in frame, a house/mansion tour, "
            "a title card, coffee, or anything that is not a car as the main object. "
            "If a person is the center of the shot, full_exterior is false even if a car is nearby."
        )
    extra = ""
    if wants_vehicle(subject):
        extra = (
            " For a vehicle, answer NO if there is no car, only a cabin/dashboard, "
            "or the frame is a person talking."
        )
    return (
        f'Does this frame clearly show this subject: "{subject}"? '
        "Answer YES only if the subject is visible as the main object. "
        "Answer NO if it is a person talking, a title card, a logo, "
        "an empty room, a different object, or anything out of context "
        f"for that subject.{extra}"
    )


def parse_opener_verdict(raw: str) -> bool | None:
    """Parse opener JSON. True only for a full front/side/3-4 exterior car."""
    text = (raw or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        upper = text.upper()
        if upper.startswith("YES"):
            return True
        if upper.startswith("NO"):
            return False
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    obj = str(payload.get("object") or "").lower()
    view = str(payload.get("view") or "").lower().replace("-", "_")
    full = payload.get("full_exterior")
    if any(token in obj for token in NON_CAR_OBJECTS):
        return False
    if view in {"rear", "cabin", "other"}:
        return False
    if view not in OPENER_VIEWS:
        return False
    if full is False or str(full).lower() in {"false", "0", "no"}:
        return False
    if full is True or str(full).lower() in {"true", "1", "yes"}:
        if any(word in obj for word in VEHICLE_WORDS) or "car" in obj:
            return True
        return False
    return None


def vision_subject_present(
    png_bytes: bytes,
    subject: str,
    *,
    opener: bool = False,
) -> bool | None:
    """Return True/False when a vision key exists, else None."""
    if not subject.strip() or not png_bytes:
        return None
    _load_env_files()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    payload = base64.b64encode(png_bytes).decode("ascii")
    client = OpenAI(api_key=api_key)
    prompt = vision_prompt(subject, opener=opener)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=80 if opener else 4,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{payload}"},
                    },
                ],
            }
        ],
    )
    answer = (response.choices[0].message.content or "").strip()
    if opener and wants_vehicle(subject):
        return parse_opener_verdict(answer)
    upper = answer.upper()
    if upper.startswith("YES"):
        return True
    if upper.startswith("NO"):
        return False
    return None


def sample_clip_stamps(duration: float, *, step: float = SCAN_STEP) -> list[float]:
    if duration <= 0:
        return [0.0]
    stamps: list[float] = []
    stamp = min(0.25, max(duration * 0.15, 0.0))
    while stamp < duration - 0.08:
        stamps.append(stamp)
        stamp += max(step, 0.25)
    if not stamps:
        stamps.append(min(0.25, max(duration * 0.5, 0.0)))
    return stamps


def scan_clip_local(
    source: Path,
    *,
    duration: float,
    step: float = SCAN_STEP,
    subject: str = "",
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for stamp in sample_clip_stamps(duration, step=step):
        frame = extract_preview_frame(source, stamp)
        if not frame:
            samples.append({"t": stamp, "ok": False, "reasons": ["no-frames"]})
            continue
        reasons = frame_fail_reasons(frame, subject)
        samples.append({"t": stamp, "ok": not reasons, "reasons": reasons})
    return samples


def clean_spans(
    samples: list[dict[str, object]],
    *,
    min_length: float = MIN_CLEAN_SPAN,
) -> list[tuple[float, float]]:
    if not samples:
        return []
    step = SCAN_STEP
    if len(samples) >= 2:
        step = max(float(samples[1]["t"]) - float(samples[0]["t"]), 0.25)
    spans: list[tuple[float, float]] = []
    start: float | None = None
    last_ok: float | None = None
    for sample in samples:
        stamp = float(sample["t"])
        if sample["ok"]:
            if start is None:
                start = stamp
            last_ok = stamp
            continue
        if start is None or last_ok is None:
            continue
        end = last_ok + step
        if end - start >= min_length:
            spans.append((start, end))
        start = None
        last_ok = None
    if start is not None and last_ok is not None:
        end = last_ok + step
        if end - start >= min_length:
            spans.append((start, end))
    return spans


def longest_clean_span(
    samples: list[dict[str, object]],
    *,
    min_length: float = MIN_CLEAN_SPAN,
) -> tuple[float, float] | None:
    spans = clean_spans(samples, min_length=min_length)
    if not spans:
        return None
    return max(spans, key=lambda item: item[1] - item[0])


def confirm_span_subject(
    source: Path,
    *,
    start: float,
    end: float,
    subject: str,
) -> bool:
    if not subject.strip():
        return True
    mid = start + max((end - start) * 0.5, 0.0)
    for stamp in (start + 0.2, mid):
        stamp = min(max(stamp, start), max(end - 0.05, start))
        frame = extract_preview_frame(source, stamp)
        if not frame:
            continue
        present = vision_subject_present(frame, subject)
        if present is False:
            return False
    return True


def score_window(
    source: Path,
    *,
    start: float,
    duration: float,
    clip_duration: float,
    subject: str = "",
    strict: bool = False,
    use_vision: bool = False,
    opener: bool = False,
) -> dict[str, object]:
    frames: list[bytes] = []
    for stamp in sample_timestamps(clip_duration, start, duration):
        frame = extract_preview_frame(source, stamp)
        if frame:
            frames.append(frame)
    report = window_report(frames, strict=strict, subject=subject)
    if opener and wants_vehicle(subject) and frames:
        opener_reasons: list[str] = []
        for frame in frames:
            opener_reasons.extend(opener_fail_reasons(frame))
        if opener_has_jump_cut(frames):
            opener_reasons.append("opener-jump")
        if opener_reasons:
            report["ok"] = False
            report["reasons"] = sorted(set(list(report["reasons"]) + opener_reasons))
            return report
    if not report["ok"] or not use_vision or not subject or not frames:
        return report
    if opener and wants_vehicle(subject):
        present = vision_subject_present(frames[0], subject, opener=True)
        if present is False:
            report["ok"] = False
            reasons = list(report["reasons"])
            reasons.append("weak-opener")
            report["reasons"] = reasons
        return report
    checked = 0
    for frame in (frames[0], frames[len(frames) // 2]):
        if checked >= 2:
            break
        present = vision_subject_present(frame, subject)
        checked += 1
        if present is False:
            report["ok"] = False
            reasons = list(report["reasons"])
            reasons.append("missing-subject")
            report["reasons"] = reasons
            return report
    return report
