#!/usr/bin/env python3
"""One-shot luxury motivation job: speech + B-roll + render + cleanup.

Speaker comes from downloads/motivational/config.json (edit `speaker`).
CLI --speaker / --speech-query override the file.
Reuse policy defaults to allow — production library is advisory context only.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import broll_pool
import content_reuse
import speech_pool
import yt_dlp
from broll_frame_gate import (
    MIN_CLEAN_SPAN,
    confirm_span_subject,
    longest_clean_span,
    scan_clip_local,
    subject_tokens,
    title_matches_subject,
    wants_vehicle,
)
from build_clips_montage import (
    DEFAULT_PLAYBACK_SPEED,
    SPEECH_TRIM_TAIL_SEC,
    build_montage,
    drop_low_fps_clips,
    probe_duration,
    remux_speech_over_video,
    segment_length_for_duration,
    unique_clips_required,
)
from discovery.driven_visuals import speech_window_defaults
from discovery.motivation_paths import (
    default_job_date,
    is_date_folder,
    iter_motivation_job_dirs,
    job_dir_for,
    motivation_output_path,
    resolve_job_dir,
)
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
    is_cabin_titled,
    pick_usable_fps_candidates,
    title_suggests_usable_fps,
)

KEEP_AUDIO = frozenset({"speech.mp3", "subs.en.json3"})
KEEP_TOP = frozenset({"url.txt", "job.json", "config.json"})


def _preview(text: str, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _reuse_hit_detail(hit: content_reuse.ReuseHit) -> str:
    where = hit.path or hit.title
    return f"{hit.reason} (prior: {where})"
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


def captions_text(path: Path, *, start: float = 0.0, duration: float = 1_000_000.0) -> str:
    if path.suffix.lower() != ".json3":
        return content_reuse.transcript_text_from_json3(path)
    words = parse_json3_words(path, start=start, duration=duration)
    return " ".join(text for _start, _end, text in words)


def _word_ends_sentence(text: str) -> bool:
    stripped = (text or "").strip().rstrip("\"'”’)")
    return bool(stripped) and stripped[-1] in ".?!"


def _sentence_start_indexes(words: list[tuple[float, str]]) -> list[int]:
    starts = [0]
    for index in range(1, len(words)):
        if _word_ends_sentence(words[index - 1][1]):
            starts.append(index)
    return starts


def _clean_speech_start_index(words: list[tuple[float, str]], start_index: int) -> int:
    """Skip duplicated opener tokens (They / They've / stutter) at excerpt start."""
    index = start_index
    while index + 1 < len(words):
        current = words[index][1].lower().strip(".,!?\"'")
        nxt = words[index + 1][1].lower().strip(".,!?\"'")
        if current in {"they", "you", "i", "we"} and (nxt.startswith(current) or nxt == current):
            index += 1
            continue
        if current == nxt:
            index += 1
            continue
        break
    return index


def json3_cue_end_sec(captions: Path, word_time: float) -> float | None:
    """End time of the json3 caption cue that contains word_time (absolute source seconds)."""
    if captions.suffix.lower() != ".json3":
        return None
    data = json.loads(captions.read_text(encoding="utf-8"))
    word_ms = word_time * 1000.0
    best: float | None = None
    for event in data.get("events") or []:
        segs = event.get("segs") or []
        spoken = [
            seg
            for seg in segs
            if str(seg.get("utf8") or "").strip() not in ("", "\n")
        ]
        if not spoken:
            continue
        base_ms = float(event.get("tStartMs") or 0)
        dur_ms = float(event.get("dDurationMs") or 0)
        if dur_ms <= 0:
            continue
        first_ms = base_ms + float(spoken[0].get("tOffsetMs") or 0)
        last_ms = base_ms + float(spoken[-1].get("tOffsetMs") or 0)
        cue_end_ms = base_ms + dur_ms
        if word_ms < first_ms - 120 or word_ms > cue_end_ms + 120:
            continue
        if word_ms >= last_ms - 80 and abs(word_ms - last_ms) <= 120:
            end_sec = cue_end_ms / 1000.0
            best = end_sec if best is None else max(best, end_sec)
    return best


def _hard_stop_after_sentence(
    words: list[tuple[float, str]],
    close_index: int,
    *,
    captions: Path | None,
) -> float:
    """End of spoken cue for this sentence, without bleeding into the next sentence."""
    when, _text = words[close_index]
    stop = when + 0.35
    if captions is not None:
        cue_end = json3_cue_end_sec(captions, when)
        if cue_end is not None:
            stop = cue_end + 0.06
    if close_index + 1 < len(words):
        stop = min(stop, words[close_index + 1][0] - 0.04)
    return stop


def _speech_tail_after_word(
    words: list[tuple[float, str]],
    index: int,
    *,
    captions: Path | None = None,
) -> float:
    when, _text = words[index]
    if captions is not None:
        cue_end = json3_cue_end_sec(captions, when)
        if cue_end is not None:
            return max(cue_end - when, 0.35)
    if index + 1 < len(words):
        gap = words[index + 1][0] - when
        return min(1.5, max(0.35, gap))
    return 1.5


def _pick_window_from_words(
    words: list[tuple[float, str]],
    *,
    min_seconds: float,
    max_seconds: float,
    default_start: float | None = None,
    captions: Path | None = None,
) -> tuple[float, float] | None:
    if not words:
        return None
    starts = _sentence_start_indexes(words)
    if default_start is None:
        start_index = starts[0]
    else:
        start_index = starts[0]
        for index in starts:
            if words[index][0] <= default_start + 0.05:
                start_index = index
            else:
                break
        if words[start_index][0] + min_seconds > words[-1][0] + 0.5:
            for index in starts:
                if words[index][0] >= default_start - 0.05:
                    start_index = index
                    break
    start_index = _clean_speech_start_index(words, start_index)
    start = words[start_index][0]
    window_min = start + min_seconds
    window_max = start + max_seconds
    best: tuple[float, float] | None = None
    for i in range(start_index, len(words)):
        when, text = words[i]
        if when < window_min:
            continue
        if when > window_max:
            break
        if not _word_ends_sentence(text):
            continue
        stop = _hard_stop_after_sentence(words, i, captions=captions)
        duration = min(stop - start, max_seconds)
        if duration < min_seconds:
            continue
        best = (start, duration)
        return best
    if best:
        return best
    return None


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
    start_points = sorted({0.0, *(word[0] for word in words if word[0] >= 0.0)})
    for start in start_points:
        if any(_range_overlaps(start, start + min_seconds, lo, hi) for lo, hi in avoid):
            continue
        picked = _pick_window_from_words(
            words,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            default_start=start,
            captions=captions,
        )
        if picked and not any(_range_overlaps(picked[0], picked[0] + picked[1], lo, hi) for lo, hi in avoid):
            return picked

    start = words[0][0] if words[0][0] < 3.0 else 0.0
    picked = _pick_window_from_words(
        words,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        default_start=start,
        captions=captions,
    )
    if picked:
        return picked
    return start, _fallback_speech_duration(
        words,
        start=start,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        captions=captions,
    )


def _fallback_speech_duration(
    words: list[tuple[float, str]],
    *,
    start: float,
    min_seconds: float,
    max_seconds: float,
    captions: Path | None,
) -> float:
    """Keep the last spoken word inside the window instead of hard-cutting at max_seconds."""
    window_end = start + max_seconds
    last_index: int | None = None
    for index, (when, _text) in enumerate(words):
        if when + 0.05 < start:
            continue
        if when <= window_end + 0.05:
            last_index = index
        else:
            break
    if last_index is None:
        return max_seconds
    tail = _speech_tail_after_word(words, last_index, captions=captions)
    end = min(words[last_index][0] + tail + 0.12, window_end)
    return max(min_seconds, min(max_seconds, end - start))


def leftover_speech_windows(
    captions: Path,
    *,
    used_start: float,
    used_duration: float,
    min_seconds: float,
    max_seconds: float,
    source_duration: float = 0.0,
) -> list[tuple[float, float]]:
    """Unused leftover excerpts after the job takes its window."""
    if captions.suffix.lower() != ".json3":
        return []
    words = json3_word_times(captions)
    if not words:
        return []
    windows: list[tuple[float, float]] = []
    cursor = used_start + used_duration + 0.15
    while True:
        remaining = [(when, text) for when, text in words if when >= cursor]
        start_at = set(_sentence_start_indexes(words))
        while remaining:
            index = next(
                (i for i, (when, _text) in enumerate(words) if abs(when - remaining[0][0]) < 1e-6),
                None,
            )
            if index is None or index in start_at:
                break
            remaining = remaining[1:]
        picked = _pick_window_from_words(
            remaining,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            captions=captions,
        )
        if picked is None:
            break
        windows.append(picked)
        cursor = picked[0] + picked[1] + 0.15
    before = [(when, text) for when, text in words if when + 0.15 < used_start]
    picked_before = _pick_window_from_words(
        before,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        captions=captions,
    )
    if picked_before and picked_before[0] + picked_before[1] <= used_start:
        windows.insert(0, picked_before)
    if source_duration <= 0:
        return windows
    clamped: list[tuple[float, float]] = []
    for start, duration in windows:
        duration = min(duration, source_duration - start)
        if duration >= min_seconds:
            clamped.append((start, duration))
    return clamped


def shift_json3(src: Path, dest: Path, *, start: float, duration: float) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    start_ms = start * 1000.0
    end_ms = (start + duration) * 1000.0
    shifted: list[dict[str, Any]] = []
    for event in data.get("events") or []:
        t0 = float(event.get("tStartMs") or 0)
        dur_ms = float(event.get("dDurationMs") or 0)
        if t0 >= end_ms or t0 + dur_ms <= start_ms:
            continue
        row = dict(event)
        rel_start = max(t0, start_ms)
        row["tStartMs"] = rel_start - start_ms
        visible_end = min(t0 + dur_ms, end_ms)
        row["dDurationMs"] = max(0.0, visible_end - rel_start)
        if row["dDurationMs"] <= 0:
            continue
        shifted.append(row)
    data["events"] = shifted
    dest.write_text(json.dumps(data), encoding="utf-8")


def extend_excerpt_duration(
    captions: Path,
    *,
    start: float,
    duration: float,
    max_seconds: float,
    source_duration: float = 0.0,
) -> float:
    """Finish the closing sentence cue without pulling in the next unrelated sentence."""
    if captions.suffix.lower() != ".json3":
        return duration
    words = json3_word_times(captions)
    if not words:
        return duration
    window_end = start + duration
    close_index: int | None = None
    for index, (when, text) in enumerate(words):
        if when + 0.02 < start:
            continue
        if when > window_end + 0.05:
            break
        if _word_ends_sentence(text):
            close_index = index
    if close_index is None:
        last_index: int | None = None
        for index, (when, _text) in enumerate(words):
            if when + 0.02 < start:
                continue
            if when <= window_end + 0.05:
                last_index = index
            else:
                break
        if last_index is None:
            return duration
        stop = _hard_stop_after_sentence(words, last_index, captions=captions)
    else:
        stop = _hard_stop_after_sentence(words, close_index, captions=captions)
    needed = max(0.2, stop - start)
    needed = min(needed, max_seconds)
    if source_duration > 0:
        needed = min(needed, max(0.2, source_duration - start))
    return needed


def trim_audio(
    src: Path,
    dest: Path,
    *,
    start: float,
    duration: float,
    tail_pad: float = SPEECH_TRIM_TAIL_SEC,
) -> None:
    ffmpeg = resolve_tool("ffmpeg") or "ffmpeg"
    out = dest
    tmp: Path | None = None
    if src.resolve() == dest.resolve():
        tmp = dest.with_name(f"{dest.stem}.trim{dest.suffix}")
        out = tmp
    start = max(0.0, float(start))
    duration = max(0.2, float(duration))
    encode_duration = duration + max(0.0, float(tail_pad))
    pad = min(1.5, start)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start - pad:.3f}",
        "-i",
        str(src),
        "-ss",
        f"{pad:.3f}",
        "-t",
        f"{encode_duration:.3f}",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        "-avoid_negative_ts",
        "make_zero",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if tmp is None:
        return
    dest.unlink(missing_ok=True)
    tmp.replace(dest)


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
        streams[kind] = float(value.strip().split(",")[0].strip())
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
    if "_source." in name or name.endswith(".part"):
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
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            removed.append(path)

    audio_dir = job_dir / "audio"
    if audio_dir.is_dir() and (audio_dir / "speech.mp3").is_file():
        for path in audio_dir.iterdir():
            if path.is_file() and path.name not in KEEP_AUDIO:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                removed.append(path)

    if output_ready and not keep_work:
        clips = job_dir / "clips"
        if clips.is_dir():
            try:
                shutil.rmtree(clips)
            except OSError:
                pass
            else:
                removed.append(clips)

    return removed


