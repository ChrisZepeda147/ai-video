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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable

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
from discovery.driven_visuals import caption_mode_default, speech_window_defaults
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
from build_stills_slideshow import burn_captions, normalize_caption_align, parse_json3_words
from broll_acquire_state import (
    bump_query_index,
    load_state,
    record_failed_source,
    record_query_attempt,
)
from broll_gate_cache import lookup_gate_result, store_gate_result
from broll_search_query import (
    broaden_broll_query_ladder,
    expand_broll_search_queries,
    gate_subject_for_query,
)
from broll_candidate_rank import rank_broll_candidates
from broll_search_cache import get_cached_candidates, store_cached_candidates
from broll_usable import BrollInventory, log_broll_progress, measure_usable_broll
from broll_usable_manifest import verify_manifest, write_manifest
from montage_timing import montage_timer
from montage_telemetry import (
    MontageFailure,
    MontageFailureError,
    emit_stage_line,
    emit_warning,
    extract_log_tail,
)
from youtube_popular_downloader import (
    VideoCandidate,
    discover_search,
    discover_urls,
    download_broll_source_parts,
    download_videos,
    filter_unwanted,
    is_cabin_titled,
    pick_usable_fps_candidates,
    title_suggests_usable_fps,
)

_VIDEO_CANDIDATE_KEYS = {field.name for field in fields(VideoCandidate)}

KEEP_AUDIO = frozenset({"speech.mp3", "subs.en.json3"})
KEEP_TOP = frozenset({"url.txt", "job.json", "config.json"})


@dataclass(frozen=True)
class MontageGateFlags:
    use_vision: bool
    quality_gate: bool
    frame_gate: bool
    segment_gate: bool
    cursor_review: bool
    speech_vet: bool


def resolve_montage_gate_flags(
    args: argparse.Namespace,
    *,
    subject: str = "",
) -> MontageGateFlags:
    """Default: Cursor agent review pack. Opt out with --code-gates.

    Vehicle B-roll queries keep frame/segment gates + vision on (unless disabled)
    so car montages are checked frequently even in Cursor review mode.
    """
    cursor = not bool(getattr(args, "code_gates", False))
    speech_vet = cursor or bool(getattr(args, "no_speech_score", False))
    vehicle_job = bool(subject.strip()) and wants_vehicle(subject)
    vehicle_gates = vehicle_job and cursor
    return MontageGateFlags(
        use_vision=not args.no_vision and (not cursor or vehicle_gates),
        quality_gate=not args.skip_quality_gate and (not cursor or vehicle_gates),
        frame_gate=not getattr(args, "no_frame_gate", False) and (not cursor or vehicle_gates),
        segment_gate=not getattr(args, "no_segment_gate", False) and (not cursor or vehicle_gates),
        cursor_review=cursor,
        speech_vet=speech_vet,
    )


class SpeechReviewReady(Exception):
    """Speech downloaded; cursor-review/SPEECH.md written — stop before render."""

    def __init__(self, review_path: Path) -> None:
        self.review_path = review_path
        super().__init__(f"Speech review ready: {review_path}")


def emit_cursor_review_pack(
    *,
    job_dir: Path,
    output: Path,
    subject: str,
    min_seconds: float = 20.0,
    max_seconds: float = 28.0,
) -> None:
    from prepare_cursor_montage_review import write_review_pack, write_speech_review_pack

    review_dir = job_dir / "cursor-review"
    meta = {}
    job_path = job_dir / "job.json"
    if job_path.is_file():
        try:
            meta = json.loads(job_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    caps = job_dir / "audio" / "subs.en.json3"
    if caps.is_file() and not (review_dir / "SPEECH.md").is_file():
        write_speech_review_pack(
            review_dir,
            title=str(meta.get("speech_title") or "Speech"),
            video_id=str(meta.get("speech_id") or ""),
            url=str(meta.get("speech_url") or ""),
            captions=caps,
            min_seconds=float(meta.get("min_seconds") or min_seconds),
            max_seconds=float(meta.get("max_seconds") or max_seconds),
            chosen_start=float(meta["speech_start"]) if meta.get("speech_start") is not None else None,
            chosen_duration=float(meta["audio_duration"])
            if meta.get("audio_duration") is not None
            else None,
            chosen_option=None,
            pick_method=str(meta.get("speech_pick_method") or "job-json"),
        )

    pack = write_review_pack(
        out_dir=review_dir,
        job_dir=job_dir,
        video=output,
        clips_dir=job_dir / "clips",
        subject=subject,
    )
    print(f"Cursor review pack: {pack / 'REVIEW.md'}")
    if (review_dir / "SPEECH.md").is_file():
        print(f"Speech review: {review_dir / 'SPEECH.md'}")
    print("Open SPEECH.md + REVIEW.md + final/*.png before ship.")


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
    agent_vet: bool = False,
) -> list[VideoCandidate]:
    raw = discover_search(query=query, limit=max(limit * 3, 12))
    used = used_ids()
    skip = used if reuse_policy == "require_new" else set()
    matches = [
        item
        for item in raw
        if item.video_id not in skip and speaker_matches(item, speaker)
    ]
    if agent_vet:
        if reuse_policy == "prefer_new":
            matches.sort(key=lambda item: (item.video_id in used, -(item.view_count or 0)))
        else:
            matches.sort(key=lambda item: item.view_count or 0, reverse=True)
    elif reuse_policy == "prefer_new":
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
    import time as _time

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
        "sleep_interval_subtitles": 2,
        "retries": 5,
        "fragment_retries": 5,
    }
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            msg = str(exc).lower()
            if "429" in msg or "too many requests" in msg:
                wait = min(90, 8 * (2**attempt))
                print(f"  subtitle rate limit — retry in {wait}s (attempt {attempt + 1}/4)")
                _time.sleep(wait)
                continue
            raise
    if last_err is not None:
        raise last_err
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


SENTENCE_PAUSE_SEC = 0.75
MIN_COMPLETE_EXCERPT_SEC = 7.5
SPEECH_WINDOW_STRETCH = 1.18

# Mid-thought openers — skip unless no stronger start exists.
CONTINUATION_STARTS = frozenset(
    {
        "and",
        "but",
        "so",
        "because",
        "then",
        "or",
        "also",
        "which",
        "that",
        "plus",
        "cause",
        "'cause",
        "though",
        "although",
        "anyway",
        "well",
        "yeah",
        "yes",
        "nah",
        "uh",
        "um",
        "like",
        "just",
        "still",
        "even",
    }
)
STRONG_STARTS = frozenset(
    {
        "you",
        "i",
        "i'm",
        "im",
        "we",
        "they",
        "people",
        "nobody",
        "everybody",
        "never",
        "don't",
        "dont",
        "if",
        "when",
        "the",
        "this",
        "there",
        "most",
        "stop",
        "start",
        "get",
        "make",
        "work",
        "listen",
        "look",
        "here's",
        "here",
        "bro",
        "success",
        "money",
        "life",
        "pain",
        "discipline",
    }
)


def _word_ends_sentence(text: str) -> bool:
    stripped = (text or "").strip().rstrip("\"'”’)")
    return bool(stripped) and stripped[-1] in ".?!"


def _word_token(text: str) -> str:
    raw = (text or "").strip().lower()
    return raw.strip(".,!?\"'“”’()[]")


def _is_continuation_start(text: str) -> bool:
    return _word_token(text) in CONTINUATION_STARTS


def _is_strong_start(text: str) -> bool:
    return _word_token(text) in STRONG_STARTS


def _is_complete_end(text: str) -> bool:
    return _word_ends_sentence(text)


