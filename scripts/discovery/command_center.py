"""Daily command center — real production + publishing stats per owner."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from discovery.analytics.account_summary import fetch_live_account_metrics
from discovery.store import DiscoveryStore

OWNERS = ("chris", "stephen")
DAILY_VIDEO_TARGET = 3
DAILY_TIKTOK_TARGET = 3
DAILY_YOUTUBE_TARGET = 3

# Broad morning / midday / evening windows — 3 TikTok + 3 YouTube slots per owner.
POSTING_SLOTS = (
    {"window": "Morning", "platform": "tiktok", "hour": 9, "minute": 0, "slot_index": 0},
    {"window": "Morning", "platform": "youtube", "hour": 10, "minute": 30, "slot_index": 0},
    {"window": "Midday", "platform": "tiktok", "hour": 12, "minute": 30, "slot_index": 1},
    {"window": "Midday", "platform": "youtube", "hour": 13, "minute": 0, "slot_index": 1},
    {"window": "Evening", "platform": "tiktok", "hour": 18, "minute": 0, "slot_index": 2},
    {"window": "Evening", "platform": "youtube", "hour": 19, "minute": 30, "slot_index": 2},
)


def command_center_tz() -> timezone:
    name = os.environ.get("COMMAND_CENTER_TZ", "America/Los_Angeles").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    # Windows without tzdata — use system local tz, then UTC.
    local = datetime.now().astimezone().tzinfo
    if local is not None:
        return local
    try:
        return ZoneInfo("UTC")
    except Exception:
        return timezone.utc


def local_now() -> datetime:
    return datetime.now(command_center_tz())


def format_time_12h(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {suffix}"


def local_today_start_utc_iso() -> str:
    now = local_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat()


def _completion_pct(videos: int, tiktok: int, youtube: int) -> int:
    targets = DAILY_VIDEO_TARGET + DAILY_TIKTOK_TARGET + DAILY_YOUTUBE_TARGET
    done = min(videos, DAILY_VIDEO_TARGET) + min(tiktok, DAILY_TIKTOK_TARGET) + min(youtube, DAILY_YOUTUBE_TARGET)
    return round((done / targets) * 100) if targets else 0


def _count_videos_today(store: DiscoveryStore, owner: str, today: str) -> int:
    row = store._conn.execute(
        """
        SELECT COUNT(DISTINCT vid) FROM (
            SELECT id AS vid FROM production_library_videos
            WHERE created_at >= ?
              AND json_extract(metadata_json, '$.owner') = ?
            UNION
            SELECT rendered_video_id AS vid FROM production_combination_usage
            WHERE created_at >= ? AND owner = ?
        )
        """,
        (today, owner, today, owner),
    ).fetchone()
    return int(row[0] or 0)


def _posts_today_by_platform(store: DiscoveryStore, owner: str, today: str) -> dict[str, int]:
    rows = store._conn.execute(
        """
        SELECT pj.platform, COUNT(*) AS cnt
        FROM publishing_jobs pj
        JOIN publishing_accounts pa ON pa.id = pj.account_id
        WHERE pa.owner = ?
          AND pj.status IN ('published', 'processing')
          AND pj.published_at >= ?
          AND pj.platform IN ('youtube', 'tiktok')
        GROUP BY pj.platform
        """,
        (owner, today),
    ).fetchall()
    out = {"youtube": 0, "tiktok": 0}
    for row in rows:
        out[str(row["platform"])] = int(row["cnt"] or 0)
    return out


def _published_jobs_today(store: DiscoveryStore, owner: str, today: str) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT pj.id, pj.platform, pj.title, pj.published_at, pj.platform_url,
               pj.production_project_id, pa.display_name
        FROM publishing_jobs pj
        JOIN publishing_accounts pa ON pa.id = pj.account_id
        WHERE pa.owner = ?
          AND pj.status IN ('published', 'processing')
          AND pj.published_at >= ?
          AND pj.platform IN ('youtube', 'tiktok')
        ORDER BY pj.published_at ASC
        """,
        (owner, today),
    ).fetchall()
    return [dict(row) for row in rows]


