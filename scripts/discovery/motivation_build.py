"""Run Stephen's build_motivation_job.py from the site API."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.motivation_paths import (
    default_job_date,
    job_dir_for,
    motivation_jobs_root,
    motivation_output_rel,
    resolve_job_dir,
)
from discovery.reuse_policy import normalize_reuse_policy, parse_reuse_policy

try:
    from toolchain_env import check_toolchain, format_toolchain_report, subprocess_env
except ImportError:
    subprocess_env = None  # type: ignore[assignment]

    def check_toolchain() -> dict:  # type: ignore[misc]
        return {"ok": True}

    def format_toolchain_report(_check: dict | None = None) -> str:
        return ""

BROLL_PRESETS: list[dict[str, str]] = [
    {"id": "cars", "label": "Luxury Cars", "query": "luxury supercar cinematic 4k short"},
    {"id": "yachts", "label": "Yachts", "query": "luxury yacht cinematic 4k short"},
    {"id": "scenery", "label": "Scenery", "query": "cinematic alpine scenery drone 4k short"},
    {"id": "watches", "label": "Watches", "query": "luxury watch cinematic macro 4k short"},
]


def jobs_dir(root: Path | None = None) -> Path:
    path = (root or project_root()) / "data" / "motivation_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "downloads" / "motivational" / "config.json"


def load_motivation_config(root: Path | None = None) -> dict[str, str]:
    path = config_path(root)
    if not path.is_file():
        return {
            "speaker": "Andrew Tate",
            "speech_query": "motivational speech discipline mindset",
            "broll_query": BROLL_PRESETS[0]["query"],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    speaker = str(data.get("speaker") or "").strip() or "Andrew Tate"
    speech_query = str(data.get("speech_query") or "").strip()
    broll_query = str(data.get("broll_query") or "").strip() or BROLL_PRESETS[0]["query"]
    if not speech_query:
        speech_query = f"{speaker} motivational speech"
    return {"speaker": speaker, "speech_query": speech_query, "broll_query": broll_query}


def _job_path(job_id: str, root: Path | None = None) -> Path:
    return jobs_dir(root) / f"{job_id}.json"


def _write_job(job_id: str, payload: dict[str, Any], root: Path | None = None) -> None:
    _job_path(job_id, root).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_job(job_id: str, root: Path | None = None) -> dict[str, Any] | None:
    path = _job_path(job_id, root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_command(body: dict[str, Any], root: Path) -> tuple[list[str], str, str]:
    config = load_motivation_config(root)
    slug = str(body.get("slug") or "").strip()
    if not slug:
        slug = f"short-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    broll_query = str(body.get("broll_query") or config.get("broll_query") or "").strip()
    if not broll_query:
        raise ValueError("broll_query is required — enter a YouTube search for visuals")

    speech_query = str(body.get("speech_query") or config.get("speech_query") or "").strip()
    speech_url = str(body.get("speech_url") or "").strip()
    speaker = str(body.get("speaker") or config.get("speaker") or "").strip()

    script = root / "scripts" / "build_motivation_job.py"
    cmd = [sys.executable, str(script), "--slug", slug, "--broll-query", broll_query]
    if speech_query:
        cmd.extend(["--speech-query", speech_query])
    if speech_url:
        cmd.extend(["--speech-url", speech_url])
    if speaker:
        cmd.extend(["--speaker", speaker])
    if body.get("min_seconds") is not None:
        cmd.extend(["--min-seconds", str(float(body["min_seconds"]))])
    if body.get("max_seconds") is not None:
        cmd.extend(["--max-seconds", str(float(body["max_seconds"]))])
    if body.get("segment_length") is not None:
        cmd.extend(["--segment-length", str(float(body["segment_length"]))])
    if body.get("apply_grade") is False or body.get("no_grade"):
        cmd.append("--no-grade")
    if body.get("keep_work"):
        cmd.append("--keep-work")
    if body.get("rerender"):
        cmd.append("--rerender")
    hook = str(body.get("hook") or "").strip()
    if hook:
        cmd.extend(["--hook", hook])
    reuse_policy = normalize_reuse_policy(
        str(body.get("reuse_policy") or ""),
        default=parse_reuse_policy(str(body.get("command") or "")),
    )
    cmd.extend(["--reuse-policy", reuse_policy])

    jobs_root = motivation_jobs_root(root)
    job_date = default_job_date()
    job_dir = job_dir_for(slug, jobs_root, job_date=job_date)
    rel_output = motivation_output_rel(root, job_dir, slug)
    cmd.extend(["--job-date", job_date])
    return cmd, slug, rel_output


def start_motivation_build(body: dict[str, Any]) -> dict[str, Any]:
    root = project_root()
    cmd, slug, rel_output = _build_command(body, root)
    job_id = f"motivation_{slug}_{uuid.uuid4().hex[:8]}"
    config = load_motivation_config(root)

    record: dict[str, Any] = {
        "job_id": job_id,
        "slug": slug,
        "status": "queued",
        "speech_query": body.get("speech_query") or config.get("speech_query"),
        "broll_query": body.get("broll_query") or config.get("broll_query"),
        "min_seconds": float(body.get("min_seconds") or 60),
        "max_seconds": float(body.get("max_seconds") or 90),
        "segment_length": float(body.get("segment_length") or 8),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_path": rel_output,
        "poll_url": f"/api/shorts/build/{job_id}",
        "command": " ".join(cmd),
    }
    _write_job(job_id, record, root)

    def _run() -> None:
        current = read_job(job_id, root) or record
        current["status"] = "running"
        current["started_at"] = datetime.now(timezone.utc).isoformat()
        toolchain = check_toolchain()
        current["toolchain"] = toolchain
        _write_job(job_id, current, root)
        try:
            if not toolchain.get("ok"):
                raise RuntimeError(
                    "FFMPEG_NOT_FOUND: "
                    + format_toolchain_report(toolchain)
                    + "\nSet FFMPEG_DIR in scripts/.env or install FFmpeg."
                )
            env = subprocess_env() if subprocess_env else None
            result = subprocess.run(
                cmd,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            log = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            current["log"] = log[-8000:] if log else ""
            output = root / rel_output
            if result.returncode != 0:
                raise RuntimeError(log or f"build_motivation_job exited {result.returncode}")

            job_dir = resolve_job_dir(slug, motivation_jobs_root(root))
            job_json = job_dir / "job.json" if job_dir else None
            if job_json and job_json.is_file():
                payload = json.loads(job_json.read_text(encoding="utf-8"))
                current["speech_youtube_id"] = payload.get("speech_id")
                current["broll_youtube_ids"] = payload.get("broll_ids") or []
                current["duration_sec"] = payload.get("audio_duration")

            if output.is_file():
                from discovery.auto_register import sync_register_best_effort

                reg = sync_register_best_effort(
                    slug=slug,
                    visual_style=body.get("broll_query"),
                    root=root,
                )
                if reg:
                    current["production_video_id"] = reg.get("id")
                    current["video_key"] = reg.get("video_key")
            if body.get("register_site", True) and output.is_file():
                from discovery.site_videos import sync_legacy_renders_to_site

                sync_legacy_renders_to_site(slugs=[slug], root=root, rebuild_catalog=False)

            current["status"] = "completed"
            current["preview_url"] = f"/media/{rel_output}"
        except Exception as exc:
            current["status"] = "failed"
            current["error"] = str(exc)
        current["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_job(job_id, current, root)

    threading.Thread(target=_run, daemon=True).start()
    return record


def build_defaults(root: Path | None = None) -> dict[str, Any]:
    config = load_motivation_config(root)
    return {
        "speaker": config.get("speaker", ""),
        "speech_query": config.get("speech_query", ""),
        "broll_query": config.get("broll_query", ""),
        "min_seconds": 60,
        "max_seconds": 90,
        "segment_length": 8,
        "visual_styles": BROLL_PRESETS,
        "config_path": config_path(root).relative_to(root or project_root()).as_posix(),
    }
