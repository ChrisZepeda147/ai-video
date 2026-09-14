#!/usr/bin/env python3
"""Shared B-roll clip pool — stash unused parts for the same subject across jobs."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from broll_frame_gate import subject_tokens

POOL_DIRNAME = "broll-pool"
POOL_META = "pool.json"
CLIP_GLOB = "*_part*.mp4"


def subject_pool_slug(subject: str) -> str:
    tokens = subject_tokens(subject)
    if not tokens:
        return "general"
    return "-".join(tokens[:3])


def pool_root(jobs_root: Path) -> Path:
    return jobs_root / POOL_DIRNAME


def pool_dir_for_subject(jobs_root: Path, subject: str) -> Path:
    return pool_root(jobs_root) / subject_pool_slug(subject)


def _load_pool_meta(path: Path) -> dict:
    meta_path = path / POOL_META
    if not meta_path.is_file():
        return {"subject": "", "tokens": path.name.split("-")}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_pool_meta(path: Path, *, subject: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    tokens = subject_tokens(subject)
    meta_path = path / POOL_META
    existing = _load_pool_meta(path) if meta_path.is_file() else {}
    merged_tokens = list(dict.fromkeys([*(existing.get("tokens") or []), *tokens]))
    payload = {
        "subject": subject or existing.get("subject") or "",
        "tokens": merged_tokens,
        "slug": path.name,
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


_MODEL_HINTS = frozenset(
    {
        "488",
        "812",
        "911",
        "agera",
        "aventador",
        "cayman",
        "carrera",
        "gemera",
        "gt2",
        "gt3",
        "gt3rs",
        "huracan",
        "jesko",
        "pista",
        "regera",
        "revuelto",
        "roma",
        "sf90",
        "targa",
        "urus",
    }
)


def _model_tokens(tokens: list[str]) -> set[str]:
    return {item for item in tokens if item in _MODEL_HINTS}


def subjects_match(left: str, right_tokens: list[str]) -> bool:
    """Same brand may share a pool. Named models (488 vs SF90) stay separate."""
    want = subject_tokens(left)
    have = [str(item) for item in right_tokens if item]
    if not want or not have:
        return want == have
    want_models = _model_tokens(want)
    have_models = _model_tokens(have)
    if want_models and have_models:
        return bool(want_models & have_models)
    if want_models and not have_models:
        return False
    if want[0] == have[0]:
        return True
    shared = set(want) & set(have)
    if not shared:
        return False
    return len(shared) >= min(len(set(want)), len(set(have)))


def find_matching_pools(jobs_root: Path, subject: str) -> list[Path]:
    root = pool_root(jobs_root)
    if not root.is_dir():
        return []
    matches: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _load_pool_meta(child)
        if subjects_match(subject, list(meta.get("tokens") or [])):
            matches.append(child)
    return matches


def _clip_fps(clip: Path) -> float:
    from build_clips_montage import probe_fps

    try:
        return probe_fps(clip)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0.0


def list_pool_clips(pool_dir: Path) -> list[Path]:
    if not pool_dir.is_dir():
        return []
    return sorted(pool_dir.glob(CLIP_GLOB))


def take_from_pool(
    jobs_root: Path,
    *,
    subject: str,
    clips_dir: Path,
    count: int | None = None,
    copy: bool = True,
) -> list[Path]:
    """Pull pooled clips into a job folder (copy by default — pool stays cached)."""
    clips_dir.mkdir(parents=True, exist_ok=True)
    taken: list[Path] = []
    from build_clips_montage import is_usable_fps

    for pool_dir in find_matching_pools(jobs_root, subject):
        for clip in list_pool_clips(pool_dir):
            if count is not None and len(taken) >= count:
                return taken
            fps = _clip_fps(clip)
            if not is_usable_fps(fps):
                print(f"  drop pool {clip.name}: {fps:.1f} fps")
                clip.unlink(missing_ok=True)
                continue
            dest = clips_dir / clip.name
            if dest.exists():
                continue
            if copy:
                shutil.copy2(clip, dest)
            else:
                shutil.move(str(clip), str(dest))
            taken.append(dest)
    if taken:
        mode = "Copied" if copy else "Pooled"
        print(f"{mode} {len(taken)} clip(s) for subject: {subject_pool_slug(subject)}")
    return taken


def _youtube_id_from_clip_name(name: str) -> str:
    if "_part" in name:
        return name.split("_part", 1)[0]
    return ""


def copy_youtube_clips(
    jobs_root: Path,
    *,
    clips_dir: Path,
    youtube_ids: list[str],
    subject: str,
    count: int | None = None,
) -> list[Path]:
    """Copy cached pool parts for specific YouTube IDs (no re-download)."""
    clips_dir.mkdir(parents=True, exist_ok=True)
    wanted = {item.strip() for item in youtube_ids if item and item.strip()}
    if not wanted:
        return []
    copied: list[Path] = []
    from build_clips_montage import is_usable_fps

    for pool_dir in find_matching_pools(jobs_root, subject):
        for clip in list_pool_clips(pool_dir):
            if count is not None and len(copied) >= count:
                return copied
            yt_id = _youtube_id_from_clip_name(clip.name)
            if yt_id not in wanted:
                continue
            fps = _clip_fps(clip)
            if not is_usable_fps(fps):
                continue
            dest = clips_dir / clip.name
            if dest.exists():
                continue
            shutil.copy2(clip, dest)
            copied.append(dest)
    if copied:
        print(f"Cached {len(copied)} clip(s) from pool for known B-roll IDs")
    return copied


def add_gated_clips_to_pool(
    jobs_root: Path,
    *,
    subject: str,
    clips: list[Path],
) -> list[Path]:
    """Copy frame-gated clips into the shared pool so later jobs can reuse them."""
    if not clips:
        return []
    from build_clips_montage import is_usable_fps

    pool_dir = pool_dir_for_subject(jobs_root, subject)
    pool_dir.mkdir(parents=True, exist_ok=True)
    added: list[Path] = []
    for clip in clips:
        if not clip.is_file():
            continue
        fps = _clip_fps(clip)
        if not is_usable_fps(fps):
            continue
        dest = pool_dir / clip.name
        if dest.exists() and dest.stat().st_size == clip.stat().st_size:
            continue
        shutil.copy2(clip, dest)
        added.append(dest)
    if added:
        _write_pool_meta(pool_dir, subject=subject)
        print(f"Pooled {len(added)} vetted clip(s) -> {pool_dir.as_posix()}")
    return added


def stash_unused_clips(
    jobs_root: Path,
    *,
    subject: str,
    clips_dir: Path,
    used: set[Path] | list[Path],
) -> list[Path]:
    """Move job clips that were not used in the render into the shared pool."""
    if not clips_dir.is_dir():
        return []
    used_names = {Path(item).name for item in used}
    pool_dir = pool_dir_for_subject(jobs_root, subject)
    stashed: list[Path] = []
    from build_clips_montage import is_usable_fps

    for clip in sorted(clips_dir.glob(CLIP_GLOB)):
        if clip.name in used_names:
            continue
        fps = _clip_fps(clip)
        if not is_usable_fps(fps):
            print(f"  drop {clip.name}: {fps:.1f} fps")
            clip.unlink(missing_ok=True)
            continue
        pool_dir.mkdir(parents=True, exist_ok=True)
        dest = pool_dir / clip.name
        if dest.exists():
            clip.unlink(missing_ok=True)
            continue
        shutil.move(str(clip), str(dest))
        stashed.append(dest)
    if stashed:
        _write_pool_meta(pool_dir, subject=subject)
        print(f"Stashed {len(stashed)} unused clip(s) -> {pool_dir.as_posix()}")
    return stashed


def purge_low_fps_clips(jobs_root: Path) -> list[Path]:
    """Delete pooled B-roll with no readable frame rate."""
    from build_clips_montage import is_usable_fps

    root = pool_root(jobs_root)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for clip in sorted(root.rglob(CLIP_GLOB)):
        fps = _clip_fps(clip)
        if is_usable_fps(fps):
            continue
        print(f"  drop pool {clip.name}: {fps:.1f} fps")
        clip.unlink(missing_ok=True)
        removed.append(clip)
    return removed
