#!/usr/bin/env python3
"""Export frames + checklist for Cursor agent review (replaces API vision + code gates)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_clips_montage import probe_duration
from broll_frame_gate import wants_vehicle
from toolchain_env import resolve_tool, subprocess_env

SPEECH_CHECKLIST = """
## Agent speech checklist (required before ship)

- [ ] Opens strong — not mid-thought (`and`, `but`, `so`, …)
- [ ] Standalone hook — makes sense without prior minute of video
- [ ] Matches luxury/motivation tone; not apology or tangent
- [ ] Ends on a finished sentence; no cliffhanger word
- [ ] Not a repeat of a prior posted excerpt (read text; reuse check is advisory)

If wrong: rerun job with `--speech-option N` or `--speech-start SEC --speech-duration SEC`.
""".strip()


def _ffmpeg() -> str:
    return resolve_tool("ffmpeg") or "ffmpeg"


def extract_frame(video: Path, timestamp: float, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-y",
        "-ss",
        f"{max(0.0, timestamp):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(dest),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, env=subprocess_env())
    except subprocess.CalledProcessError:
        return False
    return dest.is_file() and dest.stat().st_size > 0


def _load_job_meta(job_dir: Path) -> dict[str, object]:
    path = job_dir / "job.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _final_sample_times(duration: float) -> list[tuple[str, float]]:
    if duration <= 0:
        return [("t0000", 0.0)]
    stamps: list[tuple[str, float]] = [
        ("t0000", 0.0),
        ("t0250", min(2.5, max(0.0, duration - 0.1))),
        ("t0500", min(5.0, max(0.0, duration - 0.1))),
    ]
    if duration > 12:
        stamps.append(("t_mid", duration * 0.5))
    if duration > 8:
        stamps.append(("t_end", max(0.0, duration - 1.0)))
    return stamps


def _car_opener_extra(duration: float) -> list[tuple[str, float]]:
    return [
        ("opener_1s", min(1.0, max(0.0, duration - 0.1))),
        ("opener_3s", min(3.0, max(0.0, duration - 0.1))),
    ]


def write_speech_review_pack(
    out_dir: Path,
    *,
    title: str,
    video_id: str,
    url: str,
    captions: Path,
    min_seconds: float,
    max_seconds: float,
    avoid_ranges: list[tuple[float, float]] | None = None,
    chosen_start: float | None,
    chosen_duration: float | None,
    chosen_option: int | None,
    pick_method: str,
) -> Path:
    from build_motivation_job import captions_text, ranked_speech_excerpts

    out_dir.mkdir(parents=True, exist_ok=True)
    options = ranked_speech_excerpts(
        captions,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        avoid_ranges=avoid_ranges,
    )
    if chosen_option is None and chosen_start is not None:
        for index, opt in enumerate(options, start=1):
            if abs(opt.start - chosen_start) < 0.6 and abs(opt.duration - (chosen_duration or 0)) < 1.5:
                chosen_option = index
                break
    lines = [
        "# Cursor speech review",
        "",
        f"**Source:** [{title}]({url}) (`{video_id}`)",
        "",
        f"**Pick method:** `{pick_method}`",
        "",
    ]
    if chosen_start is not None and chosen_duration is not None:
        chosen_text = captions_text(captions, start=chosen_start, duration=chosen_duration).strip()
        opt_note = f" (option #{chosen_option})" if chosen_option else ""
        lines.extend(
            [
                "## Chosen excerpt (current job)",
                "",
                f"- Window: `{chosen_start:.1f}s` + `{chosen_duration:.1f}s`{opt_note}",
                "",
                f"> {chosen_text}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Chosen excerpt",
                "",
                "None yet — pick an option below, then rerun:",
                "",
                "```powershell",
                f"python scripts/build_motivation_job.py --slug ... --speech-option 1",
                "# or",
                f"python scripts/build_motivation_job.py --slug ... --speech-start 120 --speech-duration 24",
                "```",
                "",
            ]
        )

    lines.append("## Ranked options (code scores — you decide)")
    lines.append("")
    if not options:
        lines.append("(No complete sentence windows in captions.)")
    else:
        for index, opt in enumerate(options, start=1):
            marker = " **← USED**" if chosen_option == index else ""
            preview = opt.text if len(opt.text) <= 280 else opt.text[:277] + "..."
            lines.extend(
                [
                    f"### Option {index}{marker}",
                    "",
                    f"- Score `{opt.score}` (advisory) | `{opt.start:.1f}s` + `{opt.duration:.1f}s`",
                    "",
                    f"> {preview}",
                    "",
                ]
            )

    lines.append(SPEECH_CHECKLIST)
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append("- [ ] **SPEECH OK**")
    lines.append("- [ ] **PICK DIFFERENT** — note option # or new URL")
    lines.append("")

    payload = {
        "title": title,
        "video_id": video_id,
        "url": url,
        "pick_method": pick_method,
        "chosen": {
            "start": chosen_start,
            "duration": chosen_duration,
            "option": chosen_option,
        },
        "options": [
            {
                "option": i,
                "score": o.score,
                "start": o.start,
                "duration": o.duration,
                "text": o.text,
            }
            for i, o in enumerate(options, start=1)
        ],
    }
    path = out_dir / "SPEECH.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "SPEECH.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_review_pack(
    *,
    out_dir: Path,
    video: Path | None = None,
    job_dir: Path | None = None,
    clips_dir: Path | None = None,
    subject: str = "",
    clip_sample: int = 0,
) -> Path:
    """Write REVIEW.md + PNG stills. Returns out_dir."""
    meta = _load_job_meta(job_dir) if job_dir else {}
    if not subject:
        subject = str(meta.get("subject") or meta.get("broll_query") or "")
    if video is None and job_dir:
        output = meta.get("output")
        if output:
            candidate = Path(str(output))
            if not candidate.is_file():
                candidate = job_dir / "output" / f"{job_dir.name}-motivation.mp4"
            video = candidate if candidate.is_file() else None
    if clips_dir is None and job_dir:
        clips_dir = job_dir / "clips"

    out_dir.mkdir(parents=True, exist_ok=True)
    final_dir = out_dir / "final"
    clips_out = out_dir / "clips"
    lines: list[str] = [
        "# Cursor montage review",
        "",
        "Automated frame/vision gates were skipped or deferred. **You (Cursor agent) decide ship vs remake.**",
        "",
        "## Subject",
        "",
        f"`{subject or '(not set)'}`",
        "",
    ]

    speech_review = out_dir / "SPEECH.md"
    if speech_review.is_file():
        lines.extend(
            [
                "## Speech",
                "",
                "**Required:** read [`SPEECH.md`](SPEECH.md) and approve excerpt before ship.",
                "",
            ]
        )
    excerpt = str(meta.get("speech_excerpt") or "").strip()
    if excerpt:
        lines.extend(
            [
                "### On-screen excerpt (from job.json)",
                "",
                f"> {excerpt}",
                "",
            ]
        )
    if excerpt or speech_review.is_file():
        lines.extend(
            [
                "- Agent must pass speech checklist in SPEECH.md (not code score alone).",
                "- Weak line → `--speech-option N`, `--speech-start` / `--speech-duration`, or new `--speech-url`.",
                "",
            ]
        )

    vehicle = wants_vehicle(subject)
    if vehicle:
        lines.extend(
            [
                "## Car rules (required)",
                "",
                "- Opener 0–5s: **full exterior** (front / 3-4 / side). Not cabin, not rear-only, not host.",
                "- Rest of video: exterior only; no dashboard / wheel POV / cabin.",
                "- Check stills: `final/t0000.png`, `t0250`, `t0500` (+ opener extras if present).",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Visual rules",
                "",
                "- Subject on screen in opener; no talking-head host, title card, or empty room.",
                "- Check `final/t0000.png`, `t0250.png`, `t0500.png`.",
                "",
            ]
        )

    lines.append("## Verdict")
    lines.append("")
    lines.append("- [ ] **SHIP** — all checks pass")
    lines.append("- [ ] **REMAKE** — note failures below")
    lines.append("")

    if video and video.is_file():
        duration = probe_duration(video)
        lines.insert(4, f"Final: `{video.as_posix()}` ({duration:.1f}s)")
        lines.insert(5, "")
        for label, stamp in _final_sample_times(duration):
            dest = final_dir / f"{label}.png"
            if extract_frame(video, stamp, dest):
                lines.append(f"- ![{label}](final/{label}.png) @ {stamp:.1f}s")
        if vehicle:
            for label, stamp in _car_opener_extra(duration):
                dest = final_dir / f"{label}.png"
                if extract_frame(video, stamp, dest):
                    lines.append(f"- ![{label}](final/{label}.png) @ {stamp:.1f}s")
        lines.append("")
    else:
        lines.extend(["## Final video", "", "(none — pass `--video` or `--job-dir` with output)", ""])

    if clips_dir and clips_dir.is_dir():
        clips = sorted(clips_dir.glob("*.mp4"))
        if clips and clip_sample > 0:
            lines.extend(["## Sample source clips", ""])
            step = max(1, len(clips) // clip_sample)
            picked = clips[::step][:clip_sample]
            for clip in picked:
                dur = probe_duration(clip)
                mid = dur * 0.5
                safe = clip.stem.replace(" ", "_")
                for tag, t in (("start", 0.35), ("mid", mid)):
                    dest = clips_out / f"{safe}_{tag}.png"
                    if extract_frame(clip, t, dest):
                        lines.append(f"- `{clip.name}` @ {t:.1f}s: clips/{dest.name}")
            lines.append("")

    review_path = out_dir / "REVIEW.md"
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Cursor agent review pack (PNGs + REVIEW.md) for a montage or clip folder.",
    )
    parser.add_argument("--job-dir", type=Path, default=None, help="Motivation job folder")
    parser.add_argument("--video", type=Path, default=None, help="Finished MP4")
    parser.add_argument("--clips-dir", type=Path, default=None, help="Folder of B-roll parts")
    parser.add_argument("--subject", default="", help="On-screen subject (cars, yacht, …)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output folder (default: <job-dir>/cursor-review or ./cursor-review)",
    )
    parser.add_argument(
        "--clip-sample",
        type=int,
        default=0,
        help="Max source clips to sample (0 = final only; skill default)",
    )
    parser.add_argument(
        "--captions",
        type=Path,
        default=None,
        help="subs.en.json3 — write SPEECH.md only (with --min-seconds / --max-seconds)",
    )
    parser.add_argument("--speech-title", default="Speech source")
    parser.add_argument("--speech-url", default="")
    parser.add_argument("--speech-id", default="")
    parser.add_argument("--min-seconds", type=float, default=20.0)
    parser.add_argument("--max-seconds", type=float, default=28.0)
    args = parser.parse_args()

    if (
        not args.job_dir
        and not args.video
        and not args.clips_dir
        and not args.captions
    ):
        print("Pass --job-dir, --video, --clips-dir, and/or --captions", file=sys.stderr)
        return 2

    out_dir = args.out_dir
    if out_dir is None:
        if args.job_dir:
            out_dir = args.job_dir / "cursor-review"
        else:
            out_dir = Path("cursor-review")

    if args.captions:
        if not args.captions.is_file():
            print(f"Captions not found: {args.captions}", file=sys.stderr)
            return 1
        speech_path = write_speech_review_pack(
            out_dir,
            title=args.speech_title,
            video_id=args.speech_id,
            url=args.speech_url,
            captions=args.captions,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
            chosen_start=None,
            chosen_duration=None,
            chosen_option=None,
            pick_method="manual-review",
        )
        print(f"Speech review: {speech_path}")
        return 0

    pack = write_review_pack(
        out_dir=out_dir,
        video=args.video,
        job_dir=args.job_dir,
        clips_dir=args.clips_dir,
        subject=args.subject,
        clip_sample=args.clip_sample,
    )
    print(f"Review pack: {pack / 'REVIEW.md'}")
    if (out_dir / "SPEECH.md").is_file():
        print(f"Speech review: {out_dir / 'SPEECH.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
