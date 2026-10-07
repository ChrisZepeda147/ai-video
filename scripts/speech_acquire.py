"""Speech candidate validation, pacing, and failure accounting for prepare_speech."""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SHORT_FORM_RE = re.compile(
    r"\b(shorts?|#short|1 minute motivation|motivational compilation|best of|epic motivational)\b",
    re.I,
)
LONG_FORM_RE = re.compile(
    r"\b(speech|interview|podcast|talk|keynote|conversation|jocko podcast|echelon front)\b",
    re.I,
)

# ~32 kbps MP3 floor
MIN_BYTES_PER_SECOND = 3_500
ABS_MIN_AUDIO_BYTES = 8_000


@dataclass
class SpeechAcquireStats:
    speaker: str = ""
    primary_count: int = 0
    fallback_count: int = 0
    candidates_attempted: int = 0
    download_403: int = 0
    download_invalid: int = 0
    audio_too_short: int = 0
    subtitle_429: int = 0
    subtitle_missing: int = 0
    no_coherent_window: int = 0
    speaker_mismatch: int = 0
    mid_thought_window: int = 0
    reuse_skip: int = 0
    attempts: list[dict[str, object]] = field(default_factory=list)

    def record(self, video_id: str, *, status: str, reason: str, **extra: object) -> None:
        row: dict[str, object] = {"id": video_id, "status": status, "reason": reason, **extra}
        self.attempts.append(row)
        key = reason
        if key == "download_403":
            self.download_403 += 1
        elif key in {"download_invalid", "incomplete_download", "ffprobe_failed"}:
            self.download_invalid += 1
        elif key == "audio_too_short":
            self.audio_too_short += 1
        elif key == "subtitle_429":
            self.subtitle_429 += 1
        elif key == "subtitle_missing":
            self.subtitle_missing += 1
        elif key in {"no_coherent_window", "window_error"}:
            self.no_coherent_window += 1
        elif key == "speaker_mismatch":
            self.speaker_mismatch += 1
        elif key == "mid_thought_window":
            self.mid_thought_window += 1

    def failure_summary(self) -> str:
        n = self.candidates_attempted
        sp = self.speaker or "speaker"
        return (
            f"Unable to produce a valid 30–90s {sp} speech after {n} unique candidate(s)."
        )

    def failure_details(self) -> dict[str, object]:
        return {
            "speaker": self.speaker,
            "candidates_attempted": self.candidates_attempted,
            "primary_candidates": self.primary_count,
            "fallback_candidates": self.fallback_count,
            "download_403": self.download_403,
            "invalid_audio": self.download_invalid,
            "too_short": self.audio_too_short,
            "subtitle_429": self.subtitle_429,
            "subtitle_missing": self.subtitle_missing,
            "no_coherent_window": self.no_coherent_window,
            "mid_thought_window": self.mid_thought_window,
            "speaker_mismatch": self.speaker_mismatch,
        }


class SpeechPrepareFailed(Exception):
    def __init__(self, stats: SpeechAcquireStats, code: str = "SPEECH_DOWNLOAD_FAILED"):
        self.stats = stats
        self.code = code
        super().__init__(stats.failure_summary())


