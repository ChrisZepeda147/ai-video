"""Weekly 7am automation — Sunday feed, daily 3-video runs, per owner.

Style-ref images only: uploads are mood references for Cursor, not
foreground injected into the render. The runner passes image paths
into the Cursor command so the agent matches that look via B-roll
search + grade. Separate queues per owner (chris | stephen).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from discovery.config import project_root
from discovery.montage_job_errors import command_job_error_summary

OWNERS = ("chris", "stephen")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
VIDEOS_PER_DAY = 3

WEEKLY_AGENT_MODEL = "composer-2.5-fast"


def weekly_agent_model() -> str:
    import os as _os

    return _os.environ.get("WEEKLY_AGENT_MODEL", WEEKLY_AGENT_MODEL).strip() or WEEKLY_AGENT_MODEL


def normalize_owner(owner: str) -> str:
    value = (owner or "").strip().lower()
    if value not in OWNERS:
        raise ValueError(f"owner must be one of: {', '.join(OWNERS)}")
    return value


def week_start_monday(day: date | None = None) -> date:
    day = day or date.today()
    return day - timedelta(days=day.weekday())


def week_id(day: date | None = None) -> str:
    return week_start_monday(day).isoformat()


def slot_date(week_start: str, day: str) -> str:
    base = date.fromisoformat(week_start)
    idx = DAYS.index(day.lower())
    return (base + timedelta(days=idx)).isoformat()


def ensure_weekly_tables(store) -> None:
    store._conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            owner TEXT NOT NULL DEFAULT 'chris',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (week_start, owner)
        )
        """
    )
    store._conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES weekly_plans (id) ON DELETE CASCADE,
            day TEXT NOT NULL,
            slot INTEGER NOT NULL,
            speaker TEXT NOT NULL DEFAULT '',
            visual_direction TEXT NOT NULL DEFAULT '',
            image_paths TEXT NOT NULL DEFAULT '[]',
            brief_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            job_key TEXT,
            video_id INTEGER,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (plan_id, day, slot)
        )
        """
    )
    store._conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weekly_slots_status ON weekly_slots (status)"
    )
    cols = {row["name"] for row in store._conn.execute("PRAGMA table_info(weekly_slots)").fetchall()}
    if "image_prompt" not in cols:
        store._conn.execute("ALTER TABLE weekly_slots ADD COLUMN image_prompt TEXT NOT NULL DEFAULT ''")
    if "require_stills_first" not in cols:
        store._conn.execute(
            "ALTER TABLE weekly_slots ADD COLUMN require_stills_first INTEGER NOT NULL DEFAULT 0"
        )
    if "render_started_at" not in cols:
        store._conn.execute("ALTER TABLE weekly_slots ADD COLUMN render_started_at TEXT")
    store._conn.commit()


def weekly_images_dir(*, owner: str, week_start: str, root: Path | None = None) -> Path:
    path = (root or project_root()) / "downloads" / "weekly" / owner / week_start / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_or_create_plan(store, *, week_start: str, owner: str) -> dict[str, Any]:
    ensure_weekly_tables(store)
    owner = normalize_owner(owner)
    date.fromisoformat(week_start)  # validate
    ts = _now()
    store._conn.execute(
        """
        INSERT INTO weekly_plans (week_start, owner, status, created_at, updated_at)
        VALUES (?, ?, 'draft', ?, ?)
        ON CONFLICT (week_start, owner) DO NOTHING
        """,
        (week_start, owner, ts, ts),
    )
    store._conn.commit()
    row = store._conn.execute(
        "SELECT * FROM weekly_plans WHERE week_start = ? AND owner = ?",
        (week_start, owner),
    ).fetchone()
    return dict(row)


def validate_week_slots(
    slots: list[dict[str, Any]], *, week_start: str, expect_full_week: bool = False
) -> list[str]:
    """Non-blocking warnings for Sunday feed."""
    warnings: list[str] = []
    date.fromisoformat(week_start)
    if week_start < date.today().isoformat():
        warnings.append("Week start is in the past — 7am will not run retroactive days.")
    seen: set[tuple[str, str]] = set()
    filled = 0
    for item in slots:
        day = str(item.get("day") or "").lower()
        if day not in DAYS:
            continue
        speaker = str(item.get("speaker") or "").strip()
        visual = str(item.get("visual_direction") or "").strip()
        if not speaker and not visual and not str(item.get("image_prompt") or "").strip():
            continue
        filled += 1
        if speaker and not visual:
            warnings.append(f"{day} slot {item.get('slot')}: speaker without visual")
        key = (speaker.lower(), visual.lower())
        if key in seen and speaker and visual:
            warnings.append(f"Duplicate speaker+visual: {speaker} / {visual}")
        seen.add(key)
    if expect_full_week and filled < len(DAYS) * VIDEOS_PER_DAY:
        warnings.append(f"Only {filled}/21 cells filled — 7am skips empty days.")
    return warnings


def _slot_content_key(item: dict[str, Any], images_json: str) -> tuple:
    return (
        str(item.get("speaker") or ""),
        str(item.get("visual_direction") or ""),
        str(item.get("image_prompt") or ""),
        images_json,
    )


def save_slots(
    store,
    *,
    week_start: str,
    owner: str,
    slots: list[dict[str, Any]],
    replace_week: bool = False,
    expect_full_week: bool = False,
) -> dict[str, Any]:
    """Sunday feed: upsert slots; preserve done/running unless content changed."""
    import json as _json

    plan = get_or_create_plan(store, week_start=week_start, owner=owner)
    warnings = validate_week_slots(slots, week_start=week_start, expect_full_week=expect_full_week)
    running = store._conn.execute(
        "SELECT COUNT(*) AS n FROM weekly_slots WHERE plan_id = ? AND status = 'running'",
        (plan["id"],),
    ).fetchone()
    if running and int(running["n"]) > 0:
        raise ValueError("Cannot save while a slot is running — wait for Cursor job to finish.")

    existing_rows = {
        (str(r["day"]), int(r["slot"])): dict(r)
        for r in store._conn.execute(
            "SELECT * FROM weekly_slots WHERE plan_id = ?", (plan["id"],)
        ).fetchall()
    }
    ts = _now()
    if replace_week:
        store._conn.execute("DELETE FROM weekly_slots WHERE plan_id = ?", (plan["id"],))
        existing_rows = {}

    touched_keys: set[tuple[str, int]] = set()
    count = 0
    for item in slots:
        day = str(item.get("day") or "").lower()
        if day not in DAYS:
            continue
        slot_no = max(1, min(int(item.get("slot") or 1), VIDEOS_PER_DAY))
        speaker = str(item.get("speaker") or "")
        visual = str(item.get("visual_direction") or "")
        image_prompt = str(item.get("image_prompt") or "")
        if not speaker.strip() and not visual.strip() and not image_prompt.strip():
            if replace_week:
                store._conn.execute(
                    "DELETE FROM weekly_slots WHERE plan_id = ? AND day = ? AND slot = ?",
                    (plan["id"], day, slot_no),
                )
            continue
        images = item.get("image_paths") or []
        images_json = _json.dumps(list(images))
        slot_payload = {
            **item,
            "day": day,
            "slot": slot_no,
            "speaker": speaker,
            "visual_direction": visual,
            "image_paths": images,
            "image_prompt": image_prompt,
            "week_start": week_start,
            "owner": owner,
            "require_stills_first": bool(item.get("require_stills_first")),
        }
        brief = str(item.get("brief_text") or "") or build_slot_brief(slot_payload, image_paths=list(images))
        key = (day, slot_no)
        touched_keys.add(key)
        ex = existing_rows.get(key)
        status = "queued"
        if ex:
            old_images = ex.get("image_paths") or "[]"
            if _slot_content_key(item, images_json) != _slot_content_key(
                {
                    "speaker": ex.get("speaker"),
                    "visual_direction": ex.get("visual_direction"),
                    "image_prompt": ex.get("image_prompt"),
                },
                old_images if isinstance(old_images, str) else _json.dumps(old_images),
            ):
                if ex.get("status") == "done":
                    warnings.append(f"{day} #{slot_no}: content changed — reset from done to queued")
                status = "queued"
            else:
                status = str(ex.get("status") or "queued")
            stills = 1 if bool(item.get("require_stills_first")) else 0
            store._conn.execute(
                """
                UPDATE weekly_slots SET
                    speaker = ?, visual_direction = ?, image_paths = ?, image_prompt = ?,
                    require_stills_first = ?, brief_text = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (speaker, visual, images_json, image_prompt, stills, brief, status, ts, ex["id"]),
            )
        else:
            stills = 1 if bool(item.get("require_stills_first")) else 0
            store._conn.execute(
                """
                INSERT INTO weekly_slots
                    (plan_id, day, slot, speaker, visual_direction, image_paths, image_prompt,
                     require_stills_first, brief_text, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["id"],
                    day,
                    slot_no,
                    speaker,
                    visual,
                    images_json,
                    image_prompt,
                    stills,
                    brief,
                    status,
                    ts,
                    ts,
                ),
            )
        count += 1

    if not replace_week:
        for key, ex in existing_rows.items():
            if key not in touched_keys and str(ex.get("status") or "") == "queued":
                store._conn.execute("DELETE FROM weekly_slots WHERE id = ?", (ex["id"],))

    store._conn.execute(
        "UPDATE weekly_plans SET status = 'ready', updated_at = ? WHERE id = ?",
        (ts, plan["id"]),
    )
    store._conn.commit()
    refresh_plan_completion(store, plan_id=int(plan["id"]))
    return {"plan_id": plan["id"], "slots_saved": count, "warnings": warnings}


def build_slot_brief(slot: dict[str, Any], *, image_paths: list[str] | None = None) -> str:
    from discovery.motivation_command_brief import compose_from_slot

    payload = dict(slot)
    if image_paths is not None:
        payload["image_paths"] = image_paths
    return compose_from_slot(payload)


def enrich_slot_render_times(store, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backfill render_started_at from command job when the column was added later."""
    for slot in slots:
        if slot.get("render_started_at"):
            continue
        job_key = str(slot.get("job_key") or "").strip()
        if not job_key:
            continue
        row = store._conn.execute(
            "SELECT started_at FROM cursor_command_jobs WHERE job_key = ?",
            (job_key,),
        ).fetchone()
        if row and row["started_at"]:
            slot["render_started_at"] = row["started_at"]
    return slots


def get_week(store, *, week_start: str, owner: str) -> dict[str, Any]:
    ensure_weekly_tables(store)
    weekly_reconcile_pipeline(store)
    owner = normalize_owner(owner)
    row = store._conn.execute(
        "SELECT * FROM weekly_plans WHERE week_start = ? AND owner = ?",
        (week_start, owner),
    ).fetchone()
    if not row:
        from discovery.weekly_paste import build_week_progress

        return {"plan": None, "slots": [], "progress": build_week_progress([])}
    import json as _json

    slots = [
        {**dict(r), "image_paths": _json.loads(r["image_paths"] or "[]")}
        for r in store._conn.execute(
            "SELECT * FROM weekly_slots WHERE plan_id = ? ORDER BY day, slot",
            (row["id"],),
        ).fetchall()
    ]
    plan_row = dict(row)
    for slot in slots:
        slot["week_start"] = plan_row["week_start"]
        slot["owner"] = owner
        slot["brief_text"] = build_slot_brief(slot)
    slots = enrich_slot_render_times(store, slots)
    from discovery.weekly_paste import build_week_progress

    return {"plan": plan_row, "slots": slots, "progress": build_week_progress(slots)}


def count_failed_slots_for_calendar_day(store, *, day: str, owner: str | None = None) -> int:
    """Failed slots for a calendar date (for catch-up retry after a bad batch)."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT COUNT(*) AS n FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND s.status = 'failed'
          AND p.status IN ('ready', 'active')
    """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    row = store._conn.execute(query, args).fetchone()
    return int(row["n"] if row else 0)


def due_slots(store, *, day: str, owner: str | None = None) -> list[dict[str, Any]]:
    """Slots due for a calendar date (YYYY-MM-DD). Only ready/active plans, queued slots."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT s.*, p.week_start, p.owner, p.status AS plan_status
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND s.status IN ('queued', 'rerunning')
          AND p.status IN ('ready', 'active')
        """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    query += " ORDER BY p.owner, s.slot"
    import json as _json

    rows = store._conn.execute(query, args).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["image_paths"] = _json.loads(row["image_paths"] or "[]")
        except Exception:
            item["image_paths"] = []
        out.append(item)
    return out


def refresh_plan_completion(store, *, plan_id: int) -> None:
    ensure_weekly_tables(store)
    row = store._conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_n
        FROM weekly_slots WHERE plan_id = ?
        """,
        (plan_id,),
    ).fetchone()
    if not row or int(row["total"] or 0) == 0:
        return
    ts = _now()
    if int(row["done_n"] or 0) >= int(row["total"]):
        store._conn.execute(
            "UPDATE weekly_plans SET status = 'completed', updated_at = ? WHERE id = ?",
            (ts, plan_id),
        )
    store._conn.commit()


def activate_plans_for_day(store, *, day: str) -> None:
    """Mark ready plans active when calendar day falls in that week."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    ts = _now()
    store._conn.execute(
        """
        UPDATE weekly_plans SET status = 'active', updated_at = ?
        WHERE week_start = ? AND status = 'ready'
        """,
        (ts, monday),
    )
    store._conn.commit()


def reconcile_zombie_weekly_slots(store) -> int:
    """Clear weekly rows stuck running with no live job. Queued/rerunning without job_key stays eligible."""
    ensure_weekly_tables(store)
    rows = store._conn.execute(
        """
        SELECT s.id, s.job_key, s.plan_id, s.status
        FROM weekly_slots s
        WHERE s.status IN ('running', 'rerunning')
        """
    ).fetchall()
    cleared = 0
    plan_ids: set[int] = set()
    for row in rows:
        slot_id = int(row["id"])
        job_key = str(row["job_key"] or "").strip()
        if not job_key:
            st = str(row["status"] or "")
            if st == "rerunning":
                mark_slot(
                    store,
                    slot_id,
                    status="queued",
                    job_key=None,
                    error="",
                    reset_job_key=True,
                )
            else:
                mark_slot(
                    store,
                    slot_id,
                    status="failed",
                    job_key=None,
                    error="Batch interrupted (no active job — often API restart). Run this day again.",
                    reset_job_key=True,
                )
            cleared += 1
            plan_ids.add(int(row["plan_id"]))
            continue
        job = store._conn.execute(
            "SELECT status FROM cursor_command_jobs WHERE job_key = ?",
            (job_key,),
        ).fetchone()
        if not job or str(job["status"] or "") in {"completed", "failed", "cancelled"}:
            _sync_slot_from_job(store, slot_id, job_key)
            cleared += 1
            plan_ids.add(int(row["plan_id"]))
    for pid in plan_ids:
        refresh_plan_completion(store, plan_id=pid)
    return cleared


def weekly_reconcile_pipeline(store) -> dict[str, Any]:
    """Stale jobs → slot status sync → resume stuck queued."""
    from discovery.command_jobs import reconcile_stale_command_jobs, resume_weekly_queued_jobs

    zombies = reconcile_zombie_weekly_slots(store)
    stale = reconcile_stale_command_jobs(store)
    slots = reconcile_slots(store)
    resumed = resume_weekly_queued_jobs(store)
    return {"stale": stale, "slots": slots, "resumed": resumed, "zombies": zombies}


def reconcile_slots(store) -> dict[str, int]:
    """Sync running slots with cursor_command_jobs status (done/failed + video)."""
    ensure_weekly_tables(store)
    rows = store._conn.execute(
        """
        SELECT s.id, s.job_key, s.plan_id
        FROM weekly_slots s
        WHERE s.status = 'running' AND s.job_key IS NOT NULL
        """
    ).fetchall()
    done = failed = 0
    plan_ids: set[int] = set()
    for row in rows:
        job = store._conn.execute(
            """
            SELECT status, production_video_id, error_message, error_summary, stdout_log, stderr_log
            FROM cursor_command_jobs WHERE job_key = ?
            """,
            (row["job_key"],),
        ).fetchone()
        if not job:
            continue
        status = str(job["status"] or "")
        if status == "completed":
            mark_slot(
                store,
                int(row["id"]),
                status="done",
                video_id=job["production_video_id"],
                error="",
            )
            done += 1
            plan_ids.add(int(row["plan_id"]))
        elif status in {"failed", "cancelled"}:
            mark_slot(
                store,
                int(row["id"]),
                status="failed",
                error=command_job_error_summary(dict(job)),
            )
            failed += 1
            plan_ids.add(int(row["plan_id"]))
    for pid in plan_ids:
        refresh_plan_completion(store, plan_id=pid)
    return {"reconciled_done": done, "reconciled_failed": failed}


def mark_slot(
    store,
    slot_id: int,
    *,
    status: str,
    job_key: str | None = None,
    video_id: int | None = None,
    error: str | None = None,
    reset_job_key: bool = False,
) -> None:
    ensure_weekly_tables(store)
    ts = _now()
    touch_render_start = status in ("running", "rerunning")
    if reset_job_key:
        store._conn.execute(
            """
            UPDATE weekly_slots
            SET status = ?, job_key = ?, video_id = COALESCE(?, video_id),
                error_message = ?, updated_at = ?,
                render_started_at = CASE
                    WHEN ? THEN COALESCE(render_started_at, ?)
                    ELSE render_started_at
                END
            WHERE id = ?
            """,
            (status, job_key, video_id, error, ts, touch_render_start, ts, slot_id),
        )
    else:
        store._conn.execute(
            """
            UPDATE weekly_slots
            SET status = ?, job_key = COALESCE(?, job_key),
                video_id = COALESCE(?, video_id),
                error_message = ?, updated_at = ?,
                render_started_at = CASE
                    WHEN ? THEN COALESCE(render_started_at, ?)
                    ELSE render_started_at
                END
            WHERE id = ?
            """,
            (status, job_key, video_id, error, ts, touch_render_start, ts, slot_id),
        )
    store._conn.commit()


def count_running_weekly_slots(store, *, owner: str | None = None) -> int:
    ensure_weekly_tables(store)
    query = """
        SELECT COUNT(*) AS n FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.status = 'running'
    """
    args: list[Any] = []
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    row = store._conn.execute(query, args).fetchone()
    return int(row["n"] if row else 0)


def count_running_command_jobs(store) -> int:
    row = store._conn.execute(
        "SELECT COUNT(*) AS n FROM cursor_command_jobs WHERE status = 'running'"
    ).fetchone()
    return int(row["n"] if row else 0)


def production_queue_busy(store, *, owner: str | None = None) -> bool:
    """True when a weekly slot or Cursor command job is already running."""
    if count_running_command_jobs(store) > 0:
        return True
    return count_running_weekly_slots(store, owner=owner) > 0


def weekly_preflight() -> dict[str, Any]:
    from discovery.config import cursor_api_key, project_root, resolve_python_exe
    from discovery.cursor_bridge import agent_available

    try:
        from toolchain_env import check_toolchain, format_toolchain_report
    except ImportError:

        def check_toolchain() -> dict:  # type: ignore[misc]
            return {"ok": True}

        def format_toolchain_report(_check: dict | None = None) -> str:
            return "toolchain_env missing"

    issues: list[str] = []
    if not resolve_python_exe():
        issues.append("Python not found — set AI_VIDEO_PYTHON in scripts/.env")
    worker = project_root() / "scripts" / "run_direct_job.py"
    if not worker.is_file():
        issues.append(f"Missing detached montage worker: {worker}")
    toolchain = check_toolchain()
    if not toolchain.get("ok"):
        issues.append(format_toolchain_report(toolchain).strip() or "Toolchain check failed")
    ok = len(issues) == 0
    return {
        "ok": ok,
        "agent_available": agent_available(),
        "api_key_set": bool(cursor_api_key()),
        "issues": issues,
        "toolchain": toolchain,
    }


def requeue_slot(store, slot_id: int) -> bool:
    """Reset a failed slot to queued so 7am or Run due can pick it up again."""
    ensure_weekly_tables(store)
    row = store._conn.execute(
        "SELECT status FROM weekly_slots WHERE id = ?", (slot_id,)
    ).fetchone()
    if not row or str(row["status"]) != "failed":
        return False
    ts = _now()
    store._conn.execute(
        """
        UPDATE weekly_slots
        SET status = 'queued', job_key = NULL, error_message = NULL,
            render_started_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (ts, slot_id),
    )
    store._conn.commit()
    return True


def today_slot_stats(store, *, day: str, owner: str | None = None) -> dict[str, int]:
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT s.status, COUNT(*) AS n
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND p.status IN ('ready', 'active')
    """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    query += " GROUP BY s.status"
    stats = {"queued": 0, "rerunning": 0, "running": 0, "done": 0, "failed": 0}
    for row in store._conn.execute(query, args).fetchall():
        key = str(row["status"] or "")
        if key in stats:
            stats[key] = int(row["n"])
    return stats


def _morning_cutoff_hour() -> int:
    import os as _os

    try:
        return max(0, min(23, int(_os.environ.get("WEEKLY_MORNING_HOUR", "7"))))
    except ValueError:
        return 7


def past_morning_cutoff(day_iso: str | None = None) -> bool:
    """True when local time is on/after the configured morning hour for that calendar day."""
    target = date.fromisoformat(day_iso or date.today().isoformat())
    today = date.today()
    if target < today:
        return True
    if target > today:
        return False
    hour = _morning_cutoff_hour()
    return datetime.now().hour >= hour


def day_batch_started_at(store, *, day: str, owner: str | None = None) -> str | None:
    """Earliest montage start for a calendar day (slot stamp or command job started_at)."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT MIN(
            COALESCE(
                s.render_started_at,
                (SELECT j.started_at FROM cursor_command_jobs j WHERE j.job_key = s.job_key)
            )
        ) AS started
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND p.status IN ('ready', 'active')
    """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    row = store._conn.execute(query, args).fetchone()
    started = row["started"] if row else None
    return str(started) if started else None


def day_morning_status(store, *, day: str, owner: str | None = None) -> dict[str, Any]:
    """Per-calendar-day batch outcome for 7am + UI checklist."""
    if owner:
        owner = normalize_owner(owner)
    stats = today_slot_stats(store, day=day, owner=owner)
    batch_started_at = day_batch_started_at(store, day=day, owner=owner)
    filled = sum(stats.values())
    expected = VIDEOS_PER_DAY if filled >= VIDEOS_PER_DAY else max(filled, VIDEOS_PER_DAY)
    last = _read_last_run()
    morning_submitted = bool(
        last
        and str(last.get("day") or "") == day
        and int(last.get("count") or 0) > 0
        and (owner is None or str(last.get("owner") or "") in ("", owner))
    )
    catchup = _read_catchup_state()
    catchup_ran = bool(catchup.get("day") == day and catchup.get("ran"))

    done = int(stats.get("done") or 0)
    running = int(stats.get("running") or 0)
    failed = int(stats.get("failed") or 0)
    queued = int(stats.get("queued") or 0)
    rerunning = int(stats.get("rerunning") or 0)
    waiting = queued + rerunning

    if filled == 0:
        outcome = "empty"
    elif done >= min(expected, filled) and waiting == 0 and running == 0 and failed == 0:
        outcome = "finished"
    elif running > 0 or rerunning > 0 or (done > 0 and waiting > 0):
        outcome = "in_progress"
    elif failed > 0:
        outcome = "failed"
    elif past_morning_cutoff(day) and queued > 0:
        outcome = "not_finished"
    else:
        outcome = "pending"

    return {
        "day": day,
        "expected": expected,
        "filled": filled,
        "stats": stats,
        "outcome": outcome,
        "morning_submitted": morning_submitted,
        "catchup_ran": catchup_ran,
        "past_morning_cutoff": past_morning_cutoff(day),
        "last_run": last,
        "batch_started_at": batch_started_at,
    }


def _catchup_state_path() -> Path:
    return project_root() / "data" / "logs" / "weekly-morning-catchup.json"


def _read_catchup_state() -> dict[str, Any]:
    import json as _json

    path = _catchup_state_path()
    if not path.is_file():
        return {}
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_catchup_state(payload: dict[str, Any]) -> None:
    import json as _json

    path = _catchup_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({**payload, "at": _now()}, indent=2), encoding="utf-8")


def maybe_run_morning_catchup(store) -> dict[str, Any] | None:
    """If 7am task missed and slots still queued, submit morning batch once per day (API startup)."""
    import os as _os

    if _os.environ.get("WEEKLY_MORNING_CATCHUP", "1").strip().lower() in {"0", "false", "no"}:
        return None
    today = date.today().isoformat()
    state = _read_catchup_state()
    due_remaining = sum(len(due_slots(store, day=today, owner=o)) for o in OWNERS)
    failed_remaining = sum(
        count_failed_slots_for_calendar_day(store, day=today, owner=o) for o in OWNERS
    )
    work_remaining = due_remaining + failed_remaining
    if state.get("day") == today and state.get("ran") and work_remaining <= 0:
        return state
    if not past_morning_cutoff(today):
        return None
    if work_remaining <= 0:
        return None
    if count_running_command_jobs(store) > 0 or count_running_weekly_slots(store) > 0:
        return None

    any_due = False
    results: list[dict[str, Any]] = []
    for owner in OWNERS:
        if count_running_weekly_slots(store, owner=owner) > 0:
            continue
        due_n = len(due_slots(store, day=today, owner=owner))
        failed_n = count_failed_slots_for_calendar_day(store, day=today, owner=owner)
        if due_n <= 0 and failed_n <= 0:
            continue
        any_due = True
        batch = run_weekly_due_batch(
            store,
            day=today,
            owner=owner,
            limit=VIDEOS_PER_DAY,
            dry_run=False,
            serial=True,
            wait_complete=True,
            retry_failed=True,
        )
        results.append({"owner": owner, **{k: batch.get(k) for k in ("count", "deferred", "error", "submitted")}})

    if not any_due:
        _write_catchup_state({"day": today, "ran": True, "skipped": "nothing_due"})
        return _read_catchup_state()

    _write_catchup_state({"day": today, "ran": True, "results": results})
    return _read_catchup_state()


def weekly_health(store, *, day: str | None = None, owner: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    if owner:
        owner = normalize_owner(owner)
    pipe = weekly_reconcile_pipeline(store)
    reconcile = pipe.get("slots") or reconcile_slots(store)
    preflight = weekly_preflight()
    due = due_slots(store, day=day, owner=owner)
    stats = today_slot_stats(store, day=day, owner=owner)
    busy = production_queue_busy(store, owner=None)
    last_run = _read_last_run()
    return {
        "day": day,
        "owner": owner,
        "preflight": preflight,
        "reconcile": {**pipe, "slots": reconcile},
        "due_count": len(due),
        "today_stats": stats,
        "day_morning": day_morning_status(store, day=day, owner=owner),
        "queue_busy": busy,
        "running_weekly_slots": count_running_weekly_slots(store),
        "running_command_jobs": count_running_command_jobs(store),
        "agent_model": weekly_agent_model(),
        "last_run": last_run,
        "failed_digest": failed_slots_digest(store, owner=owner),
        "log_tail": tail_weekly_log(lines=40),
    }


def _last_run_path() -> Path:
    return project_root() / "data" / "logs" / "weekly-last-run.json"


def write_last_run(payload: dict[str, Any]) -> None:
    import json as _json

    path = _last_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({**payload, "at": _now()}, indent=2), encoding="utf-8")


def _read_last_run() -> dict[str, Any] | None:
    import json as _json

    path = _last_run_path()
    if not path.is_file():
        return None
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def slot_command_text(slot: dict[str, Any]) -> str:
    """Always use fresh brief template (stored brief may be stale)."""
    return build_slot_brief(slot, image_paths=list(slot.get("image_paths") or []))


def _montage_inline() -> bool:
    import os as _os

    return _os.environ.get("WEEKLY_MONTAGE_INLINE", "").strip().lower() in {"1", "true", "yes"}


def _wait_for_command_job(store, job_key: str, *, deadline: float) -> None:
    import time as _time

    from discovery.command_jobs import get_command_job

    while _time.monotonic() < deadline:
        job = get_command_job(store, job_key)
        if job and str(job.get("status") or "") in {"completed", "failed", "cancelled"}:
            return
        _time.sleep(8)
        reconcile_slots(store)


def _wait_for_production_idle(store, *, deadline: float) -> bool:
    """One montage at a time — wait until no command job is running."""
    import time as _time

    while _time.monotonic() < deadline:
        reconcile_zombie_weekly_slots(store)
        reconcile_slots(store)
        if count_running_command_jobs(store) == 0 and count_running_weekly_slots(store) == 0:
            return True
        _time.sleep(5)
    return False


def weekly_submit_command(
    store,
    *,
    user_command: str,
    slot_id: int | None = None,
    agent_model: str | None = None,
    video_id: int | None = None,
    wait_montage: bool = True,
    wait_timeout_sec: int = 14_400,
    **_: Any,
) -> dict[str, Any]:
    """Weekly direct montage: create job → attach slot → detached worker → wait → sync."""
    from discovery.command_jobs import create_command_job, get_command_job
    from discovery.command_montage import should_use_direct_montage, spawn_direct_montage_job

    if not should_use_direct_montage(user_command):
        raise ValueError("Weekly slot is not a montage brief — re-save the week from ChatGPT paste.")

    record = create_command_job(
        store,
        user_command=user_command,
        video_id=video_id,
    )
    job_key = str(record["job_key"])

    if slot_id is not None:
        mark_slot(
            store,
            int(slot_id),
            status="running",
            job_key=job_key,
            error="",
            reset_job_key=True,
        )

    try:
        spawn_direct_montage_job(store, job_key)
    except Exception as exc:
        if slot_id is not None:
            mark_slot(
                store,
                int(slot_id),
                status="failed",
                job_key=job_key,
                error=str(exc)[:500],
            )
        raise

    if wait_montage or _montage_inline():
        _wait_for_command_job(
            store,
            job_key,
            deadline=__import__("time").monotonic() + max(120, wait_timeout_sec),
        )

    if slot_id is not None:
        _sync_slot_from_job(store, int(slot_id), job_key)

    job = get_command_job(store, job_key)
    return dict(job or record)


def _sync_slot_from_job(store, slot_id: int, job_key: str) -> None:
    from discovery.command_jobs import get_command_job

    job = get_command_job(store, job_key)
    if not job:
        mark_slot(store, slot_id, status="running", job_key=job_key)
        return
    st = str(job.get("status") or "")
    if st == "completed":
        mark_slot(
            store,
            slot_id,
            status="done",
            job_key=job_key,
            video_id=job.get("production_video_id"),
            error="",
        )
    elif st in {"failed", "cancelled"}:
        mark_slot(
            store,
            slot_id,
            status="failed",
            job_key=job_key,
            error=command_job_error_summary(job),
        )
    else:
        mark_slot(store, slot_id, status="running", job_key=job_key, error="")


def export_week(store, *, week_start: str, owner: str) -> dict[str, Any]:
    data = get_week(store, week_start=week_start, owner=owner)
    return {
        "version": 1,
        "week_start": week_start,
        "owner": normalize_owner(owner),
        "plan": data.get("plan"),
        "slots": data.get("slots") or [],
    }


def import_week(store, *, payload: dict[str, Any], replace: bool = True) -> dict[str, Any]:
    week_start = str(payload.get("week_start") or "")
    owner = str(payload.get("owner") or "chris")
    slots = list(payload.get("slots") or [])
    items = [
        {
            "day": s.get("day"),
            "slot": s.get("slot"),
            "speaker": s.get("speaker"),
            "visual_direction": s.get("visual_direction"),
            "image_paths": s.get("image_paths") or [],
            "image_prompt": s.get("image_prompt") or "",
            "require_stills_first": bool(s.get("require_stills_first")),
        }
        for s in slots
    ]
    return save_slots(
        store,
        week_start=week_start,
        owner=owner,
        slots=items,
        replace_week=replace,
    )


def weekly_presets(store, *, owner: str | None = None) -> dict[str, Any]:
    from discovery.combinations import catalog_payload

    catalog = catalog_payload(store, owner=owner, prune_missing=False)
    speakers = sorted(catalog.get("audio_by_speaker") or {})
    visuals: list[str] = []
    for pack in catalog.get("visual_packs") or []:
        title = str(pack.get("title") or pack.get("slug") or "").strip()
        if title:
            visuals.append(title)
    return {"speakers": speakers[:40], "visuals": visuals[:40]}


def failed_slots_digest(store, *, owner: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    ensure_weekly_tables(store)
    query = """
        SELECT s.id, s.day, s.slot, s.speaker, s.error_message, p.week_start, p.owner
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.status = 'failed'
    """
    args: list[Any] = []
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    query += " ORDER BY s.updated_at DESC LIMIT ?"
    args.append(max(1, min(limit, 50)))
    return [dict(r) for r in store._conn.execute(query, args).fetchall()]


def tail_weekly_log(*, lines: int = 80) -> str:
    cap = max(1, min(lines, 500))
    chunks: list[str] = []
    log_dir = project_root() / "data" / "logs"
    for name in ("weekly-montage-worker.log", "weekly-7am.log"):
        path = log_dir / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if content:
            chunks.append(f"=== {name} ===")
            chunks.extend(content[-cap:])
    return "\n".join(chunks)


def restart_weekly_day_batch(
    store,
    *,
    day: str,
    owner: str,
    run_after: bool = True,
    kill_workers: bool = True,
    wait_timeout_sec: int = 14_400,
    submit_fn=None,
) -> dict[str, Any]:
    """Cancel stuck montage jobs for one calendar day, reset incomplete slots, optionally re-run."""
    from discovery.production_pause import kill_local_montage_workers

    ensure_weekly_tables(store)
    owner_norm = normalize_owner(owner)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    reason = "Restarted from Weekly — previous run stopped"

    rows = store._conn.execute(
        """
        SELECT s.id, s.job_key, s.status
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND p.owner = ?
          AND s.status != 'done'
        ORDER BY s.slot
        """,
        (monday, weekday, owner_norm),
    ).fetchall()

    job_keys: set[str] = set()
    slots_reset = 0
    for row in rows:
        key = str(row["job_key"] or "").strip()
        if key:
            job_keys.add(key)
        st = str(row["status"] or "")
        if st == "queued" and not key:
            continue
        if st not in {"running", "rerunning", "failed", "queued"}:
            continue
        mark_slot(
            store,
            int(row["id"]),
            status="queued",
            job_key=None,
            error="",
            reset_job_key=True,
        )
        store._conn.execute(
            "UPDATE weekly_slots SET render_started_at = NULL WHERE id = ?",
            (int(row["id"]),),
        )
        slots_reset += 1
    store._conn.commit()

    extra_running = store._conn.execute(
        "SELECT job_key FROM cursor_command_jobs WHERE status IN ('running', 'queued')"
    ).fetchall()
    for row in extra_running:
        job_keys.add(str(row["job_key"]))

    cancelled: list[str] = []
    ts = _now()
    for key in sorted(job_keys):
        store._conn.execute(
            """
            UPDATE cursor_command_jobs
            SET status = 'cancelled', error_message = ?, completed_at = ?
            WHERE job_key = ? AND status IN ('running', 'queued')
            """,
            (reason, ts, key),
        )
        cancelled.append(key)
    store._conn.commit()

    killed = 0
    if kill_workers:
        killed = kill_local_montage_workers(project_root())

    weekly_reconcile_pipeline(store)
    out: dict[str, Any] = {
        "day": day,
        "owner": owner_norm,
        "jobs_cancelled": len(cancelled),
        "job_keys": cancelled,
        "slots_reset": slots_reset,
        "workers_killed": killed,
    }
    if run_after:
        out["batch"] = run_weekly_due_batch(
            store,
            day=day,
            owner=owner_norm,
            limit=VIDEOS_PER_DAY,
            dry_run=False,
            serial=True,
            wait_complete=True,
            wait_timeout_sec=wait_timeout_sec,
            retry_failed=False,
            submit_fn=submit_fn,
        )
    return out


def run_weekly_retry_slot(
    store,
    slot_id: int,
    *,
    wait_timeout_sec: int = 14_400,
    submit_fn=None,
) -> dict[str, Any]:
    """Re-queue a failed slot and render it through the normal weekly montage path."""
    ensure_weekly_tables(store)
    row = store._conn.execute(
        """
        SELECT s.id, s.day, p.week_start, p.owner
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.id = ?
        """,
        (slot_id,),
    ).fetchone()
    if not row:
        raise ValueError("Slot not found")
    if not requeue_slot(store, slot_id):
        raise ValueError("Slot not found or not failed")
    cal_day = slot_date(str(row["week_start"]), str(row["day"]))
    return run_weekly_due_batch(
        store,
        day=cal_day,
        owner=str(row["owner"]),
        limit=1,
        dry_run=False,
        wait_complete=True,
        wait_timeout_sec=wait_timeout_sec,
        retry_failed=False,
        slot_ids=[slot_id],
        submit_fn=submit_fn,
    )


def run_weekly_due_batch(
    store,
    *,
    day: str,
    owner: str | None = None,
    limit: int = 3,
    dry_run: bool = False,
    serial: bool = True,
    wait_complete: bool = False,
    wait_timeout_sec: int = 14_400,
    retry_failed: bool = False,
    slot_ids: list[int] | None = None,
    submit_fn=None,
) -> dict[str, Any]:
    """Submit due weekly slots. Serial mode: one agent at a time (default 1 per invocation)."""
    import time as _time

    if submit_fn is None:
        submit_fn = weekly_submit_command

    owner_norm = normalize_owner(owner) if owner else None
    activate_plans_for_day(store, day=day)
    weekly_reconcile_pipeline(store)
    reconcile = reconcile_slots(store)
    preflight = weekly_preflight()
    if not dry_run and not preflight["ok"]:
        blocked = {
            "day": day,
            "owner": owner_norm,
            "submitted": [],
            "count": 0,
            "deferred": False,
            "reconcile": reconcile,
            "preflight": preflight,
            "error": "; ".join(preflight["issues"]),
        }
        write_last_run(blocked)
        return blocked

    if retry_failed:
        target = date.fromisoformat(day)
        monday = week_start_monday(target).isoformat()
        weekday = DAYS[target.weekday()]
        fail_query = """
            SELECT s.id FROM weekly_slots s
            JOIN weekly_plans p ON p.id = s.plan_id
            WHERE p.week_start = ? AND s.day = ? AND s.status = 'failed'
              AND p.status IN ('ready', 'active')
        """
        fail_args: list[Any] = [monday, weekday]
        if owner_norm:
            fail_query += " AND p.owner = ?"
            fail_args.append(owner_norm)
        for row in store._conn.execute(fail_query, fail_args).fetchall():
            requeue_slot(store, int(row["id"]))

    due = due_slots(store, day=day, owner=owner_norm)
    if slot_ids:
        want = {int(x) for x in slot_ids}
        due = [s for s in due if int(s["id"]) in want]
    cap = max(1, min(int(limit), 12))
    due = due[:cap]

    if dry_run:
        return {
            "day": day,
            "owner": owner_norm,
            "due": due,
            "due_count": len(due),
            "reconcile": reconcile,
            "preflight": preflight,
            "submitted": [],
            "count": 0,
            "deferred": False,
            "dry_run": True,
        }

    weekly_reconcile_pipeline(store)
    reconcile = reconcile_slots(store)
    if production_queue_busy(store, owner=None):
        return {
            "day": day,
            "owner": owner_norm,
            "submitted": [],
            "count": 0,
            "deferred": True,
            "reason": "running_job",
            "reconcile": reconcile,
            "preflight": preflight,
        }

    wait_complete = True
    max_submit = cap
    submitted: list[dict[str, str]] = []
    deadline = _time.monotonic() + max(60, wait_timeout_sec)
    pending = list(due)

    for slot in pending:
        if len(submitted) >= max_submit:
            break
        if _time.monotonic() >= deadline:
            break
        if not _wait_for_production_idle(store, deadline=deadline):
            break

        slot_id = int(slot["id"])
        row = store._conn.execute(
            "SELECT status FROM weekly_slots WHERE id = ?", (slot_id,)
        ).fetchone()
        if row and str(row["status"]) == "done":
            continue

        command = slot_command_text(slot)
        try:
            result = submit_fn(
                store,
                user_command=command,
                slot_id=slot_id,
                agent_model=None,
                wait_montage=wait_complete,
                wait_timeout_sec=wait_timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001
            mark_slot(store, slot_id, status="failed", error=str(exc)[:500], reset_job_key=True)
            _time.sleep(12)
            continue

        job_key = str(result.get("job_key") or "")
        refresh_plan_completion(store, plan_id=int(slot["plan_id"]))
        submitted.append({"slot_id": str(slot["id"]), "job_key": job_key})
        _time.sleep(12)

    out = {
        "day": day,
        "owner": owner_norm,
        "submitted": submitted,
        "count": len(submitted),
        "deferred": False,
        "reconcile": reconcile,
        "preflight": preflight,
        "agent_model": "direct_montage",
    }
    write_last_run(out)
    return out
