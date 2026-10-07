"""Speech speaker request vs media validation."""

from __future__ import annotations

from discovery.speaker_identity import infer_speaker
from youtube_popular_downloader import VideoCandidate


class SpeechSpeakerMismatchError(Exception):
    def __init__(self, requested: str, media: str, video_id: str) -> None:
        self.requested = requested
        self.media = media
        self.video_id = video_id
        super().__init__(
            f"Speech speaker mismatch: requested {requested!r}, "
            f"media indicates {media!r} (video {video_id})"
        )


def log_montage_speaker(*, requested: str, resolved: str, source_video_id: str) -> None:
    """Legacy line — prefer log_montage_speech_ok after speech.mp3 probe."""
    print(
        f'MONTAGE_SPEAKER requested="{requested}" '
        f'resolved="{resolved}" source_video_id={source_video_id}'
    )


def media_speaker(candidate: VideoCandidate, excerpt: str = "") -> str | None:
    return infer_speaker(candidate.title, candidate.channel, excerpt)


def enforce_requested_speaker(
    *,
    requested: str,
    candidate: VideoCandidate,
    excerpt: str = "",
    title_match_fn,
) -> str:
    """Return resolved speaker label; raise if media clearly conflicts with request."""
    requested_clean = (requested or "").strip()
    media = media_speaker(candidate, excerpt)
    resolved = media or requested_clean or "Unknown"
    if requested_clean and media and media.lower() != requested_clean.lower():
        if not title_match_fn(candidate, requested_clean):
            raise SpeechSpeakerMismatchError(requested_clean, media, candidate.video_id)
        resolved = requested_clean
    elif requested_clean:
        resolved = requested_clean
    return resolved
