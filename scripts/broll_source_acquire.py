"""Single-source B-roll acquisition (subprocess entry + shared logic)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dataclasses import fields

from broll_acquire_workspace import cleanup_workspace, source_workspace
from youtube_popular_downloader import VideoCandidate, download_broll_source_parts, download_videos


def _candidate_from_dict(data: dict[str, Any]) -> VideoCandidate:
    names = {f.name for f in fields(VideoCandidate)}
    payload = {k: data[k] for k in names if k in data}
    return VideoCandidate(**payload)


def acquire_broll_source(
    *,
    job_dir: Path,
    candidate: VideoCandidate,
    clip_length: int,
    parts_needed: int,
    start_offset: float,
    split_full_source: bool,
    subject: str,
    use_vision: bool,
    frame_gate: bool,
    jobs_root: Path | None,
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    video_id = candidate.video_id
    workspace = source_workspace(job_dir, video_id)
    cleanup_workspace(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    fmt_meta = preflight or {}
    try:
        if split_full_source:
            results = download_videos(
                [candidate],
                output_dir=workspace,
                max_height=1080,
                audio_only=False,
                clip_length=clip_length,
                max_parts=None,
                split_parts=True,
                keep_source=False,
                aspect_ratio="9:16",
                start_offset=start_offset,
                spaced_parts=True,
            )
            if not results or results[0].get("status") != "ok":
                return {"ok": False, "video_id": video_id, "error": "download_failed"}
        else:
            record = download_broll_source_parts(
                candidate,
                output_dir=workspace,
                clip_length=clip_length,
                parts_needed=parts_needed,
                aspect_ratio="9:16",
                max_height=1080,
                start_offset=start_offset,
                preflight_format=fmt_meta,
            )
            if record.get("status") != "ok":
                return {
                    "ok": False,
                    "video_id": video_id,
                    "error": record.get("download_mode") or "download_failed",
                }
            video_id = str(record.get("video_id") or candidate.video_id)
        parts = sorted(workspace.glob(f"{video_id}_part*.mp4"))
        return {
            "ok": True,
            "video_id": video_id,
            "workspace": str(workspace),
            "parts": [p.name for p in parts],
        }
    except Exception as exc:
        cleanup_workspace(workspace)
        return {"ok": False, "video_id": video_id, "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire one B-roll YouTube source into tmp workspace")
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    candidate = _candidate_from_dict(payload["candidate"])
    job_dir = Path(payload["job_dir"])
    result = acquire_broll_source(
        job_dir=job_dir,
        candidate=candidate,
        clip_length=int(payload["clip_length"]),
        parts_needed=int(payload["parts_needed"]),
        start_offset=float(payload.get("start_offset") or 0),
        split_full_source=bool(payload.get("split_full_source")),
        subject=str(payload.get("subject") or ""),
        use_vision=bool(payload.get("use_vision", True)),
        frame_gate=bool(payload.get("frame_gate", True)),
        jobs_root=Path(payload["jobs_root"]) if payload.get("jobs_root") else None,
        preflight=payload.get("preflight"),
    )
    workspace = source_workspace(job_dir, candidate.video_id)
    (workspace / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
