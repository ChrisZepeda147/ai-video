#!/usr/bin/env python3
"""One-shot text-over-B-roll clip: search/download clips, stitch, burn static text.

Examples:
  python scripts/build_text_clip.py \\
    --slug ocean-waves \\
    --query "ocean waves cinematic 4k short" \\
    --text "Discipline beats motivation."

  python scripts/build_text_clip.py \\
    --slug reuse-demo \\
    --query "luxury yacht cinematic" \\
    --text "Stay locked in." \\
    --text-place bottom-center \\
    --duration 20
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import broll_pool
import content_reuse
from build_clips_montage import build_silent_montage, min_unique_clips_needed, probe_duration
from build_motivation_job import (
    broll_download_plan,
    ensure_broll_clips,
    filter_broll_clips,
    resolve_segment_length,
)
from text_overlay import VALID_PLACES, build_static_ass, burn_ass_on_video

DEFAULT_DURATION = 20.0
DEFAULT_JOBS_ROOT = "downloads/text-clips"


def configure_stdio() -> None:
    """Line-buffer stdout/stderr so progress shows in piped/non-TTY shells."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(line_buffering=True)


def log(msg: str, *, verbose: bool = True) -> None:
    if verbose:
        print(msg, flush=True)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def job_dir_for(slug: str, jobs_root: Path) -> Path:
    return jobs_root / slug


def segment_length_for(duration: float, segment_length: float | None) -> float:
    if segment_length is not None:
        return segment_length
    beats = max(3, min(6, int(round(duration / 5.0))))
    return max(3.0, duration / beats)


def list_local_clips(clips_dir: Path) -> list[Path]:
    if not clips_dir.is_dir():
        return []
    return sorted(clips_dir.glob("*.mp4"))


def verify_output(path: Path, duration: float, *, tolerance: float = 0.35) -> None:
    actual = probe_duration(path)
    if abs(actual - duration) > tolerance:
        raise RuntimeError(f"Output duration {actual:.2f}s != target {duration:.2f}s")


