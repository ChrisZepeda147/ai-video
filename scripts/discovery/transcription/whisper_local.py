"""Local Whisper ASR — uses openai-whisper when installed."""

from __future__ import annotations

import os
from pathlib import Path

from discovery.transcription.base import TranscriptSegment, TranscriptWord, TranscriptionResult


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401

        return True
    except ImportError:
        return False


class WhisperLocalProvider:
    provider_name = "whisper"
    model_name: str | None = None

    def __init__(self, *, model: str | None = None) -> None:
        self.model_name = model or os.environ.get("DISCOVERY_WHISPER_MODEL", "base")

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        import whisper

        if not Path(audio_path).is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        model = whisper.load_model(self.model_name)
        raw = model.transcribe(audio_path, word_timestamps=True)
        segments: list[TranscriptSegment] = []
        for seg in raw.get("segments") or []:
            words: list[TranscriptWord] = []
            for word in seg.get("words") or []:
                words.append(
                    TranscriptWord(
                        word=str(word.get("word", "")).strip(),
                        start=float(word.get("start", 0)),
                        end=float(word.get("end", 0)),
                        confidence=float(word.get("probability"))
                        if word.get("probability") is not None
                        else None,
                    )
                )
            segments.append(
                TranscriptSegment(
                    text=str(seg.get("text", "")).strip(),
                    start=float(seg.get("start", 0)),
                    end=float(seg.get("end", 0)),
                    confidence=None,
                    words=words,
                )
            )
        text = str(raw.get("text") or "").strip()
        if not text and segments:
            text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            text=text,
            segments=segments,
            provider=self.provider_name,
            model=self.model_name,
            language=raw.get("language"),
        )