def _looks_like_sentence_break(prev_text: str, next_text: str, gap: float) -> bool:
    if _word_ends_sentence(prev_text):
        return True
    nxt = (next_text or "").lstrip()
    if gap < SENTENCE_PAUSE_SEC or not nxt:
        return False
    return nxt[0].isupper()


def _sentence_start_indexes(words: list[tuple[float, str]]) -> list[int]:
    starts = [0]
    for index in range(1, len(words)):
        prev_when, prev_text = words[index - 1]
        when, text = words[index]
        if _looks_like_sentence_break(prev_text, text, when - prev_when):
            starts.append(index)
    return starts


def _clean_speech_start_index(words: list[tuple[float, str]], start_index: int) -> int:
    """Skip duplicated opener tokens (They / They've / stutter) at excerpt start."""
    index = start_index
    skipped = 0
    openers = {"they", "you", "i", "we", "the", "and", "so"}
    while index + 1 < len(words) and skipped < 3:
        current = words[index][1].lower().strip(".,!?\"'")
        nxt = words[index + 1][1].lower().strip(".,!?\"'")
        if current in {"they", "you", "i", "we"} and (nxt.startswith(current) or nxt == current):
            index += 1
            skipped += 1
            continue
        if current == nxt and current in openers:
            index += 1
            skipped += 1
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


def _anchor_start_index(words: list[tuple[float, str]], default_start: float | None) -> int | None:
    if default_start is None or not words:
        return None
    starts = _sentence_start_indexes(words)
    start_index = starts[0]
    for index in starts:
        if words[index][0] <= default_start + 0.05:
            start_index = index
        else:
            break
    if words[start_index][0] + 8.0 > words[-1][0] + 0.5:
        for index in starts:
            if words[index][0] >= default_start - 0.05:
                return _clean_speech_start_index(words, index)
    return _clean_speech_start_index(words, start_index)


def _score_speech_window(
    *,
    start_text: str,
    end_text: str,
    duration: float,
    sentence_count: int,
    min_seconds: float,
    max_seconds: float,
    last_sentence_start_text: str,
    near_anchor: bool,
) -> float | None:
    if not _is_complete_end(end_text):
        return None
    if duration < MIN_COMPLETE_EXCERPT_SEC:
        return None
    if duration > max_seconds * SPEECH_WINDOW_STRETCH:
        return None

    score = 0.0
    if min_seconds <= duration <= max_seconds:
        score += 45.0
        span = max(max_seconds - min_seconds, 1.0)
        score += 10.0 * min(1.0, (duration - min_seconds) / span)
    elif duration < min_seconds:
        score += 16.0
        score -= 8.0 * min(1.0, (min_seconds - duration) / max(min_seconds, 1.0))
    else:
        score += 22.0

    if _is_continuation_start(start_text):
        score -= 22.0
    elif _is_strong_start(start_text):
        score += 22.0
    else:
        score += 8.0

    if sentence_count >= 2:
        score += 16.0
    if sentence_count >= 3:
        score += 6.0
    if _is_continuation_start(last_sentence_start_text) and sentence_count > 1:
        score -= 6.0
    if near_anchor:
        score += 12.0
    return score


def _scored_speech_windows(
    words: list[tuple[float, str]],
    *,
    min_seconds: float,
    max_seconds: float,
    default_start: float | None = None,
    captions: Path | None = None,
    avoid_ranges: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float, float]]:
    if not words:
        return []
    starts = [_clean_speech_start_index(words, index) for index in _sentence_start_indexes(words)]
    starts = list(dict.fromkeys(starts))
    ends = [index for index, (_when, text) in enumerate(words) if _is_complete_end(text)]
    if not starts or not ends:
        return []
    anchor = _anchor_start_index(words, default_start)
    avoid = avoid_ranges or []
    scored: list[tuple[float, float, float]] = []
    for start_index in starts:
        start = words[start_index][0]
        start_text = words[start_index][1]
        for end_index in ends:
            if end_index < start_index:
                continue
            stop = _hard_stop_after_sentence(words, end_index, captions=captions)
            duration = stop - start
            if duration < MIN_COMPLETE_EXCERPT_SEC:
                continue
            if duration > max_seconds * SPEECH_WINDOW_STRETCH:
                break
            last_start = start_index
            for later in starts:
                if start_index < later <= end_index:
                    last_start = later
            score = _score_speech_window(
                start_text=start_text,
                end_text=words[end_index][1],
                duration=duration,
                sentence_count=sum(1 for later in starts if start_index <= later <= end_index),
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                last_sentence_start_text=words[last_start][1],
                near_anchor=anchor is not None and start_index == anchor,
            )
            if score is None:
                continue
            if any(_range_overlaps(start, start + duration, lo, hi) for lo, hi in avoid):
                continue
            scored.append((score, start, duration))
    return scored


def _pick_window_from_words(
    words: list[tuple[float, str]],
    *,
    min_seconds: float,
    max_seconds: float,
    default_start: float | None = None,
    captions: Path | None = None,
    avoid_ranges: list[tuple[float, float]] | None = None,
    sequential: bool = False,
) -> tuple[float, float] | None:
    scored = _scored_speech_windows(
        words,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        default_start=default_start,
        captions=captions,
        avoid_ranges=avoid_ranges,
    )
    if not scored:
        return None
    if sequential:
        scored.sort(key=lambda item: (item[1], -item[0]))
        threshold = 10.0
        good = [item for item in scored if item[0] >= threshold]
        chosen = (good or scored)[0]
        return chosen[1], chosen[2]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1], scored[0][2]


@dataclass(frozen=True)
class SpeechExcerptOption:
    score: float
    start: float
    duration: float
    text: str


def ranked_speech_excerpts(
    captions: Path,
    *,
    min_seconds: float,
    max_seconds: float,
    avoid_ranges: list[tuple[float, float]] | None = None,
    limit: int = 10,
) -> list[SpeechExcerptOption]:
    if captions.suffix.lower() != ".json3":
        return []
    words = json3_word_times(captions)
    if not words:
        return []
    scored = _scored_speech_windows(
        words,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        captions=captions,
        avoid_ranges=avoid_ranges,
    )
    scored.sort(key=lambda item: (-item[0], item[1]))
    options: list[SpeechExcerptOption] = []
    seen: set[str] = set()
    for score, start, duration in scored:
        text = captions_text(captions, start=start, duration=duration).strip()
        if len(text) < 12:
            continue
        key = text[:120]
        if key in seen:
            continue
        seen.add(key)
        options.append(
            SpeechExcerptOption(
                score=round(score, 1),
                start=start,
                duration=duration,
                text=text,
            )
        )
        if len(options) >= limit:
            break
    return options


