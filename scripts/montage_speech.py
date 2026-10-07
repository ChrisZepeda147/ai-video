"""Post-prepare speech validation for Weekly / montage jobs."""

from __future__ import annotations

import re
from pathlib import Path

SENTENCE_END = re.compile(r'[.!?]["\']?\s*$')
TRUNCATED_ELLIPSIS = re.compile(r"\.\.\.\s*$")


class PreparedSpeechRejected(Exception):
    def __init__(self, *, source: str, duration: float, reason: str) -> None:
        self.source = source
        self.duration = duration
        self.reason = reason
        super().__init__(f"Speech rejected ({reason}): {source} {duration:.1f}s")


def log_montage_speech_ok(*, requested_speaker: str, duration: float) -> None:
    print(
        f'MONTAGE_SPEECH requested_speaker="{requested_speaker}" '
        f"duration={duration:.1f} status=ok"
    )


def log_montage_speech_reject(*, source: str, duration: float, reason: str) -> None:
    print(
        f"MONTAGE_SPEECH_REJECT source={source} duration={duration:.1f} reason={reason}"
    )


def excerpt_looks_incomplete(excerpt: str) -> bool:
    text = (excerpt or "").strip()
    if len(text) < 12:
        return True
    if TRUNCATED_ELLIPSIS.search(text):
        return True
    return not bool(SENTENCE_END.search(text))


def validate_prepared_speech_file(
    *,
    speech_mp3: Path,
    requested_speaker: str,
    source_video_id: str,
    excerpt: str,
    min_seconds: float,
    probe_duration_fn,
) -> float:
    source = source_video_id or "unknown"
    if not speech_mp3.is_file():
        log_montage_speech_reject(source=source, duration=0.0, reason="missing_audio")
        raise PreparedSpeechRejected(source=source, duration=0.0, reason="missing_audio")
    try:
        size = speech_mp3.stat().st_size
    except OSError:
        size = 0
    if size < 500:
        log_montage_speech_reject(source=source, duration=0.0, reason="broken_audio")
        raise PreparedSpeechRejected(source=source, duration=0.0, reason="broken_audio")
    try:
        duration = float(probe_duration_fn(speech_mp3))
    except (OSError, ValueError, TypeError):
        log_montage_speech_reject(source=source, duration=0.0, reason="broken_audio")
        raise PreparedSpeechRejected(source=source, duration=0.0, reason="broken_audio")
    if duration < float(min_seconds):
        log_montage_speech_reject(source=source, duration=duration, reason="too_short")
        raise PreparedSpeechRejected(source=source, duration=duration, reason="too_short")
    if excerpt_looks_incomplete(excerpt):
        log_montage_speech_reject(source=source, duration=duration, reason="incoherent_excerpt")
        raise PreparedSpeechRejected(
            source=source, duration=duration, reason="incoherent_excerpt"
        )
    log_montage_speech_ok(requested_speaker=requested_speaker, duration=duration)
    return duration
