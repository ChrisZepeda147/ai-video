"""Per-job B-roll acquisition state for smart retries."""

from __future__ import annotations

import json
from pathlib import Path


def state_path(job_dir: Path) -> Path:
    return job_dir / "broll_acquire.json"


def load_state(job_dir: Path) -> dict:
    path = state_path(job_dir)
    if not path.is_file():
        return {"failed_source_ids": [], "queries_tried": [], "query_index": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"failed_source_ids": [], "queries_tried": [], "query_index": 0}
    failed = data.get("failed_source_ids") or []
    tried = data.get("queries_tried") or []
    return {
        "failed_source_ids": [str(x) for x in failed if x],
        "queries_tried": [str(x) for x in tried if x],
        "query_index": int(data.get("query_index") or 0),
    }


def save_state(job_dir: Path, state: dict) -> None:
    path = state_path(job_dir)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_failed_source(job_dir: Path, video_id: str) -> None:
    if not video_id:
        return
    state = load_state(job_dir)
    ids = list(dict.fromkeys([*state["failed_source_ids"], video_id]))
    state["failed_source_ids"] = ids
    save_state(job_dir, state)


def record_query_attempt(job_dir: Path, query: str) -> None:
    state = load_state(job_dir)
    tried = list(dict.fromkeys([*state["queries_tried"], query]))
    state["queries_tried"] = tried
    save_state(job_dir, state)


def bump_query_index(job_dir: Path, index: int) -> None:
    state = load_state(job_dir)
    state["query_index"] = index
    save_state(job_dir, state)