def resolve_speech_window(
    captions: Path,
    *,
    min_seconds: float,
    max_seconds: float,
    avoid_ranges: list[tuple[float, float]] | None = None,
    speech_start: float | None = None,
    speech_duration: float | None = None,
    speech_option: int | None = None,
    agent_vet: bool = False,
) -> tuple[float, float, int | None, str]:
    """Return start, duration, 1-based option index if used, pick method label."""
    if speech_start is not None:
        duration = speech_duration if speech_duration is not None else max_seconds
        return speech_start, duration, None, "cli-speech-start"

    if speech_option is not None:
        options = ranked_speech_excerpts(
            captions,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            avoid_ranges=avoid_ranges,
        )
        if not options:
            raise ValueError("No speech excerpt options in captions.")
        index = speech_option - 1
        if index < 0 or index >= len(options):
            raise ValueError(
                f"--speech-option {speech_option} out of range (1–{len(options)})."
            )
        chosen = options[index]
        return chosen.start, chosen.duration, speech_option, "cli-speech-option"

    if agent_vet:
        words = json3_word_times(captions)
        picked = _pick_window_from_words(
            words,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            captions=captions,
            avoid_ranges=avoid_ranges,
            sequential=True,
        )
        if picked:
            return picked[0], picked[1], None, "agent-sequential"
        start, duration = pick_speech_excerpt(
            captions,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            avoid_ranges=avoid_ranges,
        )
        return start, duration, None, "agent-fallback"

    start, duration = pick_speech_excerpt(
        captions,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        avoid_ranges=avoid_ranges,
    )
    return start, duration, None, "code-best-score"


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

    picked = _pick_window_from_words(
        words,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        captions=captions,
        avoid_ranges=avoid_ranges,
    )
    if picked:
        return picked
    start = words[0][0] if words[0][0] < 3.0 else 0.0
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
    """End on the last finished sentence. Never pad into the next thought."""
    window_end = start + max_seconds
    close_index: int | None = None
    last_index: int | None = None
    for index, (when, text) in enumerate(words):
        if when + 0.05 < start:
            continue
        if when > window_end + 0.05:
            break
        last_index = index
        if _is_complete_end(text):
            close_index = index
    if close_index is not None:
        stop = _hard_stop_after_sentence(words, close_index, captions=captions)
        return max(0.2, min(max_seconds * SPEECH_WINDOW_STRETCH, stop - start))
    if last_index is None:
        return min_seconds
    tail = _speech_tail_after_word(words, last_index, captions=captions)
    end = min(words[last_index][0] + tail + 0.12, window_end)
    return max(0.2, min(max_seconds, end - start))


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
            sequential=True,
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
        sequential=True,
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
        kept: list[dict[str, Any]] = []
        for seg in event.get("segs") or []:
            text = str(seg.get("utf8") or "")
            if text.strip() in ("", "\n"):
                continue
            abs_ms = t0 + float(seg.get("tOffsetMs") or 0)
            if abs_ms < start_ms - 20 or abs_ms >= end_ms - 10:
                continue
            row = dict(seg)
            row["tOffsetMs"] = abs_ms - start_ms
            kept.append(row)
        if not kept:
            continue
        first_rel = float(kept[0].get("tOffsetMs") or 0)
        row = dict(event)
        row["tStartMs"] = first_rel
        for seg in kept:
            seg["tOffsetMs"] = float(seg.get("tOffsetMs") or 0) - first_rel
        last_rel = first_rel + float(kept[-1].get("tOffsetMs") or 0)
        row["dDurationMs"] = max(80.0, min(end_ms - start_ms, last_rel + 400.0) - first_rel)
        row["segs"] = kept
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
    """Finish the closing sentence, or drop an unfinished trailing sentence."""
    if captions.suffix.lower() != ".json3":
        return duration
    words = json3_word_times(captions)
    if not words:
        return duration
    window_end = start + duration
    close_index: int | None = None
    hanging = False
    for index, (when, text) in enumerate(words):
        if when + 0.02 < start:
            continue
        if when > window_end + 0.05:
            break
        if _is_complete_end(text):
            close_index = index
            hanging = False
        else:
            hanging = True
    if close_index is None:
        return duration
    stop = _hard_stop_after_sentence(words, close_index, captions=captions)
    needed = max(0.2, stop - start)
    if not hanging:
        needed = min(needed, max_seconds * SPEECH_WINDOW_STRETCH)
    else:
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


def _tail_pad_before_next_word(
    captions: Path,
    *,
    start: float,
    duration: float,
    tail_pad: float = SPEECH_TRIM_TAIL_SEC,
) -> float:
    """Keep a little ring-out after the last word, but do not start the next sentence."""
    if captions.suffix.lower() != ".json3":
        return tail_pad
    words = json3_word_times(captions)
    end = start + duration
    for when, _text in words:
        if when >= end - 0.01:
            return min(tail_pad, max(0.0, when - end - 0.03))
    return tail_pad


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
    tail = _tail_pad_before_next_word(captions, start=start, duration=duration)
    trim_audio(source_mp3, speech_mp3, start=start, duration=duration, tail_pad=tail)
    probed = probe_duration(speech_mp3)
    if not keep_source and source_mp3.resolve() != speech_mp3.resolve():
        source_mp3.unlink(missing_ok=True)
    stable_caps = audio_dir / "subs.en.json3"
    if captions.suffix.lower() == ".json3":
        shift_json3(captions, stable_caps, start=start, duration=duration)
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
    min_seconds: float,
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
    captions = item.captions
    source_mp3 = item.audio
    rel_start = 0.0
    rel_duration = duration
    if captions.is_file() and captions.suffix.lower() == ".json3":
        picked = _pick_window_from_words(
            json3_word_times(captions),
            min_seconds=min(min_seconds, duration),
            max_seconds=duration,
            captions=captions,
        )
        if picked:
            rel_start, rel_duration = picked
        else:
            rel_duration = extend_excerpt_duration(
                captions,
                start=0.0,
                duration=duration,
                max_seconds=duration,
            )
    if rel_start > 0.12 or rel_duration + 0.2 < float(item.duration):
        duration = _write_job_speech(
            audio_dir=audio_dir,
            source_mp3=source_mp3,
            captions=captions,
            start=rel_start,
            duration=rel_duration,
            keep_source=False,
        )
        excerpt = captions_text(audio_dir / "subs.en.json3", start=0.0, duration=duration)
        print(f"  refined pooled speech to complete thought {item.duration:.1f}s -> {duration:.1f}s")
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
    speech_start: float | None = None,
    speech_duration: float | None = None,
    speech_option: int | None = None,
    agent_speech_vet: bool = False,
    speech_review_only: bool = False,
    review_out_dir: Path | None = None,
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
        min_seconds=min_seconds,
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
            agent_vet=agent_speech_vet,
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
        try:
            start, duration, option_index, pick_method = resolve_speech_window(
                captions,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                avoid_ranges=avoid_ranges,
                speech_start=speech_start,
                speech_duration=speech_duration,
                speech_option=speech_option,
                agent_vet=agent_speech_vet,
            )
        except ValueError as exc:
            print(f"  skip speech window: {exc}")
            _clear_audio_dir(audio_dir)
            continue
        if speech_review_only:
            from prepare_cursor_montage_review import write_speech_review_pack

            out = review_out_dir or (audio_dir.parent / "cursor-review")
            path = write_speech_review_pack(
                out,
                title=candidate.title,
                video_id=candidate.video_id,
                url=candidate.url,
                captions=captions,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                avoid_ranges=avoid_ranges,
                chosen_start=None,
                chosen_duration=None,
                chosen_option=None,
                pick_method="pending-agent",
            )
            url_file.write_text(f"{candidate.url}\n", encoding="utf-8")
            raise SpeechReviewReady(path)
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
        if agent_speech_vet or speech_option or speech_start is not None:
            from prepare_cursor_montage_review import write_speech_review_pack

            write_speech_review_pack(
                review_out_dir or (audio_dir.parent / "cursor-review"),
                title=candidate.title,
                video_id=candidate.video_id,
                url=candidate.url,
                captions=captions,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                avoid_ranges=avoid_ranges,
                chosen_start=start,
                chosen_duration=duration,
                chosen_option=option_index,
                pick_method=pick_method,
            )
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
    split_full_source: bool = False,
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
    resolved_limit = min(resolved_limit, 6)
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


