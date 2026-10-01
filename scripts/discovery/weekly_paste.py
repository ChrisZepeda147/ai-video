"""Parse ChatGPT-style weekly plan paste into weekly slot rows."""

from __future__ import annotations

import re
from typing import Any

from discovery.weekly import DAYS, VIDEOS_PER_DAY

DAY_NAME = re.compile(
    r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b",
    re.I,
)
DAY_MAP = {
    "monday": "mon",
    "mon": "mon",
    "tuesday": "tue",
    "tue": "tue",
    "wednesday": "wed",
    "wed": "wed",
    "thursday": "thu",
    "thu": "thu",
    "friday": "fri",
    "fri": "fri",
    "saturday": "sat",
    "sat": "sat",
    "sunday": "sun",
    "sun": "sun",
}
VIDEO_LINE = re.compile(
    r"^\s*(?:video\s*)?(\d)\s*[.)]?\s*:?\s*(.+)$",
    re.I,
)
IMAGES_LINE = re.compile(
    r"^\s*(?:images?\s+to\s+make|stills?)(?:\s+(?:for\s+)?video\s*(\d))?\s*:?\s*(.+)$",
    re.I,
)

CHATGPT_FORMAT_TEMPLATE = """Plan my next week of TikTok motivation Shorts (9:16, luxury B-roll + speech clips, 60-90s).

I am planning on Sunday for the week that starts Monday {week_start}. Production runs each calendar day at 7am (3 videos that day). MONDAY in the format below is {week_start}.

Previous week (do NOT repeat — new speakers/angles/visuals):
{previous_week}

Reply using EXACTLY this format (3 videos per day, Mon-Sun):

MONDAY
1. [speaker name] | [B-roll search query for TikTok vibe]
2. [speaker] | [visuals]
3. [speaker] | [visuals]
Images to make video 1: [optional dark luxury still prompt]

TUESDAY
1. ...
(continue through SUNDAY)
"""