def speech_record_id(youtube_id: str, start: float) -> str:
    return f"video:{youtube_id}:{int(round(start * 1000))}"


def _clear_audio_dir(audio_dir: Path) -> None:
    for leftover in audio_dir.glob("*"):
        if leftover.is_file():
            leftover.unlink(missing_ok=True)


def _write_job_speech(
    *,
    audio_dir: Path,
    source_mp3: Path,
    captions: Path,
    start: float,
    duration: float,
    keep_source: bool = False,
) -> float:
    speech_mp3 = audio_dir / "speech.mp3"
    trim_audio(source_mp3, speech_mp3, start=start, duration=duration)
    probed = probe_duration(speech_mp3)
    if not keep_source and source_mp3.resolve() != speech_mp3.resolve():
        source_mp3.unlink(missing_ok=True)
    stable_caps = audio_dir / "subs.en.json3"
    if captions.suffix.lower() == ".json3":
        shift_json3(captions, stable_caps, start=start, duration=probed)
        if not keep_source and captions.resolve() != stable_caps.resolve():
            captions.unlink(missing_ok=True)
        return probed
    if not keep_source and captions.resolve() != stable_caps.resolve():
        captions.replace(stable_caps)
    return probed


def _stash_speech_leftovers(
    *,
    jobs_root: Path,
    speaker: str,
    candidate: VideoCandidate,
    source_mp3: Path,
    captions: Path,
    used_start: float,
    used_duration: float,
    min_seconds: float,
    max_seconds: float,
    source_text: str,
) -> list[Path]:
    try:
        source_duration = probe_duration(source_mp3)
    except (subprocess.CalledProcessError, ValueError):
        source_duration = 0.0
    windows = leftover_speech_windows(
        captions,
        used_start=used_start,
        used_duration=used_duration,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        source_duration=source_duration,
    )
    if not windows:
        return []
    source_hash = content_reuse.speech_fingerprint(source_text)["transcript_hash"]
    stashed: list[Path] = []
    audio_dir = source_mp3.parent
    for index, (start, duration) in enumerate(windows, start=2):
        tmp_audio = audio_dir / f"_stash_part{index:02d}.mp3"
        tmp_caps = audio_dir / f"_stash_part{index:02d}.json3"
        try:
            trim_audio(source_mp3, tmp_audio, start=start, duration=duration)
            if captions.suffix.lower() == ".json3":
                shift_json3(captions, tmp_caps, start=start, duration=duration)
            else:
                tmp_audio.unlink(missing_ok=True)
                continue
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            print(f"  skip leftover {index}: {exc}")
            tmp_audio.unlink(missing_ok=True)
            tmp_caps.unlink(missing_ok=True)
            continue
        excerpt = captions_text(captions, start=start, duration=duration)
        dest = speech_pool.stash_excerpt(
            jobs_root,
            speaker=speaker,
            youtube_id=candidate.video_id,
            title=candidate.title,
            url=candidate.url,
            start=start,
            duration=duration,
            excerpt=excerpt,
            audio=tmp_audio,
            captions=tmp_caps,
            source_hash=source_hash,
        )
        if dest is not None:
            stashed.append(dest)
    if stashed:
        print(f"Stashed {len(stashed)} leftover speech excerpt(s) for later {speaker} jobs")
    return stashed


