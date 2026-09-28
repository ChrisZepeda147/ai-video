"""Natural-language command jobs — website → Cursor Agent CLI."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.config import cursor_command_jobs_dir, default_db_path, project_root
from discovery.store import DiscoveryStore
from discovery.cursor_bridge import agent_available, create_chat, run_agent
from discovery.production_library import check_reuse, get_video, library_summary_for_agent
from discovery.reuse_policy import parse_reuse_policy
from discovery.driven_visuals import (
    agent_prompt_section,
    parse_daily_video_briefs,
    write_batch_manifest,
)
from discovery.command_montage import run_direct_montage_command, should_use_direct_montage


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_job_key(store) -> str:
    row = store._conn.execute("SELECT COUNT(*) AS cnt FROM cursor_command_jobs").fetchone()
    return f"cmd_{int(row['cnt']) + 1:06d}"


def _job_dir(job_key: str) -> Path:
    path = cursor_command_jobs_dir() / job_key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_prompt_file(job_key: str, prompt: str) -> Path:
    path = _job_dir(job_key) / "CURSOR_COMMAND_PROMPT.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def parse_video_refs(command: str) -> list[int]:
    return [int(match) for match in re.findall(r"\bVideo\s+(\d+)\b", command, flags=re.IGNORECASE)]


def parse_batch_count(command: str, explicit: int | None = None) -> int:
    if explicit is not None and explicit > 1:
        return min(int(explicit), 20)
    patterns = [
        r"\b(?:make|create)\s+(\d+)\s+new?\s*videos?\b",
        r"\b(\d+)\s+new?\s*videos?\b",
        r"\bbatch\s+of\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, command, flags=re.IGNORECASE)
        if match:
            return min(int(match.group(1)), 20)
    return 1


def build_agent_prompt(
    *,
    user_command: str,
    store,
    video_id: int | None = None,
    parent_video_id: int | None = None,
) -> str:
    root = project_root()
    lines = [
        "# Ai-Video production command",
        "",
        "You are operating inside the ai-video private production repo.",
        "Use existing Python scripts and project rules. Do NOT reimplement video logic in the backend.",
        "The dashboard / production library is **memory for Cursor** — organization, component lookup, and history.",
        "Reuse detection is **informational by default**. Do NOT reject a source, timestamp, audio segment,",
        "visual, or component merely because it was used before. Tell the user where it was used; reuse when",
        "the new composition meaningfully differs (new visuals, new excerpt, new hook, version line, etc.).",
        "Discovery references are separate — never put discovery reference IDs into content/used.json.",
        "",
        "## Mandatory workflow",
        "1. Query production library for prior usage context (advisory — never an eligibility filter).",
        "2. Use existing production tooling (build_motivation_job.py, story pipelines, stills, etc.).",
        "3. Create a NEW version when modifying an existing video — do not overwrite originals.",
        "4. Register every completed production video:",
        f"   `python scripts/register_production_video.py --title \"...\" --final-path downloads/...`",
        "5. Preserve modular components (audio, transcript, scenes, visuals, captions, final).",
        "",
        agent_prompt_section(),
        "",
        f"## Reuse policy for this command: {parse_reuse_policy(user_command)}",
        "- allow (default): previously used sources/speakers/topics/segments/components are OK.",
        "- prefer_new: rank fresher material first, but fall back if needed.",
        "- require_new: ONLY when the user explicitly asked for unused / never-used / do-not-reuse material.",
        "",
        "Run toolchain check before downloads:",
        "`python -c \"from toolchain_env import check_toolchain; import json; print(json.dumps(check_toolchain(), indent=2))\"`",
        "",
        "## Production library snapshot",
        library_summary_for_agent(store, limit=25),
        "",
    ]

    refs = parse_video_refs(user_command)
    context_ids = []
    if video_id:
        context_ids.append(video_id)
    if parent_video_id and parent_video_id not in context_ids:
        context_ids.append(parent_video_id)
    for ref in refs:
        if ref not in context_ids:
            context_ids.append(ref)

    for context_id in context_ids:
        video = get_video(store, context_id)
        if not video:
            continue
        meta = video.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        lines.extend(
            [
                f"## Reference video context — Video {video['id']}",
                f"- Video key: {video['video_key']}",
                f"- Title: {video.get('title')}",
                f"- Speaker: {video.get('speaker')}",
                f"- Topic: {video.get('topic')}",
                f"- Hook: {video.get('hook')}",
                f"- Visual style: {meta.get('visual_style') or meta.get('broll_query') or 'unknown'}",
                f"- Source URL: {video.get('source_url')}",
                f"- Source timestamps: {video.get('source_start_sec')}–{video.get('source_end_sec')}",
                f"- Final render: {video.get('final_output_path')}",
                f"- Version: {video.get('version')}",
                "",
                "Prior usage lookup (advisory):",
                f"`python scripts/production_library_cli.py check-reuse --video-id {video['id']}`",
                "",
            ]
        )
        if video.get("components"):
            lines.append("### Reusable components")
            for comp in video["components"]:
                detail = comp.get("local_path") or comp.get("url") or comp.get("text_content") or comp.get("label")
                lines.append(f"- {comp.get('component_type')}: {detail}")
            lines.append("")

    daily_briefs = parse_daily_video_briefs(user_command)
    if daily_briefs:
        manifest_path = write_batch_manifest(briefs=daily_briefs, source_command=user_command)
        lines.extend(
            [
                "## Daily batch brief (process all videos in one session)",
                f"- Batch manifest: `{manifest_path.relative_to(root).as_posix()}`",
                f"- Videos in brief: {len(daily_briefs)}",
                "- Process VIDEO 1, then VIDEO 2, then VIDEO 3 sequentially.",
                "- Register each finished render separately with hook + batch metadata.",
                "",
            ]
        )
        for brief in daily_briefs:
            lines.append(f"### VIDEO {brief.get('slot', '?')}")
            for key in (
                "speaker",
                "topic",
                "hook",
                "visual_direction",
                "duration",
                "description",
                "hashtags",
                "editing_notes",
            ):
                if brief.get(key):
                    lines.append(f"- {key.replace('_', ' ').title()}: {brief[key]}")
            if brief.get("raw"):
                lines.append("")
                lines.append(brief["raw"])
            lines.append("")

    lines.extend(
        [
            "## User command",
            user_command.strip(),
            "",
            "## Helpful commands",
            f"- Motivation job (reuse allowed): `python scripts/build_motivation_job.py --slug ... --broll-query ... --reuse-policy allow`",
            f"- Reuse advisory check: `python scripts/production_library_cli.py check-reuse --transcript \"...\"`",
            f"- Register video: `python scripts/register_production_video.py --help`",
            f"- List library: `python scripts/production_library_cli.py list`",
            "",
            f"Project root: {root.as_posix()}",
        ]
    )
    return "\n".join(lines)


def create_command_job(
    store,
    *,
    user_command: str,
    video_id: int | None = None,
    parent_video_id: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not user_command.strip():
        raise ValueError("command is required")
    job_key = _next_job_key(store)
    if should_use_direct_montage(user_command):
        enriched = user_command.strip()
    else:
        enriched = build_agent_prompt(
            user_command=user_command,
            store=store,
            video_id=video_id,
            parent_video_id=parent_video_id,
        )
    prompt_path = _write_prompt_file(job_key, enriched)
    ts = now_iso()
    store._conn.execute(
        """
        INSERT INTO cursor_command_jobs (
            job_key, user_command, enriched_prompt, status, production_video_id,
            parent_video_id, created_at
        ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
        """,
        (job_key, user_command.strip(), enriched, video_id, parent_video_id or video_id, ts),
    )
    store._conn.commit()
    row = store._conn.execute(
        "SELECT id FROM cursor_command_jobs WHERE job_key = ?",
        (job_key,),
    ).fetchone()
    return {
        "job_key": job_key,
        "job_id": int(row["id"]),
        "status": "queued",
        "user_command": user_command.strip(),
        "prompt_path": prompt_path.relative_to(project_root()).as_posix(),
        "cursor_available": agent_available(),
        "session_id": session_id,
        "poll_url": f"/api/commands/{job_key}",
        "created_at": ts,
        "execution_mode": "direct_montage" if should_use_direct_montage(user_command) else "cursor_agent",
    }


def get_command_job(store, job_key: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        "SELECT * FROM cursor_command_jobs WHERE job_key = ?",
        (job_key,),
    ).fetchone()
    return dict(row) if row else None


def _parse_iso_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _stale_job_minutes() -> int:
    try:
        return max(15, int(os.environ.get("WEEKLY_STALE_JOB_MINUTES", "90")))
    except ValueError:
        return 90


def reconcile_stale_command_jobs(store) -> dict[str, int]:
    """Mark hung running/queued jobs failed (API reload kills daemon agent threads)."""
    max_age = _stale_job_minutes()
    now = datetime.now(timezone.utc)
    failed = restarted = 0
    rows = store._conn.execute(
        """
        SELECT job_key, status, started_at, created_at, user_command
        FROM cursor_command_jobs
        WHERE status IN ('running', 'queued')
        """
    ).fetchall()
    for row in rows:
        job_key = str(row["job_key"])
        status = str(row["status"])
        anchor = _parse_iso_ts(row["started_at"]) or _parse_iso_ts(row["created_at"])
        if not anchor:
            continue
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        age_min = (now - anchor.astimezone(timezone.utc)).total_seconds() / 60.0
        if status == "running" and age_min >= max_age:
            msg = (
                f"Stale after {int(age_min)}m (likely API restart or agent hung). "
                "Retry from Weekly or Command."
            )
            store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'failed', error_message = ?, completed_at = ?
                WHERE job_key = ?
                """,
                (msg, now_iso(), job_key),
            )
            failed += 1
        elif status == "queued" and age_min >= min(15, max_age):
            cmd = str(row["user_command"] or "")
            model = None
            if should_use_direct_montage(cmd):
                start_command_job(store, job_key=job_key, agent_model=None)
            else:
                from discovery.weekly import weekly_agent_model

                start_command_job(store, job_key=job_key, agent_model=weekly_agent_model())
            restarted += 1
    if failed or restarted:
        store._conn.commit()
    return {"stale_failed": failed, "queued_restarted": restarted}