def summarize_week_for_prompt(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return "(no previous week saved yet)"
    lines: list[str] = []
    cur_day = ""
    for item in sorted(slots, key=lambda s: (DAYS.index(str(s.get("day") or "mon")), int(s.get("slot") or 1))):
        day = str(item.get("day") or "")
        if day != cur_day:
            cur_day = day
            lines.append(day.upper())
        sp = str(item.get("speaker") or "").strip()
        vis = str(item.get("visual_direction") or "").strip()
        if sp or vis:
            lines.append(f"{item.get('slot')}. {sp} | {vis}")
    return "\n".join(lines) if lines else "(empty plan)"


def _normalize_line(raw: str) -> str:
    line = raw.strip()
    if not line:
        return ""
    line = re.sub(r"^[-*•]\s+", "", line)
    line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
    line = line.replace("*", "").replace("_", "").replace("`", "")
    line = re.sub(r"^#+\s*", "", line)
    return line.strip()


def _parse_day_header(line: str) -> str | None:
    line = line.strip().rstrip(":").strip()
    line = re.sub(r"^[^\w]+", "", line, flags=re.UNICODE)
    if not line:
        return None
    m = DAY_NAME.match(line)
    if not m:
        return None
    key = m.group(1).lower()
    return DAY_MAP.get(key, key[:3] if len(key) >= 3 else None)


def resolve_week_start(raw: str | None) -> str:
    """Default week_start for apply-paste (Sunday → upcoming Monday)."""
    from datetime import date, timedelta

    from discovery.weekly import week_start_monday

    text = (raw or "").strip()
    if text:
        try:
            return week_start_monday(date.fromisoformat(text)).isoformat()
        except ValueError:
            pass
    today = date.today()
    if today.weekday() == 6:
        return (today + timedelta(days=1)).isoformat()
    return week_start_monday(today).isoformat()


def _split_speaker_visual(body: str) -> tuple[str, str]:
    text = body.strip()
    if not text:
        return "", ""
    for sep in (" | ", " — ", " - ", " – ", "|"):
        if sep in text:
            a, b = text.split(sep, 1)
            return a.strip(), b.strip()
    m = re.match(r"speaker\s*:\s*(.+?)(?:,\s*visual\s*:\s*(.+))?$", text, re.I)
    if m:
        return (m.group(1) or "").strip(), (m.group(2) or "").strip()
    m = re.match(r"visual\s*:\s*(.+)$", text, re.I)
    if m:
        return "", m.group(1).strip()
    return text, ""


def parse_weekly_paste(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    slots: list[dict[str, Any]] = []
    current_day: str | None = None
    pending_images: dict[int, str] = {}

    for raw in text.splitlines():
        line = _normalize_line(raw)
        if not line or line.startswith("#"):
            continue
        day_hdr = _parse_day_header(line)
        if day_hdr:
            current_day = day_hdr
            pending_images = {}
            continue
        if current_day is None:
            continue
        im = IMAGES_LINE.match(line)
        if im:
            slot_no = int(im.group(1) or 1)
            prompt = im.group(2).strip()
            applied = False
            for s in slots:
                if s["day"] == current_day and int(s["slot"]) == slot_no:
                    s["image_prompt"] = prompt
                    applied = True
                    break
            if not applied:
                pending_images[slot_no] = prompt
            continue
        vm = VIDEO_LINE.match(line)
        if vm:
            slot_no = max(1, min(int(vm.group(1)), VIDEOS_PER_DAY))
            speaker, visual = _split_speaker_visual(vm.group(2))
            slots.append(
                {
                    "day": current_day,
                    "slot": slot_no,
                    "speaker": speaker,
                    "visual_direction": visual,
                    "image_prompt": pending_images.pop(slot_no, ""),
                }
            )
            continue
        if "|" in line or " - " in line:
            speaker, visual = _split_speaker_visual(line)
            next_slot = len([s for s in slots if s["day"] == current_day]) + 1
            if next_slot <= VIDEOS_PER_DAY:
                slots.append(
                    {
                        "day": current_day,
                        "slot": next_slot,
                        "speaker": speaker,
                        "visual_direction": visual,
                        "image_prompt": "",
                    }
                )
            continue
        warnings.append(f"Unparsed: {line[:80]}")

    if not slots:
        warnings.append("No videos parsed — check day headers (MONDAY…) and numbered lines (1. speaker | visuals).")

    days_seen = {s["day"] for s in slots}
    for day in days_seen:
        n = len([s for s in slots if s["day"] == day])
        if n != VIDEOS_PER_DAY:
            warnings.append(f"{day}: expected {VIDEOS_PER_DAY} videos, got {n}")

    return slots, warnings


def build_week_progress(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-day status + focus day (first day not fully done)."""
    by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in DAYS}
    for s in slots:
        day = str(s.get("day") or "").lower()
        if day in by_day:
            by_day[day].append(s)

    day_rows: list[dict[str, Any]] = []
    focus_day: str | None = None
    week_complete = True

    for day in DAYS:
        items = sorted(by_day[day], key=lambda x: int(x.get("slot") or 1))
        filled = [i for i in items if str(i.get("speaker") or "").strip() or str(i.get("visual_direction") or "").strip()]
        statuses = [str(i.get("status") or "queued") for i in filled]
        done = sum(1 for st in statuses if st == "done")
        total = len(filled) if filled else (len(items) if items else 0)
        if not total and items:
            total = len(items)
            statuses = [str(i.get("status") or "queued") for i in items]
            done = sum(1 for st in statuses if st == "done")
        complete = total > 0 and done >= total and all(st in {"done", "cancelled"} for st in statuses)
        if total > 0 and not complete:
            week_complete = False
            if focus_day is None:
                focus_day = day
        elif total == 0 and focus_day is None and not week_complete:
            pass
        started_at: list[str] = []
        for item in items:
            raw = item.get("render_started_at")
            if raw:
                started_at.append(str(raw))
        batch_started_at = min(started_at) if started_at else None
        day_rows.append(
            {
                "day": day,
                "filled": total,
                "done": done,
                "complete": complete,
                "running": sum(1 for st in statuses if st == "running"),
                "failed": sum(1 for st in statuses if st == "failed"),
                "batch_started_at": batch_started_at,
            }
        )

    if week_complete and any(r["filled"] for r in day_rows):
        focus_day = None
    elif focus_day is None:
        for row in day_rows:
            if row["filled"] == 0:
                focus_day = row["day"]
                week_complete = False
                break
        if focus_day is None and not any(r["filled"] for r in day_rows):
            focus_day = "mon"

    # Suggest today's weekday when it still has work (UI may stay on user-picked tab).
    from datetime import date as _date

    today_key = DAYS[_date.today().weekday()]
    for row in day_rows:
        if row["day"] == today_key and row["filled"] > 0 and not row["complete"]:
            focus_day = today_key
            break

    return {
        "days": day_rows,
        "focus_day": focus_day,
        "week_complete": week_complete,
    }
