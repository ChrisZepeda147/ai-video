"""Trim finished production library MP4s (override or new version)."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from discovery.config import project_root
from discovery.production_library import (
    _metadata_dict,
    _sha256_file,
    get_video,
    now_iso,
    register_video,
)


def _ensure_scripts_path() -> None:
    scripts = Path(__file__).resolve().parent.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def probe_duration(path: Path) -> float:
    _ensure_scripts_path()
    from toolchain_env import resolve_tool, subprocess_env

    ffprobe = resolve_tool("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found — set FFMPEG_DIR in scripts/.env")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=subprocess_env(),
    )
    return float(result.stdout.strip())


def trim_final_mp4(src: Path, dest: Path, start_sec: float, end_sec: float) -> None:
    _ensure_scripts_path()
    from toolchain_env import resolve_tool, subprocess_env

    ffmpeg = resolve_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — set FFMPEG_DIR in scripts/.env")
    span = max(end_sec - start_sec, 0.05)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.stem}.trim-{uuid.uuid4().hex[:8]}{dest.suffix}")
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(src),
        "-t",
        f"{span:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=subprocess_env())
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(err or "ffmpeg trim failed")
    tmp.replace(dest)


def _validate_trim_bounds(duration: float, start_sec: float, end_sec: float) -> tuple[float, float]:
    start = max(0.0, float(start_sec))
    end = float(end_sec)
    if end <= start:
        raise ValueError("end_sec must be greater than start_sec")
    if start >= duration:
        raise ValueError("start_sec is beyond video duration")
    end = min(end, duration)
    if end - start < 0.05:
        raise ValueError("trim span is too short")
    return start, end


def _resolve_final_path(video: dict[str, Any]) -> Path:
    rel = str(video.get("final_output_path") or "").strip()
    if not rel:
        raise ValueError("Video has no final render to trim")
    root = project_root()
    path = Path(rel) if Path(rel).is_absolute() else root / rel
    if not path.is_file():
        raise ValueError("Final render file is missing on disk")
    return path


def _update_final_component(store, video_id: int, rel_path: str) -> None:
    root = project_root()
    path = root / rel_path if not Path(rel_path).is_absolute() else Path(rel_path)
    sha = _sha256_file(path) if path.is_file() else ""
    row = store._conn.execute(
        """
        SELECT id FROM production_video_components
        WHERE video_id = ? AND component_type = 'final'
        ORDER BY id DESC LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    if row:
        store._conn.execute(
            "UPDATE production_video_components SET local_path = ?, file_sha256 = ? WHERE id = ?",
            (rel_path, sha or None, int(row["id"])),
        )
    else:
        from discovery.production_library import _add_component

        _add_component(
            store,
            video_id=video_id,
            component_type="final",
            local_path=rel_path,
            label="Final render",
        )


def trim_library_video(
    store,
    video_id: int,
    *,
    start_sec: float,
    end_sec: float,
    mode: Literal["override", "new_version"],
    change_summary: str | None = None,
    version_label: str | None = None,
) -> dict[str, Any]:
    video = get_video(store, video_id)
    if not video:
        raise ValueError(f"Production video {video_id} not found")
    src = _resolve_final_path(video)
    duration = probe_duration(src)
    start, end = _validate_trim_bounds(duration, start_sec, end_sec)
    new_duration = end - start
    trim_note = f"Trim {start:.2f}s–{end:.2f}s ({new_duration:.2f}s)"
    summary = (change_summary or trim_note).strip()

    if mode == "override":
        tmp = src.with_name(f"{src.stem}.trim-work{src.suffix}")
        try:
            trim_final_mp4(src, tmp, start, end)
            tmp.replace(src)
        finally:
            if tmp.exists() and tmp != src:
                tmp.unlink(missing_ok=True)

        meta = _metadata_dict(video.get("metadata"))
        meta["last_trim"] = {
            "start_sec": start,
            "end_sec": end,
            "applied_at": now_iso(),
            "mode": "override",
        }
        rel = str(video.get("final_output_path") or src.relative_to(project_root()).as_posix())
        store._conn.execute(
            """
            UPDATE production_library_videos
            SET duration_sec = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_duration, json.dumps(meta), now_iso(), video_id),
        )
        _update_final_component(store, video_id, rel)
        store._conn.commit()
        updated = get_video(store, video_id)
        if not updated:
            raise RuntimeError("Trim saved but video could not be reloaded")
        return updated

    root = project_root()
    staging = root / "downloads" / "library-trim" / f"video_{video_id:06d}" / "final.mp4"
    staging.parent.mkdir(parents=True, exist_ok=True)
    trim_final_mp4(src, staging, start, end)
    rel_staging = staging.relative_to(root).as_posix()

    meta = _metadata_dict(video.get("metadata"))
    meta["last_trim"] = {
        "start_sec": start,
        "end_sec": end,
        "applied_at": now_iso(),
        "mode": "new_version",
        "source_video_id": video_id,
    }

    return register_video(
        store,
        title=str(video.get("title") or f"Video {video_id}"),
        slug=video.get("slug"),
        speaker=video.get("speaker"),
        podcast_source=video.get("podcast_source"),
        source_url=video.get("source_url"),
        source_platform=video.get("source_platform"),
        source_external_id=video.get("source_external_id"),
        source_start_sec=video.get("source_start_sec"),
        source_end_sec=video.get("source_end_sec"),
        transcript_segment=video.get("transcript_segment"),
        topic=video.get("topic"),
        hook=video.get("hook"),
        production_project_id=video.get("production_project_id"),
        parent_video_id=video_id,
        version_label=version_label,
        change_summary=summary,
        final_output_path=rel_staging,
        duration_sec=new_duration,
        metadata=meta,
        copy_final_to_library=True,
    )