def clamp_pooled_speech_duration(duration: float, max_seconds: float) -> float:
    """Honor --max-seconds on leftover pool excerpts (often cut at 26–28s)."""
    return min(max(0.2, float(duration)), float(max_seconds))


def _take_pooled_speech(
    *,
    jobs_root: Path,
    audio_dir: Path,
    url_file: Path,
    speaker: str,
    speech_url: str,
    allow_reuse: bool,
    max_seconds: float,
) -> tuple[VideoCandidate, float, float, str, str] | None:
    want_id = speech_pool.youtube_id_from_url(speech_url) if speech_url else ""
    item = speech_pool.take_from_pool(
        jobs_root,
        speaker=speaker,
        audio_dir=audio_dir,
        youtube_id=want_id,
        allow_reuse=allow_reuse,
    )
    if item is None:
        return None
    duration = clamp_pooled_speech_duration(item.duration, max_seconds)
    excerpt = item.excerpt
    if duration + 0.2 < float(item.duration):
        duration = _write_job_speech(
            audio_dir=audio_dir,
            source_mp3=item.audio,
            captions=item.captions,
            start=0.0,
            duration=duration,
            keep_source=False,
        )
        excerpt = captions_text(audio_dir / "subs.en.json3", start=0.0, duration=duration)
        print(f"  clamped pooled speech {item.duration:.1f}s -> {duration:.1f}s")
    else:
        speech_mp3 = audio_dir / "speech.mp3"
        if speech_mp3.is_file():
            duration = probe_duration(speech_mp3)
    candidate = VideoCandidate(
        video_id=item.youtube_id,
        title=item.title,
        url=item.url,
        channel="",
        view_count=None,
        duration_seconds=item.duration,
        published_at=None,
        source="speech-pool",
    )
    url_file.write_text(f"{item.url}\n", encoding="utf-8")
    content_reuse.register_video(
        youtube_id=item.youtube_id,
        title=item.title,
        transcript=excerpt,
        role="speech",
        record_id=speech_record_id(item.youtube_id, item.start),
    )
    return candidate, item.start, duration, excerpt, excerpt