def _discover_broll_candidates_for_search(
    search_query: str,
    *,
    limit: int,
    subject: str,
    min_views: int,
    min_duration: int,
    reuse_policy: str,
) -> list[VideoCandidate]:
    raw = discover_search(query=search_query, limit=max(limit * 4, 16))
    if not title_suggests_usable_fps(search_query):
        extra = discover_search(query=f"{search_query} 60fps", limit=max(limit * 3, 12))
        seen = {item.video_id for item in raw}
        raw = [*extra, *[item for item in raw if item.video_id not in seen]]
    used = used_ids()
    if reuse_policy == "require_new":
        pool = [item for item in raw if item.video_id not in used]
    else:
        pool = list(raw)
    wanted = subject_tokens(search_query, subject)
    if wanted:
        titled = [item for item in pool if title_matches_subject(item.title, wanted)]
        if titled:
            print(f"Title-matched {len(titled)}/{len(pool)} B-roll hit(s) for: {', '.join(wanted)}")
            pool = titled
        elif reuse_policy != "require_new":
            print(f"No B-roll title matched {wanted}; using search hits")
    if wants_vehicle(subject or search_query):
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
    return rank_broll_candidates(candidates)


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
    frame_gate: bool = True,
    reuse_policy: str = "allow",
    jobs_root: Path | None = None,
    split_full_source: bool = False,
    needed_clips: int | None = None,
) -> list[str]:
    search_queries = expand_broll_search_queries(query) or [query]
    search_queries = search_queries[:3]
    if len(search_queries) > 1:
        gate = ""
    else:
        gate_subject = gate_subject_for_query(query, subject or query)
        gate = gate_subject or subject or query
    token_fallback = " ".join(subject_tokens(query, subject)[:4])
    if token_fallback and "60fps" not in token_fallback.lower():
        token_fallback = f"{token_fallback} cinematic 60fps"

    candidates: list[VideoCandidate] = []
    seen_ids: set[str] = set()
    queries_to_try = list(search_queries)
    for search_query in queries_to_try:
        batch = _discover_broll_candidates_for_search(
            search_query,
            limit=limit,
            subject=gate,
            min_views=min_views,
            min_duration=min_duration,
            reuse_policy=reuse_policy,
        )
        if batch:
            print(f"B-roll candidates from search: {search_query!r} ({len(batch)})")
        for item in batch:
            if item.video_id in seen_ids:
                continue
            seen_ids.add(item.video_id)
            candidates.append(item)
        if len(candidates) >= limit:
            break

    if not candidates and token_fallback and token_fallback not in queries_to_try:
        print(f"B-roll: retry search {token_fallback!r}")
        batch = _discover_broll_candidates_for_search(
            token_fallback,
            limit=limit,
            subject=gate,
            min_views=min_views,
            min_duration=min_duration,
            reuse_policy=reuse_policy,
        )
        for item in batch:
            if item.video_id in seen_ids:
                continue
            seen_ids.add(item.video_id)
            candidates.append(item)

    if not candidates:
        if reuse_policy == "require_new":
            raise MotivationJobError(
                "REUSE_RESTRICTION",
                f"No unused B-roll for query: {query}",
            )
        tried = ", ".join(search_queries[:6])
        raise MotivationJobError(
            "NO_CANDIDATE_FOUND",
            f"No B-roll candidates for query: {query} (tried: {tried})",
        )
    return download_broll_candidates(
        clips_dir,
        candidates,
        clip_length=clip_length,
        max_parts=max_parts,
        start_offset=start_offset,
        subject=subject or query,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
        needed_clips=needed_clips,
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
    frame_gate: bool = True,
    jobs_root: Path | None = None,
    split_full_source: bool = False,
    needed_clips: int | None = None,
    parts_needed: int | None = None,
    exclude_source_ids: set[str] | None = None,
    max_sources: int | None = None,
    job_dir: Path | None = None,
    usable_ok: Callable[[], bool] | None = None,
    raise_if_empty: bool = True,
    allow_parallel: bool = False,
) -> list[str]:
    split_parts = None if split_full_source else max_parts
    blocked = exclude_source_ids or set()
    ok_ids: list[str] = []
    to_download: list[VideoCandidate] = []
    for candidate in candidates:
        if candidate.video_id in blocked:
            continue
        video_id = candidate.video_id
        existing = sorted(clips_dir.glob(f"{video_id}_part*.mp4"))
        if existing:
            kept = filter_broll_clip_list(
                existing,
                subject=subject,
                use_vision=use_vision,
                frame_gate=frame_gate,
                jobs_root=jobs_root,
            )
            if kept:
                print(f"  skip download {video_id}: {len(kept)} cached part(s) in job")
                ok_ids.append(video_id)
                if jobs_root and kept:
                    broll_pool.add_gated_clips_to_pool(jobs_root, subject=subject, clips=kept)
                if usable_ok and usable_ok():
                    return ok_ids
                continue
        to_download.append(candidate)
    if max_sources is not None and len(to_download) > max_sources:
        to_download = to_download[:max_sources]
    if not to_download:
        if raise_if_empty and not ok_ids and not list(clips_dir.glob("*_part*.mp4")):
            msg = (
                "B-roll download produced no clips that passed the subject/frame gate."
                if frame_gate
                else "B-roll download produced no clips."
            )
            raise RuntimeError(msg)
        return ok_ids
    def _parts_for_this_source() -> int:
        if parts_needed is not None:
            return max(1, min(parts_needed, 8))
        if split_parts is not None:
            return max(1, split_parts)
        return max(1, max_parts or 3)

    def _process_candidate(candidate: VideoCandidate) -> str | None:
        video_id = candidate.video_id
        request_parts = _parts_for_this_source()
        if split_full_source:
            results = download_videos(
                [candidate],
                output_dir=clips_dir,
                max_height=1080,
                audio_only=False,
                clip_length=clip_length,
                max_parts=None,
                split_parts=True,
                keep_source=False,
                aspect_ratio="9:16",
                start_offset=start_offset,
                spaced_parts=True,
            )
            if not results or results[0].get("status") != "ok":
                if job_dir:
                    record_failed_source(job_dir, video_id)
                return None
        else:
            record = download_broll_source_parts(
                candidate,
                output_dir=clips_dir,
                clip_length=clip_length,
                parts_needed=request_parts,
                aspect_ratio="9:16",
                max_height=1080,
                start_offset=start_offset,
            )
            if record.get("status") != "ok":
                if job_dir:
                    record_failed_source(job_dir, video_id)
                return None
            video_id = str(record.get("video_id") or candidate.video_id)
        source_clips = sorted(clips_dir.glob(f"{video_id}_part*.mp4"))
        kept = filter_broll_clip_list(
            source_clips,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )
        if not kept:
            if job_dir:
                record_failed_source(job_dir, video_id)
            return None
        if jobs_root and kept:
            broll_pool.add_gated_clips_to_pool(jobs_root, subject=subject, clips=kept)
        return video_id

    print(f"Downloading {len(to_download)} B-roll source(s)...")
    seen_ids: set[str] = set()

    def _after_source(video_id: str | None) -> bool:
        if not video_id:
            return False
        ok_ids.append(video_id)
        if usable_ok and usable_ok():
            print(f"  B-roll: usable target met after {len(ok_ids)} source(s)")
            return True
        if needed_clips and usable_ok is None:
            inv = measure_usable_broll(
                clips_dir,
                required=needed_clips,
                gate_fn=lambda paths: filter_broll_clip_list(
                    paths,
                    subject=subject,
                    use_vision=use_vision,
                    frame_gate=frame_gate,
                    jobs_root=jobs_root,
                ),
            )
            if inv.satisfies_count():
                print(
                    f"  B-roll: stopping early — {inv.usable_count} usable clip(s) "
                    f"(need {needed_clips}) after {len(ok_ids)} source(s)"
                )
                return True
        return False

    batch = [c for c in to_download if c.video_id not in seen_ids]
    if allow_parallel and len(batch) >= 2:
        workers = min(2, len(batch))
        parallel_results: list[str | None] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_candidate, candidate): candidate
                for candidate in batch[:workers]
            }
            for future in as_completed(futures):
                candidate = futures[future]
                seen_ids.add(candidate.video_id)
                try:
                    parallel_results.append(future.result())
                except Exception:
                    if job_dir:
                        record_failed_source(job_dir, candidate.video_id)
                    parallel_results.append(None)
        for vid in parallel_results:
            if _after_source(vid):
                break
    else:
        for candidate in batch:
            if candidate.video_id in seen_ids:
                continue
            seen_ids.add(candidate.video_id)
            vid = _process_candidate(candidate)
            if _after_source(vid):
                break
    failed = len([c for c in candidates if c.video_id not in ok_ids and c.video_id not in blocked])
    if failed:
        print(f"  download: {len(ok_ids)} ok, {failed} not used")
    if raise_if_empty and not ok_ids:
        usable_now = filter_broll_clips(
            clips_dir,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )
        if not usable_now:
            msg = (
                "B-roll download produced no clips that passed the subject/frame gate."
                if frame_gate
                else "B-roll download produced no clips."
            )
            raise RuntimeError(msg)
    label = "subject/frame gate" if frame_gate else "download (fps only)"
    usable_count = len(
        filter_broll_clips(
            clips_dir,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )
    )
    print(f"  ready: {usable_count} usable clip(s) after {label}")
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
    frame_gate: bool = True,
    jobs_root: Path | None = None,
    delete_rejects: bool = True,
) -> list[Path]:
    kept: list[Path] = []
    subject_slug = broll_pool.subject_pool_slug(subject)
    all_clips = drop_low_fps_clips(sorted(clips), delete=True)
    if not frame_gate:
        if all_clips:
            print(f"  frame gate: skipped — kept {len(all_clips)} clip(s) (fps only)")
        return all_clips
    for clip in all_clips:
        source_id = broll_pool._youtube_id_from_clip_name(clip.name) or clip.stem
        cached = lookup_gate_result(jobs_root, clip, subject_slug=subject_slug)
        if cached is not None:
            if cached.get("pass"):
                kept.append(clip)
                continue
            reason = str(cached.get("reason") or "cached fail")
            print(f"  drop {clip.name}: cached gate ({reason})")
            if delete_rejects:
                clip.unlink(missing_ok=True)
            continue
        import time as _time

        gate_start = _time.perf_counter()
        montage_timer().stats.gate_rescan_clips += 1
        try:
            try:
                duration = probe_duration(clip)
            except (subprocess.CalledProcessError, ValueError):
                print(f"  drop {clip.name}: unreadable")
                store_gate_result(
                    jobs_root,
                    clip,
                    subject_slug=subject_slug,
                    passed=False,
                    reason="unreadable",
                    source_id=source_id,
                )
                if delete_rejects:
                    clip.unlink(missing_ok=True)
                continue
            samples = scan_clip_local(clip, duration=duration, subject=subject)
            span = longest_clean_span(samples, min_length=min(MIN_CLEAN_SPAN, duration))
            if span is None:
                print(f"  drop {clip.name}: no subject span")
                store_gate_result(
                    jobs_root,
                    clip,
                    subject_slug=subject_slug,
                    passed=False,
                    reason="no subject span",
                    source_id=source_id,
                )
                if delete_rejects:
                    clip.unlink(missing_ok=True)
                continue
            start, end = span
            if use_vision and not confirm_span_subject(
                clip, start=start, end=end, subject=subject
            ):
                print(f"  drop {clip.name}: missing-subject / out-of-context")
                store_gate_result(
                    jobs_root,
                    clip,
                    subject_slug=subject_slug,
                    passed=False,
                    reason="vision reject",
                    source_id=source_id,
                )
                if delete_rejects:
                    clip.unlink(missing_ok=True)
                continue
            if start > 0.35 or end < duration - 0.35:
                print(f"  trim {clip.name}: {start:.1f}-{end:.1f}s")
                try:
                    _trim_clip_to_span(clip, start, end)
                except subprocess.CalledProcessError:
                    print(f"  drop {clip.name}: trim failed")
                    store_gate_result(
                        jobs_root,
                        clip,
                        subject_slug=subject_slug,
                        passed=False,
                        reason="trim failed",
                        source_id=source_id,
                    )
                    if delete_rejects:
                        clip.unlink(missing_ok=True)
                    continue
            store_gate_result(
                jobs_root,
                clip,
                subject_slug=subject_slug,
                passed=True,
                reason="ok",
                source_id=source_id,
            )
            kept.append(clip)
        finally:
            montage_timer().add_child("frame_gate", _time.perf_counter() - gate_start)
    if all_clips:
        print(f"  frame gate: kept {len(kept)}/{len(all_clips)} clip(s)")
    return kept


