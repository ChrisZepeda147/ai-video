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
          AND p.status IN ('ready', 'active', 'completed')
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


def slots_for_calendar_day(
    store, *, day: str, owner: str | None = None
) -> list[dict[str, Any]]:
    """All weekly slots for a calendar date, ordered 1 → 3 (any status)."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT s.*, p.week_start, p.owner, p.status AS plan_status
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ?
          AND p.status IN ('ready', 'active', 'completed')
    """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    query += " ORDER BY s.slot"
    import json as _json

    rows = store._conn.execute(query, args).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["image_paths"] = _json.loads(row["image_paths"] or "[]")
        except Exception:
            item["image_paths"] = []
        out.append(item)
    return out


def _fetch_slot_record(store, slot_id: int) -> dict[str, Any] | None:
    import json as _json

    row = store._conn.execute(
        """
        SELECT s.*, p.week_start, p.owner, p.status AS plan_status
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.id = ?
        """,
        (slot_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["image_paths"] = _json.loads(row["image_paths"] or "[]")
    except Exception:
        item["image_paths"] = []
    return item


def _slot_status(store, slot_id: int) -> str:
    row = store._conn.execute(
        "SELECT status FROM weekly_slots WHERE id = ?", (slot_id,)
    ).fetchone()
    return str(row["status"] or "") if row else ""


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
                prepare_slot_for_retry(
                    store,
                    slot_id,
                    error="Batch interrupted (no active job — often API restart). Retrying.",
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
            prepare_slot_for_retry(
                store,
                int(row["id"]),
                error=command_job_error_summary(dict(job)),
            )
            request_daily_fill_kick(store, slot_id=int(row["id"]))
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


def requeue_failed_slots_for_calendar_day(
    store, *, day: str, owner: str | None = None
) -> int:
    """Move all failed slots for a calendar day back to queued (auto-retry)."""
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT s.id FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ? AND s.status = 'failed'
          AND p.status IN ('ready', 'active')
    """
    args: list[Any] = [monday, weekday]
    if owner:
        query += " AND p.owner = ?"
        args.append(normalize_owner(owner))
    n = 0
    for row in store._conn.execute(query, args).fetchall():
        if requeue_slot(store, int(row["id"])):
            n += 1
    return n


def planned_slots_for_calendar_day(store, *, day: str, owner: str | None = None) -> int:
    stats = today_slot_stats(store, day=day, owner=owner)
    return sum(int(v) for v in stats.values())


def day_fill_complete(store, *, day: str, owner: str) -> bool:
    stats = today_slot_stats(store, day=day, owner=owner)
    return int(stats.get("done") or 0) >= VIDEOS_PER_DAY and int(stats.get("failed") or 0) == 0


def _fill_max_rounds() -> int:
    import os as _os

    try:
        return max(1, min(48, int(_os.environ.get("WEEKLY_FILL_MAX_ROUNDS", "24"))))
    except ValueError:
        return 24


def _fill_round_sleep_sec() -> int:
    import os as _os

    try:
        return max(15, int(_os.environ.get("WEEKLY_FILL_ROUND_SLEEP_SEC", "45")))
    except ValueError:
        return 45


def _fill_slot_wait_sec() -> int:
    import os as _os

    from discovery.config import weekly_montage_job_timeout_sec

    override = _os.environ.get("WEEKLY_FILL_SLOT_WAIT_SEC", "").strip()
    if override:
        try:
            return max(600, int(override))
        except ValueError:
            pass
    return weekly_montage_job_timeout_sec() + 300


def _slot_retry_sleep_sec() -> int:
    import os as _os

    try:
        return max(0, int(_os.environ.get("WEEKLY_SLOT_RETRY_SLEEP_SEC", "0")))
    except ValueError:
        return 0


def _fill_fail_round_sleep_sec() -> int:
    import os as _os

    try:
        return max(0, int(_os.environ.get("WEEKLY_FILL_FAIL_SLEEP_SEC", "0")))
    except ValueError:
        return 0


def _slot_max_attempts_per_slot() -> int:
    import os as _os

    try:
        return max(1, min(64, int(_os.environ.get("WEEKLY_SLOT_MAX_ATTEMPTS", "32"))))
    except ValueError:
        return 32


def _append_fill_log(line: str) -> None:
    path = project_root() / "data" / "logs" / "weekly-fill.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  {line}\n")


def _round_robin_state_path() -> Path:
    return project_root() / "data" / "logs" / "weekly-round-robin.json"


def round_robin_key(owner: str, day_iso: str) -> str:
    return f"{normalize_owner(owner)}:{day_iso}"


def _read_round_robin_state() -> dict[str, int]:
    import json as _json

    path = _round_robin_state_path()
    if not path.is_file():
        return {}
    try:
        raw = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, val in raw.items():
        try:
            out[str(key)] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def _write_round_robin_state(state: dict[str, int]) -> None:
    import json as _json

    path = _round_robin_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(state, indent=2), encoding="utf-8")


def clear_round_robin_cursor(*, owner: str, day: str) -> None:
    key = round_robin_key(owner, day)
    state = _read_round_robin_state()
    if key in state:
        del state[key]
        _write_round_robin_state(state)


def set_round_robin_cursor(*, owner: str, day: str, next_slot: int) -> None:
    key = round_robin_key(owner, day)
    state = _read_round_robin_state()
    state[key] = int(next_slot)
    _write_round_robin_state(state)


def get_round_robin_cursor(*, owner: str, day: str) -> int | None:
    val = _read_round_robin_state().get(round_robin_key(owner, day))
    return int(val) if val is not None else None


def _advance_round_robin_cursor(slot_numbers: list[int], attempted_slot: int) -> int:
    if not slot_numbers:
        return 1
    try:
        idx = slot_numbers.index(attempted_slot)
    except ValueError:
        return slot_numbers[0]
    return slot_numbers[(idx + 1) % len(slot_numbers)]


def _round_robin_select_slot(
    store,
    *,
    day: str,
    owner: str,
    allowed_slot_ids: set[int] | None = None,
    advance_cursor: bool,
    requeue_failed: bool,
) -> dict[str, Any] | None:
    owner_norm = normalize_owner(owner)
    ordered = slots_for_calendar_day(store, day=day, owner=owner_norm)
    if allowed_slot_ids is not None:
        ordered = [s for s in ordered if int(s["id"]) in allowed_slot_ids]
    if not ordered:
        return None

    slot_numbers = sorted({int(s.get("slot") or 0) for s in ordered if int(s.get("slot") or 0) > 0})
    if not slot_numbers:
        return None

    by_no = {int(s.get("slot") or 0): s for s in ordered}
    key = round_robin_key(owner_norm, day)
    state = _read_round_robin_state()
    cursor = int(state.get(key, slot_numbers[0]))
    if cursor not in slot_numbers:
        cursor = slot_numbers[0]

    start_idx = slot_numbers.index(cursor)
    for offset in range(len(slot_numbers)):
        slot_no = slot_numbers[(start_idx + offset) % len(slot_numbers)]
        row = by_no.get(slot_no)
        if not row:
            continue
        slot_id = int(row["id"])
        status = _slot_status(store, slot_id)
        if status == "done":
            continue
        if status == "running":
            return None
        if status == "failed":
            if requeue_failed:
                requeue_slot(store, slot_id)
            else:
                continue
        if advance_cursor:
            next_cursor = _advance_round_robin_cursor(slot_numbers, slot_no)
            state[key] = next_cursor
            _write_round_robin_state(state)
        return row

    if advance_cursor:
        clear_round_robin_cursor(owner=owner_norm, day=day)
    return None


def pick_next_round_robin_slot(
    store,
    *,
    day: str,
    owner: str,
    allowed_slot_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    """Next unfinished slot for one attempt (round-robin; persists cursor across API restarts)."""
    return _round_robin_select_slot(
        store,
        day=day,
        owner=owner,
        allowed_slot_ids=allowed_slot_ids,
        advance_cursor=True,
        requeue_failed=True,
    )


def peek_next_round_robin_slot(
    store,
    *,
    day: str,
    owner: str,
) -> dict[str, Any] | None:
    """Read-only: next slot automation would attempt (no cursor or requeue side effects)."""
    return _round_robin_select_slot(
        store,
        day=day,
        owner=owner,
        allowed_slot_ids=None,
        advance_cursor=False,
        requeue_failed=False,
    )


def run_weekly_fill_day(
    store,
    *,
    day: str,
    owner: str,
    dry_run: bool = False,
    submit_fn=None,
) -> dict[str, Any]:
    """Run serial montages until all 3 slots for this owner/day are done (re-queue failures)."""
    import time as _time

    owner_norm = normalize_owner(owner)
    if planned_slots_for_calendar_day(store, day=day, owner=owner_norm) <= 0:
        return {
            "day": day,
            "owner": owner_norm,
            "complete": True,
            "rounds": 0,
            "submitted": [],
            "skipped": "no_plan",
        }

    if dry_run:
        requeue_failed_slots_for_calendar_day(store, day=day, owner=owner_norm)
        due = due_slots(store, day=day, owner=owner_norm)
        stats = today_slot_stats(store, day=day, owner=owner_norm)
        return {
            "day": day,
            "owner": owner_norm,
            "dry_run": True,
            "due_count": len(due),
            "today_stats": stats,
            "complete": day_fill_complete(store, day=day, owner=owner_norm),
        }

    rounds = 0
    tick = _automation_tick_sec()

    while not day_fill_complete(store, day=day, owner=owner_norm):
        rounds += 1
        from discovery.production_pause import is_production_paused

        if is_production_paused():
            break
        result = weekly_automation_tick(store, day=day, owner=owner_norm)
        if result.get("action") in {"week_complete", "day_complete"}:
            break
        if result.get("action") == "preflight_blocked":
            return {
                "day": day,
                "owner": owner_norm,
                "complete": False,
                "rounds": rounds,
                "error": "; ".join(result.get("error") or []),
            }
        if result.get("action") in {"idle", "queue_busy", "submit_busy"} and tick:
            _time.sleep(tick)
        if result.get("action") == "slot_running" and tick:
            _time.sleep(min(2.0, tick))

    complete = week_automation_complete(store, owner=owner_norm)
    stats = today_slot_stats(store, day=day, owner=owner_norm)
    backlog = automation_calendar_days_to_fill(store, owner=owner_norm)
    out = {
        "day": day,
        "owner": owner_norm,
        "complete": complete,
        "rounds": rounds,
        "today_stats": stats,
        "backlog_days": backlog,
        "submitted": [],
        "count": 0,
    }
    write_last_run({**out, "fill_day": True})
    _append_fill_log(
        f"{owner_norm} fill_done complete={complete} backlog={backlog} rounds={rounds} stats={stats}"
    )
    return out


def run_weekly_fill_all_owners(
    store,
    *,
    day: str,
    dry_run: bool = False,
    submit_fn=None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for owner in OWNERS:
        if planned_slots_for_calendar_day(store, day=day, owner=owner) <= 0:
            continue
        if day_fill_complete(store, day=day, owner=owner) and not dry_run:
            continue
        results.append(
            run_weekly_fill_day(
                store,
                day=day,
                owner=owner,
                dry_run=dry_run,
                submit_fn=submit_fn,
            )
        )
    all_complete = all(r.get("complete") for r in results) if results else True
    return {"day": day, "owners": results, "all_complete": all_complete}


_automation_lock = None
_automation_running = False
_automation_thread = None
_automation_wakeup = None
_automation_submit_lock = None


def _automation_threading():
    global _automation_lock, _automation_wakeup, _automation_submit_lock
    import threading

    if _automation_lock is None:
        _automation_lock = threading.Lock()
    if _automation_wakeup is None:
        _automation_wakeup = threading.Event()
    if _automation_submit_lock is None:
        _automation_submit_lock = threading.Lock()
    return _automation_lock, _automation_wakeup, _automation_submit_lock


def _automation_tick_sec() -> float:
    import os as _os

    try:
        return max(0.25, float(_os.environ.get("WEEKLY_AUTOMATION_TICK_SEC", "0.5")))
    except ValueError:
        return 0.5


def _automation_backlog_scope() -> str:
    import os as _os

    return _os.environ.get("WEEKLY_AUTOMATION_BACKLOG", "current_week").strip().lower()


def automation_calendar_days_to_fill(
    store,
    *,
    owner: str | None = None,
    through: date | None = None,
) -> list[str]:
    """Calendar dates (sorted) with incomplete weekly slots, any active plan, through today."""
    ensure_weekly_tables(store)
    end = through or date.today()
    owner_filter = normalize_owner(owner) if owner else None
    query = """
        SELECT DISTINCT p.week_start, s.day, p.owner
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.status IN ('ready', 'active', 'completed')
          AND s.status != 'done'
    """
    args: list[Any] = []
    if owner_filter:
        query += " AND p.owner = ?"
        args.append(owner_filter)
    rows = store._conn.execute(query, args).fetchall()
    candidates: set[str] = set()
    for row in rows:
        week_start = str(row["week_start"] or "")
        weekday = str(row["day"] or "")
        owner_norm = normalize_owner(str(row["owner"] or ""))
        if not week_start or weekday not in DAYS:
            continue
        try:
            cal = slot_date(week_start, weekday)
            if date.fromisoformat(cal) > end:
                continue
        except ValueError:
            continue
        activate_plans_for_day(store, day=cal)
        if planned_slots_for_calendar_day(store, day=cal, owner=owner_norm) <= 0:
            continue
        if not day_fill_complete(store, day=cal, owner=owner_norm):
            candidates.add(cal)
    scope = _automation_backlog_scope()
    if scope in {"current_week", "week", "this_week"}:
        week_mon = week_start_monday(end)
        week_sun = week_mon + timedelta(days=6)
        candidates = {
            cal
            for cal in candidates
            if week_mon <= date.fromisoformat(cal) <= week_sun
        }
    return sorted(candidates)


def week_automation_complete(store, *, owner: str | None = None, through: date | None = None) -> bool:
    return len(automation_calendar_days_to_fill(store, owner=owner, through=through)) == 0


def weekly_automation_tick(
    store,
    *,
    day: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """One montage attempt: oldest incomplete day, round-robin slot (one try per pass)."""
    from discovery.production_pause import is_production_paused

    if is_production_paused():
        return {"day": date.today().isoformat(), "action": "production_paused"}

    owner_filter = normalize_owner(owner) if owner else None
    weekly_reconcile_pipeline(store)

    preflight = weekly_preflight()
    if not preflight["ok"]:
        today = date.today().isoformat()
        return {"day": today, "action": "preflight_blocked", "error": preflight["issues"]}

    if day:
        calendar_days = [date.fromisoformat(day).isoformat()]
    else:
        calendar_days = automation_calendar_days_to_fill(store, owner=owner_filter)
        if not calendar_days:
            return {"day": date.today().isoformat(), "action": "week_complete"}

    _, _, submit_lock = _automation_threading()
    if not submit_lock.acquire(blocking=False):
        return {"day": calendar_days[0], "action": "submit_busy"}

    try:
        if production_queue_busy(store, owner=None):
            return {"day": calendar_days[0], "action": "queue_busy"}

        owners = [owner_filter] if owner_filter else list(OWNERS)
        for day_iso in calendar_days:
            activate_plans_for_day(store, day=day_iso)
            for owner_norm in owners:
                if planned_slots_for_calendar_day(store, day=day_iso, owner=owner_norm) <= 0:
                    continue
                if day_fill_complete(store, day=day_iso, owner=owner_norm):
                    continue

                requeue_failed_slots_for_calendar_day(store, day=day_iso, owner=owner_norm)

                for slot_row in slots_for_calendar_day(store, day=day_iso, owner=owner_norm):
                    if _slot_status(store, int(slot_row["id"])) == "running":
                        return {
                            "day": day_iso,
                            "action": "slot_running",
                            "owner": owner_norm,
                            "slot": int(slot_row.get("slot") or 0),
                        }

                slot_row = pick_next_round_robin_slot(
                    store, day=day_iso, owner=owner_norm
                )
                if not slot_row:
                    if day_fill_complete(store, day=day_iso, owner=owner_norm):
                        clear_round_robin_cursor(owner=owner_norm, day=day_iso)
                        continue
                    return {"day": day_iso, "action": "idle", "owner": owner_norm}

                slot_id = int(slot_row["id"])
                slot_no = int(slot_row.get("slot") or 0)
                command = slot_command_text(slot_row)
                wait_sec = _fill_slot_wait_sec()
                _append_fill_log(
                    f"automation submit {owner_norm} day={day_iso} slot={slot_no} id={slot_id} "
                    f"(round-robin cursor→{get_round_robin_cursor(owner=owner_norm, day=day_iso)})"
                )
                try:
                    weekly_submit_command(
                        store,
                        user_command=command,
                        slot_id=slot_id,
                        wait_montage=True,
                        wait_timeout_sec=wait_sec,
                    )
                except Exception as exc:  # noqa: BLE001
                    prepare_slot_for_retry(
                        store,
                        slot_id,
                        error=str(exc)[:500],
                    )
                    _append_fill_log(
                        f"automation exception day={day_iso} slot={slot_no}: {str(exc)[:160]}"
                    )

                final = _slot_status(store, slot_id)
                if day_fill_complete(store, day=day_iso, owner=owner_norm):
                    clear_round_robin_cursor(owner=owner_norm, day=day_iso)
                return {
                    "day": day_iso,
                    "action": "attempted",
                    "owner": owner_norm,
                    "slot": slot_no,
                    "status": final,
                }

        if week_automation_complete(store, owner=owner_filter):
            return {"day": calendar_days[-1], "action": "week_complete"}
        return {"day": calendar_days[0], "action": "idle"}
    finally:
        submit_lock.release()


def automation_daemon_alive() -> bool:
    """True when the in-process weekly automation thread is running."""
    thread = _automation_thread
    return thread is not None and thread.is_alive()


def _clear_automation_daemon_state(*, reason: str) -> None:
    global _automation_running, _automation_thread
    _automation_running = False
    _automation_thread = None
    _append_fill_log(f"WEEKLY_AUTOMATION_DAEMON_STOP reason={reason}")


def repair_stale_automation_state() -> bool:
    """Reset flag when _automation_running but daemon thread is dead."""
    global _automation_running
    if _automation_running and not automation_daemon_alive():
        _append_fill_log("WEEKLY_AUTOMATION_STALE_STATE_RECOVERED")
        _clear_automation_daemon_state(reason="stale_flag_without_live_thread")
        return True
    if not _automation_running and _automation_thread is not None and not automation_daemon_alive():
        _automation_thread = None  # type: ignore[misc]
        return True
    return False


def _weekly_automation_daemon() -> None:
    global _automation_running, _automation_thread
    import threading
    import time as _time

    from discovery.config import default_db_path, load_env
    from discovery.store import DiscoveryStore

    me = threading.current_thread()
    stop_reason = "loop_exit"
    load_env()
    _append_fill_log(f"WEEKLY_AUTOMATION_DAEMON_START thread={me.name} ident={me.ident}")
    tick = _automation_tick_sec()
    try:
        while _automation_running:
            from discovery.production_pause import is_production_paused

            if is_production_paused():
                stop_reason = "production_pause"
                break
            _, wakeup, _ = _automation_threading()
            store = DiscoveryStore(default_db_path())
            try:
                weekly_automation_tick(store)
            except Exception as exc:  # noqa: BLE001
                _append_fill_log(f"automation daemon error: {exc}")
            finally:
                store.close()
            wakeup.wait(timeout=tick)
            wakeup.clear()
    finally:
        if _automation_thread is me:
            _clear_automation_daemon_state(reason=stop_reason)


def stop_weekly_automation() -> None:
    """Stop in-process automation loop (API / worker thread)."""
    global _automation_running
    _, wakeup, _ = _automation_threading()
    _automation_running = False
    wakeup.set()


def ensure_weekly_automation_started() -> dict[str, Any]:
    """Start the always-on tick loop (one montage at a time)."""
    global _automation_running, _automation_thread
    import threading

    from discovery.production_pause import is_production_paused

    lock, wakeup, _ = _automation_threading()
    with lock:
        repair_stale_automation_state()
        if is_production_paused():
            if not automation_daemon_alive():
                _automation_running = False
            return {"started": False, "reason": "production_paused", "fill_day": True}

        if automation_daemon_alive():
            wakeup.set()
            return {
                "started": False,
                "reason": "automation_already_running",
                "fill_day": True,
                "thread_alive": True,
            }

        _automation_running = True
        thread = threading.Thread(
            target=_weekly_automation_daemon,
            name="weekly-automation",
            daemon=True,
        )
        _automation_thread = thread
        thread.start()
    return {"started": True, "fill_day": True, "automation": True, "thread_alive": True}


def request_daily_fill_kick(
    store=None,
    *,
    slot_id: int | None = None,
    day: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Wake automation immediately after a failure (no debounce)."""
    _, wakeup, _ = _automation_threading()
    out = ensure_weekly_automation_started()
    wakeup.set()
    return out


def weekly_fill_running() -> bool:
    return automation_daemon_alive()


def automation_health_snapshot(store, *, owner: str | None = None) -> dict[str, Any]:
    """Read-only automation diagnostics for /api/weekly/health."""
    from discovery.production_pause import is_production_paused

    owner_norm = normalize_owner(owner) if owner else None
    backlog = automation_calendar_days_to_fill(store, owner=owner_norm)
    next_day: str | None = backlog[0] if backlog else None
    next_row: dict[str, Any] | None = None
    if next_day and owner_norm:
        next_row = peek_next_round_robin_slot(store, day=next_day, owner=owner_norm)
    elif next_day:
        for o in OWNERS:
            next_row = peek_next_round_robin_slot(store, day=next_day, owner=o)
            if next_row:
                owner_norm = o
                break
    return {
        "automation_running": bool(_automation_running),
        "automation_thread_alive": automation_daemon_alive(),
        "production_paused": is_production_paused(),
        "queue_busy": production_queue_busy(store, owner=None),
        "backlog_days": backlog,
        "next_slot_id": int(next_row["id"]) if next_row else None,
        "next_slot_day": next_day,
        "next_slot_number": int(next_row.get("slot") or 0) if next_row else None,
        "next_slot_owner": owner_norm,
    }


def weekly_api_startup_recover(store) -> dict[str, Any]:
    """Reconcile DB, ensure live daemon, wake if backlog exists."""
    pipe = weekly_reconcile_pipeline(store)
    repair_stale_automation_state()
    start = ensure_weekly_automation_started()
    backlog = automation_calendar_days_to_fill(store)
    kicked = False
    if backlog and start.get("started") or start.get("reason") == "automation_already_running":
        request_daily_fill_kick(store)
        kicked = True
    return {
        "reconcile": pipe,
        "automation": start,
        "backlog_days": backlog,
        "kicked": kicked,
    }


def kickoff_daily_fill_async(
    *,
    day: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Start background automation for today (non-blocking)."""
    day_iso = day or date.today().isoformat()
    owner_norm = normalize_owner(owner) if owner else None
    out = ensure_weekly_automation_started()
    _, wakeup, _ = _automation_threading()
    wakeup.set()
    return {**out, "day": day_iso, "owner": owner_norm}


def maybe_run_daily_fill(store) -> dict[str, Any] | None:
    """On PC/API startup: kick off fill for today whenever spots are not all done."""
    import os as _os

    if _os.environ.get("WEEKLY_DAILY_FILL", "1").strip().lower() in {"0", "false", "no"}:
        return None

    weekly_reconcile_pipeline(store)
    backlog = automation_calendar_days_to_fill(store)
    if not backlog:
        return {"day": date.today().isoformat(), "skipped": "all_complete", "backlog": []}

    if weekly_fill_running():
        return {"day": date.today().isoformat(), "skipped": "fill_already_running"}

    return ensure_weekly_automation_started()


def reset_weekly_slot_acquire_state(store, slot_id: int) -> None:
    """Explicit reset: drop speech/B-roll sidecars (manual restart / developer fresh run)."""
    _reset_weekly_slot_acquire_state(store, slot_id)


def _reset_weekly_slot_acquire_state(store, slot_id: int) -> None:
    """Drop speech/B-roll exclude sidecars (only for explicit fresh reset)."""
    row = _fetch_slot_record(store, slot_id)
    if not row:
        return
    owner = normalize_owner(str(row.get("owner") or ""))
    week = str(row.get("week_start") or "").strip()
    day = str(row.get("day") or "").strip()
    slot_no = int(row.get("slot") or 1)
    if not week or not day:
        return
    slug = f"weekly-{owner}-{week}-{day}-{slot_no}"
    try:
        from discovery.config import project_root
        from discovery.motivation_paths import (
            default_job_date,
            job_dir_for,
            motivation_jobs_root,
            resolve_job_dir,
        )

        root = project_root()
        jobs_root = motivation_jobs_root(root)
        job_dir = resolve_job_dir(slug, jobs_root) or job_dir_for(
            slug, jobs_root, job_date=default_job_date()
        )
    except Exception:
        return
    if not job_dir.is_dir():
        return
    for name in ("speech_acquire.json", "broll_acquire.json"):
        path = job_dir / name
        if path.is_file():
            path.unlink(missing_ok=True)


def prepare_slot_for_retry(
    store,
    slot_id: int,
    *,
    error: str | None = None,
    fresh_reset: bool = False,
) -> bool:
    """Return slot to queued for another attempt; preserve clips + acquire sidecars by default."""
    ensure_weekly_tables(store)
    row = store._conn.execute(
        "SELECT status FROM weekly_slots WHERE id = ?", (slot_id,)
    ).fetchone()
    if not row:
        return False
    status = str(row["status"] or "")
    if status == "done":
        return False
    if status not in {"failed", "running", "rerunning"}:
        return False
    if fresh_reset:
        _reset_weekly_slot_acquire_state(store, slot_id)
    ts = _now()
    err_val = (error or "")[:500] if error is not None else None
    if err_val is not None:
        store._conn.execute(
            """
            UPDATE weekly_slots
            SET status = 'queued', job_key = NULL, error_message = ?,
                render_started_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (err_val, ts, slot_id),
        )
    else:
        store._conn.execute(
            """
            UPDATE weekly_slots
            SET status = 'queued', job_key = NULL,
                render_started_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (ts, slot_id),
        )
    store._conn.commit()
    return True


def requeue_slot(store, slot_id: int, *, fresh_reset: bool = False) -> bool:
    """Reset a failed slot to queued so automation or Run due can pick it up again."""
    ensure_weekly_tables(store)
    row = store._conn.execute(
        "SELECT status FROM weekly_slots WHERE id = ?", (slot_id,)
    ).fetchone()
    if not row or str(row["status"]) != "failed":
        return False
    return prepare_slot_for_retry(store, slot_id, fresh_reset=fresh_reset)


def today_slot_stats(store, *, day: str, owner: str | None = None) -> dict[str, int]:
    ensure_weekly_tables(store)
    target = date.fromisoformat(day)
    monday = week_start_monday(target).isoformat()
    weekday = DAYS[target.weekday()]
    query = """
        SELECT s.status, COUNT(*) AS n
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE p.week_start = ? AND s.day = ?
          AND p.status IN ('ready', 'active', 'completed')
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


def day_morning_status(
    store,
    *,
    day: str,
    owner: str | None = None,
    automation_thread_alive: bool | None = None,
    production_paused: bool | None = None,
) -> dict[str, Any]:
    """Per-calendar-day automation status for Weekly UI (all-day backlog, not 7am-only)."""
    from discovery.production_pause import is_production_paused

    if owner:
        owner = normalize_owner(owner)
    paused = production_paused if production_paused is not None else is_production_paused()
    daemon_alive = (
        automation_thread_alive
        if automation_thread_alive is not None
        else automation_daemon_alive()
    )
    stats = today_slot_stats(store, day=day, owner=owner)
    batch_started_at = day_batch_started_at(store, day=day, owner=owner)
    filled = sum(stats.values())
    expected = VIDEOS_PER_DAY if filled >= VIDEOS_PER_DAY else max(filled, VIDEOS_PER_DAY)

    done = int(stats.get("done") or 0)
    running = int(stats.get("running") or 0)
    failed = int(stats.get("failed") or 0)
    queued = int(stats.get("queued") or 0)
    rerunning = int(stats.get("rerunning") or 0)
    waiting = queued + rerunning
    remaining = max(0, expected - done)

    if filled == 0:
        outcome = "empty"
        status_line = "No plan for this day"
    elif done >= min(expected, filled) and waiting == 0 and running == 0 and failed == 0:
        outcome = "finished"
        status_line = f"Finished — {done}/{expected} videos ready"
    elif paused and remaining > 0:
        outcome = "paused"
        status_line = f"Production paused — {remaining} video(s) remaining"
    elif running > 0 or rerunning > 0:
        outcome = "in_progress"
        status_line = f"Automation running — {done}/{expected} finished"
    elif failed > 0 and waiting > 0:
        outcome = "automation_retrying"
        status_line = f"Automation retrying — {done}/{expected} finished"
    elif failed > 0 and waiting == 0:
        outcome = "failed"
        status_line = "Failed — check preflight or retry"
    elif waiting > 0 and past_morning_cutoff(day):
        outcome = "automation_queued" if not daemon_alive else "in_progress"
        status_line = (
            f"Automation queued — {remaining} video(s) remaining"
            if not daemon_alive
            else f"Automation running — {done}/{expected} finished"
        )
    elif waiting > 0:
        outcome = "scheduled"
        status_line = "Waiting for scheduled start"
    else:
        outcome = "in_progress"
        status_line = f"Automation running — {done}/{expected} finished"

    return {
        "day": day,
        "expected": expected,
        "filled": filled,
        "stats": stats,
        "outcome": outcome,
        "status_line": status_line,
        "remaining": remaining,
        "automation_active": daemon_alive,
        "past_morning_cutoff": past_morning_cutoff(day),
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
    """API startup hook — alias for daily fill (any time of day, retries until 3/3)."""
    import os as _os

    if _os.environ.get("WEEKLY_MORNING_CATCHUP", "1").strip().lower() in {"0", "false", "no"}:
        return None
    return maybe_run_daily_fill(store)


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


def _fail_running_command_job(store, job_key: str, *, message: str) -> None:
    from discovery.command_jobs import now_iso

    ts = now_iso()
    store._conn.execute(
        """
        UPDATE cursor_command_jobs
        SET status = 'failed', error_message = ?, completed_at = ?
        WHERE job_key = ? AND status = 'running'
        """,
        (message[:2000], ts, job_key),
    )
    store._conn.commit()


def _wait_for_command_job(store, job_key: str, *, deadline: float) -> None:
    import time as _time

    from discovery.command_jobs import get_command_job

    while _time.monotonic() < deadline:
        job = get_command_job(store, job_key)
        if job and str(job.get("status") or "") in {"completed", "failed", "cancelled"}:
            return
        _time.sleep(8)
        reconcile_slots(store)

    job = get_command_job(store, job_key)
    if job and str(job.get("status") or "") == "running":
        from discovery.config import weekly_montage_job_timeout_minutes

        mins = weekly_montage_job_timeout_minutes()
        _fail_running_command_job(
            store,
            job_key,
            message=(
                f"Montage wait exceeded {mins}m — job marked failed so weekly can retry this slot."
            ),
        )


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


def sync_weekly_slots_for_job(store, job_key: str) -> int:
    """Push cursor_command_jobs terminal status onto any running weekly slot for this job."""
    ensure_weekly_tables(store)
    key = str(job_key or "").strip()
    if not key:
        return 0
    rows = store._conn.execute(
        """
        SELECT id FROM weekly_slots
        WHERE job_key = ? AND status IN ('running', 'rerunning')
        """,
        (key,),
    ).fetchall()
    plan_ids: set[int] = set()
    for row in rows:
        slot_id = int(row["id"])
        plan = store._conn.execute(
            "SELECT plan_id FROM weekly_slots WHERE id = ?",
            (slot_id,),
        ).fetchone()
        if plan:
            plan_ids.add(int(plan["plan_id"]))
        _sync_slot_from_job(store, slot_id, key)
    for pid in plan_ids:
        refresh_plan_completion(store, plan_id=pid)
    return len(rows)


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
        prepare_slot_for_retry(
            store,
            slot_id,
            error=command_job_error_summary(job),
        )
        request_daily_fill_kick(store, slot_id=slot_id)
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
        slot_id = int(row["id"])
        reset_weekly_slot_acquire_state(store, slot_id)
        mark_slot(
            store,
            slot_id,
            status="queued",
            job_key=None,
            error="",
            reset_job_key=True,
        )
        store._conn.execute(
            "UPDATE weekly_slots SET render_started_at = NULL WHERE id = ?",
            (slot_id,),
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
        requeue_failed_slots_for_calendar_day(store, day=day, owner=owner_norm)

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
    submitted: list[dict[str, str]] = []
    deadline = _time.monotonic() + max(60, wait_timeout_sec)
    retry_sleep = _slot_retry_sleep_sec()

    ordered = slots_for_calendar_day(store, day=day, owner=owner_norm)
    if slot_ids:
        want = {int(x) for x in slot_ids}
        ordered = [s for s in ordered if int(s["id"]) in want]
    ordered = ordered[:cap]
    allowed_ids = {int(s["id"]) for s in ordered}

    while _time.monotonic() < deadline:
        if all(_slot_status(store, int(s["id"])) == "done" for s in ordered):
            break
        reconcile_slots(store)
        if production_queue_busy(store, owner=None):
            if not _wait_for_production_idle(store, deadline=deadline):
                break
            continue

        slot_row = pick_next_round_robin_slot(
            store, day=day, owner=owner_norm, allowed_slot_ids=allowed_ids
        )
        if not slot_row:
            if all(_slot_status(store, int(s["id"])) == "done" for s in ordered):
                break
            if not _wait_for_production_idle(store, deadline=deadline):
                break
            continue

        slot_id = int(slot_row["id"])
        slot_row = _fetch_slot_record(store, slot_id) or slot_row
        command = slot_command_text(slot_row)
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
            prepare_slot_for_retry(
                store,
                slot_id,
                error=str(exc)[:500],
            )
            _append_fill_log(f"slot {slot_id} exception: {str(exc)[:120]}")
            if retry_sleep:
                _time.sleep(retry_sleep)
            continue

        refresh_plan_completion(store, plan_id=int(slot_row["plan_id"]))
        status = _slot_status(store, slot_id)
        if status == "done":
            job_key = str(result.get("job_key") or "")
            submitted.append({"slot_id": str(slot_id), "job_key": job_key})

        if day_fill_complete(store, day=day, owner=owner_norm):
            clear_round_robin_cursor(owner=owner_norm, day=day)
            break

        if status == "running":
            if not _wait_for_production_idle(store, deadline=deadline):
                break

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
