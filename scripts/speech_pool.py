#!/usr/bin/env python3
"""Shared leftover-speech pool — stash unused minutes for the same speaker."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import content_reuse
from broll_pool import subjects_match

POOL_DIRNAME = "speech-pool"
POOL_META = "pool.json"
PART_RE = re.compile(r"_part(\d+)$", re.IGNORECASE)
YOUTUBE_ID_RE = re.compile(
    r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)


@dataclass
class SpeechPoolItem:
    youtube_id: str
    title: str
    url: str
    speaker: str
    start: float
    duration: float
    excerpt: str
    source_hash: str
    audio: Path
    captions: Path
    meta_path: Path


def speaker_tokens(speaker: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9]+", speaker.lower()) if part]


def speaker_pool_slug(speaker: str) -> str:
    tokens = speaker_tokens(speaker)
    if not tokens:
        return "general"
    return "-".join(tokens)


def youtube_id_from_url(url: str) -> str:
    match = YOUTUBE_ID_RE.search(url or "")
    return match.group(1) if match else ""


def pool_root(jobs_root: Path) -> Path:
    return jobs_root / POOL_DIRNAME


def pool_dir_for_speaker(jobs_root: Path, speaker: str) -> Path:
    return pool_root(jobs_root) / speaker_pool_slug(speaker)


def _load_pool_meta(path: Path) -> dict:
    meta_path = path / POOL_META
    if not meta_path.is_file():
        return {"speaker": "", "tokens": path.name.split("-")}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_pool_meta(path: Path, *, speaker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    tokens = speaker_tokens(speaker)
    meta_path = path / POOL_META
    existing = _load_pool_meta(path) if meta_path.is_file() else {}
    merged_tokens = list(dict.fromkeys([*(existing.get("tokens") or []), *tokens]))
    payload = {
        "speaker": speaker or existing.get("speaker") or "",
        "tokens": merged_tokens,
        "slug": path.name,
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def find_matching_pools(jobs_root: Path, speaker: str) -> list[Path]:
    root = pool_root(jobs_root)
    if not root.is_dir():
        return []
    matches: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _load_pool_meta(child)
        if subjects_match(speaker, list(meta.get("tokens") or speaker_tokens(child.name))):
            matches.append(child)
    return matches


def _next_part_index(pool_dir: Path, youtube_id: str) -> int:
    highest = 1
    for path in pool_dir.glob(f"{youtube_id}_part*.json"):
        match = PART_RE.search(path.stem)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _item_from_meta(meta_path: Path) -> SpeechPoolItem | None:
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    audio = meta_path.with_suffix(".mp3")
    captions = meta_path.with_suffix(".json3")
    if not audio.is_file() or not captions.is_file():
        return None
    return SpeechPoolItem(
        youtube_id=str(payload.get("youtube_id") or ""),
        title=str(payload.get("title") or ""),
        url=str(payload.get("url") or ""),
        speaker=str(payload.get("speaker") or ""),
        start=float(payload.get("start") or 0.0),
        duration=float(payload.get("duration") or 0.0),
        excerpt=str(payload.get("excerpt") or ""),
        source_hash=str(payload.get("source_hash") or ""),
        audio=audio,
        captions=captions,
        meta_path=meta_path,
    )


def list_pooled_excerpts(jobs_root: Path, *, speaker: str, youtube_id: str = "") -> list[SpeechPoolItem]:
    items: list[SpeechPoolItem] = []
    for pool_dir in find_matching_pools(jobs_root, speaker):
        for meta_path in sorted(pool_dir.glob("*_part*.json")):
            item = _item_from_meta(meta_path)
            if item is None:
                continue
            if youtube_id and item.youtube_id != youtube_id:
                continue
            items.append(item)
    return items


def stash_excerpt(
    jobs_root: Path,
    *,
    speaker: str,
    youtube_id: str,
    title: str,
    url: str,
    start: float,
    duration: float,
    excerpt: str,
    audio: Path,
    captions: Path,
    source_hash: str = "",
) -> Path | None:
    """Move one leftover excerpt into the speaker pool."""
    if not audio.is_file() or not captions.is_file():
        return None
    pool_dir = pool_dir_for_speaker(jobs_root, speaker)
    pool_dir.mkdir(parents=True, exist_ok=True)
    part = _next_part_index(pool_dir, youtube_id)
    stem = f"{youtube_id}_part{part:02d}"
    dest_audio = pool_dir / f"{stem}.mp3"
    dest_caps = pool_dir / f"{stem}.json3"
    dest_meta = pool_dir / f"{stem}.json"
    if dest_audio.exists() or dest_meta.exists():
        audio.unlink(missing_ok=True)
        captions.unlink(missing_ok=True)
        return None
    shutil.move(str(audio), str(dest_audio))
    shutil.move(str(captions), str(dest_caps))
    dest_meta.write_text(
        json.dumps(
            {
                "speaker": speaker,
                "youtube_id": youtube_id,
                "title": title,
                "url": url,
                "start": start,
                "duration": duration,
                "excerpt": excerpt,
                "source_hash": source_hash,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_pool_meta(pool_dir, speaker=speaker)
    return dest_meta


def take_from_pool(
    jobs_root: Path,
    *,
    speaker: str,
    audio_dir: Path,
    youtube_id: str = "",
    allow_reuse: bool = False,
) -> SpeechPoolItem | None:
    """Move one unused leftover excerpt into a job audio folder."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    for item in list_pooled_excerpts(jobs_root, speaker=speaker, youtube_id=youtube_id):
        hits = content_reuse.find_speech_reuse(item.excerpt)
        if hits and not allow_reuse:
            print(f"  skip pooled excerpt: {hits[0].reason}")
            continue
        dest_audio = audio_dir / "speech.mp3"
        dest_caps = audio_dir / "subs.en.json3"
        dest_audio.unlink(missing_ok=True)
        dest_caps.unlink(missing_ok=True)
        shutil.move(str(item.audio), str(dest_audio))
        shutil.move(str(item.captions), str(dest_caps))
        item.meta_path.unlink(missing_ok=True)
        item.audio = dest_audio
        item.captions = dest_caps
        print(
            f"Pooled speech for {speaker_pool_slug(speaker)}: "
            f"{item.title} ({item.youtube_id}) start={item.start:.1f}s"
        )
        return item
    return None