def _broll_ids_from_clips(clips_dir: Path) -> list[str]:
    """Recover YouTube IDs from existing *_part*.mp4 clip names."""
    found: list[str] = []
    seen: set[str] = set()
    for clip in sorted(clips_dir.glob("*_part*.mp4")):
        stem = clip.stem
        marker = stem.rfind("_part")
        video_id = stem[:marker] if marker > 0 else stem
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        found.append(video_id)
    return found


def filter_broll_clips(
    clips_dir: Path,
    *,
    subject: str,
    use_vision: bool = True,
    frame_gate: bool = True,
    jobs_root: Path | None = None,
) -> list[Path]:
    return filter_broll_clip_list(
        sorted(clips_dir.glob("*_part*.mp4")),
        subject=subject,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
        delete_rejects=True,
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
    frame_gate: bool = True,
    jobs_root: Path | None = None,
    split_full_source: bool = False,
    needed_clips: int | None = None,
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
        frame_gate=frame_gate,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
        needed_clips=needed_clips,
    )


def _broll_gate_fn(
    *,
    subject: str,
    use_vision: bool,
    frame_gate: bool,
    jobs_root: Path | None,
) -> Callable[[list[Path]], list[Path]]:
    def _gate(paths: list[Path]) -> list[Path]:
        return filter_broll_clip_list(
            paths,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )

    return _gate


def _inventory(
    clips_dir: Path,
    *,
    required: int,
    subject: str,
    use_vision: bool,
    frame_gate: bool,
    jobs_root: Path | None,
) -> BrollInventory:
    with montage_timer().stage_child("inventory_gate"):
        return measure_usable_broll(
            clips_dir,
            required=required,
            gate_fn=_broll_gate_fn(
                subject=subject,
                use_vision=use_vision,
                frame_gate=frame_gate,
                jobs_root=jobs_root,
            ),
        )


def _raise_broll_insufficient(
    *,
    slug: str,
    query: str,
    inv: BrollInventory,
    downloads_attempted: int,
    downloads_ok: int,
    log_blob: str = "",
) -> None:
    summary = (
        f"B-roll insufficient: need {inv.required} usable clips, "
        f"have {inv.usable_count} after gate from {inv.distinct_sources} source(s)."
    )
    failure = MontageFailure(
        slug=slug,
        stage="ensure_broll_clips",
        code="BROLL_INSUFFICIENT",
        summary=summary,
        details={
            "broll_query": query,
            "needed_clips": inv.required,
            "clips_on_disk": inv.raw,
            "clips_after_gate": inv.usable_count,
            "distinct_sources": inv.distinct_sources,
            "downloads_attempted": downloads_attempted,
            "downloads_ok": downloads_ok,
        },
        log_tail=extract_log_tail(log_blob),
    )
    print(failure.emit_json_line())
    emit_stage_line(
        "ensure_broll",
        "fail",
        needed=inv.required,
        have=inv.usable_count,
        sources=inv.distinct_sources,
    )
    raise MontageFailureError(failure)


