"""ASR provider interface — not locked to one vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TranscriptWord:
    word: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class TranscriptSegment:
    text: str
    start: float
    end: float
    confidence: float | None = None
    words: list[TranscriptWord] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    text: str
    segments: list[TranscriptSegment]
    provider: str
    model: str | None = None
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "segments": [
                {
                    "text": s.text,
                    "start": s.start,
                    "end": s.end,
                    "confidence": s.confidence,
                    "words": [
                        {
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "confidence": w.confidence,
                        }
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }


class TranscriptionProvider(Protocol):
    provider_name: str
    model_name: str | None

    def transcribe(self, audio_path: str) -> TranscriptionResult: ...
