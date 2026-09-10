"""Production content library — separate from discovery references."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from discovery.config import production_library_dir, project_root
from discovery.reuse_detection import normalize_transcript, transcript_hash


COMPONENT_TYPES = frozenset({
    "source",
    "audio",
    "transcript",
    "scene",
    "visual",
    "caption",
    "music",
    "final",
    "thumbnail",
    "other",
})


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _video_key(video_id: int) -> str:
    return f"video_{video_id:06d}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_youtube_id(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.hostname and "youtu" in parsed.hostname:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2] or None
        if parsed.path.startswith("/watch"):
            return (parse_qs(parsed.query).get("v") or [None])[0]
        if parsed.path.startswith("/"):
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0]
    return None


MIN_PLAYABLE_BYTES = 100_000


def _final_path_on_disk(rel_path: str | None, root: Path | None = None) -> Path | None:
    if not rel_path:
        return None
    root = root or project_root()
    path = Path(rel_path)
    if not path.is_absolute():
        path = root / path
    return path if path.is_file() else None


def _is_playable_final(path: Path | None, *, min_bytes: int = MIN_PLAYABLE_BYTES) -> bool:
    return bool(path and path.is_file() and path.stat().st_size >= min_bytes)


def _motivation_output_candidates(slug: str | None, root: Path) -> list[Path]:
    if not slug:
        return []
    out_dir = root / "downloads" / "motivational" / slug / "output"
    if not out_dir.is_dir():
        return []
    names = [
        f"{slug}-motivation.mp4",
        f"{slug}-motivation.nocap.mp4",
    ]
    return [out_dir / name for name in names if (out_dir / name).is_file()]


def heal_final_output(store, video: dict[str, Any], *, root: Path | None = None) -> bool:
    """Restore library final.mp4 from job output when the copy is missing or stub-sized."""
    root = root or project_root()
    rel = video.get("final_output_path")
    if not rel:
        return False
    dest = _final_path_on_disk(str(rel), root)
    if _is_playable_final(dest):
        return True
    slug = str(video.get("slug") or "")
    for src in _motivation_output_candidates(slug, root):
        if not _is_playable_final(src):
            continue
        if dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        else:
            key = video.get("video_key") or _video_key(int(video["id"]))
            dest_dir = production_library_dir() / key
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "final.mp4"
            shutil.copy2(src, dest)
            rel = dest.relative_to(root).as_posix()
            store._conn.execute(
                "UPDATE production_library_videos SET final_output_path = ?, updated_at = ? WHERE id = ?",
                (rel, now_iso(), int(video["id"])),
            )
            store._conn.commit()
            video["final_output_path"] = rel
        return True
    return _is_playable_final(dest)


def _row_to_video(row) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    for key in ("tags_json", "scene_plan_json", "platform_ids_json", "metadata_json"):
        raw = data.get(key)
        if raw and isinstance(raw, str):
            try:
                data[key.replace("_json", "")] = json.loads(raw)
            except json.JSONDecodeError:
                data[key.replace("_json", "")] = raw
        else:
            data[key.replace("_json", "")] = None
    data["posted"] = bool(data.get("posted"))
    final_path = _final_path_on_disk(data.get("final_output_path"))
    data["playable"] = _is_playable_final(final_path)
    return data


def _row_to_component(row) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    raw = data.get("metadata_json")
    if raw and isinstance(raw, str):
        try:
            data["metadata"] = json.loads(raw)
        except json.JSONDecodeError:
            data["metadata"] = raw
    return data


def _next_video_id(store) -> int:
    row = store._conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM production_library_videos").fetchone()
    return int(row["n"])


def list_videos(
    store,
    *,
    limit: int = 100,
    speaker: str | None = None,
    topic: str | None = None,
    status: str | None = None,
    playable_only: bool = True,
    heal: bool = True,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if speaker:
        clauses.append("LOWER(speaker) LIKE ?")
        params.append(f"%{speaker.lower()}%")
    if topic:
        clauses.append("LOWER(topic) LIKE ?")
        params.append(f"%{topic.lower()}%")
    if status:
        clauses.append("status = ?")
        params.append(status)
    fetch_limit = limit * 3 if playable_only else limit
    params.append(fetch_limit)
    rows = store._conn.execute(
        f"""
        SELECT * FROM production_library_videos
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        video = _row_to_video(row)
        if heal:
            heal_final_output(store, video)
            final_path = _final_path_on_disk(video.get("final_output_path"))
            video["playable"] = _is_playable_final(final_path)
        if playable_only and not video.get("playable"):
            continue
        items.append(video)
        if len(items) >= limit:
            break
    return items


