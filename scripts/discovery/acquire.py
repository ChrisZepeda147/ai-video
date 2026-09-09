"""Acquire source media using the existing youtube_popular_downloader — no duplicate downloader."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discovery.config import source_media_dir

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _ypd():
    import youtube_popular_downloader as ypd  # noqa: E402

    return ypd


@dataclass
class AcquireResult:
    source_media_id: int
    download_path: str
    raw_path: str | None
    status: str
    error: str | None = None


def _source_output_dir(source_media_id: int) -> Path:
    path = source_media_dir() / f"source_{source_media_id:06d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _candidate_from_source(source):
    ypd = _ypd()
    if not source.url or not source.external_id:
        raise ValueError("Source media requires url and external_id for acquisition")
    return ypd.VideoCandidate(
        video_id=source.external_id,
        title=source.title,
        url=source.url,
        channel="unknown",
        view_count=None,
        duration_seconds=source.duration_sec,
        published_at=None,
        source="source_media_acquire",
    )


def acquire_source_media(store, source_media_id: int) -> AcquireResult:
    """Download source file via existing downloader. Does NOT register content as used."""
    source = store.get_source_media(source_media_id)
    if not source:
        raise ValueError(f"Source media {source_media_id} not found")
    if not source.url:
        raise ValueError("Source media has no URL to acquire")

    store.update_source_media_download(source_media_id, status="downloading")
    output_dir = _source_output_dir(source_media_id)
    audio_only = source.media_type == "audio" or source.source_mode == "audio"

    try:
        ypd = _ypd()
        results = ypd.download_videos(
            [_candidate_from_source(source)],
            output_dir=output_dir,
            max_height=1080,
            audio_only=audio_only,
            clip_length=120,
            max_parts=1,
            split_parts=False,
            keep_source=True,
            aspect_ratio="9:16" if not audio_only else "original",
        )
        record = results[0] if results else {}
        if record.get("status") != "ok":
            err = record.get("error") or "download failed"
            store.update_source_media_download(source_media_id, status="failed", error_message=err)
            return AcquireResult(source_media_id, "", None, "failed", err)

        raw_path = record.get("source_file")
        file_path = record.get("file_path") or raw_path
        if not file_path:
            store.update_source_media_download(source_media_id, status="failed", error_message="no output file")
            raise RuntimeError("Downloader returned no file path")

        store.update_source_media_download(
            source_media_id,
            status="acquired",
            download_path=str(file_path),
            raw_local_path=str(raw_path) if raw_path else str(file_path),
            local_path=str(file_path),
        )
        return AcquireResult(
            source_media_id=source_media_id,
            download_path=str(file_path),
            raw_path=str(raw_path) if raw_path else None,
            status="acquired",
        )
    except Exception as exc:
        store.update_source_media_download(source_media_id, status="failed", error_message=str(exc))
        raise


def extract_audio_segment(
    source_path: Path,
    output_path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> None:
    duration = max(0.1, end_sec - start_sec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        str(source_path),
        "-t",
        str(duration),
        "-vn",
        "-acodec",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def clip_source_segment(
    store,
    source_media_id: int,
    *,
    start_sec: float,
    end_sec: float,
    segment_id: int | None = None,
) -> dict[str, Any]:
    """Cut selected segment from acquired source using existing FFmpeg helpers."""
    source = store.get_source_media(source_media_id)
    if not source:
        raise ValueError(f"Source media {source_media_id} not found")
    raw = source.raw_local_path or source.download_path or source.local_path
    if not raw or not Path(raw).is_file():
        raise ValueError("Source must be acquired before clipping")

    out_dir = _source_output_dir(source_media_id) / "segments"
    out_dir.mkdir(parents=True, exist_ok=True)
    is_audio = source.media_type == "audio" or source.source_mode == "audio"
    ext = "m4a" if is_audio else "mp4"
    out_path = out_dir / f"segment_{int(start_sec)}_{int(end_sec)}.{ext}"

    if is_audio:
        extract_audio_segment(Path(raw), out_path, start_sec=start_sec, end_sec=end_sec)
    else:
        _ypd().export_clip(
            Path(raw),
            out_path,
            start=start_sec,
            duration=max(0.1, end_sec - start_sec),
            aspect_ratio="9:16",
            max_height=1920,
        )

    if segment_id:
        store.update_source_segment_clip(segment_id, local_path=str(out_path), clip_status="clipped")
    else:
        segment_id = store.create_source_segment(
            source_media_id=source_media_id,
            start_sec=start_sec,
            end_sec=end_sec,
            transcript=None,
            local_path=str(out_path),
            rights_confidence=source.rights_confidence,
            monetization_confidence=source.monetization_confidence,
            reuse_confidence=source.reuse_confidence,
            clip_status="clipped",
        )

    return {
        "segment_id": segment_id,
        "local_path": str(out_path),
        "start_sec": start_sec,
        "end_sec": end_sec,
    }
