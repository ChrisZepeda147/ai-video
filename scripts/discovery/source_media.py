"""Source media workflow — separate from reference metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from discovery.models import SourceMedia, SourceSegment
from discovery.reuse_detection import check_global_reuse, transcript_hash
from discovery.risk_scoring import risk_explanations_json, score_source_media


ALLOWED_SOURCE_MODES = {"topic", "audio", "video", "original"}
ALLOWED_MEDIA_TYPES = {"topic", "audio", "video", "original"}


@dataclass
class CreateSourceResult:
    source: SourceMedia
    reuse_report: dict[str, Any]
    risk_scores: dict[str, Any]


def create_source_media(
    store,
    *,
    title: str,
    source_mode: str,
    media_type: str | None = None,
    reference_id: int | None = None,
    platform: str | None = None,
    external_id: str | None = None,
    url: str | None = None,
    local_path: str | None = None,
    transcript: str | None = None,
    duration_sec: float | None = None,
    mark_used: bool = False,
) -> CreateSourceResult:
    if source_mode not in ALLOWED_SOURCE_MODES:
        raise ValueError(f"Invalid source_mode: {source_mode}")
    resolved_type = media_type or source_mode
    if resolved_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError(f"Invalid media_type: {resolved_type}")

    if reference_id is not None:
        ref = store.get_reference_by_id(reference_id)
        if not ref:
            raise ValueError(f"Reference {reference_id} not found")
        platform = platform or ref.platform
        external_id = external_id or ref.external_id
        url = url or ref.url
        title = title or ref.title
        duration_sec = duration_sec or ref.duration_sec
        if not transcript and ref.description:
            transcript = ref.description[:2000]

    reuse = check_global_reuse(
        store,
        platform=platform,
        external_id=external_id,
        transcript=transcript,
        local_audio_path=local_path if resolved_type == "audio" else None,
        reference_id=reference_id,
    )
    risk = score_source_media(
        source_mode=source_mode,
        media_type=resolved_type,
        platform=platform,
        has_transcript=bool(transcript),
        reuse_report=reuse,
        is_original=source_mode == "original",
    )

    source_id = store.create_source_media(
        title=title,
        source_mode=source_mode,
        media_type=resolved_type,
        reference_id=reference_id,
        platform=platform,
        external_id=external_id,
        url=url,
        local_path=local_path,
        transcript=transcript,
        transcript_hash=transcript_hash(transcript or ""),
        duration_sec=duration_sec,
        rights_confidence=risk.rights_confidence,
        monetization_confidence=risk.monetization_confidence,
        reuse_confidence=reuse.reuse_confidence,
        seen_as_reference=reuse.seen_as_reference or reference_id is not None,
        actually_used_in_content=mark_used or reuse.actually_used_in_content,
        reuse_explanations_json=json.dumps(reuse.to_dict()),
        risk_explanations_json=risk_explanations_json(risk),
    )
    source = store.get_source_media(source_id)
    if not source:
        raise RuntimeError("Failed to load created source media")
    return CreateSourceResult(
        source=source,
        reuse_report=reuse.to_dict(),
        risk_scores=risk.to_dict(),
    )


def add_source_segment(
    store,
    source_media_id: int,
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
    transcript: str | None = None,
    local_path: str | None = None,
) -> SourceSegment:
    source = store.get_source_media(source_media_id)
    if not source:
        raise ValueError(f"Source media {source_media_id} not found")
    segment_id = store.create_source_segment(
        source_media_id=source_media_id,
        start_sec=start_sec,
        end_sec=end_sec,
        transcript=transcript,
        local_path=local_path,
        rights_confidence=source.rights_confidence,
        monetization_confidence=source.monetization_confidence,
        reuse_confidence=source.reuse_confidence,
    )
    segment = store.get_source_segment(segment_id)
    if not segment:
        raise RuntimeError("Failed to load created segment")
    return segment


def transcribe_source_media_with_asr(store, source_media_id: int, *, provider=None) -> SourceMedia:
    """Run ASR provider on local audio/video and store timestamped transcript."""
    from discovery.reuse_detection import audio_fingerprint, chromaprint_fingerprint
    from discovery.transcription.factory import build_transcription_provider

    source = store.get_source_media(source_media_id)
    if not source:
        raise ValueError(f"Source media {source_media_id} not found")
    audio_path = source.local_path or source.download_path
    if not audio_path:
        raise ValueError("Source must be acquired before transcription")

    asr = provider or build_transcription_provider()
    result = asr.transcribe(audio_path)
    return _persist_transcription(store, source_media_id, source, result.text, result.to_dict(), audio_path)


def transcribe_source_media(store, source_media_id: int, *, transcript: str | None = None) -> SourceMedia:
    """Store transcript text. Uses ASR when no transcript supplied and file exists."""
    source = store.get_source_media(source_media_id)
    if not source:
        raise ValueError(f"Source media {source_media_id} not found")

    if not transcript and (source.local_path or source.download_path):
        try:
            return transcribe_source_media_with_asr(store, source_media_id)
        except (ValueError, RuntimeError):
            pass

    text = transcript
    if not text and source.reference_id:
        ref = store.get_reference_by_id(source.reference_id)
        if ref and ref.description:
            text = ref.description[:4000]
    if not text:
        text = f"[transcript pending for {source.title}]"
    return _persist_transcription(store, source_media_id, source, text, None, source.local_path)


def _persist_transcription(
    store,
    source_media_id: int,
    source: SourceMedia,
    text: str,
    transcript_json: dict | None,
    audio_path: str | None,
) -> SourceMedia:
    from discovery.reuse_detection import audio_fingerprint, chromaprint_fingerprint

    reuse = check_global_reuse(
        store,
        platform=source.platform,
        external_id=source.external_id,
        transcript=text,
        local_audio_path=source.local_path if source.media_type == "audio" else None,
        reference_id=source.reference_id,
    )
    risk = score_source_media(
        source_mode=source.source_mode,
        media_type=source.media_type,
        platform=source.platform,
        has_transcript=True,
        reuse_report=reuse,
        is_original=source.source_mode == "original",
    )
    fp = chromaprint_fingerprint(audio_path) or audio_fingerprint(audio_path)
    store.update_source_media_transcript(
        source_media_id,
        transcript=text,
        transcript_json=json.dumps(transcript_json) if transcript_json else None,
        transcript_hash=transcript_hash(text),
        audio_fingerprint=fp or None,
        reuse_confidence=reuse.reuse_confidence,
        rights_confidence=risk.rights_confidence,
        monetization_confidence=risk.monetization_confidence,
        reuse_explanations_json=json.dumps(reuse.to_dict()),
        risk_explanations_json=risk_explanations_json(risk),
    )
    updated = store.get_source_media(source_media_id)
    if not updated:
        raise RuntimeError("Failed to reload source media")
    return updated


def create_source_from_reference(
    store,
    reference_id: int,
    source_mode: str,
) -> CreateSourceResult:
    return create_source_media(
        store,
        title="",
        source_mode=source_mode,
        reference_id=reference_id,
    )
