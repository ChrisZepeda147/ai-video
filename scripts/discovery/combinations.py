"""Combination Board — reusable audio + visual packs with per-owner pairing memory."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.production_library import check_reuse, get_video, now_iso

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


def get_audio_component(store, component_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT c.*, v.speaker, v.title AS video_title, v.source_url, v.source_external_id,
               v.transcript_segment, v.duration_sec AS video_duration_sec, v.slug AS video_slug,
               v.metadata_json AS video_metadata_json
        FROM production_video_components c
        JOIN production_library_videos v ON v.id = c.video_id
        WHERE c.id = ? AND c.component_type = 'audio'
        """,
        (component_id,),
    ).fetchone()
    return dict(row) if row else None


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

        clips_root = root / "downloads" / "motivational" / slug / "clips"
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
        SELECT c.id, c.video_id, c.local_path, c.start_sec, c.end_sec, c.label,
               v.speaker, v.title AS video_title, v.source_url, v.source_external_id,
               v.transcript_segment, v.duration_sec, v.slug
        FROM production_video_components c
        JOIN production_library_videos v ON v.id = c.video_id
        WHERE c.component_type = 'audio' AND c.local_path IS NOT NULL
        ORDER BY LOWER(COALESCE(v.speaker, '')), c.id
        """
    ).fetchall()
    speaker_order: dict[str, int] = {}
    per_speaker: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for row in rows:
        speaker = str(row["speaker"] or "Unknown").strip()
        sp_num = _speaker_number(speaker, speaker_order)
        idx = per_speaker.get(speaker.lower(), 0)
        per_speaker[speaker.lower()] = idx + 1
        display_id = f"{sp_num}{_letter(idx)}"
        excerpt = (row["transcript_segment"] or "")[:240]
        items.append(
            {
                "component_id": int(row["id"]),
                "video_id": int(row["video_id"]),
                "display_id": display_id,
                "speaker": speaker,
                "label": row["label"] or "Speech audio",
                "local_path": row["local_path"],
                "start_sec": row["start_sec"],
                "end_sec": row["end_sec"],
                "duration_sec": row["duration_sec"],
                "source_url": row["source_url"],
                "source_external_id": row["source_external_id"],
                "transcript_excerpt": excerpt,
                "video_title": row["video_title"],
                "video_slug": row["slug"],
            }
        )
    return items


def list_visual_packs(store) -> list[dict[str, Any]]:
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
            packs.append(pack)
    return packs


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
            available = True
        else:
            status = "available"
            available = True

        prior_ids: list[int] = []
        if own and own.get("rendered_video_id"):
            prior_ids.append(int(own["rendered_video_id"]))
        if other_use and other_use.get("rendered_video_id"):
            prior_ids.append(int(other_use["rendered_video_id"]))

        visual_items.append(
            {
                "visual_pack_id": pack_id,
                "display_id": pack.get("display_id"),
                "category": pack.get("category"),
                "label": pack.get("label"),
                "preview_clip_path": pack.get("preview_clip_path"),
                "clip_count": pack.get("clip_count", 0),
                "status": status,
                "available": available,
                "used_by_selected_owner": bool(own),
                "used_by_other_owner": bool(other_use),
                "other_owner": other if other_use else None,
                "rendered_video_ids": prior_ids,
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
            "duration_sec": audio.get("video_duration_sec") or audio.get("duration_sec"),
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
        video = get_video(store, vid)
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


def catalog_payload(store, *, owner: str | None = None) -> dict[str, Any]:
    sync_visual_packs(store)
    audio_items = list_audio_catalog(store)
    packs = list_visual_packs(store)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in audio_items:
        grouped.setdefault(item["speaker"], []).append(item)

    return {
        "owners": sorted(OWNERS),
        "selected_owner": normalize_owner(owner) if owner else None,
        "audio_by_speaker": grouped,
        "visual_packs": packs,
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
