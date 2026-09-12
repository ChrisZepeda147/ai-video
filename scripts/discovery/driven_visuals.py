"""DrivenVisuals default creative preset — pacing, captions, batches, agent prompts."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from discovery.config import project_root

_DEFAULTS_PATH = project_root() / "content" / "driven-visuals-defaults.json"
_cached: dict[str, Any] | None = None


def load_defaults(*, refresh: bool = False) -> dict[str, Any]:
    global _cached
    if _cached is not None and not refresh:
        return _cached
    if not _DEFAULTS_PATH.is_file():
        _cached = {"preset_id": "fallback", "captions": {"mode": "phrase"}}
        return _cached
    _cached = json.loads(_DEFAULTS_PATH.read_text(encoding="utf-8"))
    return _cached


def driven_beat_duration(*, elapsed: float, remaining: float) -> float:
    """Opening uses faster beats; then settles into longer beats."""
    preset = load_defaults()
    opener = preset.get("opener") or {}
    fast_window = float(opener.get("fast_pacing_window_sec") or 6)
    fast_min = float(opener.get("fast_beat_min_sec") or 0.8)
    fast_max = float(opener.get("fast_beat_max_sec") or 1.8)
    slow_min = float(opener.get("settle_beat_min_sec") or 2.0)
    slow_max = float(opener.get("settle_beat_max_sec") or 3.5)

    if elapsed < fast_window:
        target = (fast_min + fast_max) / 2
        beat = min(fast_max, max(fast_min, target))
    else:
        target = (slow_min + slow_max) / 2
        beat = min(slow_max, max(slow_min, target))
    return min(beat, max(remaining, 0.05))


def planning_segment_length(*, driven_pacing: bool, fallback: float) -> float:
    """Conservative beat length for clip-count planning."""
    if not driven_pacing:
        return fallback
    preset = load_defaults()
    opener = preset.get("opener") or {}
    fast_min = float(opener.get("fast_beat_min_sec") or 0.8)
    return max(0.8, min(fallback, fast_min + 0.2))


def caption_mode_default() -> str:
    return str((load_defaults().get("captions") or {}).get("mode") or "phrase")


def quality_gate_enabled() -> bool:
    return bool((load_defaults().get("quality_gate") or {}).get("enabled", True))


def parse_daily_video_briefs(text: str) -> list[dict[str, Any]]:
    """Parse VIDEO 1 / VIDEO 2 / VIDEO 3 blocks from a daily brief."""
    normalized = text.replace("\r\n", "\n")
    pattern = re.compile(r"(?im)^\s*VIDEO\s+(\d+)\s*$")
    matches = list(pattern.finditer(normalized))
    if not matches:
        return []

    briefs: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        slot = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[start:end].strip()
        fields = _parse_brief_fields(body)
        fields["slot"] = slot
        briefs.append(fields)
    return briefs


def _parse_brief_fields(body: str) -> dict[str, Any]:
    fields: dict[str, Any] = {"raw": body}
    key_map = {
        "speaker": r"^(?:speaker|audio/source)\s*:?\s*(.+)$",
        "hook": r"^hook\s*:?\s*(.+)$",
        "visual_direction": r"^visual(?:\s+direction)?\s*:?\s*(.+)$",
        "duration": r"^(?:duration|target duration)\s*:?\s*(.+)$",
        "topic": r"^topic\s*:?\s*(.+)$",
        "description": r"^description\s*:?\s*(.+)$",
        "hashtags": r"^hashtags?\s*:?\s*(.+)$",
        "editing_notes": r"^(?:special editing notes|editing notes)\s*:?\s*(.+)$",
    }
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        for key, pattern in key_map.items():
            hit = re.match(pattern, stripped, flags=re.IGNORECASE)
            if hit:
                fields[key] = hit.group(1).strip()
                break
    return fields


def daily_batch_id(for_date: date | None = None) -> str:
    day = for_date or date.today()
    return day.isoformat()


def batch_dir(for_date: date | None = None) -> Path:
    path = project_root() / "data" / "daily_batches" / daily_batch_id(for_date)
    path.mkdir(parents=True, exist_ok=True)
    return path


def agent_prompt_section(*, brief_overrides: str | None = None) -> str:
    preset = load_defaults()
    opener = preset.get("opener") or {}
    captions = preset.get("captions") or {}
    lines = [
        "## DrivenVisuals default edit preset (apply unless brief overrides)",
        f"- Preset: `{preset.get('preset_id', 'driven_visuals')}`",
        "- Opener must hit hard in first 1–2s: movement, strong subject, no black/static open.",
        f"- Opening pacing (~{opener.get('fast_pacing_window_sec', 6)}s): "
        f"{opener.get('fast_beat_min_sec', 0.8)}–{opener.get('fast_beat_max_sec', 1.8)}s per visual; "
        f"then ~{opener.get('settle_beat_min_sec', 2)}–{opener.get('settle_beat_max_sec', 3.5)}s beats.",
        f"- Hook: {captions.get('words_per_phrase_min', 2)}–{captions.get('words_per_phrase_max', 5)} word phrases; "
        "strong 4–7 word hook when it matches speech (within ~1s).",
        f"- Captions: `{captions.get('mode', 'phrase')}` blocks (not single-word karaoke default).",
        "- Pattern interrupts: vary shot type/mood every few seconds without cheesy transitions.",
        "- Visual arc supports speech emotion; three daily videos must look distinct.",
        "- No background music unless brief requests it.",
        "- Run production library reuse checks (advisory unless user asked unused-only).",
        "- Before ship: `python scripts/check_render_quality.py --video path/to/final.mp4`",
        "",
        "Motivation montage defaults:",
        "`python scripts/build_motivation_job.py --slug ... --broll-query ...` "
        "(Driven pacing + phrase captions on by default; `--classic-captions` / `--uniform-pacing` to revert).",
        "",
    ]
    if brief_overrides and brief_overrides.strip():
        lines.extend(["### Daily brief overrides (authority for this batch)", brief_overrides.strip(), ""])
    return "\n".join(lines)


def write_batch_manifest(
    *,
    briefs: list[dict[str, Any]],
    batch_date: date | None = None,
    source_command: str = "",
) -> Path:
    folder = batch_dir(batch_date)
    manifest = {
        "batch_id": daily_batch_id(batch_date),
        "video_count": len(briefs),
        "briefs": briefs,
        "source_command_excerpt": source_command[:2000],
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path
