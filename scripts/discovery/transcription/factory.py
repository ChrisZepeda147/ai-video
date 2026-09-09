"""Build transcription provider from environment."""

from __future__ import annotations

import os

from discovery.transcription.base import TranscriptionProvider
from discovery.transcription.mock import MockTranscriptionProvider
from discovery.transcription.whisper_local import WhisperLocalProvider, whisper_available


def build_transcription_provider(*, provider: str = "auto") -> TranscriptionProvider:
    if provider == "auto":
        provider = os.environ.get("DISCOVERY_ASR_PROVIDER", "auto").strip() or "auto"
    if provider == "auto":
        if whisper_available():
            return WhisperLocalProvider()
        provider = "mock"
    if provider == "mock":
        return MockTranscriptionProvider()
    if provider == "whisper":
        if not whisper_available():
            raise ValueError("Whisper ASR requested but openai-whisper is not installed")
        return WhisperLocalProvider()
    raise ValueError(f"Unknown ASR provider: {provider}")
