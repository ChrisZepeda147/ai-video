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

from discovery.config import default_db_path, project_root, resolve_python_exe
from discovery.motivation_build import _build_command
from discovery.reuse_policy import normalize_reuse_policy, parse_reuse_policy
from discovery.store import DiscoveryStore

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _subprocess_run(*popenargs, **kwargs):
    """subprocess.run without flashing a console on Windows."""
    if sys.platform == "win32" and "creationflags" not in kwargs:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(*popenargs, **kwargs)


try:
    from toolchain_env import check_toolchain, format_toolchain_report, subprocess_env
except ImportError:
    subprocess_env = None  # type: ignore[assignment]

    def check_toolchain() -> dict:  # type: ignore[misc]
        return {"ok": True}

    def format_toolchain_report(_check: dict | None = None) -> str:
        return ""


def _montage_actionable_error(
    stdout: str,
    stderr: str,
    *,
    exit_code: int | None = None,
):
    scripts = project_root() / "scripts"
    path = str(scripts)
    if path not in sys.path:
        sys.path.insert(0, path)
    from montage_telemetry import resolve_actionable_error

    return resolve_actionable_error(stdout, stderr, exit_code=exit_code)


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

    min_sec = 30.0
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

    speaker: str | None = _first_match(
        r"^Requested speaker:\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if speaker:
        speaker = speaker.strip().strip("\"'")
    audio_hint = (speech_query or "").lower()
    if not speaker and ("hormozi" in audio_hint or "alex hormozi" in (text or "").lower()):
        speaker = "Alex Hormozi"
    if not speaker and speech_query:
        try:
            from discovery.speaker_identity import infer_speaker

            speaker = infer_speaker(speech_query)
        except ImportError:
            pass

    extra_match = re.search(r"Extra instructions:\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if extra_match:
        extra = re.split(r"Before downloading audio", extra_match.group(1), maxsplit=1)[0].strip()
        if not extra:
            reuse_policy = "allow"
        else:
            reuse_policy = parse_reuse_policy(extra)
    else:
        extra = ""
        reuse_policy = parse_reuse_policy(text)
    reuse_policy = normalize_reuse_policy(reuse_policy, default="allow")

    extra_duration = re.search(r"(\d+)\s*-\s*(\d+)\s*seconds", extra, flags=re.IGNORECASE)
    if extra_duration:
        min_sec = float(extra_duration.group(1))
        max_sec = float(extra_duration.group(2))

    video_count = 1
    if re.search(r"\btwo videos\b", extra, flags=re.IGNORECASE):
        video_count = 2
    else:
        count_match = re.search(r"\b(\d+)\s+videos?\b", extra, flags=re.IGNORECASE)
        if count_match:
            video_count = min(int(count_match.group(1)), 10)

    opener_note = ""
    if re.search(r"stunning view|strong opener|first clip", extra, flags=re.IGNORECASE):
        opener_note = "stunning view opener"

    slug_from_brief = _first_match(r"Use job slug:\s*`([^`]+)`", text, flags=re.IGNORECASE)
    if slug_from_brief:
        slug = re.sub(r"[^a-z0-9-]+", "-", slug_from_brief.lower()).strip("-")[:80]
    else:
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
        "video_count": video_count,
        "opener_note": opener_note,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_speech_url(title: str, root: Path) -> str | None:
    query = title.strip()
    if not query:
        return None
    try:
        result = _subprocess_run(
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

            # Only use speech_url when the brief names a URL — do not ytsearch1-pin one video
            # (that bypasses multi-candidate search and fails fast on 403 / bad windows).
            speech_url = plan.get("speech_url")

            toolchain = check_toolchain()
            if not toolchain.get("ok"):
                raise RuntimeError(
                    "FFMPEG_NOT_FOUND: "
                    + format_toolchain_report(toolchain)
                )

            env = dict(subprocess_env() if subprocess_env else os.environ)
            env["PUBLISHING_OWNER"] = str(plan.get("owner") or "chris")

            broll_query = str(plan["broll_query"])
            if plan.get("opener_note") and "drone" not in broll_query.lower():
                broll_query = f"{broll_query} drone cinematic"

            video_count = max(1, int(plan.get("video_count") or 1))
            logs: list[str] = []
            last_slug = plan["slug"]
            last_output: Path | None = None
            production_video_id = None

            for index in range(video_count):
                slug = plan["slug"] if index == 0 else f"{plan['slug']}-v{index + 1}"
                body = {
                    "slug": slug,
                    "speech_query": plan.get("speech_query"),
                    "broll_query": broll_query,
                    "speech_url": speech_url,
                    "speaker": plan.get("speaker"),
                    "min_seconds": plan.get("min_seconds"),
                    "max_seconds": plan.get("max_seconds"),
                    "reuse_policy": plan.get("reuse_policy"),
                    "command": command_text,
                    "hook": plan.get("hook"),
                }
                cmd, slug, rel_output = _build_command(body, root)
                result = _subprocess_run(
                    cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                part_log = "\n".join(p for p in (result.stdout, result.stderr) if p).strip()
                if part_log:
                    logs.append(f"=== build {index + 1}/{video_count} ({slug}) ===\n{part_log}")
                if result.returncode != 0:
                    truncated = "\n\n".join(logs)[-120_000:]
                    summary, _failure = _montage_actionable_error(
                        truncated,
                        "",
                        exit_code=result.returncode,
                    )
                    thread_store._conn.execute(
                        """
                        UPDATE cursor_command_jobs
                        SET status = 'failed', stdout_log = ?, stderr_log = ?, error_message = ?,
                            error_summary = ?, completed_at = ?
                        WHERE job_key = ?
                        """,
                        (
                            truncated,
                            "",
                            truncated or f"exit {result.returncode} on video {index + 1}",
                            summary,
                            _now_iso(),
                            job_key,
                        ),
                    )
                    thread_store._conn.commit()
                    return
                output = root / rel_output
                last_slug = slug
                last_output = output
                if output.is_file():
                    from discovery.auto_register import sync_register_best_effort

                    reg = sync_register_best_effort(
                        slug=slug,
                        visual_style=plan.get("broll_query"),
                        root=root,
                    )
                    if reg:
                        production_video_id = reg.get("id")
                    try:
                        from discovery.site_videos import sync_legacy_renders_to_site

                        sync_legacy_renders_to_site(slugs=[slug], root=root, rebuild_catalog=False)
                    except Exception:
                        pass

            truncated = "\n\n".join(logs)[-120_000:]
            rel_output = (
                last_output.relative_to(root).as_posix()
                if last_output and last_output.is_file()
                else None
            )
            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'completed', stdout_log = ?, stderr_log = '', agent_result = ?,
                    final_output_path = ?, production_video_id = ?, completed_at = ?
                WHERE job_key = ?
                """,
                (
                    truncated,
                    f"Direct montage: {video_count} video(s) ({last_slug}).",
                    rel_output,
                    production_video_id,
                    _now_iso(),
                    job_key,
                ),
            )
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

    if block:
        _run()
        return
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def spawn_direct_montage_job(store, job_key: str) -> None:
    """Start montage in a detached process so API reload does not kill the render."""
    root = project_root()
    python = resolve_python_exe()
    script = root / "scripts" / "run_direct_job.py"
    if not script.is_file():
        raise FileNotFoundError(f"Missing {script}")

    env = dict(subprocess_env() if subprocess_env else os.environ)
    env["AI_VIDEO_PYTHON"] = python
    exe = Path(python)
    pythonw = exe.with_name("pythonw.exe")
    launch_python = str(pythonw) if pythonw.is_file() else python
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0

    store._conn.execute(
        """
        UPDATE cursor_command_jobs
        SET status = 'running', started_at = ?, error_message = NULL
        WHERE job_key = ?
        """,
        (_now_iso(), job_key),
    )
    store._conn.commit()

    try:
        subprocess.Popen(
            [launch_python, str(script), "--job-key", job_key],
            cwd=root,
            env=env,
            creationflags=flags,
            close_fds=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        msg = f"Failed to launch direct montage worker: {exc}"[:500]
        store._conn.execute(
            """
            UPDATE cursor_command_jobs
            SET status = 'failed', error_message = ?, completed_at = ?
            WHERE job_key = ?
            """,
            (msg, _now_iso(), job_key),
        )
        store._conn.commit()
        raise RuntimeError(msg) from exc


def should_use_direct_montage(text: str) -> bool:
    if os.environ.get("COMMAND_FORCE_AGENT", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return is_direct_montage_command(text)
