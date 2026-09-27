"""Parse ChatGPT-style weekly plan paste into weekly slot rows."""

from __future__ import annotations

import re
from typing import Any

from discovery.weekly import DAYS, VIDEOS_PER_DAY

DAY_PATTERN = re.compile(
    r"^\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s*:?\s*$",
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
    r"^\s*(?:video\s*)?(\d)\s*[.)]\s*(.+)$",
    re.I,
)
IMAGES_LINE = re.compile(
    r"^\s*(?:images?\s+to\s+make|stills?)(?:\s+(?:for\s+)?video\s*(\d))?\s*:?\s*(.+)$",
    re.I,
)

CHATGPT_FORMAT_TEMPLATE = """Plan my next week of TikTok motivation Shorts (9:16, luxury B-roll + speech clips, 60-90s).

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
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        dm = DAY_PATTERN.match(line)
        if dm:
            key = dm.group(1).lower()
            current_day = DAY_MAP.get(key, key[:3])
            pending_images = {}
            continue
        if current_day is None:
            warnings.append(f"Skipped line before any day header: {line[:60]}")
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
        day_rows.append(
            {
                "day": day,
                "filled": total,
                "done": done,
                "complete": complete,
                "running": sum(1 for st in statuses if st == "running"),
                "failed": sum(1 for st in statuses if st == "failed"),
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

    return {
        "days": day_rows,
        "focus_day": focus_day,
        "week_complete": week_complete,
    }