def _candidate_from_cache(item: dict[str, Any]) -> VideoCandidate:
    payload = {key: item[key] for key in _VIDEO_CANDIDATE_KEYS if key in item}
    return VideoCandidate(**payload)


def _discover_candidates_for_query(
    search_query: str,
    *,
    limit: int,
    subject: str,
    min_views: int,
    min_duration: int,
    reuse_policy: str,
    exclude_source_ids: set[str],
    jobs_root: Path | None = None,
    force_search: bool = False,
) -> list[VideoCandidate]:
    gate_subject = gate_subject_for_query(search_query, subject)
    gate = gate_subject or subject or search_query
    batch: list[VideoCandidate] = []
    if not force_search:
        cached = get_cached_candidates(
            jobs_root,
            query=search_query,
            min_views=min_views,
            min_duration=min_duration,
        )
        if cached:
            montage_timer().stats.search_cache_hit = True
            print(
                f"BROLL_SEARCH cache_hit query={search_query!r} candidates={len(cached)}"
            )
            batch = [_candidate_from_cache(item) for item in cached]
    if not batch:
        print(f"BROLL_SEARCH cache_miss query={search_query!r}")
        batch = _discover_broll_candidates_for_search(
            search_query,
            limit=max(limit, 12),
            subject=gate,
            min_views=min_views,
            min_duration=min_duration,
            reuse_policy=reuse_policy,
        )
        if jobs_root and batch:
            store_cached_candidates(
                jobs_root,
                query=search_query,
                min_views=min_views,
                min_duration=min_duration,
                candidates=[asdict(item) for item in batch],
            )
    filtered = [item for item in batch if item.video_id not in exclude_source_ids]
    return filtered[:limit] if limit else filtered


def _try_diversity_download(
    *,
    clips_dir: Path,
    job_dir: Path,
    subject: str,
    query: str,
    clips_limit: int,
    clip_length: int,
    max_parts: int | None,
    min_views: int,
    min_duration: int,
    start_offset: float,
    use_vision: bool,
    frame_gate: bool,
    jobs_root: Path,
    split_full_source: bool,
    reuse_policy: str,
    exclude_source_ids: set[str],
    inv: BrollInventory,
) -> BrollInventory:
    if inv.distinct_sources >= 2 or not inv.satisfies_count():
        return inv
    if reuse_policy == "require_new":
        emit_warning("BROLL_LOW_DIVERSITY", sources=inv.distinct_sources)
        return inv
    candidates: list[VideoCandidate] = []
    for search_query in broaden_broll_query_ladder(query)[:2]:
        with montage_timer().stage_child("youtube_search"):
            candidates = _discover_candidates_for_query(
                search_query,
                limit=1,
                subject=subject,
                min_views=min_views,
                min_duration=min_duration,
                reuse_policy=reuse_policy,
                exclude_source_ids=exclude_source_ids,
                jobs_root=jobs_root,
            )
        if candidates:
            break
    if not candidates:
        emit_warning("BROLL_LOW_DIVERSITY", sources=inv.distinct_sources)
        return inv
    montage_timer().stats.downloads_attempted += 1
    try:
        with montage_timer().stage_child("broll_download"):
            ids = download_broll_candidates(
                clips_dir,
                candidates[:1],
                clip_length=clip_length,
                max_parts=max_parts,
                start_offset=start_offset,
                subject=subject,
                use_vision=use_vision,
                frame_gate=frame_gate,
                jobs_root=jobs_root,
                split_full_source=split_full_source,
                max_sources=1,
                job_dir=job_dir,
                exclude_source_ids=exclude_source_ids,
                parts_needed=max(1, inv.required - inv.usable_count),
                raise_if_empty=False,
            )
        if ids:
            montage_timer().stats.downloads_successful += 1
    except RuntimeError:
        pass
    inv = _inventory(
        clips_dir,
        required=inv.required,
        subject=subject,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
    )
    if inv.distinct_sources < 2:
        emit_warning("BROLL_LOW_DIVERSITY", sources=inv.distinct_sources)
    return inv


