"""Shared Cursor command text for luxury-clips montage (Make Short + weekly)."""

from __future__ import annotations

import re
from typing import Any

_CAR = re.compile(
    r"\b(porsche|ferrari|lamborghini|911|gt3|supercar|coupe|mclaren|amg|bmw m|corvette)\b",
    re.I,
)


def visual_production_hints(visual: str) -> list[str]:
    """Append montage rules inferred from the visual / B-roll line."""
    text = (visual or "").strip()
    if not text:
        return []
    hints: list[str] = []
    def _no_people(q: str) -> bool:
        try:
            from broll_frame_gate import prefers_no_people as fn

            return bool(fn(q))
        except ImportError:
            return "view" in q.lower() or "ocean" in q.lower() or "skyline" in q.lower()

    if _no_people(text):
        hints.append(
            "View / scenery B-roll: no people in frame; use exclude-people / view-only search; "
            "50fps+ clips only."
        )
    if _CAR.search(text):
        hints.append(
            "Car B-roll: exterior only for opener (full body 5s+); no cabin/dashboard; 50fps+ source clips."
        )
    if "ocean" in text.lower() or "drone" in text.lower() or "apartment" in text.lower():
        hints.append("Prefer high-fps drone or skyline views; reject 24p/30p sources.")
    return hints


def compose_montage_command(
    *,
    owner: str,
    audio_query: str | None = None,
    broll_query: str,
    speaker: str | None = None,
    min_seconds: int = 30,
    max_seconds: int = 90,
    extra_instructions: str | None = None,
    style_ref_paths: list[str] | None = None,
    images_to_make: str | None = None,
    require_stills_first: bool = False,
    job_slug: str | None = None,
) -> str:
    owner = (owner or "chris").strip().lower()
    broll = (broll_query or "cinematic b-roll").strip()
    audio = (audio_query or "").strip()

    lines = [
        "Make a new 9:16 motivational Short using the luxury-clips-montage workflow.",
        "Run `python scripts/build_motivation_job.py` with appropriate flags — do not reimplement FFmpeg or download logic.",
        f"Owner account: {owner} — record combination usage for this owner when done.",
        "",
        "Before picking audio or visuals:",
        "- Query production library: `python scripts/production_library_cli.py list`",
        "- Check combinations catalog / existing transcripts — skip the same excerpt unless Extra instructions allow a remake.",
        "- Set speaker from actual clip title/channel (not search query). If search was Goggins but clip is Jocko, register as Jocko Willink.",
        "- Reuse of prior sources is allowed by default. Unused-only only if Extra instructions say unused / never used.",
        "",
    ]

    if job_slug:
        lines.append(f"Use job slug: `{job_slug}` for downloads under downloads/motivational/.")
        lines.append("")

    spk = (speaker or "").strip()
    if spk:
        lines.append(f"Requested speaker: {spk}")
        lines.append("")

    if audio:
        lines.append(f"Search for audio (any type — speech, podcast clip, interview, etc.): {audio}")
    else:
        lines.append("Search for audio: pick fitting motivational audio (any type — not limited to speeches).")

    lines.append(f"Visual / B-roll search: {broll}")
    lines.append(
        "Pipeline: download speech from YouTube, scrape captions for the clip, search B-roll for the visual line, "
        "grade + one-word captions (centered), register in production library. No background music on B-roll unless the brief asks for it."
    )
    lines.append(f"Default target length: {min_seconds}–{max_seconds} seconds unless extra instructions override.")

    for hint in visual_production_hints(broll):
        lines.append(f"- {hint}")

    refs = list(style_ref_paths or [])[:6]
    if refs:
        lines.append("")
        lines.append("Style-ref images (match this look via B-roll search + grade, do not overlay):")
        lines.extend(f"- {path}" for path in refs)

    make = (images_to_make or "").strip()
    if make or require_stills_first:
        lines.append("")
        if require_stills_first:
            lines.append(
                "Required: generate still(s) first with the dark-luxury-still skill, then run the montage "
                "(use stills as style refs for B-roll matching, do not overlay)."
            )
        if make:
            lines.append(
                "Images to make for this video (dark-luxury-still skill, charcoal + light plum cast; "
                "use as style refs, do not overlay):"
            )
            lines.append(make)

    if extra_instructions and extra_instructions.strip():
        lines.append("")
        lines.append("Extra instructions:")
        lines.append(extra_instructions.strip())

    lines.extend(
        [
            "",
            "Before downloading audio, query the production library and check existing transcripts — skip the same excerpt unless Extra instructions allow a remake.",
            "Register the finished video in the production library when done.",
        ]
    )
    return "\n".join(lines)


def compose_from_slot(slot: dict[str, Any], *, owner: str | None = None) -> str:
    """Build command body from a weekly slot dict."""
    own = str(owner or slot.get("owner") or "chris")
    speaker = str(slot.get("speaker") or "").strip()
    visual = str(slot.get("visual_direction") or "cinematic b-roll").strip()
    audio = f"{speaker} motivational speech" if speaker else None
    week = str(slot.get("week_start") or "")
    day = str(slot.get("day") or "")
    slot_no = int(slot.get("slot") or 1)
    slug = None
    if week and day:
        slug = f"weekly-{own}-{week}-{day}-{slot_no}"
    stills = slot.get("require_stills_first")
    if isinstance(stills, int):
        stills = bool(stills)
    return compose_montage_command(
        owner=own,
        audio_query=audio,
        broll_query=visual,
        speaker=speaker or None,
        style_ref_paths=list(slot.get("image_paths") or []),
        images_to_make=str(slot.get("image_prompt") or "") or None,
        require_stills_first=bool(stills),
        job_slug=slug,
        extra_instructions=str(slot.get("extra_instructions") or "") or None,
    )