def prepare_speech(
    *,
    jobs_root: Path,
    audio_dir: Path,
    url_file: Path,
    speaker: str,
    speech_query: str,
    speech_url: str,
    min_seconds: float,
    max_seconds: float,
    reuse_policy: str = "allow",
    allow_reuse: bool | None = None,
) -> tuple[VideoCandidate, float, float, str, str]:
    if allow_reuse is None:
        allow_reuse = reuse_policy != "require_new"
    toolchain = check_toolchain()
    if not toolchain["ffmpeg"]["found"] or not toolchain["ffprobe"]["found"]:
        raise MotivationJobError(
            "FFMPEG_NOT_FOUND",
            format_toolchain_report(toolchain)
            + "\nSet FFMPEG_DIR in scripts/.env or install FFmpeg and add it to PATH.",
        )

    pooled = _take_pooled_speech(
        jobs_root=jobs_root,
        audio_dir=audio_dir,
        url_file=url_file,
        speaker=speaker,
        speech_url=speech_url,
        allow_reuse=allow_reuse,
        max_seconds=max_seconds,
    )
    if pooled is not None:
        return pooled

    if speech_url:
        candidates = discover_urls([speech_url])
        print(f"Speech URL: {speech_url}")
    else:
        candidates = search_speeches(
            query=speech_query,
            speaker=speaker,
            limit=8,
            reuse_policy=reuse_policy,
        )
        print(f"Speech candidates: {len(candidates)} (search: {speech_query})")
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
    excerpt_text = ""
    source_text = ""
    start = 0.0
    duration = max_seconds
    captions: Path | None = None
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
            if source_mp3:
                captions = download_subs(candidate.url, audio_dir)
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
        if source_mp3 is None or captions is None:
            continue
        source_text = captions_text(captions)
        avoid_ranges = prior_ranges if reuse_policy == "require_new" else None
        start, duration = pick_speech_excerpt(
            captions,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            avoid_ranges=avoid_ranges,
        )
        try:
            source_duration = probe_duration(source_mp3)
        except (subprocess.CalledProcessError, ValueError):
            source_duration = 0.0
        duration = extend_excerpt_duration(
            captions,
            start=start,
            duration=duration,
            max_seconds=max_seconds,
            source_duration=source_duration,
        )
        excerpt_text = captions_text(captions, start=start, duration=duration)
        hits = content_reuse.find_speech_reuse(
            excerpt_text,
            youtube_id=candidate.video_id,
            source_text=source_text,
        )
        if hits and not allow_reuse:
            print(f"  skip repeat transcript: {_reuse_hit_detail(hits[0])}")
            if speech_url:
                raise RuntimeError(f"Speech transcript already used: {_reuse_hit_detail(hits[0])}")
            _clear_audio_dir(audio_dir)
            continue
        chosen = candidate
        break

    if last_code == "FFMPEG_NOT_FOUND":
        raise MotivationJobError("FFMPEG_NOT_FOUND", format_toolchain_report())
    if chosen is None or source_mp3 is None or captions is None:
        if skipped_reuse and skipped_reuse == len(candidates):
            raise MotivationJobError(
                "REUSE_RESTRICTION",
                "All speech candidates were skipped by require_new reuse policy.",
            )
        if last_code:
            raise MotivationJobError(last_code, f"Speech download failed ({last_code}).")
        raise MotivationJobError("DOWNLOAD_FAILED", "Could not download speech from any candidate.")

    url_file.write_text(f"{chosen.url}\n", encoding="utf-8")
    print(f"Speech picked: {chosen.title} ({chosen.video_id})")
    print(f"Excerpt: start={start:.2f}s duration={duration:.2f}s")
    print(f"  preview: {_preview(excerpt_text)}")
    _stash_speech_leftovers(
        jobs_root=jobs_root,
        speaker=speaker,
        candidate=chosen,
        source_mp3=source_mp3,
        captions=captions,
        used_start=start,
        used_duration=duration,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        source_text=source_text,
    )
    duration = _write_job_speech(
        audio_dir=audio_dir,
        source_mp3=source_mp3,
        captions=captions,
        start=start,
        duration=duration,
    )
    content_reuse.register_video(
        youtube_id=chosen.video_id,
        title=chosen.title,
        transcript=excerpt_text,
        source_transcript=source_text,
        role="speech",
        record_id=speech_record_id(chosen.video_id, start),
    )
    return chosen, start, duration, excerpt_text, source_text


def resolve_segment_length(duration: float, segment_length: float | None) -> float:
    if segment_length is not None:
        return segment_length
    resolved = segment_length_for_duration(duration)
    print(f"Segment length: {resolved:.1f}s (auto from {duration:.0f}s speech)")
    return resolved


def broll_download_plan(
    *,
    duration: float,
    segment_length: float,
    clips_limit: int,
    clip_length: int,
    max_parts: int,
    split_full_source: bool = True,
    driven_pacing: bool = True,
    subject: str = "",
) -> tuple[int, int, int | None]:
    """Scale B-roll download so longer montages get longer parts and enough unique clips."""
    needed = unique_clips_required(
        target_duration=duration,
        segment_length=segment_length,
        layout="single",
        driven_pacing=driven_pacing,
        subject=subject,
    )
    resolved_clip_length = max(clip_length, int(math.ceil(segment_length * 1.25)))
    resolved_limit = max(clips_limit, needed + 2)
    if split_full_source:
        resolved_max_parts: int | None = None
        print(
            "B-roll plan: "
            f"{resolved_limit} source(s), full split @ {resolved_clip_length}s "
            f"(frame-gated + pooled, {needed} unique clips needed)"
        )
    else:
        parts_per_source = max(1, math.ceil(needed / max(resolved_limit, 1)))
        resolved_max_parts = max(max_parts, min(4, parts_per_source + 1))
        if (
            resolved_clip_length != clip_length
            or resolved_limit != clips_limit
            or resolved_max_parts != max_parts
        ):
            print(
                "B-roll plan: "
                f"{resolved_limit} source(s), {resolved_max_parts} part(s) each, "
                f"{resolved_clip_length}s per part ({needed} unique clips needed)"
            )
    return resolved_limit, resolved_clip_length, resolved_max_parts


