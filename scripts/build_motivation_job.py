#!/usr/bin/env python3
"""One-shot luxury motivation job: speech + B-roll + render + cleanup.

Speaker comes from downloads/motivational/config.json (edit `speaker`).
CLI --speaker / --speech-query override the file.
Reuse policy defaults to allow — production library is advisory context only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import content_reuse
import yt_dlp
from build_clips_montage import build_montage, probe_duration
from discovery.reuse_policy import REUSE_POLICIES, normalize_reuse_policy
from toolchain_env import (
    check_toolchain,
    classify_download_error,
    format_toolchain_report,
    resolve_tool,
    subprocess_env,
)
from build_stills_slideshow import burn_captions, parse_json3_words
from youtube_popular_downloader import (
    VideoCandidate,
    discover_search,
    discover_urls,
    download_videos,
    filter_unwanted,
)

KEEP_AUDIO = frozenset({"speech.mp3", "subs.en.json3"})
KEEP_TOP = frozenset({"url.txt", "job.json", "config.json"})
JUNK_SUFFIXES = (
    "_source.webp",
    "_source.info.json",
    "_source.mp4",
    ".burn.ass",
    ".trim.srt",
    ".trim.center.ass",
    ".info.json",
    ".nocap.mp4",
)
JUNK_NAMES = frozenset({"manifest.json", "clips-urls.txt"})


class MotivationJobError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def job_dir_for(slug: str, jobs_root: Path) -> Path:
    return jobs_root / slug


def default_config_path(jobs_root: Path) -> Path:
    return jobs_root / "config.json"


def load_speech_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {"speaker": "Andrew Tate", "speech_query": ""}
    data = json.loads(path.read_text(encoding="utf-8"))
    speaker = str(data.get("speaker") or "").strip()
    query = str(data.get("speech_query") or "").strip()
    return {"speaker": speaker or "Andrew Tate", "speech_query": query}


def speech_query_for(speaker: str, query: str) -> str:
    if query:
        return query
    return f"{speaker} motivational speech"


def resolve_speech_settings(
    *,
    jobs_root: Path,
    config_path: Path | None,
    speaker_flag: str | None,
    query_flag: str | None,
) -> tuple[str, str, Path]:
    path = config_path or default_config_path(jobs_root)
    config = load_speech_config(path)
    speaker = (speaker_flag or "").strip() or config["speaker"]
    query = speech_query_for(speaker, (query_flag or "").strip() or config["speech_query"])
    return speaker, query, path


def used_ids() -> set[str]:
    return content_reuse.used_youtube_ids()


def speaker_matches(candidate: VideoCandidate, speaker: str) -> bool:
    hay = f"{candidate.title} {candidate.channel}".lower()
    tokens = [part for part in speaker.lower().split() if part]
    if not tokens:
        return True
    if "tate" in tokens:
        return "tate" in hay
    return all(token in hay for token in tokens)


def speech_score(candidate: VideoCandidate) -> tuple[int, int]:
    title = candidate.title.lower()
    score = 0
    if "no music" in title:
        score += 5
    if "motivational" in title:
        score += 2
    duration = candidate.duration_seconds or 0
    if 180 <= duration <= 2400:
        score += 3
    return (score, candidate.view_count or 0)


def prior_source_ranges(video_id: str) -> list[tuple[float, float]]:
    """Advisory ranges from production library for this YouTube source."""
    try:
        from discovery.config import default_db_path, load_env
        from discovery.store import DiscoveryStore

        load_env()
        store = DiscoveryStore(default_db_path())
        try:
            rows = store._conn.execute(
                """
                SELECT source_start_sec, source_end_sec
                FROM production_library_videos
                WHERE source_external_id = ?
                  AND source_start_sec IS NOT NULL
                  AND source_end_sec IS NOT NULL
                ORDER BY created_at DESC
                """,
                (video_id,),
            ).fetchall()
        finally:
            store.close()
        return [
            (float(row["source_start_sec"]), float(row["source_end_sec"]))
            for row in rows
            if row["source_start_sec"] is not None and row["source_end_sec"] is not None
        ]
    except Exception:
        return []


def search_speeches(
    *,
    query: str,
    speaker: str,
    limit: int,
    reuse_policy: str = "allow",
) -> list[VideoCandidate]:
    raw = discover_search(query=query, limit=max(limit * 3, 12))
    used = used_ids()
    skip = used if reuse_policy == "require_new" else set()
    matches = [
        item
        for item in raw
        if item.video_id not in skip and speaker_matches(item, speaker)
    ]
    if reuse_policy == "prefer_new":
        matches.sort(
            key=lambda item: (
                item.video_id in used,
                -speech_score(item)[0],
                -speech_score(item)[1],
            )
        )
    else:
        matches.sort(key=speech_score, reverse=True)
    return matches[:limit]


def download_one_audio(candidate: VideoCandidate, audio_dir: Path) -> tuple[Path | None, str | None]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    results = download_videos(
        [candidate],
        output_dir=audio_dir,
        max_height=1080,
        audio_only=True,
        clip_length=15,
        max_parts=1,
        split_parts=False,
        keep_source=False,
        aspect_ratio="original",
    )
    if not results or results[0].get("status") != "ok":
        error = results[0].get("error") if results else "download failed"
        return None, classify_download_error(str(error))
    mp3s = sorted(audio_dir.glob("*.mp3"))
    return (mp3s[0], None) if mp3s else (None, "DOWNLOAD_FAILED")


def download_subs(url: str, audio_dir: Path) -> Path:
    audio_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3/srt/best",
        "outtmpl": str(audio_dir / "subs.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    json3 = audio_dir / "subs.en.json3"
    if json3.is_file():
        return json3
    matches = list(audio_dir.glob("subs*.json3")) + list(audio_dir.glob("subs*.srt"))
    if not matches:
        raise FileNotFoundError(f"No captions downloaded for {url}")
    return matches[0]


def json3_word_times(path: Path) -> list[tuple[float, str]]:
    words = parse_json3_words(path, start=0.0, duration=1_000_000.0)
    return [(start, text) for start, _end, text in words]


def _range_overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return max(a0, b0) < min(a1, b1)


def pick_speech_excerpt(
    captions: Path,
    *,
    min_seconds: float,
    max_seconds: float,
    avoid_ranges: list[tuple[float, float]] | None = None,
) -> tuple[float, float]:
    if captions.suffix.lower() != ".json3":
        return 0.0, max_seconds
    words = json3_word_times(captions)
    if not words:
        return 0.0, max_seconds

    avoid = avoid_ranges or []
    candidates: list[tuple[float, float, int]] = []
    start_points = sorted({0.0, *(word[0] for word in words if word[0] >= 0.0)})
    for start in start_points:
        if any(_range_overlaps(start, start + min_seconds, lo, hi) for lo, hi in avoid):
            continue
        window_end = start + max_seconds
        window_min = start + min_seconds
        best: tuple[float, float] | None = None
        score = 0
        for i, (when, text) in enumerate(words):
            if when < window_min or when > window_end:
                continue
            nxt = words[i + 1][0] if i + 1 < len(words) else when + 2.0
            gap = nxt - when
            ends_sentence = text.endswith((".", "?", "!"))
            if gap < 0.65 and not ends_sentence:
                continue
            duration = min(when - start + 0.45, max_seconds)
            if duration < min_seconds:
                continue
            local_score = 2 if ends_sentence else 1
            best = (start, duration)
            score = local_score
            if ends_sentence and gap >= 0.65:
                break
        if best and not any(_range_overlaps(best[0], best[0] + best[1], lo, hi) for lo, hi in avoid):
            candidates.append((best[0], best[1], score))

    if candidates:
        candidates.sort(key=lambda item: (-item[2], item[0]))
        chosen = candidates[0]
        return chosen[0], chosen[1]

    start = words[0][0] if words[0][0] < 3.0 else 0.0
    last = min(words[-1][0] - start + 0.4, max_seconds)
    return start, max(last, min_seconds)


def shift_json3(src: Path, dest: Path, *, start: float, duration: float) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    start_ms = start * 1000.0
    end_ms = (start + duration) * 1000.0
    shifted: list[dict[str, Any]] = []
    for event in data.get("events") or []:
        t0 = float(event.get("tStartMs") or 0)
        if t0 > end_ms or t0 + 4000 < start_ms:
            continue
        row = dict(event)
        row["tStartMs"] = t0 - start_ms
        shifted.append(row)
    data["events"] = shifted
    dest.write_text(json.dumps(data), encoding="utf-8")


def trim_audio(src: Path, dest: Path, *, start: float, duration: float) -> None:
    ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(src),
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def verify_output(path: Path, expected: float) -> None:
    ffprobe = resolve_tool("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    streams: dict[str, float] = {}
    for line in result.stdout.strip().splitlines():
        kind, _, value = line.partition(",")
        streams[kind] = float(value)
    video = streams.get("video")
    audio = streams.get("audio")
    if video is None or audio is None:
        raise RuntimeError(f"Missing streams in {path}: {streams}")
    if abs(video - audio) > 0.1:
        raise RuntimeError(f"Sync fail: video={video:.3f} audio={audio:.3f}")
    if abs(video - expected) > 0.15:
        raise RuntimeError(f"Duration fail: got {video:.3f} want {expected:.3f}")


def is_junk(path: Path) -> bool:
    name = path.name
    if name in JUNK_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in JUNK_SUFFIXES)


def cleanup_job_dir(job_dir: Path, *, keep_work: bool = False) -> list[Path]:
    if not job_dir.is_dir():
        return []
    removed: list[Path] = []
    output_ready = any((job_dir / "output").glob("*.mp4")) if (job_dir / "output").is_dir() else False

    for path in job_dir.rglob("*"):
        if not path.is_file():
            continue
        if "stills" in path.parts:
            continue
        if path.parent.name == "output" and path.suffix.lower() == ".mp4":
            continue
        if path.name in KEEP_TOP or path.name in KEEP_AUDIO:
            continue
        extra_srt = path.name.endswith(".srt") and (path.with_suffix(".json3")).is_file()
        if is_junk(path) or extra_srt:
            path.unlink(missing_ok=True)
            removed.append(path)

    audio_dir = job_dir / "audio"
    if audio_dir.is_dir() and (audio_dir / "speech.mp3").is_file():
        for path in audio_dir.iterdir():
            if path.is_file() and path.name not in KEEP_AUDIO:
                path.unlink(missing_ok=True)
                removed.append(path)

    if output_ready and not keep_work:
        clips = job_dir / "clips"
        if clips.is_dir():
            shutil.rmtree(clips)
            removed.append(clips)

    return removed


def prepare_speech(
    *,
    audio_dir: Path,
    url_file: Path,
    speaker: str,
    speech_query: str,
    speech_url: str,
    min_seconds: float,
    max_seconds: float,
    reuse_policy: str = "allow",
) -> tuple[VideoCandidate, float]:
    toolchain = check_toolchain()
    if not toolchain["ffmpeg"]["found"] or not toolchain["ffprobe"]["found"]:
        raise MotivationJobError(
            "FFMPEG_NOT_FOUND",
            format_toolchain_report(toolchain)
            + "\nSet FFMPEG_DIR in scripts/.env or install FFmpeg and add it to PATH.",
        )

    if speech_url:
        candidates = discover_urls([speech_url])
    else:
        candidates = search_speeches(
            query=speech_query,
            speaker=speaker,
            limit=8,
            reuse_policy=reuse_policy,
        )
    if not candidates:
        if reuse_policy == "require_new":
            raise MotivationJobError(
                "REUSE_RESTRICTION",
                "No unused speech candidates found. Try --speech-url or relax reuse policy.",
            )
        raise MotivationJobError(
            "NO_CANDIDATE_FOUND",
            "No speech candidates found. Try --speech-url or a different --speech-query.",
        )

    source_mp3: Path | None = None
    chosen: VideoCandidate | None = None
    last_code: str | None = None
    skipped_reuse = 0
    for candidate in candidates:
        if reuse_policy == "require_new" and candidate.video_id in used_ids() and not speech_url:
            skipped_reuse += 1
            continue
        used_before = candidate.video_id in used_ids()
        prior_ranges = prior_source_ranges(candidate.video_id) if used_before else []
        if used_before:
            print(
                f"Trying speech (previously used source): {candidate.title} ({candidate.video_id})"
            )
            if prior_ranges:
                formatted = ", ".join(f"{lo:.0f}s–{hi:.0f}s" for lo, hi in prior_ranges[:6])
                print(f"  prior ranges: {formatted}")
        else:
            print(f"Trying speech: {candidate.title} ({candidate.video_id})")
        try:
            source_mp3, error_code = download_one_audio(candidate, audio_dir)
        except Exception as exc:  # noqa: BLE001 — next candidate on age-gate / download fail
            error_code = classify_download_error(exc)
            print(f"  skip ({error_code}): {exc}")
            last_code = error_code
            if error_code == "FFMPEG_NOT_FOUND":
                break
            continue
        if error_code:
            print(f"  skip ({error_code})")
            last_code = error_code
            if error_code == "FFMPEG_NOT_FOUND":
                break
            continue
        if source_mp3:
            chosen = candidate
            break

    if last_code == "FFMPEG_NOT_FOUND":
        raise MotivationJobError("FFMPEG_NOT_FOUND", format_toolchain_report())
    if chosen is None or source_mp3 is None:
        if skipped_reuse and skipped_reuse == len(candidates):
            raise MotivationJobError(
                "REUSE_RESTRICTION",
                "All speech candidates were skipped by require_new reuse policy.",
            )
        if last_code:
            raise MotivationJobError(last_code, f"Speech download failed ({last_code}).")
        raise MotivationJobError("DOWNLOAD_FAILED", "Could not download speech from any candidate.")

    url_file.write_text(f"{chosen.url}\n", encoding="utf-8")
    captions = download_subs(chosen.url, audio_dir)
    prior_ranges = prior_source_ranges(chosen.video_id)
    avoid_ranges = prior_ranges if reuse_policy == "require_new" else None
    if prior_ranges and reuse_policy != "require_new":
        formatted = ", ".join(f"{lo:.0f}s–{hi:.0f}s" for lo, hi in prior_ranges[:8])
        print(f"  prior production segments (advisory): {formatted}")
    start, duration = pick_speech_excerpt(
        captions,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        avoid_ranges=avoid_ranges,
    )
    print(f"Excerpt: start={start:.2f}s duration={duration:.2f}s")

    speech_mp3 = audio_dir / "speech.mp3"
    trim_audio(source_mp3, speech_mp3, start=start, duration=duration)
    if source_mp3.resolve() != speech_mp3.resolve():
        source_mp3.unlink(missing_ok=True)

    stable_caps = audio_dir / "subs.en.json3"
    if captions.suffix.lower() == ".json3":
        shift_json3(captions, stable_caps, start=start, duration=duration)
        if captions.resolve() != stable_caps.resolve():
            captions.unlink(missing_ok=True)
    elif captions.resolve() != stable_caps.resolve():
        captions.replace(stable_caps)

    content_reuse.register_video(youtube_id=chosen.video_id, title=chosen.title)
    return chosen, duration


def prepare_broll(
    *,
    clips_dir: Path,
    query: str,
    limit: int,
    clip_length: int,
    max_parts: int,
    min_views: int,
    min_duration: int,
    reuse_policy: str = "allow",
) -> list[str]:
    raw = discover_search(query=query, limit=max(limit * 4, 16))
    used = used_ids()
    if reuse_policy == "require_new":
        pool = [item for item in raw if item.video_id not in used]
    else:
        pool = list(raw)
    candidates = filter_unwanted(
        pool,
        limit=limit,
        exclude_music=True,
        exclude_trailers=True,
        exclude_live=True,
        background_gameplay_only=False,
        min_views=min_views,
        min_duration=float(min_duration),
    )
    if reuse_policy == "prefer_new":
        candidates.sort(key=lambda item: item.video_id in used)
    if not candidates:
        if reuse_policy == "require_new":
            raise MotivationJobError(
                "REUSE_RESTRICTION",
                f"No unused B-roll for query: {query}",
            )
        raise MotivationJobError("NO_CANDIDATE_FOUND", f"No B-roll candidates for query: {query}")
    return download_broll_candidates(
        clips_dir,
        candidates,
        clip_length=clip_length,
        max_parts=max_parts,
    )


def download_broll_candidates(
    clips_dir: Path,
    candidates: list[VideoCandidate],
    *,
    clip_length: int,
    max_parts: int,
) -> list[str]:
    print(f"Downloading {len(candidates)} B-roll source(s)...")
    results = download_videos(
        candidates,
        output_dir=clips_dir,
        max_height=1080,
        audio_only=False,
        clip_length=clip_length,
        max_parts=max_parts,
        split_parts=True,
        keep_source=False,
        aspect_ratio="9:16",
    )
    ok_ids = [str(row.get("video_id") or "") for row in results if row.get("status") == "ok"]
    parts = list(clips_dir.glob("*_part*.mp4"))
    if not parts:
        raise RuntimeError("B-roll download produced no clips.")
    return [item for item in ok_ids if item]


def prepare_broll_from_ids(
    clips_dir: Path,
    video_ids: list[str],
    *,
    clip_length: int,
    max_parts: int,
) -> list[str]:
    urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids if video_id]
    candidates = discover_urls(urls)
    if not candidates:
        raise RuntimeError("Could not load B-roll IDs from job.json")
    return download_broll_candidates(
        clips_dir,
        candidates,
        clip_length=clip_length,
        max_parts=max_parts,
    )


def render_job(
    *,
    clips_dir: Path,
    audio: Path,
    captions: Path,
    output: Path,
    duration: float,
    segment_length: float,
    seed: int | None,
    grade: bool,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(".nocap.mp4")
    build_montage(
        clips_dir=clips_dir,
        audio=audio,
        output=temp_output,
        segment_length=segment_length,
        layout="single",
        grade=grade,
        seed=seed,
        width=1080,
        height=1920,
        audio_start=0.0,
        audio_duration=duration,
    )
    burn_captions(
        temp_output,
        captions,
        output,
        width=1080,
        height=1920,
        audio_start=0.0,
        audio_duration=duration,
        word_by_word=captions.suffix.lower() == ".json3",
    )
    temp_output.unlink(missing_ok=True)
    verify_output(output, duration)


def rerender_existing_job(
    *,
    jobs_root: Path,
    slug: str,
    segment_length: float,
    seed: int | None,
    grade: bool,
    clip_length: int,
    max_parts: int,
    keep_work: bool,
    cleanup: bool,
) -> int:
    job_dir = job_dir_for(slug, jobs_root)
    job_path = job_dir / "job.json"
    audio = job_dir / "audio" / "speech.mp3"
    captions = job_dir / "audio" / "subs.en.json3"
    output = job_dir / "output" / f"{slug}-motivation.mp4"
    if not job_path.is_file():
        print(f"No job.json at {job_path}", file=sys.stderr)
        return 1
    if not audio.is_file() or not captions.is_file():
        print(f"Missing speech or captions in {job_dir / 'audio'}", file=sys.stderr)
        return 1
    payload = json.loads(job_path.read_text(encoding="utf-8"))
    broll_ids = [str(item) for item in (payload.get("broll_ids") or []) if item]
    duration = float(payload.get("audio_duration") or probe_duration(audio))
    if not broll_ids:
        print("job.json has no broll_ids", file=sys.stderr)
        return 1
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    try:
        existing = list(clips_dir.glob("*_part*.mp4"))
        if not existing:
            prepare_broll_from_ids(
                clips_dir,
                broll_ids,
                clip_length=clip_length,
                max_parts=max_parts,
            )
        render_job(
            clips_dir=clips_dir,
            audio=audio,
            captions=captions,
            output=output,
            duration=duration,
            segment_length=segment_length,
            seed=seed,
            grade=grade,
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if cleanup:
        removed = cleanup_job_dir(job_dir, keep_work=keep_work)
        print(f"Cleaned {len(removed)} leftover file(s).")
    print(f"Saved: {output}")
    return 0


def write_job_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cleanup_all(jobs_root: Path, *, keep_work: bool) -> int:
    if not jobs_root.is_dir():
        print(f"No jobs folder: {jobs_root}", file=sys.stderr)
        return 1
    total = 0
    for child in sorted(jobs_root.iterdir()):
        if not child.is_dir():
            continue
        removed = cleanup_job_dir(child, keep_work=keep_work)
        print(f"Cleaned {child.name}: {len(removed)} item(s)")
        total += len(removed)
    content_reuse.rebuild()
    print(f"Cleanup done. Removed {total} item(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="Job folder name, e.g. yacht-motivation")
    parser.add_argument("--broll-query", default="", help="YouTube search for B-roll")
    parser.add_argument(
        "--speech-query",
        default=None,
        help="YouTube search for speech. Default: '{speaker} motivational speech'",
    )
    parser.add_argument("--speech-url", default="", help="Use this speech URL instead of search")
    parser.add_argument(
        "--reuse-policy",
        default="allow",
        choices=sorted(REUSE_POLICIES),
        help="allow (default): reuse OK; prefer_new: rank fresh first; require_new: unused only",
    )
    parser.add_argument(
        "--speaker",
        default=None,
        help="Who the speech is from. Default: downloads/motivational/config.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON with speaker + optional speech_query",
    )
    parser.add_argument("--jobs-root", type=Path, default=None)
    parser.add_argument("--min-seconds", type=float, default=60.0)
    parser.add_argument("--max-seconds", type=float, default=90.0)
    parser.add_argument("--segment-length", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-grade", action="store_true")
    parser.add_argument("--clips-limit", type=int, default=5)
    parser.add_argument("--clip-length", type=int, default=15)
    parser.add_argument("--max-parts", type=int, default=3)
    parser.add_argument("--min-views", type=int, default=50000)
    parser.add_argument("--min-duration", type=int, default=30)
    parser.add_argument("--keep-work", action="store_true", help="Keep clips/ after render")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true", help="Clean job folders and exit")
    parser.add_argument(
        "--rerender",
        action="store_true",
        help="Remake an existing job from job.json (same speech + B-roll IDs)",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = build_parser().parse_args()
    subprocess_env()
    reuse_policy = normalize_reuse_policy(args.reuse_policy)
    jobs_root = args.jobs_root or (project_root() / "downloads" / "motivational")
    speaker, speech_query, config_path = resolve_speech_settings(
        jobs_root=jobs_root,
        config_path=args.config,
        speaker_flag=args.speaker,
        query_flag=args.speech_query,
    )

    if args.cleanup_only:
        target = jobs_root / args.slug if args.slug else jobs_root
        if args.slug:
            removed = cleanup_job_dir(target, keep_work=args.keep_work)
            content_reuse.rebuild()
            print(f"Cleaned {target}: {len(removed)} item(s)")
            return 0
        return cleanup_all(jobs_root, keep_work=args.keep_work)

    if args.rerender:
        if not args.slug:
            print("--slug is required with --rerender", file=sys.stderr)
            return 2
        return rerender_existing_job(
            jobs_root=jobs_root,
            slug=args.slug,
            segment_length=args.segment_length,
            seed=args.seed,
            grade=not args.no_grade,
            clip_length=args.clip_length,
            max_parts=args.max_parts,
            keep_work=args.keep_work,
            cleanup=not args.no_cleanup,
        )

    if not args.slug or not args.broll_query:
        print("--slug and --broll-query are required unless --cleanup-only or --rerender", file=sys.stderr)
        return 2

    job_dir = job_dir_for(args.slug, jobs_root)
    audio_dir = job_dir / "audio"
    clips_dir = job_dir / "clips"
    output = job_dir / "output" / f"{args.slug}-motivation.mp4"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    print(f"Speaker: {speaker}  (edit {config_path.as_posix()})")
    print(f"Speech search: {speech_query}")
    print(f"Reuse policy: {reuse_policy}")
    print(format_toolchain_report())
    try:
        speech, duration = prepare_speech(
            audio_dir=audio_dir,
            url_file=job_dir / "url.txt",
            speaker=speaker,
            speech_query=speech_query,
            speech_url=args.speech_url,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
            reuse_policy=reuse_policy,
        )
        broll_ids = prepare_broll(
            clips_dir=clips_dir,
            query=args.broll_query,
            limit=args.clips_limit,
            clip_length=args.clip_length,
            max_parts=args.max_parts,
            min_views=args.min_views,
            min_duration=args.min_duration,
            reuse_policy=reuse_policy,
        )
        render_job(
            clips_dir=clips_dir,
            audio=audio_dir / "speech.mp3",
            captions=audio_dir / "subs.en.json3",
            output=output,
            duration=duration,
            segment_length=args.segment_length,
            seed=args.seed,
            grade=not args.no_grade,
        )
    except MotivationJobError as exc:
        print(exc, file=sys.stderr)
        return 1
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        code = classify_download_error(exc)
        print(f"{code}: {exc}", file=sys.stderr)
        return 1

    write_job_json(
        job_dir / "job.json",
        {
            "slug": args.slug,
            "speaker": speaker,
            "speech_query": speech_query,
            "speech_id": speech.video_id,
            "speech_title": speech.title,
            "speech_url": speech.url,
            "broll_ids": broll_ids,
            "audio_duration": duration,
            "output": str(output.as_posix()),
        },
    )
    content_reuse.rebuild()
    if not args.no_cleanup:
        removed = cleanup_job_dir(job_dir, keep_work=args.keep_work)
        print(f"Cleaned {len(removed)} leftover file(s).")
    try:
        from discovery.auto_register import sync_register_best_effort

        reg = sync_register_best_effort(slug=args.slug, visual_style=args.broll_query)
        if reg:
            print(f"Production library: Video {reg.get('id')} ({reg.get('video_key')})")
    except Exception as exc:
        print(f"Library register skipped: {exc}", file=sys.stderr)
    try:
        from discovery.site_videos import sync_legacy_renders_to_site

        sync_legacy_renders_to_site(slugs=[args.slug], rebuild_catalog=False)
    except Exception:
        pass
    print(f"Saved: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