def _slot_states(
    posts: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    by_platform: dict[str, list[dict[str, Any]]] = {"tiktok": [], "youtube": []}
    for post in posts:
        platform = str(post.get("platform") or "")
        if platform in by_platform:
            by_platform[platform].append(post)

    slots: list[dict[str, Any]] = []
    for spec in POSTING_SLOTS:
        platform = spec["platform"]
        idx = spec["slot_index"]
        completed_post = by_platform[platform][idx] if len(by_platform[platform]) > idx else None
        target = now.replace(
            hour=spec["hour"],
            minute=spec["minute"],
            second=0,
            microsecond=0,
        )
        slots.append(
            {
                "window": spec["window"],
                "platform": platform,
                "target_time": target.strftime("%H:%M"),
                "target_label": format_time_12h(target),
                "completed": completed_post is not None,
                "job_id": completed_post["id"] if completed_post else None,
                "production_project_id": completed_post.get("production_project_id") if completed_post else None,
                "title": completed_post.get("title") if completed_post else None,
                "platform_url": completed_post.get("platform_url") if completed_post else None,
                "minutes_until": int((target - now).total_seconds() // 60),
            }
        )
    return slots


def _next_post(slots: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    incomplete = [s for s in slots if not s["completed"]]
    if not incomplete:
        return None
    future = [s for s in incomplete if s["minutes_until"] >= 0]
    chosen = min(future, key=lambda s: s["minutes_until"]) if future else incomplete[0]
    mins = chosen["minutes_until"]
    if mins < 0:
        away = "now"
    elif mins < 60:
        away = f"{mins} min away"
    else:
        away = f"{mins // 60}h {mins % 60}m away"
    return {
        "platform": chosen["platform"],
        "window": chosen["window"],
        "time_label": chosen["target_label"],
        "minutes_until": mins,
        "away_label": away,
        "job_id": chosen.get("job_id"),
        "production_project_id": chosen.get("production_project_id"),
        "title": chosen.get("title"),
    }


def _owner_views(store: DiscoveryStore, owner: str) -> dict[str, Any]:
    overview = store.analytics_overview(owner=owner, days=30)
    accounts = store.list_publishing_accounts(owner=owner, enabled_only=True)
    live_total = 0
    account_rows: list[dict[str, Any]] = []
    for account in accounts:
        if account.auth_status not in {"connected", "verified"}:
            continue
        live = fetch_live_account_metrics(store, account.id)
        followers = None
        if live and not live.get("error"):
            followers = live.get("follower_count")
            if followers is not None:
                live_total += int(followers)
        account_rows.append(
            {
                "id": account.id,
                "platform": account.platform,
                "display_name": account.display_name,
                "follower_count": followers,
            }
        )
    return {
        "total_views_30d": overview.get("views_last_30_days") or 0,
        "total_views_7d": overview.get("views_last_7_days") or 0,
        "linked_posts": overview.get("total_published_posts") or 0,
        "live_followers": live_total,
        "accounts": account_rows,
    }


def _review_queue(store: DiscoveryStore) -> list[dict[str, Any]]:
    projects = store.list_production_projects(status="review", limit=20)
    return [
        {
            "id": p.id,
            "title": p.title,
            "slug": p.slug,
            "niche": p.niche,
            "output_path": p.output_path,
            "rendered_at": p.rendered_at,
            "href": f"/create?project_id={p.id}",
        }
        for p in projects
    ]


def _ready_videos(store: DiscoveryStore) -> list[dict[str, Any]]:
    from discovery.video_library import build_video_library

    items = build_video_library(store, include_missing_legacy=False, limit=80)
    ready: list[dict[str, Any]] = []
    for item in items:
        if not item.preview_available or item.media_kind == "audio":
            continue
        ready.append(
            {
                "key": item.key,
                "title": item.speaker or item.title,
                "slug": item.slug,
                "project_id": item.project_id,
                "library_id": item.library_id,
                "href": f"/library/{item.library_id}" if item.library_id else "/videos",
            }
        )
        if len(ready) >= 8:
            break
    return ready


def _day_stats(store: DiscoveryStore, owner: str, start: datetime) -> dict[str, Any]:
    start_local = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_iso = start_local.astimezone(timezone.utc).isoformat()
    end_iso = end_local.astimezone(timezone.utc).isoformat()
    posts = store._conn.execute(
        """
        SELECT pj.platform, COUNT(*) AS cnt
        FROM publishing_jobs pj
        JOIN publishing_accounts pa ON pa.id = pj.account_id
        WHERE pa.owner = ?
          AND pj.status IN ('published', 'processing')
          AND pj.published_at >= ? AND pj.published_at < ?
          AND pj.platform IN ('youtube', 'tiktok')
        GROUP BY pj.platform
        """,
        (owner, start_iso, end_iso),
    ).fetchall()
    tiktok = 0
    youtube = 0
    for row in posts:
        if row["platform"] == "tiktok":
            tiktok = int(row["cnt"] or 0)
        if row["platform"] == "youtube":
            youtube = int(row["cnt"] or 0)
    videos = store._conn.execute(
        """
        SELECT COUNT(DISTINCT vid) FROM (
            SELECT id AS vid FROM production_library_videos
            WHERE created_at >= ? AND created_at < ?
              AND json_extract(metadata_json, '$.owner') = ?
            UNION
            SELECT rendered_video_id AS vid FROM production_combination_usage
            WHERE created_at >= ? AND created_at < ? AND owner = ?
        )
        """,
        (start_iso, end_iso, owner, start_iso, end_iso, owner),
    ).fetchone()
    video_count = int(videos[0] or 0)
    pct = _completion_pct(video_count, tiktok, youtube)
    met = (
        video_count >= DAILY_VIDEO_TARGET
        and tiktok >= DAILY_TIKTOK_TARGET
        and youtube >= DAILY_YOUTUBE_TARGET
    )
    return {
        "date": start_local.strftime("%a"),
        "date_iso": start_local.date().isoformat(),
        "completion_pct": pct,
        "met_targets": met,
    }


def _streak_and_week(store: DiscoveryStore, owner: str) -> tuple[int, list[dict[str, Any]]]:
    now = local_now()
    week: list[dict[str, Any]] = []
    for offset in range(6, -1, -1):
        week.append(_day_stats(store, owner, now - timedelta(days=offset)))
    streak = 0
    for entry in reversed(week[:-1]):
        if entry["met_targets"]:
            streak += 1
        else:
            break
    return streak, week


def _checklist(owner: str, progress: dict[str, int], review_count: int) -> list[dict[str, Any]]:
    items = [
        {
            "id": "videos",
            "label": f"Create {DAILY_VIDEO_TARGET} videos",
            "done": progress["videos"] >= DAILY_VIDEO_TARGET,
            "detail": f"{progress['videos']} / {DAILY_VIDEO_TARGET}",
            "href": "/create",
        },
        {
            "id": "tiktok",
            "label": f"Post {DAILY_TIKTOK_TARGET} TikToks",
            "done": progress["tiktok"] >= DAILY_TIKTOK_TARGET,
            "detail": f"{progress['tiktok']} / {DAILY_TIKTOK_TARGET}",
            "href": "/accounts",
        },
        {
            "id": "youtube",
            "label": f"Post {DAILY_YOUTUBE_TARGET} YouTube Shorts",
            "done": progress["youtube"] >= DAILY_YOUTUBE_TARGET,
            "detail": f"{progress['youtube']} / {DAILY_YOUTUBE_TARGET}",
            "href": "/accounts",
        },
        {
            "id": "review",
            "label": "Clear review queue",
            "done": review_count == 0,
            "detail": f"{review_count} waiting" if review_count else "Clear",
            "href": "/review",
        },
    ]
    return items


def _owner_bundle(store: DiscoveryStore, owner: str, today: str, now: datetime) -> dict[str, Any]:
    posts = _published_jobs_today(store, owner, today)
    progress = _posts_today_by_platform(store, owner, today)
    videos = _count_videos_today(store, owner, today)
    prog = {"videos": videos, "tiktok": progress["tiktok"], "youtube": progress["youtube"]}
    slots = _slot_states(posts, now)
    streak, week = _streak_and_week(store, owner)
    return {
        "owner": owner,
        "progress": {
            "videos": {"done": videos, "target": DAILY_VIDEO_TARGET},
            "tiktok": {"done": progress["tiktok"], "target": DAILY_TIKTOK_TARGET},
            "youtube": {"done": progress["youtube"], "target": DAILY_YOUTUBE_TARGET},
            "completion_pct": _completion_pct(videos, progress["tiktok"], progress["youtube"]),
        },
        "schedule": slots,
        "next_post": _next_post(slots, now),
        "views": _owner_views(store, owner),
        "streak_days": streak,
        "week": week,
        "checklist": _checklist(owner, prog, len(_review_queue(store))),
    }


def build_command_center(store: DiscoveryStore, *, owner_filter: str | None = None) -> dict[str, Any]:
    """Build daily command center payload."""
    now = local_now()
    today = local_today_start_utc_iso()
    filter_norm = (owner_filter or "all").strip().lower()
    if filter_norm not in {"all", "chris", "stephen"}:
        filter_norm = "all"

    owners = OWNERS if filter_norm == "all" else (filter_norm,)
    bundles = [_owner_bundle(store, o, today, now) for o in owners]

    combined_progress = {
        "videos": sum(b["progress"]["videos"]["done"] for b in bundles),
        "tiktok": sum(b["progress"]["tiktok"]["done"] for b in bundles),
        "youtube": sum(b["progress"]["youtube"]["done"] for b in bundles),
    }
    owner_count = len(bundles)
    combined_targets = {
        "videos": DAILY_VIDEO_TARGET * owner_count,
        "tiktok": DAILY_TIKTOK_TARGET * owner_count,
        "youtube": DAILY_YOUTUBE_TARGET * owner_count,
    }
    combined_completion = _completion_pct(
        combined_progress["videos"],
        combined_progress["tiktok"],
        combined_progress["youtube"],
    )
    # scale completion against total targets for all owners
    total_done = (
        min(combined_progress["videos"], combined_targets["videos"])
        + min(combined_progress["tiktok"], combined_targets["tiktok"])
        + min(combined_progress["youtube"], combined_targets["youtube"])
    )
    total_target = sum(combined_targets.values())
    combined_completion = round((total_done / total_target) * 100) if total_target else 0

    next_post = None
    candidates: list[tuple[str, dict[str, Any]]] = [
        (b["owner"], b["next_post"]) for b in bundles if b.get("next_post")
    ]
    if candidates:
        candidates.sort(key=lambda pair: pair[1].get("minutes_until", 9999))
        owner_name, chosen = candidates[0]
        next_post = {**chosen, "owner": owner_name}

    pipeline = {
        "total_references": store.catalog_stats().total_references,
        "concepts_ready": store.count_concepts(statuses=("generated", "shortlisted", "approved")),
        "visuals_waiting_review": store.visual_library_stats().waiting_review,
    }

    return {
        "brand": "DRIVEN VISUALS",
        "date_label": now.strftime("%A, %B %d"),
        "timezone": str(command_center_tz()),
        "owner_filter": filter_norm,
        "targets": {
            "videos_per_owner": DAILY_VIDEO_TARGET,
            "tiktok_per_owner": DAILY_TIKTOK_TARGET,
            "youtube_per_owner": DAILY_YOUTUBE_TARGET,
        },
        "combined_progress": {
            "videos": {"done": combined_progress["videos"], "target": combined_targets["videos"]},
            "tiktok": {"done": combined_progress["tiktok"], "target": combined_targets["tiktok"]},
            "youtube": {"done": combined_progress["youtube"], "target": combined_targets["youtube"]},
            "completion_pct": combined_completion,
        },
        "owners": {b["owner"]: b for b in bundles},
        "next_post": next_post,
        "review_queue": _review_queue(store),
        "ready_videos": _ready_videos(store),
        "pipeline": pipeline,
        "generated_at": now.isoformat(),
    }