def prepare_broll(
    *,
    clips_dir: Path,
    query: str,
    limit: int,
    clip_length: int,
    max_parts: int | None,
    min_views: int,
    min_duration: int,
    start_offset: float = 0.0,
    subject: str = "",
    use_vision: bool = True,
    reuse_policy: str = "allow",
    jobs_root: Path | None = None,
    split_full_source: bool = True,
) -> list[str]:
    raw = discover_search(query=query, limit=max(limit * 4, 16))
    if not title_suggests_usable_fps(query):
        extra = discover_search(query=f"{query} 60fps", limit=max(limit * 3, 12))
        seen = {item.video_id for item in raw}
        raw = [*extra, *[item for item in raw if item.video_id not in seen]]
    used = used_ids()
    if reuse_policy == "require_new":
        pool = [item for item in raw if item.video_id not in used]
    else:
        pool = list(raw)
    wanted = subject_tokens(query, subject)
    if wanted:
        titled = [item for item in pool if title_matches_subject(item.title, wanted)]
        if titled:
            print(f"Title-matched {len(titled)}/{len(pool)} B-roll hit(s) for: {', '.join(wanted)}")
            pool = titled
        elif reuse_policy != "require_new":
            print(f"No B-roll title matched {wanted}; using search hits")
    if wants_vehicle(subject or query):
        outside = [item for item in pool if not is_cabin_titled(item)]
        cabin = [item for item in pool if is_cabin_titled(item)]
        if outside and cabin:
            print(f"Ranked {len(outside)} exterior title(s) ahead of {len(cabin)} interior/walkaround")
            pool = [*outside, *cabin]
    candidates = filter_unwanted(
        pool,
        limit=max(limit * 4, 24),
        exclude_music=True,
        exclude_trailers=True,
        exclude_live=True,
        background_gameplay_only=False,
        min_views=min_views,
        min_duration=float(min_duration),
    )
    candidates = pick_usable_fps_candidates(candidates, limit=limit)
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
        start_offset=start_offset,
        subject=subject or query,
        use_vision=use_vision,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
    )


def download_broll_candidates(
    clips_dir: Path,
    candidates: list[VideoCandidate],
    *,
    clip_length: int,
    max_parts: int | None,
    start_offset: float = 0.0,
    subject: str = "",
    use_vision: bool = True,
    jobs_root: Path | None = None,
    split_full_source: bool = True,
) -> list[str]:
    split_parts = None if split_full_source else max_parts
    ok_ids: list[str] = []
    to_download: list[VideoCandidate] = []
    for candidate in candidates:
        video_id = candidate.video_id
        existing = sorted(clips_dir.glob(f"{video_id}_part*.mp4"))
        if existing:
            kept = filter_broll_clip_list(
                existing,
                subject=subject,
                use_vision=use_vision,
            )
            if kept:
                print(f"  skip download {video_id}: {len(kept)} cached part(s) in job")
                ok_ids.append(video_id)
                if jobs_root and kept:
                    broll_pool.add_gated_clips_to_pool(jobs_root, subject=subject, clips=kept)
                continue
        to_download.append(candidate)
    if not to_download:
        print("B-roll: all requested sources already cached — skip download")
    else:
        print(f"Downloading {len(to_download)} B-roll source(s)...")
    for candidate in to_download:
        results = download_videos(
            [candidate],
            output_dir=clips_dir,
            max_height=1080,
            audio_only=False,
            clip_length=clip_length,
            max_parts=split_parts,
            split_parts=True,
            keep_source=False,
            aspect_ratio="9:16",
            start_offset=start_offset,
        )
        if not results or results[0].get("status") != "ok":
            continue
        video_id = str(results[0].get("video_id") or candidate.video_id)
        ok_ids.append(video_id)
        source_clips = sorted(clips_dir.glob(f"{video_id}_part*.mp4"))
        kept = filter_broll_clip_list(
            source_clips,
            subject=subject,
            use_vision=use_vision,
        )
        if jobs_root and kept:
            broll_pool.add_gated_clips_to_pool(jobs_root, subject=subject, clips=kept)
    failed = len(candidates) - len(ok_ids)
    if failed:
        print(f"  download: {len(ok_ids)} ok, {failed} failed")
    kept_all = sorted(clips_dir.glob("*_part*.mp4"))
    if not kept_all:
        raise RuntimeError("B-roll download produced no clips that passed the subject/frame gate.")
    print(f"  ready: {len(kept_all)} clip(s) after subject/frame gate")
    return ok_ids


def _trim_clip_to_span(clip: Path, start: float, end: float) -> None:
    tmp = clip.with_name(f"{clip.stem}.trim{clip.suffix}")
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(clip),
        "-t",
        f"{max(end - start, 0.4):.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    clip.unlink(missing_ok=True)
    tmp.replace(clip)


def filter_broll_clip_list(
    clips: list[Path],
    *,
    subject: str,
    use_vision: bool = True,
) -> list[Path]:
    kept: list[Path] = []
    all_clips = drop_low_fps_clips(sorted(clips), delete=True)
    for clip in all_clips:
        try:
            duration = probe_duration(clip)
        except (subprocess.CalledProcessError, ValueError):
            print(f"  drop {clip.name}: unreadable")
            clip.unlink(missing_ok=True)
            continue
        samples = scan_clip_local(clip, duration=duration, subject=subject)
        span = longest_clean_span(samples, min_length=min(MIN_CLEAN_SPAN, duration))
        if span is None:
            print(f"  drop {clip.name}: no subject span")
            clip.unlink(missing_ok=True)
            continue
        start, end = span
        if use_vision and not confirm_span_subject(
            clip, start=start, end=end, subject=subject
        ):
            print(f"  drop {clip.name}: missing-subject / out-of-context")
            clip.unlink(missing_ok=True)
            continue
        if start > 0.35 or end < duration - 0.35:
            print(f"  trim {clip.name}: {start:.1f}-{end:.1f}s")
            try:
                _trim_clip_to_span(clip, start, end)
            except subprocess.CalledProcessError:
                print(f"  drop {clip.name}: trim failed")
                clip.unlink(missing_ok=True)
                continue
        kept.append(clip)
    if all_clips:
        print(f"  frame gate: kept {len(kept)}/{len(all_clips)} clip(s)")
    return kept


