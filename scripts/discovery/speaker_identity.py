"""Speaker detection, correction memory, and registration resolution."""

from __future__ import annotations

import json
from typing import Any

from discovery.production_library import get_video, now_iso

# Canonical speakers — order longer / more specific hints first within each entry.
KNOWN_SPEAKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("David Goggins", ("david goggins", " goggins")),
    ("Jocko Willink", ("jocko willink", "jocko", "willink")),
    ("Andrew Tate", ("andrew tate", " tate", "top g")),
    ("Alex Hormozi", ("alex hormozi", "hormozi")),
    ("Jordan Peterson", ("jordan peterson", " peterson")),
    ("Joe Rogan", ("joe rogan", " rogan", "jre")),
    ("Eric Thomas", ("eric thomas", "et the hip hop preacher")),
    ("Les Brown", ("les brown",)),
    ("Jim Rohn", ("jim rohn",)),
    ("Gary Vee", ("gary vee", "gary vaynerchuk", "garyv")),
    ("Chris Williamson", ("chris williamson", "williamson", "modern wisdom", "chris williams")),
)


def ensure_speaker_tables(store) -> None:
    store._conn.execute(
        """
        CREATE TABLE IF NOT EXISTS production_speaker_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_external_id TEXT NOT NULL UNIQUE,
            speaker TEXT NOT NULL,
            source_url TEXT,
            speech_title TEXT,
            corrected_by TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    store._conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_speaker_corrections_speaker
        ON production_speaker_corrections (speaker)
        """
    )


def infer_speaker(*texts: str | None) -> str | None:
    blob = " ".join(str(t) for t in texts if t).lower()
    if not blob.strip():
        return None
    best_name: str | None = None
    best_score = 0
    for name, hints in KNOWN_SPEAKERS:
        score = sum(1 for hint in hints if hint in blob)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name if best_score > 0 else None


def get_correction(store, source_external_id: str | None) -> str | None:
    if not source_external_id:
        return None
    ensure_speaker_tables(store)
    row = store._conn.execute(
        "SELECT speaker FROM production_speaker_corrections WHERE source_external_id = ?",
        (str(source_external_id).strip(),),
    ).fetchone()
    if not row:
        return None
    speaker = str(row["speaker"] or "").strip()
    return speaker or None


def save_correction(
    store,
    *,
    source_external_id: str,
    speaker: str,
    source_url: str | None = None,
    speech_title: str | None = None,
    corrected_by: str = "user",
    notes: str | None = None,
) -> None:
    ensure_speaker_tables(store)
    source_external_id = source_external_id.strip()
    speaker = speaker.strip()
    if not source_external_id or not speaker:
        raise ValueError("source_external_id and speaker are required")
    ts = now_iso()
    existing = store._conn.execute(
        "SELECT id FROM production_speaker_corrections WHERE source_external_id = ?",
        (source_external_id,),
    ).fetchone()
    if existing:
        store._conn.execute(
            """
            UPDATE production_speaker_corrections SET
                speaker = ?, source_url = ?, speech_title = ?, corrected_by = ?,
                notes = ?, updated_at = ?
            WHERE source_external_id = ?
            """,
            (speaker, source_url, speech_title, corrected_by, notes, ts, source_external_id),
        )
    else:
        store._conn.execute(
            """
            INSERT INTO production_speaker_corrections (
                source_external_id, speaker, source_url, speech_title,
                corrected_by, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_external_id, speaker, source_url, speech_title, corrected_by, notes, ts, ts),
        )
    store._conn.commit()


def resolve_registration_speaker(
    store,
    *,
    intended: str | None,
    title: str | None = None,
    channel: str | None = None,
    transcript: str | None = None,
    youtube_id: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Pick library speaker from correction memory, media metadata, or search intent."""
    meta: dict[str, Any] = {}
    intended_clean = (intended or "").strip()

    if youtube_id:
        corrected = get_correction(store, youtube_id)
        if corrected:
            meta["speaker_source"] = "correction_memory"
            if intended_clean and corrected.lower() != intended_clean.lower():
                meta["search_intent"] = intended_clean
            return corrected, meta

    inferred = infer_speaker(title, channel, transcript)
    if inferred:
        if intended_clean and inferred.lower() != intended_clean.lower():
            meta["search_intent"] = intended_clean
            meta["speaker_inferred_from"] = "media_metadata"
            meta["speaker_source"] = "inferred"
            return inferred, meta
        meta["speaker_source"] = "inferred" if not intended_clean else "intended"
        return inferred, meta

    if intended_clean:
        meta["speaker_source"] = "intended"
        return intended_clean, meta
    return None, meta


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def update_video_speaker(
    store,
    video_id: int,
    speaker: str,
    *,
    remember: bool = True,
    corrected_by: str = "user",
    notes: str | None = None,
) -> dict[str, Any]:
    video = get_video(store, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    speaker = speaker.strip()
    if not speaker:
        raise ValueError("speaker is required")

    meta = _parse_metadata(video.get("metadata"))
    meta["speaker_corrected_at"] = now_iso()
    meta["speaker_corrected_by"] = corrected_by
    if remember:
        meta["speaker_remembered"] = True

    store._conn.execute(
        """
        UPDATE production_library_videos
        SET speaker = ?, podcast_source = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (speaker, speaker, json.dumps(meta), now_iso(), video_id),
    )

    source_id = str(video.get("source_external_id") or "").strip()
    if remember and source_id:
        save_correction(
            store,
            source_external_id=source_id,
            speaker=speaker,
            source_url=video.get("source_url"),
            speech_title=video.get("title"),
            corrected_by=corrected_by,
            notes=notes,
        )
    else:
        store._conn.commit()

    updated = get_video(store, video_id)
    if not updated:
        raise ValueError(f"Video {video_id} not found after update")
    return updated