def write_job_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_text_clip(
    *,
    jobs_root: Path,
    clips_dir: Path,
    output: Path,
    text: str,
    duration: float,
    segment_length: float,
    text_place: str,
    seed: int | None,
    grade: bool,
    subject: str,
    playback_speed: float,
    use_vision: bool,
    width: int,
    height: int,
    verbose: bool = True,
) -> set[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    silent = output.with_suffix(".silent.mp4")
    grade_note = "charcoal grade" if grade else "no grade"
    log(
        f"Rendering {duration:.0f}s montage: {len(list_local_clips(clips_dir))} clip(s), "
        f"{segment_length:.1f}s beats, {playback_speed:.0%} speed, {grade_note}",
        verbose=verbose,
    )
    used_clips = build_silent_montage(
        clips_dir=clips_dir,
        output=silent,
        target_duration=duration,
        segment_length=segment_length,
        grade=grade,
        seed=seed,
        width=width,
        height=height,
        subject=subject,
        playback_speed=playback_speed,
        use_vision=use_vision,
    )
    ass_path = output.with_suffix(".text.ass")
    ass_path.write_text(
        build_static_ass(
            text,
            duration=duration,
            width=width,
            height=height,
            place=text_place,
        ),
        encoding="utf-8",
    )
    log("Burning text overlay...", verbose=verbose)
    burn_ass_on_video(silent, ass_path, output)
    silent.unlink(missing_ok=True)
    verify_output(output, duration)
    size_mb = output.stat().st_size / (1024 * 1024)
    log(f"  render done: {output.name} ({size_mb:.1f} MB, {duration:.1f}s)", verbose=verbose)
    broll_pool.stash_unused_clips(
        jobs_root,
        subject=subject,
        clips_dir=clips_dir,
        used=used_clips,
    )
    return used_clips


def ensure_clips(
    *,
    jobs_root: Path,
    clips_dir: Path,
    query: str,
    needed_clips: int,
    clips_limit: int,
    clip_length: int,
    max_parts: int,
    min_views: int,
    min_duration: int,
    start_offset: float,
    use_vision: bool,
    local_only: bool,
    verbose: bool = True,
) -> list[str]:
    if local_only:
        log(f"Local-only: using clips in {clips_dir.as_posix()}", verbose=verbose)
        kept = filter_broll_clips(clips_dir, subject=query, use_vision=use_vision)
        if len(kept) < needed_clips:
            plain = [path for path in list_local_clips(clips_dir) if path not in kept]
            kept.extend(plain)
        log(f"  found {len(kept)} clip(s), need {needed_clips}", verbose=verbose)
        if len(kept) < needed_clips:
            raise RuntimeError(
                f"Need {needed_clips} clip(s) in {clips_dir}, found {len(kept)}. "
                "Drop more mp4s there or rerun without --local-only."
            )
        return []

    existing = len(list_local_clips(clips_dir))
    if existing:
        log(f"Clips folder already has {existing} mp4(s)", verbose=verbose)
    log(f"Pulling unused B-roll from pool for: {query}", verbose=verbose)
    log(
        f"Searching/downloading if needed: {clips_limit} source(s), "
        f"{max_parts} part(s) each, {clip_length}s per part",
        verbose=verbose,
    )
    return ensure_broll_clips(
        jobs_root=jobs_root,
        clips_dir=clips_dir,
        subject=query,
        query=query,
        needed_clips=needed_clips,
        clips_limit=clips_limit,
        clip_length=clip_length,
        max_parts=max_parts,
        min_views=min_views,
        min_duration=min_duration,
        start_offset=start_offset,
        use_vision=use_vision,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="Job folder name")
    parser.add_argument("--query", required=True, help="YouTube search query / on-screen subject")
    parser.add_argument("--text", required=True, help="Static text burned onto the clip")
    parser.add_argument(
        "--text-place",
        default="mid-center",
        choices=sorted(VALID_PLACES),
        help="Text anchor on frame (default: mid-center)",
    )
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Output length in seconds")
    parser.add_argument("--segment-length", type=float, default=None, help="Seconds per montage beat")
    parser.add_argument(
        "--jobs-root",
        type=Path,
        default=None,
        help=f"Job root directory (default: {DEFAULT_JOBS_ROOT})",
    )
    parser.add_argument("--clips-dir", type=Path, default=None, help="Use clips from this folder instead of downloading")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Do not download; only use clips already in the job clips folder",
    )
    parser.add_argument("--clips-limit", type=int, default=4, help="Max YouTube sources to download")
    parser.add_argument("--clip-length", type=int, default=12, help="Seconds per downloaded source part")
    parser.add_argument("--max-parts", type=int, default=2, help="Parts per downloaded source")
    parser.add_argument("--min-views", type=int, default=10_000, help="Skip low-view B-roll")
    parser.add_argument("--min-duration", type=int, default=20, help="Skip very short sources")
    parser.add_argument("--intro-skip", type=float, default=8.0, help="Skip first N seconds of each source")
    parser.add_argument("--playback-speed", type=float, default=1.0, help="Clip playback rate (1 = source speed)")
    parser.add_argument("--seed", type=int, default=None, help="Shuffle seed for reproducible cuts")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--no-grade", action="store_true", help="Skip dark-luxury color grade")
    parser.add_argument("--no-vision", action="store_true", help="Skip optional vision subject check")
    parser.add_argument("--keep-work", action="store_true", help="Keep clips/ after render")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip post-render cleanup")
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print step-by-step progress (default: on)",
    )
    return parser


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    verbose = bool(args.verbose)
    jobs_root = args.jobs_root or (project_root() / DEFAULT_JOBS_ROOT)
    job_dir = job_dir_for(args.slug, jobs_root)
    clips_dir = args.clips_dir or (job_dir / "clips")
    output = job_dir / "output" / f"{args.slug}-text.mp4"

    duration = float(args.duration)
    if duration <= 0:
        print("--duration must be positive", file=sys.stderr)
        return 1

    segment_length = segment_length_for(duration, args.segment_length)
    needed_clips = min_unique_clips_needed(
        duration=duration,
        segment_length=segment_length,
        layout="single",
    )
    clips_limit, clip_length, max_parts = broll_download_plan(
        duration=duration,
        segment_length=segment_length,
        clips_limit=args.clips_limit,
        clip_length=args.clip_length,
        max_parts=args.max_parts,
    )

    clips_dir.mkdir(parents=True, exist_ok=True)
    log(f"Text clip job: {args.slug}", verbose=verbose)
    log(f"  query: {args.query}", verbose=verbose)
    log(f"  text: {args.text!r} @ {args.text_place}", verbose=verbose)
    log(f"  output: {output.as_posix()}", verbose=verbose)
    log(
        f"  plan: {duration:.0f}s, {needed_clips} clip(s) needed, "
        f"{segment_length:.1f}s beats",
        verbose=verbose,
    )
    try:
        broll_ids = ensure_clips(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            query=args.query,
            needed_clips=needed_clips,
            clips_limit=clips_limit,
            clip_length=clip_length,
            max_parts=max_parts,
            min_views=args.min_views,
            min_duration=args.min_duration,
            start_offset=args.intro_skip,
            use_vision=not args.no_vision,
            local_only=args.local_only or args.clips_dir is not None,
            verbose=verbose,
        )
        if broll_ids:
            log(f"B-roll sources: {', '.join(broll_ids)}", verbose=verbose)
        render_text_clip(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            output=output,
            text=args.text,
            duration=duration,
            segment_length=segment_length,
            text_place=args.text_place,
            seed=args.seed,
            grade=not args.no_grade,
            subject=args.query,
            playback_speed=args.playback_speed,
            use_vision=not args.no_vision,
            width=args.width,
            height=args.height,
            verbose=verbose,
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr, flush=True)
        return 1

    log("Writing job.json...", verbose=verbose)
    write_job_json(
        job_dir / "job.json",
        {
            "slug": args.slug,
            "query": args.query,
            "text": args.text,
            "text_place": args.text_place,
            "duration": duration,
            "segment_length": segment_length,
            "playback_speed": args.playback_speed,
            "broll_ids": broll_ids,
            "output": str(output.as_posix()),
        },
    )
    log("Rebuilding content catalog...", verbose=verbose)
    content_reuse.rebuild()

    if not args.no_cleanup and not args.keep_work:
        clips_path = clips_dir
        if clips_path.is_dir() and args.clips_dir is None:
            try:
                shutil.rmtree(clips_path)
                log(f"Cleaned {clips_path.name}/", verbose=verbose)
            except OSError:
                pass

    log(f"Saved: {output}", verbose=verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
