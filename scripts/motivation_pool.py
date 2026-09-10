"""Local speech + B-roll pool for mix-and-match motivation Shorts."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_reuse  # noqa: E402
from youtube_popular_downloader import (  # noqa: E402
    VideoCandidate,
    _configure_stdout,
    discover_search,
    download_videos,
    filter_unwanted,
    probe_duration,
)

AssetKind = Literal["speech", "broll"]


def project_root() -> Path:
    return ROOT


def pool_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "downloads" / "motivational" / "pool.json"


def pool_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "downloads" / "motivational" / "pool"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_pool(root: Path | None = None) -> dict[str, Any]:
    path = pool_path(root)
    if not path.is_file():
        return {"updated_at": "", "speech": [], "broll": [], "combinations": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_pool(pool: dict[str, Any], root: Path | None = None) -> Path:
    path = pool_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    pool["updated_at"] = _now_iso()
    path.write_text(json.dumps(pool, indent=2), encoding="utf-8")
    return path


def combination_key(speech_id: str, broll_ids: list[str]) -> str:
    payload = f"{speech_id}|{'|'.join(sorted(broll_ids))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def used_combination_keys(pool: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for row in pool.get("combinations") or []:
        key = row.get("key")
        if key:
            keys.add(str(key))
        else:
            keys.add(combination_key(str(row.get("speech_youtube_id") or ""), list(row.get("broll_youtube_ids") or [])))
    return keys


def used_youtube_ids(root: Path | None = None) -> set[str]:
    root = root or project_root()
    pool = load_pool(root)
    ids = content_reuse.used_youtube_ids(root=root)
    for kind in ("speech", "broll"):
        for item in pool.get(kind) or []:
            yt = item.get("youtube_id")
            if yt:
                ids.add(str(yt))
    return ids


def _search_unused(
    query: str,
    *,
    kind: AssetKind,
    limit: int,
    root: Path,
    min_duration: float,
) -> list[VideoCandidate]:
    blocked = used_youtube_ids(root)
    raw = discover_search(query=query, limit=max(limit * 5, 25))
    filtered = filter_unwanted(
        raw,
        limit=limit * 5,
        exclude_music=kind == "speech",
        exclude_trailers=True,
        exclude_live=True,
        background_gameplay_only=False,
        min_views=25_000 if kind == "broll" else 10_000,
        min_duration=min_duration,
        quiet=True,
    )
    return [item for item in filtered if item.video_id not in blocked][:limit]


def _pool_index(pool: dict[str, Any], kind: AssetKind) -> dict[str, dict[str, Any]]:
    return {str(item.get("youtube_id")): item for item in pool.get(kind) or [] if item.get("youtube_id")}


def _asset_record(candidate: VideoCandidate, *, kind: AssetKind, query: str, local_path: str) -> dict[str, Any]:
    return {
        "youtube_id": candidate.video_id,
        "title": candidate.title,
        "url": candidate.url,
        "query": query,
        "kind": kind,
        "local_path": local_path,
        "duration_sec": candidate.duration_seconds,
        "added_at": _now_iso(),
        "use_count": 0,
    }


def pull_assets(
    *,
    speech_query: str,
    broll_query: str,
    speech_count: int = 3,
    broll_count: int = 6,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or project_root()
    _configure_stdout()
    speech_query = speech_query.strip()
    broll_query = broll_query.strip()
    if not speech_query:
        raise ValueError("speech_query is required")
    if not broll_query:
        raise ValueError("broll_query is required")

    pool = load_pool(root)
    speech_index = _pool_index(pool, "speech")
    broll_index = _pool_index(pool, "broll")

    speech_dir = pool_dir(root) / "speech"
    broll_dir = pool_dir(root) / "broll"
    speech_dir.mkdir(parents=True, exist_ok=True)
    broll_dir.mkdir(parents=True, exist_ok=True)

    pulled_speech: list[dict[str, Any]] = []
    pulled_broll: list[dict[str, Any]] = []

    speech_candidates = _search_unused(
        speech_query,
        kind="speech",
        limit=speech_count,
        root=root,
        min_duration=45.0,
    )
    for candidate in speech_candidates:
        if candidate.video_id in speech_index:
            continue
        batch = download_videos(
            [candidate],
            output_dir=speech_dir / candidate.video_id,
            max_height=720,
            audio_only=True,
            clip_length=120,
            max_parts=None,
            split_parts=False,
            keep_source=True,
            aspect_ratio="9:16",
            quiet=True,
            id_only_filenames=True,
        )
        if not batch or batch[0].get("status") != "ok":
            continue
        local = Path(str(batch[0]["file_path"]))
        if not local.is_file():
            continue
        rel = local.relative_to(root).as_posix()
        record = _asset_record(candidate, kind="speech", query=speech_query, local_path=rel)
        pool.setdefault("speech", []).append(record)
        speech_index[candidate.video_id] = record
        pulled_speech.append(record)

    broll_candidates = _search_unused(
        broll_query,
        kind="broll",
        limit=broll_count,
        root=root,
        min_duration=10.0,
    )
    for candidate in broll_candidates:
        if candidate.video_id in broll_index:
            continue
        batch = download_videos(
            [candidate],
            output_dir=broll_dir / candidate.video_id,
            max_height=1080,
            audio_only=False,
            clip_length=30,
            max_parts=None,
            split_parts=False,
            keep_source=False,
            aspect_ratio="9:16",
            quiet=True,
            id_only_filenames=True,
        )
        if not batch or batch[0].get("status") != "ok":
            continue
        local = Path(str(batch[0].get("file_path") or batch[0].get("source_file") or ""))
        if not local.is_file():
            continue
        rel = local.relative_to(root).as_posix()
        record = _asset_record(candidate, kind="broll", query=broll_query, local_path=rel)
        pool.setdefault("broll", []).append(record)
        broll_index[candidate.video_id] = record
        pulled_broll.append(record)

    save_pool(pool, root)
    return {
        "speech_pulled": len(pulled_speech),
        "broll_pulled": len(pulled_broll),
        "speech": pulled_speech,
        "broll": pulled_broll,
        "pool_summary": pool_summary(root),
    }


def pool_summary(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    pool = load_pool(root)
    combo_keys = used_combination_keys(pool)
    return {
        "speech_count": len(pool.get("speech") or []),
        "broll_count": len(pool.get("broll") or []),
        "combinations_used": len(combo_keys),
        "updated_at": pool.get("updated_at"),
    }


def list_pool(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    pool = load_pool(root)
    combo_keys = used_combination_keys(pool)
    speech = []
    for item in pool.get("speech") or []:
        path = root / str(item.get("local_path") or "")
        speech.append({**item, "available": path.is_file()})
    broll = []
    for item in pool.get("broll") or []:
        path = root / str(item.get("local_path") or "")
        broll.append({**item, "available": path.is_file()})
    return {
        "summary": pool_summary(root),
        "speech": speech,
        "broll": broll,
        "combinations": pool.get("combinations") or [],
        "combination_keys": sorted(combo_keys),
    }


def get_pool_asset(kind: AssetKind, youtube_id: str, root: Path | None = None) -> dict[str, Any] | None:
    pool = load_pool(root)
    for item in pool.get(kind) or []:
        if str(item.get("youtube_id")) == youtube_id:
            return item
    return None


def combination_is_used(speech_id: str, broll_ids: list[str], root: Path | None = None) -> bool:
    pool = load_pool(root)
    key = combination_key(speech_id, broll_ids)
    return key in used_combination_keys(pool)


def register_combination(
    *,
    speech_id: str,
    broll_ids: list[str],
    slug: str,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or project_root()
    pool = load_pool(root)
    key = combination_key(speech_id, broll_ids)
    row = {
        "key": key,
        "speech_youtube_id": speech_id,
        "broll_youtube_ids": sorted(broll_ids),
        "slug": slug,
        "created_at": _now_iso(),
    }
    pool.setdefault("combinations", []).append(row)
    for kind, yt_id in [("speech", speech_id), *[( "broll", bid) for bid in broll_ids]]:
        for item in pool.get(kind if kind == "speech" else "broll") or []:
            if str(item.get("youtube_id")) == yt_id:
                item["use_count"] = int(item.get("use_count") or 0) + 1
                item["last_used_at"] = _now_iso()
    save_pool(pool, root)
    return row


def pick_auto_combo(
    *,
    root: Path | None = None,
    min_broll: int = 2,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    import itertools

    root = root or project_root()
    pool = load_pool(root)
    speech_items = [s for s in pool.get("speech") or [] if (root / str(s.get("local_path") or "")).is_file()]
    broll_items = [b for b in pool.get("broll") or [] if (root / str(b.get("local_path") or "")).is_file()]
    if not speech_items or len(broll_items) < min_broll:
        return None

    used = used_combination_keys(pool)
    speech_items.sort(key=lambda item: int(item.get("use_count") or 0))
    broll_items.sort(key=lambda item: int(item.get("use_count") or 0))
    need = min(min_broll, len(broll_items))

    for speech in speech_items:
        speech_id = str(speech["youtube_id"])
        for chosen in itertools.combinations(broll_items, need):
            broll_ids = [str(item["youtube_id"]) for item in chosen]
            key = combination_key(speech_id, broll_ids)
            if key not in used:
                return speech, list(chosen)

    return None


def resolve_build_selection(
    *,
    speech_youtube_id: str | None,
    broll_youtube_ids: list[str] | None,
    root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = root or project_root()
    if speech_youtube_id and broll_youtube_ids:
        speech = get_pool_asset("speech", speech_youtube_id, root)
        if not speech:
            raise ValueError(f"Speech {speech_youtube_id} not in pool — pull sources first")
        broll: list[dict[str, Any]] = []
        for yt_id in broll_youtube_ids:
            item = get_pool_asset("broll", yt_id, root)
            if not item:
                raise ValueError(f"B-roll {yt_id} not in pool — pull sources first")
            broll.append(item)
        if combination_is_used(speech_youtube_id, broll_youtube_ids, root):
            raise ValueError("This speech + visual mix was already used — pick a different combo")
        return speech, broll

    picked = pick_auto_combo(root=root)
    if not picked:
        raise ValueError("Pool empty or all mixes used — pull new speech/visual sources first")
    return picked
