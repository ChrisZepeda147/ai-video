#!/usr/bin/env python3
"""Render two Ferrari jobs from clips already on disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from build_motivation_job import probe_duration, render_job, write_job_json

JOBS = ROOT / "downloads" / "motivational"


def render_one(slug: str, query: str, hook: str, clips_dir: Path) -> None:
    job = JOBS / slug
    audio = job / "audio" / "speech.mp3"
    captions = job / "audio" / "subs.en.json3"
    output = job / "output" / f"{slug}-motivation.mp4"
    if not audio.is_file() or not captions.is_file():
        raise FileNotFoundError(f"missing speech for {slug}")
    have = list(clips_dir.glob("*_part*.mp4"))
    if len(have) < 6:
        raise RuntimeError(f"{slug} only has {len(have)} clips")
    duration = probe_duration(audio)
    print(f"RENDER {slug}: {len(have)} clips, {duration:.1f}s speech", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    render_job(
        jobs_root=JOBS,
        clips_dir=clips_dir,
        audio=audio,
        captions=captions,
        output=output,
        duration=duration,
        segment_length=3.2,
        seed=None,
        grade=True,
        subject=query,
        playback_speed=0.80,
        use_vision=True,
        driven_pacing=False,
        caption_mode="phrase",
        hook_text=hook,
        quality_gate=True,
    )
    write_job_json(
        job / "job.json",
        {
            "slug": slug,
            "speaker": "Andrew Tate",
            "broll_query": query,
            "subject": query,
            "hook": hook,
            "audio_duration": duration,
            "output": str(output.as_posix()),
        },
    )
    print(f"SAVED {output}", flush=True)


def main() -> int:
    render_one(
        "ferrari-roma-coast-hero2",
        "Ferrari Roma full body coastal cinematic 4k",
        "YOU ARE BORN WITH FIRE",
        JOBS / "ferrari-roma-coast-hero2" / "clips",
    )
    render_one(
        "ferrari-sf90-hero-run",
        "Ferrari SF90 Stradale full exterior cinematic 4k",
        "THIS IS THE HILL",
        JOBS / "ferrari-sf90-hero-run" / "clips",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