def resume_weekly_queued_jobs(store) -> int:
    """Restart queued jobs still tied to weekly slots (submit thread never ran)."""
    rows = store._conn.execute(
        """
        SELECT DISTINCT j.job_key, j.user_command
        FROM weekly_slots s
        JOIN cursor_command_jobs j ON j.job_key = s.job_key
        WHERE s.status = 'running' AND j.status = 'queued'
        """
    ).fetchall()
    n = 0
    for row in rows:
        cmd = str(row["user_command"] or "")
        model = None
        if not should_use_direct_montage(cmd):
            from discovery.weekly import weekly_agent_model

            model = weekly_agent_model()
        start_command_job(store, job_key=str(row["job_key"]), agent_model=model)
        n += 1
    return n


def list_command_jobs(store, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT job_key, user_command, status, production_video_id, cursor_session_id,
               final_output_path, error_message, created_at, started_at, completed_at
        FROM cursor_command_jobs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _truncate(text: str, limit: int = 120_000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def start_command_job(
    store,
    *,
    job_key: str,
    session_id: str | None = None,
    auto_run: bool = True,
    agent_model: str | None = None,
) -> dict[str, Any]:
    job = get_command_job(store, job_key)
    if not job:
        raise ValueError(f"Job not found: {job_key}")
    if not auto_run:
        return job

    def _run() -> None:
        user_command = str(job.get("user_command") or "")
        if not agent_model and should_use_direct_montage(user_command):
            run_direct_montage_command(job_key=job_key, user_command=user_command)
            return

        thread_store = DiscoveryStore(default_db_path())
        try:
            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'running', started_at = ?
                WHERE job_key = ?
                """,
                (now_iso(), job_key),
            )
            thread_store._conn.commit()

            enriched = job.get("enriched_prompt") or user_command
            active_session = session_id or job.get("cursor_session_id")
            if not active_session and agent_available():
                active_session = create_chat()

            result = run_agent(
                enriched,
                job_id=job_key,
                video_id=job.get("production_video_id"),
                session_id=active_session,
                model=agent_model,
            )

            status = "completed" if result.ok else "failed"
            agent_messages = json.dumps(result.messages[-200:]) if result.messages else None
            thread_store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = ?, cursor_session_id = ?, cursor_request_id = ?,
                    stdout_log = ?, stderr_log = ?, agent_messages_json = ?,
                    agent_result = ?, error_message = ?, completed_at = ?
                WHERE job_key = ?
                """,
                (
                    status,
                    result.session_id,
                    result.request_id,
                    _truncate(result.stdout),
                    _truncate(result.stderr),
                    agent_messages,
                    result.result_text,
                    result.error,
                    now_iso(),
                    job_key,
                ),
            )
            if status == "completed":
                started_row = thread_store._conn.execute(
                    "SELECT started_at FROM cursor_command_jobs WHERE job_key = ?",
                    (job_key,),
                ).fetchone()
                _link_new_videos_to_job(thread_store, job_key, started_row["started_at"] if started_row else None)
            thread_store._conn.commit()
        finally:
            thread_store.close()

    if os.environ.get("CURSOR_BRIDGE_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
    return get_command_job(store, job_key) or {}


def _link_new_videos_to_job(store, job_key: str, started_at: str | None) -> None:
    if not started_at:
        return
    rows = store._conn.execute(
        """
        SELECT id, final_output_path FROM production_library_videos
        WHERE created_at >= ? ORDER BY id DESC LIMIT 5
        """,
        (started_at,),
    ).fetchall()
    if not rows:
        return
    latest = rows[0]
    store._conn.execute(
        """
        UPDATE cursor_command_jobs
        SET production_video_id = ?, final_output_path = ?
        WHERE job_key = ? AND production_video_id IS NULL
        """,
        (latest["id"], latest["final_output_path"], job_key),
    )
    store._conn.commit()


def submit_command(
    store,
    *,
    user_command: str,
    video_id: int | None = None,
    parent_video_id: int | None = None,
    session_id: str | None = None,
    batch_count: int | None = None,
    agent_model: str | None = None,
) -> dict[str, Any]:
    refs = parse_video_refs(user_command)
    if video_id is None and refs:
        video_id = refs[0]

    count = parse_batch_count(user_command, batch_count)
    daily_briefs = parse_daily_video_briefs(user_command)
    if len(daily_briefs) >= 2:
        count = len(daily_briefs)
    if count <= 1:
        record = create_command_job(
            store,
            user_command=user_command,
            video_id=video_id,
            parent_video_id=parent_video_id,
            session_id=session_id,
        )
        started = start_command_job(
            store, job_key=record["job_key"], session_id=session_id, agent_model=agent_model
        )
        record.update(
            {
                "status": started.get("status", "running"),
                "started_at": started.get("started_at"),
            }
        )
        return record

    batch_jobs: list[dict[str, Any]] = []
    shared_session = session_id
    for index in range(count):
        item_command = (
            f"{user_command.strip()}\n\n"
            f"[Mass production item {index + 1} of {count}. "
            f"Vary hook, excerpt, or visuals so each item is a distinct composition. "
            f"Check library for prior usage (advisory). Register each completed video separately.]"
        )
        record = create_command_job(
            store,
            user_command=item_command,
            video_id=video_id,
            parent_video_id=parent_video_id,
            session_id=shared_session,
        )
        started = start_command_job(
            store, job_key=record["job_key"], session_id=shared_session, agent_model=agent_model
        )
        if started.get("cursor_session_id"):
            shared_session = started["cursor_session_id"]
        record.update({"status": started.get("status", "running"), "started_at": started.get("started_at")})
        batch_jobs.append(record)

    return {
        "batch": True,
        "batch_count": count,
        "jobs": batch_jobs,
        "job_key": batch_jobs[0]["job_key"] if batch_jobs else None,
        "poll_url": batch_jobs[0]["poll_url"] if batch_jobs else None,
        "status": "running",
        "user_command": user_command.strip(),
    }
