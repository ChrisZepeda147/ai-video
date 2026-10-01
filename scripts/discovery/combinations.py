"""Combination Board — reusable audio + visual packs with per-owner pairing memory."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.media_paths import display_media_path, file_exists_rel
from discovery.production_library import check_reuse, get_video, now_iso, posting_summary_for_video_ids
from discovery.reuse_detection import transcript_hash
from discovery.speaker_identity import get_correction, infer_speaker

OWNERS = frozenset({"chris", "stephen"})
CATEGORY_ORDER = (
    "Cars",
    "Luxury",
    "Mansions",
    "Beaches",
    "City",
    "Scenery",
    "Watches",
    "Horror",
    "Custom",
)
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Cars": ("car", "supercar", "lamborghini", "ferrari", "hypercar", "automotive"),
    "Luxury": ("luxury", "rich", "wealth", "elite", "premium"),
    "Mansions": ("mansion", "estate", "villa", "penthouse", "house"),
    "Beaches": ("beach", "ocean", "sunset", "coast", "tropical"),
    "City": ("city", "urban", "skyline", "downtown", "night city"),
    "Scenery": ("scenery", "nature", "alpine", "mountain", "landscape", "drone"),
    "Watches": ("watch", "rolex", "timepiece", "horology"),
    "Horror": ("horror", "dark", "creepy", "scary"),
}


def normalize_owner(owner: str) -> str:
    value = (owner or "").strip().lower()
    if value not in OWNERS:
        raise ValueError(f"owner must be one of: {', '.join(sorted(OWNERS))}")
    return value


def other_owner(owner: str) -> str:
    return "stephen" if owner == "chris" else "chris"


def _parse_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def _infer_category(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for category in CATEGORY_ORDER:
        if category == "Custom":
            continue
        if any(word in blob for word in CATEGORY_KEYWORDS.get(category, ())):
            return category
    return "Custom"


def _letter(index: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(letters):
        return letters[index]
    return f"{letters[index % len(letters)]}{index // len(letters)}"


def _speaker_number(speaker: str, speaker_order: dict[str, int]) -> int:
    key = (speaker or "Unknown").strip().lower()
    if key not in speaker_order:
        speaker_order[key] = len(speaker_order) + 1
    return speaker_order[key]


def _category_base(category: str) -> int:
    try:
        return 10 + CATEGORY_ORDER.index(category)
    except ValueError:
        return 10 + len(CATEGORY_ORDER) - 1


def _resolve_speaker(row: dict[str, Any], store) -> str:
    source_id = str(row.get("source_external_id") or "").strip()
    if source_id:
        corrected = get_correction(store, source_id)
        if corrected:
            return corrected

    for field in ("speaker", "podcast_source"):
        value = str(row.get(field) or "").strip()
        if value:
            return value

    meta = _parse_json(row.get("metadata_json") or row.get("video_metadata_json"))
    parent_id = meta.get("parent_audio_video_id") or row.get("parent_video_id")
    if parent_id:
        parent = store._conn.execute(
            "SELECT speaker, title FROM production_library_videos WHERE id = ?",
            (int(parent_id),),
        ).fetchone()
        if parent and parent["speaker"]:
            return str(parent["speaker"]).strip()

    blob = " ".join(
        part
        for part in (
            row.get("video_title"),
            row.get("slug"),
            row.get("transcript_segment"),
            meta.get("visual_style"),
            meta.get("broll_query"),
        )
        if part
    ).lower()
    inferred = infer_speaker(blob)
    if inferred:
        return inferred

    local_path = str(row.get("local_path") or "")
    if local_path:
        job_json = project_root() / Path(local_path).parent.parent / "job.json"
        if job_json.is_file():
            try:
                job = json.loads(job_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                job = {}
            speaker = str(job.get("speaker") or "").strip()
            if speaker:
                return speaker
        info_dir = project_root() / Path(local_path).parent
        for info_path in sorted(info_dir.glob("*.info.json")):
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            title = str(info.get("title") or "")
            channel = str(info.get("channel") or "")
            inferred = infer_speaker(title, channel)
            if inferred:
                return inferred

    return "Unknown"


def _audio_dedupe_key(data: dict[str, Any], speaker: str) -> str:
    """One catalog slot per speaker + transcript (or file when no transcript)."""
    th = str(data.get("transcript_hash") or "").strip()
    if not th:
        segment = str(data.get("transcript_segment") or "").strip()
        if segment:
            th = transcript_hash(segment)
    if th:
        return f"transcript:{speaker.lower()}:{th}"
    file_key = (data.get("file_sha256") or str(data.get("local_path") or "")).strip().lower()
    if not file_key:
        return ""
    return f"file:{file_key}"


def _probe_media_duration(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        from build_clips_montage import probe_duration

        value = float(probe_duration(path))
        return value if value > 0 else None
    except Exception:
        return None


def _effective_audio_duration(data: dict[str, Any], root: Path | None = None) -> float | None:
    start = data.get("start_sec")
    end = data.get("end_sec")
    if start is not None and end is not None and float(end) > float(start):
        return float(end) - float(start)

    root = root or project_root()
    local_path = str(data.get("local_path") or "")
    if local_path:
        probed = _probe_media_duration(root / local_path)
        if probed:
            return probed

    for field in ("duration_sec", "video_duration_sec"):
        value = data.get(field)
        if value is not None and float(value) > 0:
            return float(value)
    return None


def _visual_pack_duration(store, pack: dict[str, Any], root: Path | None = None) -> float | None:
    root = root or project_root()
    preview = str(pack.get("preview_clip_path") or "")
    if preview:
        probed = _probe_media_duration(root / preview)
        if probed:
            return probed

    source_video_id = pack.get("source_video_id")
    if source_video_id:
        row = store._conn.execute(
            "SELECT duration_sec, final_output_path FROM production_library_videos WHERE id = ?",
            (int(source_video_id),),
        ).fetchone()
        if row:
            if row["duration_sec"] is not None and float(row["duration_sec"]) > 0:
                return float(row["duration_sec"])
            final_path = str(row["final_output_path"] or "")
            if final_path:
                probed = _probe_media_duration(root / final_path)
                if probed:
                    return probed
    return None


def _prefer_audio_row(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    """Keep the older production video when transcript/content duplicates."""
    cand_vid = int(candidate.get("video_id") or 0)
    exist_vid = int(existing.get("video_id") or 0)
    if cand_vid != exist_vid:
        return cand_vid < exist_vid
    return int(candidate.get("id") or 0) < int(existing.get("id") or 0)


def _is_catalog_audio_row(row: dict[str, Any], speaker: str) -> bool:
    slug = str(row.get("slug") or "")
    transcript = str(row.get("transcript_segment") or "").strip()
    if slug.startswith("combo-") and speaker == "Unknown" and len(transcript) <= 8:
        return False
    local_path = str(row.get("local_path") or "")
    if local_path:
        audio_path = project_root() / local_path
        if (
            slug.startswith("combo-")
            and audio_path.is_file()
            and audio_path.stat().st_size < 4096
            and len(transcript) <= 8
        ):
            return False
    return True


def get_audio_component(store, component_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT c.*, v.speaker, v.podcast_source, v.title AS video_title, v.source_url,
               v.source_external_id, v.transcript_segment, v.duration_sec AS video_duration_sec,
               v.slug AS video_slug, v.metadata_json AS video_metadata_json, v.parent_video_id
        FROM production_video_components c
        JOIN production_library_videos v ON v.id = c.video_id
        WHERE c.id = ? AND c.component_type = 'audio'
        """,
        (component_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["speaker"] = _resolve_speaker(data, store)
    return data


def get_visual_pack(store, pack_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT * FROM production_visual_packs WHERE id = ?",
        (pack_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    raw = data.get("broll_ids_json")
    if raw and isinstance(raw, str):
        try:
            data["broll_ids"] = json.loads(raw)
        except json.JSONDecodeError:
            data["broll_ids"] = []
    meta = data.get("metadata_json")
    if meta and isinstance(meta, str):
        try:
            data["metadata"] = json.loads(meta)
        except json.JSONDecodeError:
            data["metadata"] = {}
    return data


def sync_visual_packs(store, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Derive visual packs from existing library videos and job clip folders."""
    root = root or project_root()
    rows = store._conn.execute(
        """
        SELECT id, slug, title, metadata_json
        FROM production_library_videos
        WHERE status IN ('completed', 'imported')
        ORDER BY id ASC
        """
    ).fetchall()
    synced: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row in rows:
        video_id = int(row["id"])
        slug = str(row["slug"] or f"video-{video_id}")
        meta = _parse_json(row["metadata_json"])
        broll_ids = [str(x) for x in (meta.get("broll_ids") or []) if x]
        visual_style = str(meta.get("visual_style") or meta.get("broll_query") or "")
        category = _infer_category(visual_style, row["title"])

        from discovery.motivation_paths import motivation_jobs_root, resolve_job_dir

        job_dir = resolve_job_dir(slug, motivation_jobs_root(root))
        clips_root = (job_dir / "clips") if job_dir else root / "downloads" / "motivational" / slug / "clips"
        clip_paths = sorted(clips_root.glob("*_part*.mp4")) if clips_root.is_dir() else []
        if not clip_paths and not broll_ids:
            clip_components = store._conn.execute(
                """
                SELECT local_path FROM production_video_components
                WHERE video_id = ? AND component_type = 'visual' AND local_path LIKE '%_part%.mp4'
                ORDER BY sort_order, id
                """,
                (video_id,),
            ).fetchall()
            if clip_components:
                first = str(clip_components[0]["local_path"] or "")
                if first:
                    clips_root = (root / first).parent

        if not clips_root.is_dir() and not broll_ids:
            continue

        key_material = "|".join(sorted(broll_ids)) or str(clips_root.as_posix())
        pack_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]
        if pack_key in seen_keys:
            continue
        seen_keys.add(pack_key)

        preview = None
        if clips_root.is_dir():
            parts = sorted(clips_root.glob("*_part*.mp4"))
            if parts:
                try:
                    preview = parts[0].relative_to(root).as_posix()
                except ValueError:
                    preview = parts[0].as_posix()
        if not preview:
            comp = store._conn.execute(
                """
                SELECT local_path FROM production_video_components
                WHERE video_id = ? AND component_type = 'visual' AND local_path LIKE '%.mp4'
                ORDER BY sort_order, id LIMIT 1
                """,
                (video_id,),
            ).fetchone()
            if comp and comp["local_path"]:
                preview = str(comp["local_path"])

        clips_rel = None
        if clips_root.is_dir():
            try:
                clips_rel = clips_root.relative_to(root).as_posix()
            except ValueError:
                clips_rel = clips_root.as_posix()

        label = visual_style or f"{category} pack ({slug})"
        ts = now_iso()
        existing = store._conn.execute(
            "SELECT id FROM production_visual_packs WHERE pack_key = ?",
            (pack_key,),
        ).fetchone()
        meta_json = json.dumps({"source_slug": slug, "visual_style": visual_style})
        broll_json = json.dumps(broll_ids) if broll_ids else None
        if existing:
            store._conn.execute(
                """
                UPDATE production_visual_packs SET
                    category = ?, label = ?, clips_root_path = ?, broll_ids_json = ?,
                    preview_clip_path = ?, source_video_id = ?, metadata_json = ?, updated_at = ?
                WHERE pack_key = ?
                """,
                (
                    category,
                    label[:200],
                    clips_rel,
                    broll_json,
                    preview,
                    video_id,
                    meta_json,
                    ts,
                    pack_key,
                ),
            )
            pack_id = int(existing["id"])
        else:
            store._conn.execute(
                """
                INSERT INTO production_visual_packs (
                    pack_key, display_id, category, label, clips_root_path, broll_ids_json,
                    preview_clip_path, source_video_id, metadata_json, created_at, updated_at
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_key,
                    category,
                    label[:200],
                    clips_rel,
                    broll_json,
                    preview,
                    video_id,
                    meta_json,
                    ts,
                    ts,
                ),
            )
            pack_id = int(store._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        synced.append(get_visual_pack(store, pack_id) or {})

    _assign_visual_display_ids(store)
    store._conn.commit()
    return [p for p in synced if p]


def _assign_visual_display_ids(store) -> None:
    rows = store._conn.execute(
        "SELECT id, category FROM production_visual_packs ORDER BY category, id"
    ).fetchall()
    counters: dict[str, int] = {}
    for row in rows:
        category = str(row["category"] or "Custom")
        idx = counters.get(category, 0)
        counters[category] = idx + 1
        display_id = f"{_category_base(category)}{_letter(idx)}"
        store._conn.execute(
            "UPDATE production_visual_packs SET display_id = ? WHERE id = ?",
            (display_id, int(row["id"])),
        )


def list_audio_catalog(store) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT c.id, c.video_id, c.local_path, c.start_sec, c.end_sec, c.label, c.file_sha256,
               v.speaker, v.podcast_source, v.title AS video_title, v.source_url,
               v.source_external_id, v.transcript_segment, v.transcript_hash,
               v.duration_sec AS video_duration_sec, v.slug,
               v.metadata_json, v.parent_video_id, v.final_output_path
        FROM production_video_components c
        JOIN production_library_videos v ON v.id = c.video_id
        WHERE c.component_type = 'audio' AND c.local_path IS NOT NULL
        ORDER BY c.id
        """
    ).fetchall()

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = dict(row)
        speaker = _resolve_speaker(data, store)
        if not _is_catalog_audio_row(data, speaker):
            continue
        key = _audio_dedupe_key(data, speaker)
        if not key:
            continue
        existing = deduped.get(key)
        row = {**data, "speaker": speaker}
        if existing:
            if existing["speaker"] == "Unknown" and speaker != "Unknown":
                deduped[key] = row
            elif _prefer_audio_row(row, existing):
                deduped[key] = row
            continue
        deduped[key] = row

    speaker_order: dict[str, int] = {}
    per_speaker: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for data in sorted(deduped.values(), key=lambda item: (item["speaker"].lower(), int(item["id"]))):
        speaker = str(data["speaker"])
        sp_num = _speaker_number(speaker, speaker_order)
        idx = per_speaker.get(speaker.lower(), 0)
        per_speaker[speaker.lower()] = idx + 1
        display_id = f"{sp_num}{_letter(idx)}"
        excerpt = (data.get("transcript_segment") or "")[:240]
        duration_sec = _effective_audio_duration(data)
        local_path = str(data.get("local_path") or "")
        if local_path and not file_exists_rel(project_root(), local_path):
            continue
        items.append(
            {
                "component_id": int(data["id"]),
                "video_id": int(data["video_id"]),
                "display_id": display_id,
                "speaker": speaker,
                "label": data.get("label") or "Speech audio",
                "local_path": local_path or None,
                "display_path": display_media_path(local_path),
                "preview_available": bool(local_path and file_exists_rel(project_root(), local_path)),
                "start_sec": data.get("start_sec"),
                "end_sec": data.get("end_sec"),
                "duration_sec": duration_sec,
                "source_url": data.get("source_url"),
                "source_external_id": data.get("source_external_id"),
                "transcript_excerpt": excerpt,
                "video_title": data.get("video_title"),
                "video_slug": data.get("slug"),
            }
        )
    return items


def list_visual_packs(store) -> list[dict[str, Any]]:
    root = project_root()
    rows = store._conn.execute(
        "SELECT * FROM production_visual_packs ORDER BY category, display_id, id"
    ).fetchall()
    packs: list[dict[str, Any]] = []
    for row in rows:
        pack = get_visual_pack(store, int(row["id"]))
        if pack:
            clips_root = pack.get("clips_root_path")
            clip_count = 0
            if clips_root:
                path = project_root() / clips_root
                if path.is_dir():
                    clip_count = len(list(path.glob("*_part*.mp4")))
            pack["clip_count"] = clip_count
            pack["duration_sec"] = _visual_pack_duration(store, pack, root)
            preview = str(pack.get("preview_clip_path") or "")
            broll_ids = pack.get("broll_ids") or []
            has_preview = bool(preview and file_exists_rel(root, preview))
            has_clips = clip_count > 0
            has_broll = bool(broll_ids)
            if not has_preview and not has_clips and not has_broll:
                continue
            pack["display_path"] = display_media_path(preview or clips_root)
            pack["preview_available"] = has_preview
            packs.append(pack)
    return packs


def prune_stale_combination_catalog(store) -> dict[str, int]:
    """Remove combination rows whose media files no longer exist."""
    root = project_root()
    removed_audio = 0
    removed_packs = 0

    audio_rows = store._conn.execute(
        """
        SELECT id, local_path FROM production_video_components
        WHERE component_type = 'audio' AND local_path IS NOT NULL
        """
    ).fetchall()
    for row in audio_rows:
        path = str(row["local_path"] or "")
        if path and not file_exists_rel(root, path):
            store._conn.execute(
                "DELETE FROM production_video_components WHERE id = ?",
                (int(row["id"]),),
            )
            removed_audio += 1

    pack_rows = store._conn.execute("SELECT * FROM production_visual_packs").fetchall()
    for row in pack_rows:
        pack = get_visual_pack(store, int(row["id"])) or {}
        preview = str(pack.get("preview_clip_path") or "")
        clips_root = str(pack.get("clips_root_path") or "")
        broll_ids = pack.get("broll_ids") or []
        clip_count = 0
        if clips_root:
            clip_dir = root / clips_root
            if clip_dir.is_dir():
                clip_count = len(list(clip_dir.glob("*_part*.mp4")))
        has_preview = bool(preview and file_exists_rel(root, preview))
        if not has_preview and clip_count == 0 and not broll_ids:
            store._conn.execute(
                "DELETE FROM production_visual_packs WHERE id = ?",
                (int(row["id"]),),
            )
            removed_packs += 1

    if removed_audio or removed_packs:
        store._conn.commit()
    return {"removed_audio": removed_audio, "removed_visual_packs": removed_packs}


def _usage_for_pair(
    store,
    *,
    owner: str,
    audio_component_id: int,
    visual_pack_id: int,
) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT * FROM production_combination_usage
        WHERE owner = ? AND audio_component_id = ? AND visual_pack_id = ?
        """,
        (owner, audio_component_id, visual_pack_id),
    ).fetchone()
    return dict(row) if row else None


def pair_used_by_any_owner(
    store,
    *,
    audio_component_id: int,
    visual_pack_id: int,
) -> bool:
    """True if Chris or Stephen already used this audio + visual pairing."""
    row = store._conn.execute(
        """
        SELECT 1 FROM production_combination_usage
        WHERE audio_component_id = ? AND visual_pack_id = ?
        LIMIT 1
        """,
        (audio_component_id, visual_pack_id),
    ).fetchone()
    return row is not None


def combination_status(
    store,
    *,
    owner: str,
    audio_component_id: int,
) -> dict[str, Any]:
    owner = normalize_owner(owner)
    audio = get_audio_component(store, audio_component_id)
    if not audio:
        raise ValueError(f"Audio component {audio_component_id} not found")

    packs = list_visual_packs(store)
    other = other_owner(owner)
    visual_items: list[dict[str, Any]] = []

    for pack in packs:
        pack_id = int(pack["id"])
        own = _usage_for_pair(store, owner=owner, audio_component_id=audio_component_id, visual_pack_id=pack_id)
        other_use = _usage_for_pair(
            store, owner=other, audio_component_id=audio_component_id, visual_pack_id=pack_id
        )
        if own:
            status = "used_by_selected_owner"
            available = False
        elif other_use:
            status = "used_by_other_owner"
            available = False
        else:
            status = "available"
            available = True

        prior_ids: list[int] = []
        for usage in (own, other_use):
            if not usage or not usage.get("rendered_video_id"):
                continue
            vid = int(usage["rendered_video_id"])
            if vid not in prior_ids:
                prior_ids.append(vid)

        visual_items.append(
            {
                "visual_pack_id": pack_id,
                "display_id": pack.get("display_id"),
                "category": pack.get("category"),
                "label": pack.get("label"),
                "preview_clip_path": pack.get("preview_clip_path"),
                "clip_count": pack.get("clip_count", 0),
                "duration_sec": pack.get("duration_sec"),
                "status": status,
                "available": available,
                "used_by_selected_owner": bool(own),
                "used_by_other_owner": bool(other_use),
                "other_owner": other if other_use else None,
                "rendered_video_ids": prior_ids,
                "posting": posting_summary_for_video_ids(store, prior_ids) if prior_ids else None,
            }
        )

    catalog_lookup = {int(a["component_id"]): a for a in list_audio_catalog(store)}
    audio_display = catalog_lookup.get(audio_component_id, {}).get("display_id")

    advisory = check_reuse(
        store,
        source_url=audio.get("source_url"),
        source_external_id=audio.get("source_external_id"),
        transcript=audio.get("transcript_segment"),
        speaker=audio.get("speaker"),
    )

    return {
        "owner": owner,
        "audio_component_id": audio_component_id,
        "audio": {
            "display_id": audio_display,
            "speaker": audio.get("speaker"),
            "local_path": audio.get("local_path"),
            "transcript_excerpt": (audio.get("transcript_segment") or "")[:240],
            "duration_sec": _effective_audio_duration(audio),
            "start_sec": audio.get("start_sec"),
            "end_sec": audio.get("end_sec"),
            "source_url": audio.get("source_url"),
        },
        "visuals": visual_items,
        "advisory_reuse": advisory,
    }


def record_combination_usage(
    store,
    *,
    owner: str,
    audio_component_id: int,
    visual_pack_id: int,
    rendered_video_id: int,
    audio_start_sec: float | None = None,
    audio_end_sec: float | None = None,
    visual_start_sec: float | None = None,
    visual_end_sec: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    owner = normalize_owner(owner)
    ts = now_iso()
    existing = _usage_for_pair(
        store,
        owner=owner,
        audio_component_id=audio_component_id,
        visual_pack_id=visual_pack_id,
    )
    if existing and not force:
        store._conn.execute(
            """
            UPDATE production_combination_usage SET
                rendered_video_id = ?, audio_start_sec = ?, audio_end_sec = ?,
                visual_start_sec = ?, visual_end_sec = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                rendered_video_id,
                audio_start_sec,
                audio_end_sec,
                visual_start_sec,
                visual_end_sec,
                ts,
                int(existing["id"]),
            ),
        )
        row = store._conn.execute(
            "SELECT * FROM production_combination_usage WHERE id = ?",
            (int(existing["id"]),),
        ).fetchone()
        store._conn.commit()
        return dict(row) if row else existing

    store._conn.execute(
        """
        INSERT INTO production_combination_usage (
            owner, audio_component_id, visual_pack_id, rendered_video_id,
            audio_start_sec, audio_end_sec, visual_start_sec, visual_end_sec,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner, audio_component_id, visual_pack_id) DO UPDATE SET
            rendered_video_id = excluded.rendered_video_id,
            audio_start_sec = excluded.audio_start_sec,
            audio_end_sec = excluded.audio_end_sec,
            visual_start_sec = excluded.visual_start_sec,
            visual_end_sec = excluded.visual_end_sec,
            updated_at = excluded.updated_at
        """,
        (
            owner,
            audio_component_id,
            visual_pack_id,
            rendered_video_id,
            audio_start_sec,
            audio_end_sec,
            visual_start_sec,
            visual_end_sec,
            ts,
            ts,
        ),
    )
    store._conn.commit()
    row = store._conn.execute(
        """
        SELECT * FROM production_combination_usage
        WHERE owner = ? AND audio_component_id = ? AND visual_pack_id = ?
        """,
        (owner, audio_component_id, visual_pack_id),
    ).fetchone()
    return dict(row) if row else {}


def owners_with_posting_flags(video: dict[str, Any]) -> list[str]:
    """Owners who marked at least one platform for this library video."""
    status = video.get("posting_status") or {}
    by_owner = status.get("by_owner") or {}
    found: list[str] = []
    for name, slot in by_owner.items():
        if name not in OWNERS:
            continue
        manual = (slot or {}).get("manual") or {}
        if any(bool(v) for v in manual.values()):
            found.append(str(name))
    return sorted(set(found))


def ensure_combination_usage_for_library_video(
    store,
    video_id: int,
    *,
    owners: list[str] | None = None,
) -> dict[str, Any]:
    """Record one audio+visual pairing from a library video (exact pair only, per owner)."""
    sync_visual_packs(store)
    video = _video_bundle_for_usage_import(store, int(video_id))
    if not video:
        return {"video_id": video_id, "ok": False, "reason": "video_not_found"}
    target_owners = [normalize_owner(o) for o in (owners or owners_with_posting_flags(video))]
    if not target_owners:
        return {"video_id": video_id, "ok": False, "reason": "no_posting_owner"}
    by_owner: dict[str, Any] = {}
    for owner in target_owners:
        by_owner[owner] = import_usage_from_videos(store, owner=owner, video_ids=[int(video_id)])
    return {"video_id": int(video_id), "ok": True, "by_owner": by_owner}


def sync_combination_usage_from_posted_videos(
    store,
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    """Optional manual backfill from posted library videos (not run on every catalog load)."""
    sync_visual_packs(store)
    rows = store._conn.execute(
        "SELECT id FROM production_library_videos WHERE posted = 1 ORDER BY id"
    ).fetchall()
    video_ids = [int(row["id"]) for row in rows]
    if not video_ids:
        return {"video_count": 0, "by_owner": {}}
    owners = [normalize_owner(owner)] if owner else sorted(OWNERS)
    by_owner: dict[str, Any] = {}
    for name in owners:
        by_owner[name] = import_usage_from_videos(store, owner=name, video_ids=video_ids)
    return {"video_count": len(video_ids), "by_owner": by_owner}


def _video_bundle_for_usage_import(store, video_id: int) -> dict[str, Any] | None:
    """Load video + components for usage import without relocating library files."""
    from discovery.production_library import _row_to_component, _row_to_video

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
        WHERE video_id = ? ORDER BY component_type, sort_order, id
        """,
        (video_id,),
    ).fetchall()
    root = project_root()
    video["components"] = [_row_to_component(c, root=root) for c in components]
    return video


def import_usage_from_videos(
    store,
    *,
    owner: str,
    video_ids: list[int] | None = None,
    all_videos: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill combination usage from existing library videos (non-destructive)."""
    owner = normalize_owner(owner)
    sync_visual_packs(store)
    audio_catalog = {int(a["component_id"]): a for a in list_audio_catalog(store)}
    packs = list_visual_packs(store)
    pack_by_source: dict[int, int] = {}
    for pack in packs:
        src = pack.get("source_video_id")
        if src:
            pack_by_source[int(src)] = int(pack["id"])

    if all_videos:
        rows = store._conn.execute(
            "SELECT id FROM production_library_videos ORDER BY id"
        ).fetchall()
        video_ids = [int(r["id"]) for r in rows]
    elif not video_ids:
        return {"imported": 0, "skipped": 0, "unknown": 0, "details": []}

    imported = skipped = unknown = 0
    details: list[dict[str, Any]] = []

    for vid in video_ids or []:
        video = _video_bundle_for_usage_import(store, int(vid))
        if not video:
            unknown += 1
            continue
        audio_comp = next(
            (c for c in (video.get("components") or []) if c.get("component_type") == "audio"),
            None,
        )
        if not audio_comp:
            unknown += 1
            details.append({"video_id": vid, "status": "no_audio_component"})
            continue
        pack_id = pack_by_source.get(vid)
        if not pack_id:
            meta = video.get("metadata") or _parse_json(video.get("metadata_json"))
            broll_ids = sorted(str(x) for x in (meta.get("broll_ids") or []) if x)
            for pack in packs:
                pb = sorted(str(x) for x in (pack.get("broll_ids") or []) if x)
                if broll_ids and pb == broll_ids:
                    pack_id = int(pack["id"])
                    break
        if not pack_id:
            unknown += 1
            details.append({"video_id": vid, "status": "no_visual_pack_match"})
            continue

        audio_id = int(audio_comp["id"])
        existing = _usage_for_pair(
            store, owner=owner, audio_component_id=audio_id, visual_pack_id=pack_id
        )
        if existing:
            skipped += 1
            details.append({"video_id": vid, "status": "already_recorded"})
            continue

        if not dry_run:
            record_combination_usage(
                store,
                owner=owner,
                audio_component_id=audio_id,
                visual_pack_id=pack_id,
                rendered_video_id=vid,
                force=True,
            )
        imported += 1
        details.append({"video_id": vid, "status": "imported", "audio_id": audio_id, "pack_id": pack_id})

    return {
        "owner": owner,
        "imported": imported,
        "skipped": skipped,
        "unknown": unknown,
        "dry_run": dry_run,
        "details": details,
    }


def catalog_payload(store, *, owner: str | None = None, prune_missing: bool = False) -> dict[str, Any]:
    if prune_missing:
        prune_stale_combination_catalog(store)
    sync_visual_packs(store)
    audio_items = list_audio_catalog(store)
    packs = list_visual_packs(store)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in audio_items:
        grouped.setdefault(item["speaker"], []).append(item)

    visual_by_category: dict[str, list[dict[str, Any]]] = {}
    for pack in packs:
        category = str(pack.get("category") or "Custom")
        visual_by_category.setdefault(category, []).append(pack)

    return {
        "owners": sorted(OWNERS),
        "selected_owner": normalize_owner(owner) if owner else None,
        "audio_by_speaker": grouped,
        "visual_packs": packs,
        "visual_by_category": visual_by_category,
        "audio_count": len(audio_items),
        "visual_pack_count": len(packs),
    }


def query_unused_combinations(
    store,
    *,
    owner: str,
    speaker: str | None = None,
) -> list[dict[str, Any]]:
    owner = normalize_owner(owner)
    sync_visual_packs(store)
    audio_items = list_audio_catalog(store)
    if speaker:
        needle = speaker.lower()
        audio_items = [a for a in audio_items if needle in (a.get("speaker") or "").lower()]
    results: list[dict[str, Any]] = []
    for audio in audio_items:
        status = combination_status(store, owner=owner, audio_component_id=int(audio["component_id"]))
        greens = [v for v in status["visuals"] if v["status"] == "available"]
        if greens:
            results.append(
                {
                    "audio": audio,
                    "available_visuals": greens,
                }
            )
    return results