def _persist_broll_success(job_dir: Path, inv: BrollInventory) -> None:
    write_manifest(
        job_dir,
        clip_names=[clip.name for clip in inv.usable],
        required=inv.required,
    )
    stats = montage_timer().stats
    stats.clips_raw = inv.raw
    stats.clips_usable = inv.usable_count
    stats.distinct_sources = inv.distinct_sources


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
    frame_gate: bool = True,
    broll_ids: list[str] | None = None,
    reuse_policy: str = "allow",
    split_full_source: bool | None = None,
    slug: str = "",
) -> list[str]:
    """Incremental ladder: pool → one source at a time → broadened query fallbacks."""
    if split_full_source is None:
        split_full_source = bool(frame_gate and use_vision)
    clips_dir.mkdir(parents=True, exist_ok=True)
    job_dir = clips_dir.parent
    acquire = load_state(job_dir)
    exclude = set(acquire["failed_source_ids"])
    downloads_attempted = 0
    downloads_ok = 0
    collected_ids: list[str] = list(broll_ids or [])

    inv = _inventory(
        clips_dir,
        required=needed_clips,
        subject=subject,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
    )
    montage_timer().stats.starting_usable = inv.usable_count
    montage_timer().stats.required_clips = needed_clips
    log_broll_progress("ensure_broll", inv, status="progress")

    if inv.satisfies_count():
        inv = _try_diversity_download(
            clips_dir=clips_dir,
            job_dir=job_dir,
            subject=subject,
            query=query,
            clips_limit=clips_limit,
            clip_length=clip_length,
            max_parts=max_parts,
            min_views=min_views,
            min_duration=min_duration,
            start_offset=start_offset,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
            split_full_source=split_full_source,
            reuse_policy=reuse_policy,
            exclude_source_ids=exclude,
            inv=inv,
        )
        log_broll_progress("ensure_broll", inv, status="ok")
        _persist_broll_success(job_dir, inv)
        return collected_ids

    missing = max(0, needed_clips - inv.usable_count)
    with montage_timer().stage_child("pool_lookup"):
        broll_pool.take_from_pool(
            jobs_root,
            subject=subject,
            clips_dir=clips_dir,
            count=missing,
            copy=True,
        )
    inv = _inventory(
        clips_dir,
        required=needed_clips,
        subject=subject,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
    )
    log_broll_progress("ensure_broll", inv, status="progress")
    if inv.satisfies_count():
        inv = _try_diversity_download(
            clips_dir=clips_dir,
            job_dir=job_dir,
            subject=subject,
            query=query,
            clips_limit=clips_limit,
            clip_length=clip_length,
            max_parts=max_parts,
            min_views=min_views,
            min_duration=min_duration,
            start_offset=start_offset,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
            split_full_source=split_full_source,
            reuse_policy=reuse_policy,
            exclude_source_ids=exclude,
            inv=inv,
        )
        log_broll_progress("ensure_broll", inv, status="ok")
        _persist_broll_success(job_dir, inv)
        return collected_ids

    if broll_ids:
        broll_pool.copy_youtube_clips(
            jobs_root,
            clips_dir=clips_dir,
            youtube_ids=[vid for vid in broll_ids if vid not in exclude],
            subject=subject,
            count=missing,
        )
        inv = _inventory(
            clips_dir,
            required=needed_clips,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )
        log_broll_progress("ensure_broll", inv, status="progress")
        if inv.satisfies_count():
            log_broll_progress("ensure_broll", inv, status="ok")
            _persist_broll_success(job_dir, inv)
            return broll_ids

    ladder = broaden_broll_query_ladder(query)
    start_idx = min(acquire["query_index"], max(0, len(ladder) - 1))
    source_cap = 3 if not split_full_source else 4
    max_attempts = source_cap * len(ladder)
    ranked_queues: dict[str, list[VideoCandidate]] = {}
    queue_cursors: dict[str, int] = {}

    def _pop_candidate(search_query: str) -> VideoCandidate | None:
        if search_query not in ranked_queues:
            with montage_timer().stage_child("youtube_search"):
                ranked_queues[search_query] = _discover_candidates_for_query(
                    search_query,
                    limit=max(clips_limit, 12),
                    subject=subject,
                    min_views=min_views,
                    min_duration=min_duration,
                    reuse_policy=reuse_policy,
                    exclude_source_ids=exclude,
                    jobs_root=jobs_root,
                )
            queue_cursors[search_query] = 0
            if ranked_queues[search_query]:
                record_query_attempt(job_dir, search_query)
        cursor = queue_cursors.get(search_query, 0)
        queue = ranked_queues.get(search_query) or []
        while cursor < len(queue):
            candidate = queue[cursor]
            queue_cursors[search_query] = cursor + 1
            cursor += 1
            if candidate.video_id in exclude:
                continue
            return candidate
        return None

    attempt = 0
    while not inv.satisfies_count() and attempt < max_attempts:
        q_idx = start_idx + (attempt // source_cap)
        if q_idx >= len(ladder):
            break
        search_query = ladder[q_idx]
        bump_query_index(job_dir, q_idx)
        missing_now = max(0, needed_clips - inv.usable_count)
        parallel_n = 2 if missing_now >= 4 else 1
        batch: list[VideoCandidate] = []
        for _ in range(parallel_n):
            candidate = _pop_candidate(search_query)
            if candidate:
                batch.append(candidate)
        if not batch:
            attempt += 1
            continue
        downloads_attempted += len(batch)
        montage_timer().stats.downloads_attempted += len(batch)
        try:
            with montage_timer().stage_child("broll_download"):
                ids = download_broll_candidates(
                    clips_dir,
                    batch,
                    clip_length=clip_length,
                    max_parts=max_parts,
                    start_offset=start_offset,
                    subject=subject,
                    use_vision=use_vision,
                    frame_gate=frame_gate,
                    jobs_root=jobs_root,
                    split_full_source=split_full_source,
                    job_dir=job_dir,
                    exclude_source_ids=exclude,
                    max_sources=len(batch),
                    parts_needed=missing_now,
                    needed_clips=needed_clips,
                    allow_parallel=parallel_n >= 2 and len(batch) >= 2,
                    raise_if_empty=False,
                )
            if ids:
                downloads_ok += len(ids)
                montage_timer().stats.downloads_successful += len(ids)
                collected_ids = list(dict.fromkeys([*collected_ids, *ids]))
            for candidate in batch:
                if candidate.video_id not in ids:
                    record_failed_source(job_dir, candidate.video_id)
                    exclude.add(candidate.video_id)
        except RuntimeError:
            for candidate in batch:
                record_failed_source(job_dir, candidate.video_id)
                exclude.add(candidate.video_id)
        inv = _inventory(
            clips_dir,
            required=needed_clips,
            subject=subject,
            use_vision=use_vision,
            frame_gate=frame_gate,
            jobs_root=jobs_root,
        )
        log_broll_progress("ensure_broll", inv, status="progress")
        attempt += 1

    if not inv.satisfies_count():
        _raise_broll_insufficient(
            slug=slug,
            query=query,
            inv=inv,
            downloads_attempted=downloads_attempted,
            downloads_ok=downloads_ok,
        )

    inv = _try_diversity_download(
        clips_dir=clips_dir,
        job_dir=job_dir,
        subject=subject,
        query=query,
        clips_limit=clips_limit,
        clip_length=clip_length,
        max_parts=max_parts,
        min_views=min_views,
        min_duration=min_duration,
        start_offset=start_offset,
        use_vision=use_vision,
        frame_gate=frame_gate,
        jobs_root=jobs_root,
        split_full_source=split_full_source,
        reuse_policy=reuse_policy,
        exclude_source_ids=exclude,
        inv=inv,
    )
    log_broll_progress("ensure_broll", inv, status="ok")
    _persist_broll_success(job_dir, inv)
    montage_timer().stats.downloads_attempted = max(
        montage_timer().stats.downloads_attempted,
        downloads_attempted,
    )
    montage_timer().stats.downloads_successful = max(
        montage_timer().stats.downloads_successful,
        downloads_ok,
    )
    return list(dict.fromkeys([*collected_ids])) if collected_ids else []


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
    caption_mode: str = "word",
    hook_text: str | None = None,
    quality_gate: bool = True,
    segment_gate: bool = True,
    frame_gate: bool = True,
    caption_align: str | None = None,
) -> set[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    actual_duration = probe_duration(audio)
    if abs(actual_duration - duration) > 0.35:
        print(
            f"  audio file is {actual_duration:.2f}s (job said {duration:.2f}s) — using file"
        )
        duration = actual_duration
    temp_output = output.with_suffix(".nocap.mp4")
    job_dir = clips_dir.parent
    min_files = unique_clips_required(
        target_duration=duration,
        segment_length=segment_length,
        layout="single",
        driven_pacing=driven_pacing,
        subject=subject,
    )
    with montage_timer().stage_top("render"):
        manifest_ok, present, required = verify_manifest(job_dir, clips_dir)
        if manifest_ok and present >= min_files:
            usable_count = present
            sources = montage_timer().stats.distinct_sources or 0
            emit_stage_line(
                "pre_render",
                "ok",
                usable=usable_count,
                required=min_files,
                sources=sources,
                manifest=1,
            )
        else:
            usable = filter_broll_clips(
                clips_dir,
                subject=subject,
                use_vision=use_vision,
                frame_gate=frame_gate,
                jobs_root=jobs_root,
            )
            usable_count = len(usable)
            if usable_count < min_files:
                emit_stage_line(
                    "pre_render",
                    "fail",
                    needed=min_files,
                    have=usable_count,
                )
                raise RuntimeError(
                    f"Pre-render B-roll check: need {min_files} usable clips, have {usable_count}."
                )
            emit_stage_line(
                "pre_render",
                "ok",
                usable=usable_count,
                required=min_files,
                sources=len(
                    {
                        broll_pool._youtube_id_from_clip_name(c.name) or c.stem
                        for c in usable
                    }
                ),
                manifest=0,
            )
        grade_note = "charcoal grade" if grade else "no grade"
        print(
            f"Rendering montage: {usable_count} usable clip(s), {duration:.0f}s speech, "
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
            segment_gate=segment_gate,
        )
        if len(used_clips) != len(set(used_clips)):
            raise RuntimeError("Montage reused a B-roll clip file in one render")
        print(f"  montage used {len(used_clips)} unique clip file(s)")
        caption_label = "phrase" if caption_mode == "phrase" else "word"
        align = normalize_caption_align(caption_align, caption_mode=caption_mode)
        print(f"Burning {caption_label} captions ({align})...")
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
            caption_align=align,
            keep_video_audio=False,
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
    frame_gate: bool = True,
    segment_gate: bool = True,
    cursor_review: bool = False,
    caption_mode: str | None = None,
    caption_align: str | None = None,
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
    if caption_mode:
        payload["caption_mode"] = caption_mode
    if caption_align:
        payload["caption_align"] = normalize_caption_align(
            caption_align,
            caption_mode=str(caption_mode or payload.get("caption_mode") or caption_mode_default()),
        )
    if caption_mode or caption_align:
        write_job_json(job_path, payload)
    segment_length = resolve_segment_length(duration, segment_length)
    subject = str(payload.get("subject") or payload.get("broll_query") or slug)
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    if not broll_ids:
        broll_ids = _broll_ids_from_clips(clips_dir)
    if not broll_ids and not list(clips_dir.glob("*_part*.mp4")):
        print("job.json has no broll_ids and clips/ is empty", file=sys.stderr)
        return 1
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
            frame_gate=frame_gate,
            broll_ids=broll_ids,
            slug=slug,
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
            caption_mode=str(caption_mode or payload.get("caption_mode") or caption_mode_default()),
            hook_text=str(payload.get("hook") or "") or None,
            quality_gate=quality_gate,
            segment_gate=segment_gate,
            frame_gate=frame_gate,
            caption_align=str(caption_align or payload.get("caption_align") or "") or None,
        )
    except MontageFailureError as exc:
        print(exc.failure.emit_json_line())
        print(exc, file=sys.stderr)
        return 1
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if cursor_review and output.is_file():
        emit_cursor_review_pack(job_dir=job_dir, output=output, subject=subject)
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
        "--speech-start",
        type=float,
        default=None,
        help="Source timestamp (seconds) for speech excerpt — agent pick after SPEECH.md review",
    )
    parser.add_argument(
        "--speech-duration",
        type=float,
        default=None,
        help="Speech excerpt length (seconds). Use with --speech-start",
    )
    parser.add_argument(
        "--speech-option",
        type=int,
        default=None,
        help="1-based index from cursor-review/SPEECH.md ranked options",
    )
    parser.add_argument(
        "--speech-review-only",
        action="store_true",
        help="Download speech + write cursor-review/SPEECH.md only; no B-roll/render",
    )
    parser.add_argument(
        "--no-speech-score",
        action="store_true",
        help="Do not auto-pick highest-scored excerpt; use sequential window + SPEECH.md",
    )
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
        help="Same as default: one word at a time (kept for older scripts).",
    )
    parser.add_argument(
        "--phrase-captions",
        action="store_true",
        help="Use 2–5 word phrase captions instead of one word at a time.",
    )
    parser.add_argument(
        "--caption-align",
        default=None,
        choices=("center", "lower_middle"),
        help="Caption placement. Default: center for --classic-captions, lower_middle for phrases.",
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
    parser.add_argument(
        "--no-frame-gate",
        action="store_true",
        help="Skip B-roll scan/trim gate. Agent reviews visuals.",
    )
    parser.add_argument(
        "--no-segment-gate",
        action="store_true",
        help="Skip per-beat frame gate when cutting montage beats.",
    )
    parser.add_argument(
        "--code-gates",
        action="store_true",
        help="Legacy automated gates: vision, frame/segment trim, speech max-score, render quality check.",
    )
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
    gate_flags = resolve_montage_gate_flags(args)
    if args.rerender and args.slug:
        job_dir = resolve_job_dir(args.slug, args.jobs_root or (project_root() / "downloads" / "motivational"))
        if job_dir and (job_dir / "job.json").is_file():
            payload = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            rerender_subject = str(
                payload.get("broll_query") or payload.get("visual_style") or payload.get("subject") or ""
            ).strip()
            gate_flags = resolve_montage_gate_flags(args, subject=rerender_subject)
    if gate_flags.cursor_review:
        if not args.keep_work:
            args.keep_work = True
            print("Cursor review (default): keeping clips/ for agent inspection.")
    elif args.code_gates:
        print("Code gates enabled (--code-gates).")
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
            keep_work=args.keep_work or gate_flags.cursor_review,
            cleanup=not args.no_cleanup,
            start_offset=args.intro_skip,
            playback_speed=args.playback_speed,
            use_vision=gate_flags.use_vision,
            quality_gate=gate_flags.quality_gate,
            frame_gate=gate_flags.frame_gate,
            segment_gate=gate_flags.segment_gate,
            cursor_review=gate_flags.cursor_review,
            caption_mode="phrase" if args.phrase_captions else None,
            caption_align=args.caption_align,
        )

    if args.speech_review_only:
        if not args.slug:
            print("--slug is required with --speech-review-only", file=sys.stderr)
            return 2
    elif not args.slug or not args.broll_query:
        print(
            "--slug and --broll-query are required unless --cleanup-only, --rerender, or --speech-review-only",
            file=sys.stderr,
        )
        return 2

    gate_flags = resolve_montage_gate_flags(args, subject=(args.broll_query or "").strip())
    if gate_flags.cursor_review and wants_vehicle(args.broll_query or ""):
        if gate_flags.use_vision:
            print(
                "Vehicle B-roll: frame + segment gates with vision (Cursor review pack still written)."
            )
        else:
            print(
                "Vehicle B-roll: frame + segment gates local-only (--no-vision skips AI frame checks)."
            )

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
    if args.speech_review_only:
        try:
            prepare_speech(
                jobs_root=jobs_root,
                audio_dir=audio_dir,
                url_file=job_dir / "url.txt",
                speaker=speaker,
                speech_query=speech_query,
                speech_url=args.speech_url,
                min_seconds=args.min_seconds,
                max_seconds=args.max_seconds,
                reuse_policy=reuse_policy,
                speech_review_only=True,
                review_out_dir=job_dir / "cursor-review",
            )
        except SpeechReviewReady as exc:
            print(exc)
            print("Pick an option in SPEECH.md, then rerun with --speech-option or --speech-start.")
            return 0
        except MotivationJobError as exc:
            print(exc, file=sys.stderr)
            return 1
        print("Speech review did not stop early — check logs.", file=sys.stderr)
        return 1

    montage_timer().reset(slug=args.slug)
    try:
        with montage_timer().stage_top("prepare_speech"):
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
                speech_start=args.speech_start,
                speech_duration=args.speech_duration,
                speech_option=args.speech_option,
                agent_speech_vet=gate_flags.speech_vet,
                review_out_dir=job_dir / "cursor-review",
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
        montage_timer().stats.required_clips = needed_clips
        with montage_timer().stage_top("ensure_broll"):
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
                use_vision=gate_flags.use_vision,
                frame_gate=gate_flags.frame_gate,
                reuse_policy=reuse_policy,
                slug=args.slug,
            )
        caption_mode = "phrase" if args.phrase_captions else caption_mode_default()
        caption_align = normalize_caption_align(args.caption_align, caption_mode=caption_mode)
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
            use_vision=gate_flags.use_vision,
            driven_pacing=driven_pacing,
            caption_mode=caption_mode,
            hook_text=args.hook,
            quality_gate=gate_flags.quality_gate,
            segment_gate=gate_flags.segment_gate,
            frame_gate=gate_flags.frame_gate,
            caption_align=caption_align,
        )
    except SpeechReviewReady as exc:
        print(exc)
        return 0
    except MotivationJobError as exc:
        print(exc, file=sys.stderr)
        montage_timer().emit()
        return 1
    except MontageFailureError as exc:
        print(exc.failure.emit_json_line())
        print(exc, file=sys.stderr)
        montage_timer().emit()
        return 1
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        code = classify_download_error(exc)
        print(f"{code}: {exc}", file=sys.stderr)
        montage_timer().emit()
        return 1

    if gate_flags.cursor_review:
        emit_cursor_review_pack(
            job_dir=job_dir,
            output=output,
            subject=args.broll_query,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
        )

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
            "speech_pick_method": "agent" if gate_flags.speech_vet else "code",
            "min_seconds": args.min_seconds,
            "max_seconds": args.max_seconds,
            "audio_duration": duration,
            "segment_length": segment_length,
            "playback_speed": args.playback_speed,
            "driven_pacing": driven_pacing,
            "caption_mode": caption_mode,
            "caption_align": caption_align,
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
    with montage_timer().stage_top("register"):
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
    montage_timer().emit()
    print(f"Saved: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