def filter_broll_clips(
    clips_dir: Path,
    *,
    subject: str,
    use_vision: bool = True,
) -> list[Path]:
    return filter_broll_clip_list(
        sorted(clips_dir.glob("*_part*.mp4")),
        subject=subject,
        use_vision=use_vision,
    )


def prepare_broll_from_ids(
    clips_dir: Path,
    video_ids: list[str],
    *,
    clip_length: int,
    max_parts: int | None,
    start_offset: float = 0.0,
    subject: str = "",
    use_vision: bool = True,
    jobs_root: Path | None = None,
    split_full_source: bool = True,
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
        start_offset=start_offset,
        subject=subject,
        use_vision=use_vision,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
    )


def ensure_broll_clips(
    *,
    jobs_root: Path,
    clips_dir: Path,
    subject: str,
    query: str,
    needed_clips: int,
    clips_limit: int,
    clip_length: int,
    max_parts: int | None,
    min_views: int,
    min_duration: int,
    start_offset: float,
    use_vision: bool,
    broll_ids: list[str] | None = None,
    reuse_policy: str = "allow",
    split_full_source: bool = True,
) -> list[str]:
    """Job clips → shared pool cache → known IDs → YouTube search (last resort)."""
    clips_dir.mkdir(parents=True, exist_ok=True)

    def ready() -> list[Path]:
        return filter_broll_clips(clips_dir, subject=subject, use_vision=use_vision)

    kept = ready()
    if len(kept) >= needed_clips:
        print(f"B-roll: {len(kept)} clip(s) ready (need {needed_clips}) — using job cache")
        return broll_ids or []

    missing = max(0, needed_clips - len(kept))
    broll_pool.take_from_pool(
        jobs_root,
        subject=subject,
        clips_dir=clips_dir,
        count=missing,
        copy=True,
    )
    kept = ready()
    if len(kept) >= needed_clips:
        print(f"B-roll: {len(kept)} clip(s) ready (need {needed_clips}) — pool cache")
        return broll_ids or []

    if broll_ids:
        missing = max(0, needed_clips - len(kept))
        broll_pool.copy_youtube_clips(
            jobs_root,
            clips_dir=clips_dir,
            youtube_ids=broll_ids,
            subject=subject,
            count=missing,
        )
        kept = ready()
        if len(kept) >= needed_clips:
            print(f"B-roll: {len(kept)} clip(s) ready (need {needed_clips}) — known ID cache")
            return broll_ids

        candidates = discover_urls(
            [f"https://www.youtube.com/watch?v={video_id}" for video_id in broll_ids]
        )
        if candidates:
            download_broll_candidates(
                clips_dir,
                candidates,
                clip_length=clip_length,
                max_parts=max_parts,
                start_offset=start_offset,
                subject=subject,
                use_vision=use_vision,
                jobs_root=jobs_root,
                split_full_source=split_full_source,
            )
            kept = ready()
            if len(kept) >= needed_clips:
                return broll_ids
    downloaded = prepare_broll(
        clips_dir=clips_dir,
        query=query,
        limit=clips_limit,
        clip_length=clip_length,
        max_parts=max_parts,
        min_views=min_views,
        min_duration=min_duration,
        start_offset=start_offset,
        subject=subject,
        use_vision=use_vision,
        reuse_policy=reuse_policy,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
    )
    have = len(list(clips_dir.glob("*_part*.mp4")))
    if have < needed_clips:
        raise RuntimeError(
            f"Need {needed_clips} unique B-roll clips after subject gate, have {have}. "
            "Use a shorter --max-seconds or a broader --broll-query."
        )
    if broll_ids:
        return list(dict.fromkeys([*broll_ids, *downloaded]))
    return downloaded


def render_job(
    *,
    jobs_root: Path,
    clips_dir: Path,
    audio: Path,
    captions: Path,
    output: Path,
    duration: float,
    segment_length: float,
    seed: int | None,
    grade: bool,
    subject: str = "",
    playback_speed: float = DEFAULT_PLAYBACK_SPEED,
    use_vision: bool = True,
    driven_pacing: bool = True,
    caption_mode: str = "phrase",
    hook_text: str | None = None,
    quality_gate: bool = True,
) -> set[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    actual_duration = probe_duration(audio)
    if abs(actual_duration - duration) > 0.35:
        print(
            f"  audio file is {actual_duration:.2f}s (job said {duration:.2f}s) — using file"
        )
        duration = actual_duration
    temp_output = output.with_suffix(".nocap.mp4")
    clip_count = len(list(clips_dir.glob("*_part*.mp4")))
    grade_note = "charcoal grade" if grade else "no grade"
    print(
        f"Rendering montage: {clip_count} clip(s), {duration:.0f}s speech, "
        f"{segment_length:.1f}s beats, {playback_speed:.0%} speed, {grade_note}"
    )
    used_clips = build_montage(
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
        subject=subject,
        playback_speed=playback_speed,
        use_vision=use_vision,
        driven_pacing=driven_pacing,
    )
    if len(used_clips) != len(set(used_clips)):
        raise RuntimeError("Montage reused a B-roll clip file in one render")
    print(f"  montage used {len(used_clips)} unique clip file(s)")
    caption_label = "phrase" if caption_mode == "phrase" else "word"
    print(f"Burning {caption_label} captions...")
    captioned = output.with_suffix(".captioned.mp4")
    burn_captions(
        temp_output,
        captions,
        captioned,
        width=1080,
        height=1920,
        audio_start=0.0,
        audio_duration=duration,
        caption_mode=caption_mode,
        hook_text=hook_text,
    )
    temp_output.unlink(missing_ok=True)
    remux_speech_over_video(captioned, audio, output, audio_start=0.0)
    captioned.unlink(missing_ok=True)
    duration = probe_duration(output)
    if quality_gate:
        from discovery.render_quality_gate import check_render_quality

        report = check_render_quality(output, expected_duration=duration, subject=subject)
        for warning in report.warnings:
            print(f"  quality warn: {warning}")
        if not report.ok:
            joined = "; ".join(report.errors)
            raise RuntimeError(f"Render quality gate failed: {joined}")
    verify_output(output, duration)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"  render done: {output.name} ({size_mb:.1f} MB, {duration:.1f}s)")
    broll_pool.stash_unused_clips(
        jobs_root,
        subject=subject,
        clips_dir=clips_dir,
        used=used_clips,
    )
    return used_clips


