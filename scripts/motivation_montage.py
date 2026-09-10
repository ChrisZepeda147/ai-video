"""Core logic for luxury motivational montage jobs."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_reuse  # noqa: E402
from build_stills_slideshow import burn_captions  # noqa: E402
from motivation_grade import grade_filter  # noqa: E402
from motivation_pool import (  # noqa: E402
    pull_assets,
    register_combination,
    resolve_build_selection,
)
from youtube_popular_downloader import (  # noqa: E402
    VideoCandidate,
    export_clip,
    probe_duration,
)

try:
    import yt_dlp
except ImportError as exc:
    raise RuntimeError("pip install -r scripts/requirements-youtube.txt") from exc


VISUAL_STYLE_QUERIES = {
    "scenery": "cinematic luxury scenery drone 4k short",
    "ai_cars": "luxury supercar cinematic b-roll 4k short",
    "mixed": "luxury car yacht mansion cinematic 4k short",
}

DEFAULT_CONFIG = {"speech_query": "", "broll_query": ""}


@dataclass
class MotivationJobResult:
    slug: str
    status: str
    output_path: str | None = None
    job_json_path: str | None = None
    speech_youtube_id: str | None = None
    broll_youtube_ids: list[str] | None = None
    duration_sec: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_root() -> Path:
    return ROOT


def config_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "downloads" / "motivational" / "config.json"


def load_config(root: Path | None = None) -> dict[str, str]:
    path = config_path(root)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def job_dir(root: Path, slug: str) -> Path:
    return root / "downloads" / "motivational" / slug


def output_path_for(root: Path, slug: str) -> Path:
    return job_dir(root, slug) / "output" / f"{slug}-motivation.mp4"


def _download_subtitles(url: str, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return None
    matches = sorted(out_dir.glob("*.json3"))
    return matches[0] if matches else None


def _trim_audio(input_path: Path, output_path: Path, *, start: float, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-i", str(input_path),
        "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _concat_clips(clips: list[Path], output: Path) -> None:
    list_file = output.with_suffix(".txt")
    lines = [f"file '{clip.resolve().as_posix()}'" for clip in clips]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _trim_video(input_path: Path, output_path: Path, *, duration: float) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path), "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", "-movflags", "+faststart", str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _mux_audio(video: Path, audio: Path, output: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _apply_grade(input_path: Path, output_path: Path, *, enabled: bool) -> None:
    vf = grade_filter(enabled=enabled)
    if not vf:
        shutil.copy2(input_path, output_path)
        return
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path), "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy", "-movflags", "+faststart", str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _export_broll_from_pool(
    broll_assets: list[dict[str, Any]],
    *,
    work_dir: Path,
    root: Path,
    segment_length: float,
) -> tuple[list[Path], list[str]]:
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    broll_ids: list[str] = []

    for asset in broll_assets:
        source = root / str(asset["local_path"])
        if not source.is_file():
            continue
        yt_id = str(asset["youtube_id"])
        duration = probe_duration(source)
        start = max(0.0, min(duration - segment_length, random.random() * max(duration - segment_length, 0)))
        clip_path = clips_dir / f"{yt_id}_{len(exported)+1:02d}.mp4"
        export_clip(
            source,
            clip_path,
            start=start,
            duration=min(segment_length, duration),
            aspect_ratio="9:16",
            max_height=1080,
        )
        exported.append(clip_path)
        broll_ids.append(yt_id)

    if not exported:
        raise RuntimeError("No B-roll clips could be exported from pool")
    random.shuffle(exported)
    return exported, broll_ids


def _candidate_from_asset(asset: dict[str, Any]) -> VideoCandidate:
    return VideoCandidate(
        video_id=str(asset["youtube_id"]),
        title=str(asset.get("title") or asset["youtube_id"]),
        url=str(asset.get("url") or f"https://www.youtube.com/watch?v={asset['youtube_id']}"),
        channel="pool",
        view_count=None,
        duration_seconds=asset.get("duration_sec"),
        published_at=None,
        source="pool",
    )


def run_motivation_job(
    *,
    slug: str,
    broll_query: str | None = None,
    visual_style: str = "mixed",
    speech_query: str | None = None,
    speech_url: str | None = None,
    speech_youtube_id: str | None = None,
    broll_youtube_ids: list[str] | None = None,
    pull_before_build: bool = False,
    speech_pull_count: int = 3,
    broll_pull_count: int = 6,
    target_seconds: float = 30.0,
    segment_length: float = 8.0,
    apply_grade: bool = True,
    keep_work: bool = False,
    rerender: bool = False,
    register_site: bool = True,
    root: Path | None = None,
) -> MotivationJobResult:
    root = root or project_root()
    config = load_config(root)
    broll_query = broll_query or config.get("broll_query") or VISUAL_STYLE_QUERIES.get(visual_style, VISUAL_STYLE_QUERIES["mixed"])
    speech_query = (speech_query if speech_query is not None else config.get("speech_query", "")).strip()

    out_final = output_path_for(root, slug)
    work = job_dir(root, slug)
    if out_final.is_file() and not rerender:
        return MotivationJobResult(
            slug=slug,
            status="completed",
            output_path=out_final.relative_to(root).as_posix(),
            job_json_path=str((work / "job.json").relative_to(root).as_posix()) if (work / "job.json").is_file() else None,
            duration_sec=probe_duration(out_final),
        )

    if work.exists() and rerender:
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    (work / "output").mkdir(parents=True, exist_ok=True)

    if pull_before_build:
        if not speech_query:
            raise ValueError("speech_query is required when pulling new sources")
        pull_assets(
            speech_query=speech_query,
            broll_query=broll_query,
            speech_count=speech_pull_count,
            broll_count=broll_pull_count,
            root=root,
        )

    if speech_url:
        raise RuntimeError("Use pool pull for speech — paste a YouTube search query instead of URL")

    speech_asset, broll_assets = resolve_build_selection(
        speech_youtube_id=speech_youtube_id,
        broll_youtube_ids=broll_youtube_ids,
        root=root,
    )
    speech = _candidate_from_asset(speech_asset)

    speech_audio = root / str(speech_asset["local_path"])
    if not speech_audio.is_file():
        raise RuntimeError(f"Speech file missing in pool: {speech_asset['local_path']}")

    speech_duration = probe_duration(speech_audio)
    target = min(target_seconds, max(speech_duration - 1, 10))
    max_start = max(0.0, speech_duration - target - 1)
    speech_start = random.uniform(0.0, max_start) if max_start > 0 else 0.0

    trimmed_audio = work / "speech_trim.mp3"
    _trim_audio(speech_audio, trimmed_audio, start=speech_start, duration=target)

    subtitle_path = _download_subtitles(speech.url, work / "subs")

    broll_clips, broll_ids = _export_broll_from_pool(
        broll_assets,
        work_dir=work,
        root=root,
        segment_length=segment_length,
    )

    montage_raw = work / "montage_raw.mp4"
    if len(broll_clips) == 1:
        _trim_video(broll_clips[0], montage_raw, duration=target)
    else:
        looped: list[Path] = []
        total = 0.0
        idx = 0
        while total < target and idx < len(broll_clips) * 4:
            clip = broll_clips[idx % len(broll_clips)]
            looped.append(clip)
            total += min(segment_length, probe_duration(clip))
            idx += 1
        concat_path = work / "montage_concat.mp4"
        _concat_clips(looped, concat_path)
        _trim_video(concat_path, montage_raw, duration=target)

    muxed = work / "muxed.mp4"
    _mux_audio(montage_raw, trimmed_audio, muxed)

    graded = work / "graded.mp4"
    _apply_grade(muxed, graded, enabled=apply_grade)

    if subtitle_path and subtitle_path.is_file():
        burn_captions(
            graded,
            subtitle_path,
            out_final,
            width=1080,
            height=1920,
            audio_start=speech_start,
            audio_duration=target,
            word_by_word=True,
        )
    else:
        shutil.copy2(graded, out_final)

    register_combination(speech_id=speech.video_id, broll_ids=broll_ids, slug=slug, root=root)

    job_meta = {
        "slug": slug,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "speech_query": speech_query or speech_asset.get("query"),
        "broll_query": broll_query,
        "visual_style": visual_style,
        "target_seconds": target,
        "segment_length": segment_length,
        "speech_youtube_id": speech.video_id,
        "broll_youtube_ids": broll_ids,
        "speech_start_sec": speech_start,
        "output_path": out_final.relative_to(root).as_posix(),
    }
    job_json = work / "job.json"
    job_json.write_text(json.dumps(job_meta, indent=2), encoding="utf-8")

    content_reuse.register_video(
        youtube_id=speech.video_id,
        file_path=out_final,
        title=slug.replace("-", " ").title(),
        root=root,
    )
    for yt_id in broll_ids:
        content_reuse.register_video(youtube_id=yt_id, title=f"broll:{yt_id}", root=root)
    content_reuse.rebuild(root)

    if register_site:
        try:
            from discovery.site_videos import sync_legacy_renders_to_site

            sync_legacy_renders_to_site(slugs=[slug], root=root)
        except Exception:
            pass

    if not keep_work:
        for folder_name in ("clips", "subs"):
            shutil.rmtree(work / folder_name, ignore_errors=True)
        for temp in work.glob("*.mp4"):
            if temp.name != out_final.name:
                temp.unlink(missing_ok=True)

    duration = probe_duration(out_final)
    return MotivationJobResult(
        slug=slug,
        status="completed",
        output_path=out_final.relative_to(root).as_posix(),
        job_json_path=job_json.relative_to(root).as_posix(),
        speech_youtube_id=speech.video_id,
        broll_youtube_ids=broll_ids,
        duration_sec=duration,
    )