def get_video(store, video_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT * FROM production_library_videos WHERE id = ?",
        (video_id,),
    ).fetchone()
    if not row:
        return None
    video = _row_to_video(row)
    components = store._conn.execute(
        """
        SELECT * FROM production_video_components
        WHERE video_id = ?
        ORDER BY component_type, sort_order, id
        """,
        (video_id,),
    ).fetchall()
    video["components"] = [_row_to_component(c) for c in components]
    versions = store._conn.execute(
        """
        SELECT id, video_key, version, version_label, change_summary, status, final_output_path, created_at
        FROM production_library_videos
        WHERE id = ? OR parent_video_id = ?
        ORDER BY version, id
        """,
        (video.get("parent_video_id") or video_id, video_id),
    ).fetchall()
    video["versions"] = [dict(v) for v in versions]
    return video


def get_video_by_key(store, video_key: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT id FROM production_library_videos WHERE video_key = ?",
        (video_key,),
    ).fetchone()
    if not row:
        return None
    return get_video(store, int(row["id"]))


def _add_component(
    store,
    *,
    video_id: int,
    component_type: str,
    local_path: str | None = None,
    label: str | None = None,
    text_content: str | None = None,
    url: str | None = None,
    start_sec: float | None = None,
    end_sec: float | None = None,
    sort_order: int = 0,
    metadata: dict[str, Any] | None = None,
) -> int:
    if component_type not in COMPONENT_TYPES:
        component_type = "other"
    sha = ""
    if local_path:
        path = project_root() / local_path if not Path(local_path).is_absolute() else Path(local_path)
        if path.is_file():
            sha = _sha256_file(path)
    store._conn.execute(
        """
        INSERT INTO production_video_components (
            video_id, component_type, label, sort_order, local_path, url, text_content,
            start_sec, end_sec, metadata_json, file_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            component_type,
            label,
            sort_order,
            local_path,
            url,
            text_content,
            start_sec,
            end_sec,
            json.dumps(metadata) if metadata else None,
            sha or None,
            now_iso(),
        ),
    )
    store._conn.commit()
    return int(store._conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def register_video(
    store,
    *,
    title: str,
    slug: str | None = None,
    speaker: str | None = None,
    podcast_source: str | None = None,
    source_url: str | None = None,
    source_platform: str | None = None,
    source_external_id: str | None = None,
    source_start_sec: float | None = None,
    source_end_sec: float | None = None,
    transcript_segment: str | None = None,
    topic: str | None = None,
    hook: str | None = None,
    tags: list[str] | None = None,
    creation_prompt: str | None = None,
    creation_command_job_id: int | None = None,
    status: str = "completed",
    parent_video_id: int | None = None,
    version_label: str | None = None,
    change_summary: str | None = None,
    final_output_path: str | None = None,
    duration_sec: float | None = None,
    production_project_id: int | None = None,
    components: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    copy_final_to_library: bool = True,
) -> dict[str, Any]:
    """Register a completed production video and modular components."""
    root = project_root()
    if not title.strip():
        raise ValueError("title is required")

    if source_url and not source_external_id:
        source_external_id = _parse_youtube_id(source_url)
        if source_external_id and not source_platform:
            source_platform = "youtube"

    t_hash = transcript_hash(transcript_segment or "")
    video_id = _next_video_id(store)
    key = _video_key(video_id)
    version = 1
    if parent_video_id:
        parent = store._conn.execute(
            "SELECT version FROM production_library_videos WHERE id = ?",
            (parent_video_id,),
        ).fetchone()
        if parent:
            version = int(parent["version"]) + 1

    dest_dir = production_library_dir() / key
    dest_dir.mkdir(parents=True, exist_ok=True)

    rel_final = final_output_path
    if final_output_path and copy_final_to_library:
        src = root / final_output_path if not Path(final_output_path).is_absolute() else Path(final_output_path)
        if src.is_file():
            dest = dest_dir / "final.mp4"
            if not dest.exists() or dest.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dest)
            rel_final = dest.relative_to(root).as_posix()

    ts = now_iso()
    store._conn.execute(
        """
        INSERT INTO production_library_videos (
            id, video_key, slug, title, internal_name, speaker, podcast_source,
            source_url, source_platform, source_external_id, source_start_sec, source_end_sec,
            transcript_segment, transcript_hash, topic, hook, tags_json, scene_plan_json,
            creation_prompt, creation_command_job_id, status, version, parent_video_id,
            version_label, change_summary, posted, platform_ids_json, thumbnail_path,
            final_output_path, duration_sec, production_project_id, metadata_json,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL,
            ?, ?, ?, ?, ?, ?
        )
        """,
        (
            video_id,
            key,
            slug,
            title,
            slug or title,
            speaker,
            podcast_source,
            source_url,
            source_platform,
            source_external_id,
            source_start_sec,
            source_end_sec,
            transcript_segment,
            t_hash or None,
            topic,
            hook,
            json.dumps(tags) if tags else None,
            creation_prompt,
            creation_command_job_id,
            status,
            version,
            parent_video_id,
            version_label or (f"v{version}" if parent_video_id else None),
            change_summary,
            rel_final,
            duration_sec,
            production_project_id,
            json.dumps(metadata) if metadata else None,
            ts,
            ts,
        ),
    )
    if rel_final:
        _add_component(store, video_id=video_id, component_type="final", local_path=rel_final, label="Final render")
    if transcript_segment:
        _add_component(
            store,
            video_id=video_id,
            component_type="transcript",
            text_content=transcript_segment,
            label="Transcript segment",
        )
    if source_url:
        _add_component(
            store,
            video_id=video_id,
            component_type="source",
            url=source_url,
            label=podcast_source or "Source",
            start_sec=source_start_sec,
            end_sec=source_end_sec,
        )
    for index, comp in enumerate(components or []):
        _add_component(
            store,
            video_id=video_id,
            component_type=str(comp.get("component_type") or comp.get("type") or "other"),
            local_path=comp.get("local_path"),
            label=comp.get("label"),
            text_content=comp.get("text_content") or comp.get("text"),
            url=comp.get("url"),
            start_sec=comp.get("start_sec"),
            end_sec=comp.get("end_sec"),
            sort_order=int(comp.get("sort_order") or index),
            metadata=comp.get("metadata"),
        )
    store._conn.commit()
    return get_video(store, video_id) or {"id": video_id, "video_key": key}


def import_uploaded_video(
    store,
    *,
    upload_path: Path,
    title: str | None = None,
    speaker: str | None = None,
    topic: str | None = None,
    extract_audio: bool = True,
    transcribe: bool = False,
) -> dict[str, Any]:
    """Import a legacy MP4 into the production library."""
    if not upload_path.is_file():
        raise FileNotFoundError(upload_path)
    root = project_root()
    video_id = _next_video_id(store)
    key = _video_key(video_id)
    dest_dir = production_library_dir() / key
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_dest = dest_dir / "final.mp4"
    shutil.copy2(upload_path, final_dest)
    rel_final = final_dest.relative_to(root).as_posix()
    display_title = title or upload_path.stem.replace("-", " ").replace("_", " ").strip() or key

    duration_sec: float | None = None
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(final_dest),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        duration_sec = float(probe.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        duration_sec = None

    components: list[dict[str, Any]] = []
    if extract_audio and shutil.which("ffmpeg"):
        audio_dest = dest_dir / "audio.mp3"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(final_dest),
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(audio_dest),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
            components.append(
                {
                    "component_type": "audio",
                    "local_path": audio_dest.relative_to(root).as_posix(),
                    "label": "Extracted audio",
                }
            )
        except (subprocess.SubprocessError, OSError):
            pass

    transcript_text = ""
    if transcribe and components:
        audio_path = root / components[0]["local_path"]
        try:
            from discovery.transcription.whisper_local import WhisperLocalTranscriber

            if audio_path.is_file():
                result = WhisperLocalTranscriber().transcribe(str(audio_path))
                transcript_text = result.text or ""
        except Exception:
            transcript_text = ""

    return register_video(
        store,
        title=display_title,
        speaker=speaker,
        topic=topic,
        final_output_path=rel_final,
        duration_sec=duration_sec,
        status="imported",
        components=components,
        transcript_segment=transcript_text or None,
        metadata={"import_source": upload_path.name},
        copy_final_to_library=False,
    )


def check_reuse(
    store,
    *,
    source_url: str | None = None,
    source_external_id: str | None = None,
    source_platform: str | None = None,
    source_start_sec: float | None = None,
    source_end_sec: float | None = None,
    transcript: str | None = None,
    speaker: str | None = None,
    topic: str | None = None,
    hook: str | None = None,
    audio_path: str | None = None,
    video_id: int | None = None,
) -> dict[str, Any]:
    """Advisory prior-usage lookup against the production library — never hard-blocks production."""
    matches: list[dict[str, Any]] = []
    warnings: list[str] = []

    if video_id and not any([source_url, transcript, speaker, topic, hook]):
        ref = get_video(store, video_id)
        if ref:
            return check_reuse(
                store,
                source_url=ref.get("source_url"),
                source_external_id=ref.get("source_external_id"),
                source_platform=ref.get("source_platform"),
                source_start_sec=ref.get("source_start_sec"),
                source_end_sec=ref.get("source_end_sec"),
                transcript=ref.get("transcript_segment"),
                speaker=ref.get("speaker"),
                topic=ref.get("topic"),
                hook=ref.get("hook"),
            )

    if source_url and not source_external_id:
        source_external_id = _parse_youtube_id(source_url)
        source_platform = source_platform or "youtube"

    if source_external_id:
        rows = store._conn.execute(
            """
            SELECT id, video_key, title, speaker, topic, source_start_sec, source_end_sec, transcript_segment
            FROM production_library_videos
            WHERE source_platform = ? AND source_external_id = ?
            ORDER BY created_at DESC
            """,
            (source_platform or "youtube", source_external_id),
        ).fetchall()
        for row in rows:
            overlap = _timestamp_overlap(
                source_start_sec,
                source_end_sec,
                row["source_start_sec"],
                row["source_end_sec"],
            )
            matches.append(
                {
                    "video_id": row["id"],
                    "video_key": row["video_key"],
                    "title": row["title"],
                    "speaker": row["speaker"],
                    "topic": row["topic"],
                    "source_start_sec": row["source_start_sec"],
                    "source_end_sec": row["source_end_sec"],
                    "match_reason": "same_source_id" + ("_timestamp_overlap" if overlap else ""),
                }
            )
            if overlap:
                warnings.append(
                    f"Video {row['id']}: {row['speaker'] or 'unknown'}, {row['topic'] or row['title']}, "
                    f"timestamp {row['source_start_sec']}–{row['source_end_sec']}"
                )

    if transcript:
        th = transcript_hash(transcript)
        if th:
            rows = store._conn.execute(
                """
                SELECT id, video_key, title, speaker, topic, transcript_segment
                FROM production_library_videos
                WHERE transcript_hash = ?
                """,
                (th,),
            ).fetchall()
            for row in rows:
                matches.append(
                    {
                        "video_id": row["id"],
                        "video_key": row["video_key"],
                        "title": row["title"],
                        "speaker": row["speaker"],
                        "topic": row["topic"],
                        "match_reason": "exact_transcript_hash",
                    }
                )
                warnings.append(f"Video {row['id']}: exact transcript match — {row['title']}")

        norm_new = normalize_transcript(transcript)
        if len(norm_new) >= 40:
            rows = store._conn.execute(
                """
                SELECT id, video_key, title, speaker, topic, transcript_segment
                FROM production_library_videos
                WHERE transcript_segment IS NOT NULL AND LENGTH(transcript_segment) > 20
                ORDER BY created_at DESC LIMIT 200
                """
            ).fetchall()
            for row in rows:
                norm_old = normalize_transcript(row["transcript_segment"] or "")
                if not norm_old:
                    continue
                if norm_new in norm_old or norm_old in norm_new:
                    matches.append(
                        {
                            "video_id": row["id"],
                            "video_key": row["video_key"],
                            "title": row["title"],
                            "speaker": row["speaker"],
                            "topic": row["topic"],
                            "match_reason": "transcript_substring",
                        }
                    )

    if speaker and topic:
        rows = store._conn.execute(
            """
            SELECT id, video_key, title, speaker, topic, created_at
            FROM production_library_videos
            WHERE LOWER(speaker) = ? AND LOWER(topic) = ?
            ORDER BY created_at DESC LIMIT 10
            """,
            (speaker.lower(), topic.lower()),
        ).fetchall()
        for row in rows:
            matches.append(
                {
                    "video_id": row["id"],
                    "video_key": row["video_key"],
                    "title": row["title"],
                    "speaker": row["speaker"],
                    "topic": row["topic"],
                    "match_reason": "speaker_topic_combo",
                }
            )

    if hook:
        norm_hook = normalize_transcript(hook)
        if norm_hook:
            rows = store._conn.execute(
                """
                SELECT id, video_key, title, speaker, topic, hook
                FROM production_library_videos
                WHERE hook IS NOT NULL AND LENGTH(hook) > 5
                ORDER BY created_at DESC LIMIT 100
                """
            ).fetchall()
            for row in rows:
                if normalize_transcript(row["hook"] or "") == norm_hook:
                    matches.append(
                        {
                            "video_id": row["id"],
                            "video_key": row["video_key"],
                            "title": row["title"],
                            "speaker": row["speaker"],
                            "topic": row["topic"],
                            "match_reason": "exact_hook",
                        }
                    )
                    warnings.append(f"Video {row['id']}: same hook — {row['title']}")

    if audio_path:
        root = project_root()
        path = root / audio_path if not Path(audio_path).is_absolute() else Path(audio_path)
        if path.is_file():
            from discovery.reuse_detection import audio_fingerprint

            fp = audio_fingerprint(str(path))
            if fp:
                rows = store._conn.execute(
                    """
                    SELECT c.video_id, c.local_path, v.video_key, v.title, v.speaker, v.topic
                    FROM production_video_components c
                    JOIN production_library_videos v ON v.id = c.video_id
                    WHERE c.component_type = 'audio' AND c.local_path IS NOT NULL
                    """
                ).fetchall()
                for row in rows:
                    other = root / str(row["local_path"])
                    if other.is_file() and audio_fingerprint(str(other)) == fp:
                        matches.append(
                            {
                                "video_id": row["video_id"],
                                "video_key": row["video_key"],
                                "title": row["title"],
                                "speaker": row["speaker"],
                                "topic": row["topic"],
                                "match_reason": "same_audio_fingerprint",
                            }
                        )
                        warnings.append(f"Video {row['video_id']}: same audio fingerprint")

    deduped: dict[int, dict[str, Any]] = {}
    for item in matches:
        deduped[int(item["video_id"])] = item

    prior_ranges: list[dict[str, Any]] = []
    if source_external_id:
        range_rows = store._conn.execute(
            """
            SELECT id, source_start_sec, source_end_sec
            FROM production_library_videos
            WHERE source_platform = ? AND source_external_id = ?
              AND source_start_sec IS NOT NULL
              AND source_end_sec IS NOT NULL
            ORDER BY created_at DESC
            """,
            (source_platform or "youtube", source_external_id),
        ).fetchall()
        for row in range_rows:
            prior_ranges.append(
                {
                    "video_id": row["id"],
                    "start_sec": row["source_start_sec"],
                    "end_sec": row["source_end_sec"],
                }
            )

    return {
        "already_used": list(deduped.values()),
        "warnings": warnings,
        "prior_usage_detected": bool(deduped),
        "prior_timestamp_ranges": prior_ranges,
        "advisory_only": True,
        "policy": "advisory",
        "safe_to_proceed": True,
        "summary": (
            "No prior production-library usage found for this query."
            if not deduped
            else (
                f"Prior usage found ({len(deduped)} match(es)). "
                "Informational only — reuse is allowed when the new composition meaningfully differs. "
                "See prior_timestamp_ranges for earlier segments on this source."
            )
        ),
    }


def _timestamp_overlap(a0: float | None, a1: float | None, b0: float | None, b1: float | None) -> bool:
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return bool(a0 is None and a1 is None and b0 is None and b1 is None)
    return max(a0, b0) < min(a1, b1)


def library_summary_for_agent(store, *, limit: int = 20) -> str:
    """Compact library snapshot for Cursor agent prompts (memory — not eligibility rules)."""
    rows = list_videos(store, limit=limit)
    if not rows:
        return "Production library is empty."
    lines = [
        "Production library memory (advisory — reuse allowed unless user asked for unused-only):",
    ]
    for row in rows:
        ts = ""
        if row.get("source_start_sec") is not None and row.get("source_end_sec") is not None:
            ts = f", segment {row['source_start_sec']:.0f}s–{row['source_end_sec']:.0f}s"
        source = row.get("source_external_id") or row.get("source_url") or ""
        source_bit = f", source {source}" if source else ""
        lines.append(
            f"- Video {row['id']} ({row['video_key']}): {row.get('speaker') or '?'}, "
            f"{row.get('topic') or row.get('title')}{ts}{source_bit} [{row.get('status')}]"
        )
    return "\n".join(lines)