def rerender_existing_job(
    *,
    jobs_root: Path,
    slug: str,
    segment_length: float | None,
    seed: int | None,
    grade: bool,
    clip_length: int,
    max_parts: int,
    clips_limit: int,
    keep_work: bool,
    cleanup: bool,
    start_offset: float,
    playback_speed: float,
    use_vision: bool,
    quality_gate: bool = True,
) -> int:
    job_dir = resolve_job_dir(slug, jobs_root)
    if not job_dir:
        print(f"No job folder for slug {slug} under {jobs_root}", file=sys.stderr)
        return 1
    job_path = job_dir / "job.json"
    audio = job_dir / "audio" / "speech.mp3"
    captions = job_dir / "audio" / "subs.en.json3"
    output = job_dir / "output" / f"{slug}-motivation.mp4"
    if not job_path.is_file():
        print(f"No job.json at {job_path}", file=sys.stderr)
        return 1
    payload = json.loads(job_path.read_text(encoding="utf-8"))
    if not audio.is_file() or not captions.is_file():
        speech_url = str(payload.get("speech_url") or "").strip()
        speech_id = str(payload.get("speech_id") or "").strip()
        if not speech_url and speech_id:
            speech_url = f"https://www.youtube.com/watch?v={speech_id}"
        if not speech_url:
            print(f"Missing speech or captions in {job_dir / 'audio'}", file=sys.stderr)
            return 1
        print("Restoring speech from job.json...")
        try:
            _speech, start, duration, excerpt_text, source_text = prepare_speech(
                jobs_root=jobs_root,
                audio_dir=job_dir / "audio",
                url_file=job_dir / "url.txt",
                speaker=str(payload.get("speaker") or "Andrew Tate"),
                speech_query=str(payload.get("speech_query") or ""),
                speech_url=speech_url,
                min_seconds=60.0,
                max_seconds=float(payload.get("audio_duration") or 90.0),
                allow_reuse=True,
            )
        except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            print(exc, file=sys.stderr)
            return 1
        payload["audio_duration"] = duration
        payload["speech_start"] = start
        payload["speech_excerpt"] = excerpt_text
        payload["speech_source_hash"] = content_reuse.speech_fingerprint(source_text)["transcript_hash"]
        write_job_json(job_path, payload)
    broll_ids = [str(item) for item in (payload.get("broll_ids") or []) if item]
    duration = float(payload.get("audio_duration") or probe_duration(audio))
    segment_length = resolve_segment_length(duration, segment_length)
    subject = str(payload.get("subject") or payload.get("broll_query") or slug)
    if not broll_ids:
        print("job.json has no broll_ids", file=sys.stderr)
        return 1
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    driven_pacing = bool(payload.get("driven_pacing", True))
    clips_limit, clip_length, max_parts = broll_download_plan(
        duration=duration,
        segment_length=segment_length,
        clips_limit=clips_limit,
        clip_length=clip_length,
        max_parts=max_parts,
        driven_pacing=driven_pacing,
        subject=subject,
    )
    needed_clips = unique_clips_required(
        target_duration=duration,
        segment_length=segment_length,
        layout="single",
        driven_pacing=driven_pacing,
        subject=subject,
    )
    try:
        ensure_broll_clips(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            subject=subject,
            query=str(payload.get("broll_query") or subject),
            needed_clips=needed_clips,
            clips_limit=clips_limit,
            clip_length=clip_length,
            max_parts=max_parts,
            min_views=50000,
            min_duration=30,
            start_offset=start_offset,
            use_vision=use_vision,
            broll_ids=broll_ids,
        )
        render_job(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            audio=audio,
            captions=captions,
            output=output,
            duration=duration,
            segment_length=segment_length,
            seed=seed,
            grade=grade,
            subject=subject,
            playback_speed=float(payload.get("playback_speed") or playback_speed),
            use_vision=use_vision,
            driven_pacing=bool(payload.get("driven_pacing", True)),
            caption_mode=str(payload.get("caption_mode") or "phrase"),
            hook_text=str(payload.get("hook") or "") or None,
            quality_gate=quality_gate,
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
    for job_dir in iter_motivation_job_dirs(jobs_root):
        removed = cleanup_job_dir(job_dir, keep_work=keep_work)
        print(f"Cleaned {job_dir.name}: {len(removed)} item(s)")
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
    parser.add_argument(
        "--job-date",
        default=None,
        help="Folder date YYYY-MM-DD under downloads/motivational (default: today, local)",
    )
    _min_speech, _max_speech = speech_window_defaults()
    parser.add_argument("--min-seconds", type=float, default=_min_speech)
    parser.add_argument("--max-seconds", type=float, default=_max_speech)
    parser.add_argument(
        "--segment-length",
        type=float,
        default=None,
        help="Seconds per montage beat (default: scales with speech length, 60s->12s, 90s->18s)",
    )
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=DEFAULT_PLAYBACK_SPEED,
        help="Clip playback rate. Lower = slower motion",
    )
    parser.add_argument("--intro-skip", type=float, default=8.0, help="Skip this many seconds of each B-roll source")
    parser.add_argument(
        "--hook",
        default=None,
        help="Opening hook text (4–7 words). Must match speech; styled stronger in captions.",
    )
    parser.add_argument(
        "--classic-captions",
        action="store_true",
        help="Revert to single-word captions instead of DrivenVisuals phrase blocks.",
    )
    parser.add_argument(
        "--uniform-pacing",
        action="store_true",
        help="Disable DrivenVisuals fast-open pacing (use uniform segment length).",
    )
    parser.add_argument(
        "--skip-quality-gate",
        action="store_true",
        help="Skip pre-ship render quality checks.",
    )
    parser.add_argument("--no-vision", action="store_true", help="Skip optional vision subject check")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-grade", action="store_true")
    parser.add_argument("--clips-limit", type=int, default=5)
    parser.add_argument("--clip-length", type=int, default=24)
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
        target = resolve_job_dir(args.slug, jobs_root) if args.slug else jobs_root
        if args.slug:
            if not target:
                print(f"No job folder for slug {args.slug}", file=sys.stderr)
                return 1
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
            clips_limit=args.clips_limit,
            keep_work=args.keep_work,
            cleanup=not args.no_cleanup,
            start_offset=args.intro_skip,
            playback_speed=args.playback_speed,
            use_vision=not args.no_vision,
            quality_gate=not args.skip_quality_gate,
        )

    if not args.slug or not args.broll_query:
        print("--slug and --broll-query are required unless --cleanup-only or --rerender", file=sys.stderr)
        return 2

    if args.job_date and not is_date_folder(args.job_date):
        print("--job-date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    job_date = args.job_date or default_job_date()
    job_dir = job_dir_for(args.slug, jobs_root, job_date=job_date)
    audio_dir = job_dir / "audio"
    clips_dir = job_dir / "clips"
    output = motivation_output_path(job_dir, args.slug)
    audio_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    print(f"Job: {args.slug}")
    print(f"Output: {output.as_posix()}")
    print(f"Speaker: {speaker}  (edit {config_path.as_posix()})")
    print(f"Speech search: {speech_query}")
    print(f"B-roll query: {args.broll_query}")
    print(f"Reuse policy: {reuse_policy}")
    print(format_toolchain_report())
    try:
        speech, start, duration, excerpt_text, source_text = prepare_speech(
            jobs_root=jobs_root,
            audio_dir=audio_dir,
            url_file=job_dir / "url.txt",
            speaker=speaker,
            speech_query=speech_query,
            speech_url=args.speech_url,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
            reuse_policy=reuse_policy,
        )
        speaker_resolution: dict[str, object] = {}
        try:
            from discovery.config import default_db_path, load_env
            from discovery.speaker_identity import resolve_registration_speaker
            from discovery.store import DiscoveryStore

            load_env()
            _speaker_store = DiscoveryStore(default_db_path())
            try:
                resolved_speaker, speaker_resolution = resolve_registration_speaker(
                    _speaker_store,
                    intended=speaker,
                    title=speech.title,
                    channel=speech.channel,
                    transcript=excerpt_text or source_text,
                    youtube_id=speech.video_id,
                )
            finally:
                _speaker_store.close()
            if resolved_speaker:
                if resolved_speaker != speaker:
                    print(f"Speaker resolved: {speaker} -> {resolved_speaker} (from clip metadata)")
                speaker = resolved_speaker
        except Exception as exc:  # noqa: BLE001 — registration still proceeds
            print(f"Speaker resolution skipped: {exc}")
        segment_length = resolve_segment_length(duration, args.segment_length)
        driven_pacing = not args.uniform_pacing
        plan_length = segment_length
        if driven_pacing:
            from discovery.driven_visuals import planning_segment_length

            plan_length = planning_segment_length(
                driven_pacing=True,
                fallback=segment_length,
                duration=duration,
            )
        clips_limit, clip_length, max_parts = broll_download_plan(
            duration=duration,
            segment_length=segment_length,
            clips_limit=args.clips_limit,
            driven_pacing=driven_pacing,
            subject=args.broll_query,
            clip_length=args.clip_length,
            max_parts=args.max_parts,
        )
        needed_clips = unique_clips_required(
            target_duration=duration,
            segment_length=segment_length,
            layout="single",
            driven_pacing=driven_pacing,
            subject=args.broll_query,
        )
        broll_ids = ensure_broll_clips(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            subject=args.broll_query,
            query=args.broll_query,
            needed_clips=needed_clips,
            clips_limit=clips_limit,
            clip_length=clip_length,
            max_parts=max_parts,
            min_views=args.min_views,
            min_duration=args.min_duration,
            start_offset=args.intro_skip,
            use_vision=not args.no_vision,
            reuse_policy=reuse_policy,
        )
        caption_mode = "word" if args.classic_captions else "phrase"
        render_job(
            jobs_root=jobs_root,
            clips_dir=clips_dir,
            audio=audio_dir / "speech.mp3",
            captions=audio_dir / "subs.en.json3",
            output=output,
            duration=duration,
            segment_length=segment_length,
            seed=args.seed,
            grade=not args.no_grade,
            subject=args.broll_query,
            playback_speed=args.playback_speed,
            use_vision=not args.no_vision,
            driven_pacing=driven_pacing,
            caption_mode=caption_mode,
            hook_text=args.hook,
            quality_gate=not args.skip_quality_gate,
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
            "job_date": job_date,
            "speaker": speaker,
            "speech_query": speech_query,
            "speech_id": speech.video_id,
            "speech_title": speech.title,
            "speech_url": speech.url,
            "broll_query": args.broll_query,
            "subject": args.broll_query,
            "broll_ids": broll_ids,
            "speech_excerpt": excerpt_text,
            "speech_source_hash": content_reuse.speech_fingerprint(source_text)["transcript_hash"],
            "speech_start": start,
            "audio_duration": duration,
            "segment_length": segment_length,
            "playback_speed": args.playback_speed,
            "driven_pacing": driven_pacing,
            "caption_mode": caption_mode,
            "hook": args.hook,
            "driven_visuals_preset": "driven_visuals_v1",
            "output": str(output.as_posix()),
            "speaker_resolution": speaker_resolution,
            "search_intent": speaker_resolution.get("search_intent"),
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
