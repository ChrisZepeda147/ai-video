#!/usr/bin/env python3
"""Export a 9:16 montage for Instagram feed (4:5) or Reels (9:16 + square pixels).

Instagram feed posts only accept 4:5 to 16:9. A 1080x1920 file is 9:16, so
Business Suite rejects it. A broken sample aspect ratio also makes IG read the
file as ultra-wide (e.g. 10800x1920).

Examples:
  python scripts/export_instagram_video.py --input in.mp4 --output feed.mp4 --preset feed
  python scripts/export_instagram_video.py --input in.mp4 --output reel.mp4 --preset reel
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from toolchain_env import resolve_tool

PRESETS = {
    "feed": (1080, 1350),  # 4:5 — Instagram in-feed
    "reel": (1080, 1920),  # 9:16 — Reels / Stories / TikTok / Shorts
}


def _tool(name: str) -> str:
    path = resolve_tool(name)
    if not path:
        raise RuntimeError(f"{name} not found — set FFMPEG_DIR in scripts/.env")
    return path


def probe_video(path: Path) -> dict:
    raw = subprocess.check_output(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,sample_aspect_ratio,display_aspect_ratio,duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    streams = json.loads(raw).get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream in {path}")
    return streams[0]


def feed_crop_filter(src_w: int, src_h: int, out_w: int, out_h: int) -> str:
    """Cover-crop to 4:5. Bias toward the bottom so burned captions stay in frame."""
    scale = max(out_w / src_w, out_h / src_h)
    scaled_w = max(out_w, int(round(src_w * scale)))
    scaled_h = max(out_h, int(round(src_h * scale)))
    crop_x = max(0, (scaled_w - out_w) // 2)
    # Keep the lower third: captions sit ~120px from the bottom on 9:16 renders.
    crop_y = max(0, scaled_h - out_h)
    return (
        f"scale={scaled_w}:{scaled_h}:flags=lanczos,"
        f"crop={out_w}:{out_h}:{crop_x}:{crop_y},"
        "setsar=1,format=yuv420p"
    )


def reel_filter(out_w: int, out_h: int) -> str:
    return (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1,format=yuv420p"
    )


def export_instagram_video(
    source: Path,
    output: Path,
    *,
    preset: str,
) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset {preset!r}")
    if not source.is_file():
        raise FileNotFoundError(f"Input not found: {source}")

    out_w, out_h = PRESETS[preset]
    info = probe_video(source)
    src_w = int(info["width"])
    src_h = int(info["height"])
    vf = (
        feed_crop_filter(src_w, src_h, out_w, out_h)
        if preset == "feed"
        else reel_filter(out_w, out_h)
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _tool("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]
    subprocess.run(cmd, check=True)
    written = probe_video(output)
    return {
        "preset": preset,
        "output": str(output),
        "width": int(written["width"]),
        "height": int(written["height"]),
        "sar": written.get("sample_aspect_ratio"),
        "dar": written.get("display_aspect_ratio"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="feed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = export_instagram_video(args.input, args.output, preset=args.preset)
    print(
        f"wrote {result['output']} {result['width']}x{result['height']} "
        f"sar={result['sar']} dar={result['dar']} preset={result['preset']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
