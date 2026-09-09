"""Mock ASR for tests — no external API calls."""

from __future__ import annotations

from pathlib import Path

from discovery.transcription.base import TranscriptSegment, TranscriptionResult


class MockTranscriptionProvider:
    provider_name = "mock"
    model_name = "mock-asr-v1"

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        name = Path(audio_path).stem
        text = f"Mock transcript for {name}. Discipline beats motivation every single day."
        segments = [
            TranscriptSegment(text="Mock transcript for", start=0.0, end=1.2, confidence=0.95),
            TranscriptSegment(
                text="Discipline beats motivation every single day.",
                start=1.2,
                end=4.5,
                confidence=0.92,
            ),
        ]
        return TranscriptionResult(
            text=text,
            segments=segments,
            provider=self.provider_name,
            model=self.model_name,
            language="en",
        )
