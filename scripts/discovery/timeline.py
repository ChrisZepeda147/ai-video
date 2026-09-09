"""Timeline planner for Short assembly."""

from __future__ import annotations

import json
from typing import Any


def plan_timeline(
    *,
    duration_sec: float,
    format_profile: str,
    visual_assets: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]] | None = None,
    source_segment_path: str | None = None,
    pacing: str = "balanced",
) -> dict[str, Any]:
    """Build machine-readable timeline JSON distributing visuals intentionally."""
    if duration_sec <= 0:
        raise ValueError("duration_sec must be positive")

    segments: list[dict[str, Any]] = []
    cursor = 0.0
    visuals = list(visual_assets)
    vi = 0

    if format_profile == "source_video_visuals" and source_segment_path:
        lead = min(2.5, duration_sec * 0.15)
        segments.append(
            {
                "type": "source_video",
                "start": 0.0,
                "end": lead,
                "path": source_segment_path,
                "layout": "fullscreen",
                "crop": "center",
                "transition": "cut",
            }
        )
        cursor = lead

    slot = 3.0 if pacing == "balanced" else (2.5 if pacing == "fast" else 4.0)
    while cursor < duration_sec - 0.5:
        end = min(cursor + slot, duration_sec)
        if vi < len(visuals):
            asset = visuals[vi]
            vi += 1
            asset_type = asset.get("asset_type", "image")
            segments.append(
                {
                    "type": "ai_video" if asset_type == "video" else "image",
                    "start": cursor,
                    "end": end,
                    "visual_asset_id": asset.get("id"),
                    "path": asset.get("local_path"),
                    "layout": "fullscreen",
                    "motion": "zoom_in" if asset_type == "image" else "none",
                    "transition": "cut",
                }
            )
        elif format_profile == "source_video_visuals" and source_segment_path:
            segments.append(
                {
                    "type": "source_video",
                    "start": cursor,
                    "end": end,
                    "path": source_segment_path,
                    "layout": "fullscreen",
                    "crop": "center",
                    "transition": "cut",
                }
            )
        else:
            break
        cursor = end

    if format_profile == "source_video_visuals" and cursor < duration_sec and source_segment_path:
        segments.append(
            {
                "type": "source_video",
                "start": cursor,
                "end": duration_sec,
                "path": source_segment_path,
                "layout": "fullscreen",
                "crop": "center",
                "transition": "cut",
            }
        )

    return {
        "duration_sec": duration_sec,
        "format_profile": format_profile,
        "pacing": pacing,
        "segments": segments,
        "caption_segments": transcript_segments or [],
    }


def timeline_to_json(timeline: dict[str, Any]) -> str:
    return json.dumps(timeline, indent=2)
