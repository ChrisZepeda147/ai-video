"""Killable subprocess wrapper for one B-roll source acquisition."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from broll_acquire_workspace import cleanup_workspace, source_workspace
from broll_process_util import kill_process_tree
from youtube_popular_downloader import VideoCandidate

_SCRIPTS_DIR = Path(__file__).resolve().parent
_WORKER = _SCRIPTS_DIR / "broll_source_acquire.py"


def run_broll_source_subprocess(
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
    timeout_sec: float,
) -> dict[str, Any]:
    video_id = candidate.video_id
    job_dir = job_dir.resolve()
    workspace = source_workspace(job_dir, video_id)
    cleanup_workspace(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    req_path = (workspace / "acquire_request.json").resolve()
    payload = {
        "candidate": asdict(candidate),
        "job_dir": str(job_dir),
        "clip_length": clip_length,
        "parts_needed": parts_needed,
        "start_offset": start_offset,
        "split_full_source": split_full_source,
        "subject": subject,
        "use_vision": use_vision,
        "frame_gate": frame_gate,
        "jobs_root": str(jobs_root.resolve()) if jobs_root else None,
        "preflight": preflight,
    }
    req_path.write_text(json.dumps(payload), encoding="utf-8")

    cmd = [sys.executable, str(_WORKER), "--request", str(req_path)]
    proc = subprocess.Popen(
        cmd,
        cwd=str(_SCRIPTS_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        proc.wait(timeout=max(timeout_sec, 1.0))
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f"BROLL_SOURCE_TIMEOUT id={video_id} seconds={timeout_sec:.0f}")
        kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait(timeout=10)

    if proc.stdout and not timed_out:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(line)
    elif timed_out and proc.stdout:
        try:
            proc.stdout.close()
        except OSError:
            pass

    if timed_out:
        cleanup_workspace(workspace)
        return {"ok": False, "video_id": video_id, "timeout": True}

    result_path = workspace / "result.json"
    if proc.returncode != 0 or not result_path.is_file():
        cleanup_workspace(workspace)
        return {
            "ok": False,
            "video_id": video_id,
            "error": f"worker_exit_{proc.returncode}",
        }
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cleanup_workspace(workspace)
        return {"ok": False, "video_id": video_id, "error": "bad_result_json"}
    if not result.get("ok"):
        cleanup_workspace(workspace)
    return result
