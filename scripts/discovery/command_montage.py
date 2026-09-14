"""Fast path: run luxury-clips montage without Cursor Agent."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import default_db_path, project_root
from discovery.motivation_build import _build_command
from discovery.reuse_policy import normalize_reuse_policy, parse_reuse_policy
from discovery.store import DiscoveryStore

try:
    from toolchain_env import check_toolchain, format_toolchain_report, subprocess_env
except ImportError:
    subprocess_env = None  # type: ignore[assignment]

    def check_toolchain() -> dict:  # type: ignore[misc]
        return {"ok": True}

    def format_toolchain_report(_check: dict | None = None) -> str:
        return ""


def is_direct_montage_command(text: str) -> bool:
    lower = (text or "").lower()
    return "luxury-clips-montage" in lower or "build_motivation_job.py" in lower


def _first_match(pattern: str, text: str, *, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return match.group(1).strip()


def parse_montage_command(text: str) -> dict[str, Any] | None:
    if not is_direct_montage_command(text):
        return None

    speech_query = _first_match(
        r"Search for audio(?:[^\n:]*)?:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    broll_query = _first_match(
        r"Visual / B-roll search:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if not broll_query:
        return None

    owner = (_first_match(r"Owner account:\s*(chris|stephen)", text, flags=re.IGNORECASE) or "chris").lower()
    hook = _first_match(r"^Hook:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    source_title = _first_match(
        r"^Source:\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not source_title:
        source_title = _first_match(
            r"^Source:\s*\r?\n(.+)$",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    if source_title:
        source_title = re.sub(r"^Official video\s+", "", source_title.strip(), flags=re.IGNORECASE)
        source_title = source_title.strip("\"'“”")

    min_sec = 60.0
    max_sec = 90.0
    length_match = re.search(
        r"Default target length:\s*(\d+)\s*[–-]\s*(\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if length_match:
        min_sec = float(length_match.group(1))
        max_sec = float(length_match.group(2))

    url_match = re.search(r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s]+)", text, flags=re.IGNORECASE)
    speech_url = url_match.group(1) if url_match else None

    speech_url_from_text = _first_match(
        r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+)",
        text,
        flags=re.IGNORECASE,
    )
    if speech_url_from_text:
        speech_url = speech_url_from_text
    if source_title:
        # Prefer official source title over broad search when user named a specific video.
        speech_query = source_title

    speaker: str | None = None
    audio_hint = (speech_query or "").lower()
    if "hormozi" in audio_hint or "alex hormozi" in (text or "").lower():
        speaker = "Alex Hormozi"

    reuse_policy = parse_reuse_policy(text)
    if re.search(r"require_new|do not reuse|never used|unused-only", text, flags=re.IGNORECASE):
        reuse_policy = "require_new"
    reuse_policy = normalize_reuse_policy(reuse_policy, default="allow")

    slug_base = re.sub(r"[^a-z0-9]+", "-", (speech_query or broll_query or "short").lower()).strip("-")[:36]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = f"{slug_base or 'short'}-{stamp}"

    return {
        "slug": slug,
        "speech_query": speech_query,
        "broll_query": broll_query,
        "speech_url": speech_url,
        "speaker": speaker,
        "hook": hook,
        "owner": owner,
        "min_seconds": min_sec,
        "max_seconds": max_sec,
        "reuse_policy": reuse_policy,
        "command": text,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_speech_url(title: str, root: Path) -> str | None:
    query = title.strip()
    if not query:
        return None
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                f"ytsearch1:{query}",
                "--print",
                "webpage_url",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=subprocess_env() if subprocess_env else None,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        url = line.strip()
        if url.startswith("http"):
            return url
    return None


def run_direct_montage_command(
    *,
    job_key: str,
    user_command: str | None = None,
    block: bool = False,
) -> None:
    """Execute build_motivation_job in a background thread and update cursor_command_jobs."""

    def _run() -> None:
        thread_store = DiscoveryStore(default_db_path())
        try:
            job = thread_store._conn.execute(
                "SELECT * FROM cursor_command_jobs WHERE job_key = ?",
                (job_key,),
            ).fetchone()
            if not job:
                raise ValueError(f"Job not found: {job_key}")

            command_text = user_command or str(job["user_command"] or "")
            plan = parse_montage_command(command_text)
            if not plan:
                raise ValueError("Not a direct montage command")

            root = project_root()
            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'running', started_at = ?, error_message = NULL
                WHERE job_key = ?
                """,
                (_now_iso(), job_key),
            )
            thread_store._conn.commit()

            speech_url = plan.get("speech_url")
            if not speech_url and plan.get("speech_query"):
                speech_url = _resolve_speech_url(str(plan["speech_query"]), root)

            body = {
                "slug": plan["slug"],
                "speech_query": plan.get("speech_query"),
                "broll_query": plan["broll_query"],
                "speech_url": speech_url,
                "speaker": plan.get("speaker"),
                "min_seconds": plan.get("min_seconds"),
                "max_seconds": plan.get("max_seconds"),
                "reuse_policy": plan.get("reuse_policy"),
                "command": command_text,
                "hook": plan.get("hook"),
            }
            cmd, slug, rel_output = _build_command(body, root)

            toolchain = check_toolchain()
            if not toolchain.get("ok"):
                raise RuntimeError(
                    "FFMPEG_NOT_FOUND: "
                    + format_toolchain_report(toolchain)
                )

            env = dict(subprocess_env() if subprocess_env else os.environ)
            env["PUBLISHING_OWNER"] = str(plan.get("owner") or "chris")

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
            truncated = log[-120_000:] if log else ""

            if result.returncode != 0:
                thread_store._conn.execute(
                    """
                    UPDATE cursor_command_jobs
                    SET status = 'failed', stdout_log = ?, stderr_log = ?, error_message = ?,
                        completed_at = ?
                    WHERE job_key = ?
                    """,
                    (truncated, "", truncated or f"exit {result.returncode}", _now_iso(), job_key),
                )
                thread_store._conn.commit()
                return

            output = root / rel_output
            production_video_id = None
            if output.is_file():
                from discovery.auto_register import sync_register_best_effort

                reg = sync_register_best_effort(
                    slug=slug,
                    visual_style=plan.get("broll_query"),
                    root=root,
                )
                if reg:
                    production_video_id = reg.get("id")

            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'completed', stdout_log = ?, stderr_log = '', agent_result = ?,
                    final_output_path = ?, production_video_id = ?, completed_at = ?
                WHERE job_key = ?
                """,
                (
                    truncated,
                    f"Direct montage build completed ({slug}).",
                    rel_output if output.is_file() else None,
                    production_video_id,
                    _now_iso(),
                    job_key,
                ),
            )
            if output.is_file():
                try:
                    from discovery.site_videos import sync_legacy_renders_to_site

                    sync_legacy_renders_to_site(slugs=[slug], root=root, rebuild_catalog=False)
                except Exception:
                    pass
            thread_store._conn.commit()
        except Exception as exc:
            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'failed', error_message = ?, completed_at = ?
                WHERE job_key = ?
                """,
                (str(exc), _now_iso(), job_key),
            )
            thread_store._conn.commit()
        finally:
            thread_store.close()

    thread = threading.Thread(target=_run, daemon=not block)
    thread.start()
    if block:
        thread.join()


def should_use_direct_montage(text: str) -> bool:
    if os.environ.get("COMMAND_FORCE_AGENT", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return is_direct_montage_command(text)