def log_candidate_reject(video_id: str, reason: str, **kwargs: object) -> None:
    parts = [f"SPEECH_CANDIDATE_REJECT id={video_id} reason={reason}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    print(" ".join(str(p) for p in parts))


def log_candidate_result(video_id: str, status: str, reason: str, **kwargs: object) -> None:
    parts = [f"SPEECH_CANDIDATE_RESULT id={video_id} status={status} reason={reason}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    print(" ".join(str(p) for p in parts))


def candidate_delay(*, after_429: int = 0, normal: bool = True) -> None:
    if after_429 > 0:
        wait = min(20.0, 5.0 * (2 ** min(after_429 - 1, 2)))
        print(f"  speech backoff {wait:.0f}s after subtitle 429")
        time.sleep(wait)
    elif normal:
        time.sleep(random.uniform(1.0, 3.0))


@dataclass
class AudioProbe:
    ok: bool
    duration: float
    bytes: int
    reason: str = ""


def validate_downloaded_audio(
    path: Path,
    *,
    min_seconds: float,
    probe_duration_fn: Callable[[Path], float],
) -> AudioProbe:
    try:
        size = path.stat().st_size
    except OSError:
        log_candidate_reject("", reason="incomplete_download", bytes=0)
        return AudioProbe(ok=False, duration=0.0, bytes=0, reason="incomplete_download")
    min_bytes = max(ABS_MIN_AUDIO_BYTES, int(min_seconds * MIN_BYTES_PER_SECOND))
    if size < min_bytes:
        log_candidate_reject(
            path.stem[:11],
            reason="incomplete_download",
            bytes=size,
        )
        return AudioProbe(ok=False, duration=0.0, bytes=size, reason="incomplete_download")
    try:
        duration = float(probe_duration_fn(path))
    except (OSError, ValueError, TypeError):
        log_candidate_reject(path.stem[:11], reason="ffprobe_failed", bytes=size)
        return AudioProbe(ok=False, duration=0.0, bytes=size, reason="ffprobe_failed")
    if duration < float(min_seconds) - 0.15:
        log_candidate_reject(
            path.stem[:11],
            reason="audio_too_short",
            duration=f"{duration:.1f}",
            bytes=size,
        )
        return AudioProbe(ok=False, duration=duration, bytes=size, reason="audio_too_short")
    if duration > 0 and size / duration < MIN_BYTES_PER_SECOND * 0.5:
        log_candidate_reject(
            path.stem[:11],
            reason="incomplete_download",
            duration=f"{duration:.1f}",
            bytes=size,
        )
        return AudioProbe(ok=False, duration=duration, bytes=size, reason="incomplete_download")
    return AudioProbe(ok=True, duration=duration, bytes=size, reason="")


def find_candidate_audio(audio_dir: Path, video_id: str) -> Path | None:
    matches = sorted(audio_dir.glob(f"{video_id}*.mp3"))
    if matches:
        return matches[-1]
    all_mp3 = sorted(audio_dir.glob("*.mp3"))
    for path in all_mp3:
        if path.name.startswith(video_id):
            return path
    return all_mp3[-1] if len(all_mp3) == 1 else None


def speech_search_queries(speaker: str, speech_query: str) -> tuple[str, str]:
    base = (speech_query or f"{speaker} motivational speech").strip()
    primary = base
    tokens = [t for t in re.split(r"[^a-z0-9]+", speaker.lower()) if t]
    lead = tokens[0] if tokens else speaker
    fallback = f"{lead} interview speech motivation discipline talk"
    if "interview" not in base.lower() and "podcast" not in base.lower():
        primary = f"{lead} interview motivational speech"
    return primary, fallback


def rank_speech_candidate(item) -> tuple[int, int, int]:
    """Higher is better: (score, duration_bucket, views)."""
    title = (getattr(item, "title", "") or "").lower()
    duration = int(getattr(item, "duration_seconds", 0) or 0)
    views = int(getattr(item, "view_count", 0) or 0)
    score = 0
    if SHORT_FORM_RE.search(title):
        score -= 4
    if LONG_FORM_RE.search(title):
        score += 3
    if duration >= 180:
        score += 2
    elif duration >= 90:
        score += 1
    elif 0 < duration < 45:
        score -= 3
    return (score, duration, views)


def load_failed_source_ids(job_dir: Path) -> set[str]:
    path = job_dir / "speech_acquire.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data.get("failed_source_ids") or []
        return {str(x) for x in ids}
    except (OSError, json.JSONDecodeError):
        return set()


def record_failed_source_id(job_dir: Path, video_id: str, *, reason: str) -> None:
    if not video_id:
        return
    path = job_dir / "speech_acquire.json"
    payload: dict[str, object] = {"failed_source_ids": [], "reasons": {}}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"failed_source_ids": [], "reasons": {}}
    ids = set(str(x) for x in (payload.get("failed_source_ids") or []))
    ids.add(video_id)
    reasons = dict(payload.get("reasons") or {})
    reasons[video_id] = reason
    payload["failed_source_ids"] = sorted(ids)
    payload["reasons"] = reasons
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
