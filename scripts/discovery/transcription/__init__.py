"""Transcription providers."""

from discovery.transcription.base import TranscriptionResult, TranscriptSegment
from discovery.transcription.factory import build_transcription_provider

__all__ = ["TranscriptionResult", "TranscriptSegment", "build_transcription_provider"]
