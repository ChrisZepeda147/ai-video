"""Montage failure incidents: taxonomy, fingerprints, remediation, escalation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from montage_telemetry import (
    MONTAGE_FAILURE_PREFIX,
    MontageFailure,
    parse_failure_from_log,
)

# Stable taxonomy (small set)
KNOWN_FAILURE_CODES = frozenset(
    {
        "SPEECH_NO_CANDIDATE",
        "SPEECH_DOWNLOAD_FAILED",
        "SPEECH_SUBTITLE_RATE_LIMIT",
        "SPEECH_NO_COHERENT_WINDOW",
        "SPEECH_EXHAUSTED",
        "BROLL_INSUFFICIENT",
        "BROLL_DOWNLOAD_TIMEOUT",
        "BROLL_NO_CANDIDATES",
        "BROLL_GATE_REJECT_ALL",
        "BROLL_FPS_REJECT_ALL",
        "BROLL_TEXT_REJECT_ALL",
        "MONTAGE_TIMEOUT",
        "RENDER_FAILED",
        "FFMPEG_FAILED",
        "WORKER_CRASH",
        "WORKER_ENVIRONMENT",
        "UNKNOWN_FAILURE",
    }
)

SPEECH_CODE_ALIASES = {
    "SPEECH_EXHAUSTED": "SPEECH_NO_CANDIDATE",
    "NO_CANDIDATE_FOUND": "SPEECH_NO_CANDIDATE",
    "REUSE_RESTRICTION": "SPEECH_NO_CANDIDATE",
    "DOWNLOAD_FAILED": "SPEECH_DOWNLOAD_FAILED",
    "FFMPEG_NOT_FOUND": "FFMPEG_FAILED",
}

BROLL_CODE_ALIASES = {
    "BROLL_SOURCE_TIMEOUT": "BROLL_DOWNLOAD_TIMEOUT",
}

CODE_TO_LIKELY_FILES: dict[str, list[str]] = {
    "SPEECH_NO_CANDIDATE": [
        "scripts/speech_acquire.py",
        "scripts/build_motivation_job.py",
    ],
    "SPEECH_DOWNLOAD_FAILED": ["scripts/speech_acquire.py", "scripts/build_motivation_job.py"],
    "SPEECH_SUBTITLE_RATE_LIMIT": ["scripts/speech_acquire.py"],
    "BROLL_INSUFFICIENT": ["scripts/build_motivation_job.py", "scripts/broll_acquire_state.py"],
    "BROLL_DOWNLOAD_TIMEOUT": [
        "scripts/broll_source_subprocess.py",
        "scripts/youtube_popular_downloader.py",
        "scripts/build_motivation_job.py",
    ],
    "BROLL_NO_CANDIDATES": ["scripts/youtube_popular_downloader.py", "scripts/build_motivation_job.py"],
    "MONTAGE_TIMEOUT": ["scripts/discovery/command_montage.py", "scripts/build_motivation_job.py"],
    "RENDER_FAILED": ["scripts/build_clips_montage.py", "scripts/build_motivation_job.py"],
    "WORKER_ENVIRONMENT": ["scripts/discovery/config.py", "scripts/run_direct_job.py"],
    "UNKNOWN_FAILURE": ["scripts/build_motivation_job.py", "scripts/discovery/command_montage.py"],
}

ESCALATION_MIN_FAILURES = 3
ESCALATION_MIN_UNIQUE_SLOTS = 2
SLOT_SAME_FINGERPRINT_MAX = 3
COOLDOWN_MINUTES = 45
RESOLVE_QUIET_HOURS = 6
RESOLVE_MIN_SUCCESS_AFTER = 2

REMEDIATION_PREFIX = "MONTAGE_REMEDIATION"

VISUAL_FAMILY_RE = re.compile(
    r"\b(car|porsche|ferrari|lamborghini|yacht|jet|mountain|sunrise|dolomites|"
    r"city|night|ocean|beach|desert|forest|mansion|house|watch|luxury)\b",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_failure_code(raw: str | None, *, log_text: str = "") -> str:
    code = (raw or "").strip().upper()
    if not code and log_text:
        if "BROLL_SOURCE_TIMEOUT" in log_text or "source subprocess timed out" in log_text.lower():
            code = "BROLL_DOWNLOAD_TIMEOUT"
        elif "BROLL_INSUFFICIENT" in log_text or "B-roll insufficient" in log_text:
            code = "BROLL_INSUFFICIENT"
        elif "WEEKLY_MONTAGE_TIMEOUT" in log_text or "exceeded" in log_text.lower():
            code = "MONTAGE_TIMEOUT"
        elif "SPEECH_EXHAUSTED" in log_text:
            code = "SPEECH_EXHAUSTED"
        elif "subtitle_429" in log_text or "subtitle 429" in log_text.lower():
            code = "SPEECH_SUBTITLE_RATE_LIMIT"
        elif "no_coherent_window" in log_text or "mid_thought_window" in log_text:
            code = "SPEECH_NO_COHERENT_WINDOW"
        elif "ffmpeg" in log_text.lower():
            code = "FFMPEG_FAILED"
    code = SPEECH_CODE_ALIASES.get(code, code)
    code = BROLL_CODE_ALIASES.get(code, code)
    if code in KNOWN_FAILURE_CODES:
        return code
    if code.startswith("SPEECH_"):
        return "SPEECH_DOWNLOAD_FAILED"
    if code.startswith("BROLL_"):
        return "BROLL_INSUFFICIENT"
    return "UNKNOWN_FAILURE"


def visual_family(visual_query: str) -> str:
    text = (visual_query or "").lower().strip()
    if not text:
        return "generic"
    match = VISUAL_FAMILY_RE.search(text)
    if match:
        return match.group(1).lower()
    words = re.findall(r"[a-z]{4,}", text)
    return "-".join(words[:3]) if words else "generic"


def failure_fingerprint(
    *,
    failure_code: str,
    failure_stage: str,
    speaker: str = "",
    visual_query: str = "",
    details: dict[str, Any] | None = None,
) -> str:
    code = normalize_failure_code(failure_code)
    stage = (failure_stage or "unknown").strip()
    sp = re.sub(r"\s+", "-", (speaker or "any").lower())[:40]
    fam = visual_family(visual_query)
    extra = ""
    det = details or {}
    if code == "BROLL_DOWNLOAD_TIMEOUT" and det.get("source_id"):
        extra = f"|src={det['source_id']}"
    elif code == "SPEECH_SUBTITLE_RATE_LIMIT":
        extra = "|rate-limit"
    return f"{code}|{stage}|{sp}|{fam}{extra}"


def synthesize_failure(
    *,
    stdout: str,
    stderr: str = "",
    exit_code: int | None = None,
    slug: str = "",
    timed_out: bool = False,
    worker_crashed: bool = False,
) -> MontageFailure:
    combined = "\n".join(p for p in (stdout, stderr) if p)
    parsed = parse_failure_from_log(combined)
    if parsed:
        parsed.code = normalize_failure_code(parsed.code, log_text=combined)
        return parsed
    if timed_out:
        return MontageFailure(
            slug=slug,
            stage="montage_wall_clock",
            code="MONTAGE_TIMEOUT",
            summary="Montage exceeded wall-clock timeout",
            details={"exit_code": exit_code},
        )
    if worker_crashed:
        return MontageFailure(
            slug=slug,
            stage="worker",
            code="WORKER_CRASH",
            summary="Montage worker crashed or failed to start",
            details={"exit_code": exit_code},
        )
    code = normalize_failure_code("", log_text=combined)
    summary = f"Montage build exited {exit_code}" if exit_code else "Montage job failed"
    return MontageFailure(
        slug=slug,
        stage="unknown",
        code=code,
        summary=summary,
        details={"exit_code": exit_code},
    )


def emit_remediation(*, code: str, action: str, result: str, **kwargs: Any) -> None:
    parts = [f"{REMEDIATION_PREFIX} code={code} action={action} result={result}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    print(" ".join(str(p) for p in parts))


REMEDIATION_ACTIONS: dict[str, str] = {
    "SPEECH_SUBTITLE_RATE_LIMIT": "speech_cooldown_next_candidate",
    "SPEECH_NO_CANDIDATE": "speech_broaden_ladder",
    "SPEECH_DOWNLOAD_FAILED": "speech_skip_failed_id",
    "SPEECH_NO_COHERENT_WINDOW": "speech_skip_failed_id",
    "BROLL_NO_CANDIDATES": "broll_broaden_query_ladder",
    "BROLL_INSUFFICIENT": "broll_preserve_partial_extend_ladder",
    "BROLL_DOWNLOAD_TIMEOUT": "broll_mark_source_failed",
    "BROLL_FPS_REJECT_ALL": "broll_search_without_metadata_prefilter",
    "BROLL_GATE_REJECT_ALL": "broll_new_sources_keep_gates",
    "MONTAGE_TIMEOUT": "preserve_assets_retry_next_pass",
    "WORKER_CRASH": "reconcile_retry_if_preflight_ok",
    "RENDER_FAILED": "retry_render_if_inputs_valid",
    "UNKNOWN_FAILURE": "log_only",
}


def incidents_dir(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    path = base / "data" / "incidents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def remediation_sidecar_path(job_dir: Path) -> Path:
    return job_dir / "montage_remediation.json"


def load_remediation_sidecar(job_dir: Path) -> dict[str, Any]:
    path = remediation_sidecar_path(job_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_remediation_sidecar(job_dir: Path, payload: dict[str, Any]) -> None:
    path = remediation_sidecar_path(job_dir)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def apply_remediation_to_job_dir(
    job_dir: Path,
    *,
    failure_code: str,
    fingerprint: str,
) -> tuple[str, str, dict[str, Any]]:
    """Safe runtime remediation — never edits source code."""
    code = normalize_failure_code(failure_code)
    action = REMEDIATION_ACTIONS.get(code, "log_only")
    sidecar = load_remediation_sidecar(job_dir)
    sidecar["last_fingerprint"] = fingerprint
    sidecar["last_failure_code"] = code
    sidecar["remediation_count"] = int(sidecar.get("remediation_count") or 0) + 1
    sidecar["updated_at"] = _now_iso()
    result = "skipped"

    if action == "speech_broaden_ladder":
        speech_path = job_dir / "speech_acquire.json"
        speech: dict[str, Any] = {"failed_source_ids": [], "reasons": {}}
        if speech_path.is_file():
            try:
                speech = json.loads(speech_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        speech["speech_ladder_offset"] = int(speech.get("speech_ladder_offset") or 0) + 1
        speech_path.write_text(json.dumps(speech, indent=2), encoding="utf-8")
        sidecar["speech_ladder_offset"] = speech["speech_ladder_offset"]
        result = "applied"

    elif action == "speech_skip_failed_id":
        sidecar["speech_retry"] = True
        result = "applied"

    elif action == "speech_cooldown_next_candidate":
        sidecar["speech_cooldown_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=15)
        ).replace(microsecond=0).isoformat()
        result = "applied"

    elif action == "broll_broaden_query_ladder":
        from broll_acquire_state import load_state, save_state

        state = load_state(job_dir)
        idx = int(state.get("query_index") or 0)
        state["query_index"] = idx + 1
        save_state(job_dir, state)
        sidecar["broll_query_index"] = state["query_index"]
        result = "applied"

    elif action == "broll_preserve_partial_extend_ladder":
        from broll_acquire_state import load_state, save_state

        state = load_state(job_dir)
        state["query_index"] = int(state.get("query_index") or 0) + 1
        save_state(job_dir, state)
        sidecar["broll_fresh_search"] = True
        sidecar["broll_extend_partial"] = True
        result = "applied"

    elif action == "broll_mark_source_failed":
        sidecar["broll_skip_recent_timeout_sources"] = True
        result = "applied"

    elif action == "broll_search_without_metadata_prefilter":
        sidecar["broll_skip_fps_search_prefilter"] = True
        result = "applied"

    elif action == "broll_new_sources_keep_gates":
        from broll_acquire_state import bump_query_index, load_state

        state = load_state(job_dir)
        bump_query_index(job_dir, int(state.get("query_index") or 0) + 1)
        sidecar["broll_new_sources"] = True
        result = "applied"

    elif action == "preserve_assets_retry_next_pass":
        sidecar["preserve_assets"] = True
        result = "applied"

    elif action == "retry_render_if_inputs_valid":
        sidecar["render_only_retry"] = True
        result = "applied"

    elif action == "reconcile_retry_if_preflight_ok":
        result = "deferred"

    save_remediation_sidecar(job_dir, sidecar)
    emit_remediation(code=code, action=action, result=result, job_dir=str(job_dir))
    return action, result, sidecar


def remediation_env_from_sidecar(job_dir: Path) -> dict[str, str]:
    sidecar = load_remediation_sidecar(job_dir)
    env: dict[str, str] = {}
    if sidecar.get("broll_fresh_search"):
        env["MONTAGE_BROLL_FRESH_SEARCH"] = "1"
    if sidecar.get("broll_skip_fps_search_prefilter"):
        env["MONTAGE_BROLL_SKIP_FPS_PREFILTER"] = "1"
    if sidecar.get("render_only_retry"):
        env["MONTAGE_RENDER_ONLY_RETRY"] = "1"
    off = sidecar.get("speech_ladder_offset")
    if off is not None:
        env["MONTAGE_SPEECH_LADDER_OFFSET"] = str(int(off))
    return env


def parse_timing_metrics(log_text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if not log_text:
        return metrics
    for line in log_text.splitlines():
        line = line.strip()
        if line.startswith("MONTAGE_TIMING ") and "stage=" in line:
            m = re.search(r"stage=(\S+)\s+seconds=([\d.]+)", line)
            if m:
                metrics[f"stage_{m.group(1)}_sec"] = float(m.group(2))
        if line.startswith("MONTAGE_TIMING_COUNTS "):
            for part in line.split()[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    try:
                        metrics[k] = int(v) if v.isdigit() else float(v)
                    except ValueError:
                        metrics[k] = v
        if line.startswith("MONTAGE_TIMING_TOTAL "):
            m = re.search(r"wall_seconds=([\d.]+)", line)
            if m:
                metrics["wall_seconds"] = float(m.group(1))
    return metrics


def parse_acquire_counts(job_dir: Path | None) -> tuple[int, int]:
    if not job_dir or not job_dir.is_dir():
        return 0, 0
    sp = 0
    bp = 0
    for name, key in (
        ("speech_acquire.json", "failed_source_ids"),
        ("broll_acquire.json", "failed_source_ids"),
    ):
        path = job_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            n = len(data.get(key) or [])
            if name.startswith("speech"):
                sp = n
            else:
                bp = n
        except (OSError, json.JSONDecodeError):
            pass
    return sp, bp


@dataclass
class IncidentRecord:
    outcome: str
    owner: str = ""
    week_start: str = ""
    day: str = ""
    slot_id: int | None = None
    job_key: str = ""
    slug: str = ""
    speaker: str = ""
    visual_query: str = ""
    failure_code: str = ""
    failure_stage: str = ""
    failure_summary: str = ""
    failure_details_json: str = ""
    fingerprint: str = ""
    attempt_number: int = 0
    pass_number: int = 0
    speech_valid: bool | None = None
    speech_duration: float | None = None
    broll_required: int | None = None
    broll_usable: int | None = None
    downloads_attempted: int | None = None
    downloads_successful: int | None = None
    failed_speech_ids_count: int = 0
    failed_broll_ids_count: int = 0
    runtime_seconds: float | None = None
    worker_python: str = ""
    status: str = "open"
    remediation_action: str = ""
    remediation_result: str = ""
    metrics_json: str = ""


def ensure_montage_incident_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS montage_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            outcome TEXT NOT NULL,
            owner TEXT,
            week_start TEXT,
            day TEXT,
            slot_id INTEGER,
            job_key TEXT,
            slug TEXT,
            speaker TEXT,
            visual_query TEXT,
            failure_code TEXT,
            failure_stage TEXT,
            failure_summary TEXT,
            failure_details_json TEXT,
            fingerprint TEXT,
            attempt_number INTEGER,
            pass_number INTEGER,
            speech_valid INTEGER,
            speech_duration REAL,
            broll_required INTEGER,
            broll_usable INTEGER,
            downloads_attempted INTEGER,
            downloads_successful INTEGER,
            failed_speech_ids_count INTEGER,
            failed_broll_ids_count INTEGER,
            runtime_seconds REAL,
            worker_python TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            remediation_action TEXT,
            remediation_result TEXT,
            metrics_json TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_montage_incidents_fp ON montage_incidents (fingerprint, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_montage_incidents_slot ON montage_incidents (slot_id, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS montage_engineering_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL,
            failure_code TEXT NOT NULL,
            failure_stage TEXT,
            severity TEXT NOT NULL DEFAULT 'engineering',
            status TEXT NOT NULL DEFAULT 'active',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            failure_count_24h INTEGER DEFAULT 0,
            unique_slots INTEGER DEFAULT 0,
            details_json TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_montage_eng_inc_fp ON montage_engineering_incidents (fingerprint)"
    )


def _slot_context(store, job_key: str) -> dict[str, Any]:
    row = store._conn.execute(
        """
        SELECT s.id, s.day, s.speaker, s.visual_direction, p.week_start, p.owner
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.job_key = ?
        LIMIT 1
        """,
        (job_key,),
    ).fetchone()
    return dict(row) if row else {}


def _attempt_number_for_slot(conn, slot_id: int | None) -> int:
    if not slot_id:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM montage_incidents WHERE slot_id = ? AND outcome = 'failure'",
        (slot_id,),
    ).fetchone()
    return int(row["n"]) + 1 if row else 1


def insert_incident(conn, rec: IncidentRecord) -> int:
    ts = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO montage_incidents (
            created_at, updated_at, outcome, owner, week_start, day, slot_id, job_key,
            slug, speaker, visual_query, failure_code, failure_stage, failure_summary,
            failure_details_json, fingerprint, attempt_number, pass_number,
            speech_valid, speech_duration, broll_required, broll_usable,
            downloads_attempted, downloads_successful, failed_speech_ids_count,
            failed_broll_ids_count, runtime_seconds, worker_python, status,
            remediation_action, remediation_result, metrics_json
        ) VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            ts,
            ts,
            rec.outcome,
            rec.owner,
            rec.week_start,
            rec.day,
            rec.slot_id,
            rec.job_key,
            rec.slug,
            rec.speaker,
            rec.visual_query,
            rec.failure_code,
            rec.failure_stage,
            rec.failure_summary,
            rec.failure_details_json,
            rec.fingerprint,
            rec.attempt_number,
            rec.pass_number,
            None if rec.speech_valid is None else int(rec.speech_valid),
            rec.speech_duration,
            rec.broll_required,
            rec.broll_usable,
            rec.downloads_attempted,
            rec.downloads_successful,
            rec.failed_speech_ids_count,
            rec.failed_broll_ids_count,
            rec.runtime_seconds,
            rec.worker_python,
            rec.status,
            rec.remediation_action,
            rec.remediation_result,
            rec.metrics_json,
        ),
    )
    return int(cur.lastrowid or 0)


def fingerprint_stats(conn, fingerprint: str, *, hours: float = 24) -> dict[str, Any]:
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT slot_id FROM montage_incidents
        WHERE fingerprint = ? AND outcome = 'failure' AND created_at >= ?
        """,
        (fingerprint, cut),
    ).fetchall()
    slots = {int(r["slot_id"]) for r in rows if r["slot_id"] is not None}
    return {
        "failure_count_24h": len(rows),
        "unique_slots": len(slots),
        "slot_ids": sorted(slots),
    }


def slot_same_fingerprint_streak(conn, slot_id: int, fingerprint: str) -> int:
    rows = conn.execute(
        """
        SELECT fingerprint FROM montage_incidents
        WHERE slot_id = ? AND outcome = 'failure'
        ORDER BY id DESC LIMIT 10
        """,
        (slot_id,),
    ).fetchall()
    streak = 0
    for row in rows:
        if str(row["fingerprint"]) == fingerprint:
            streak += 1
        else:
            break
    return streak


def slot_cooldown_until(conn, slot_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT metrics_json FROM montage_incidents
        WHERE slot_id = ? AND outcome = 'failure'
        ORDER BY id DESC LIMIT 1
        """,
        (slot_id,),
    ).fetchone()
    if not row or not row["metrics_json"]:
        return None
    try:
        data = json.loads(row["metrics_json"])
        return data.get("cooldown_until")
    except json.JSONDecodeError:
        return None


def slot_on_cooldown(conn, slot_id: int) -> bool:
    until = slot_cooldown_until(conn, slot_id)
    if not until:
        return False
    try:
        end = datetime.fromisoformat(until.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < end
    except ValueError:
        return False


def last_remediation_changed(conn, slot_id: int, fingerprint: str) -> bool:
    rows = conn.execute(
        """
        SELECT fingerprint, remediation_action, remediation_result
        FROM montage_incidents
        WHERE slot_id = ? AND outcome = 'failure'
        ORDER BY id DESC LIMIT 2
        """,
        (slot_id,),
    ).fetchall()
    if len(rows) < 2:
        return True
    prev, cur = rows[1], rows[0]
    if str(cur["fingerprint"]) != fingerprint:
        return True
    return (
        str(cur["remediation_action"]) != str(prev["remediation_action"])
        or str(cur["remediation_result"]) == "applied"
    )


def should_skip_slot_this_pass(store, slot_id: int, fingerprint: str | None = None) -> bool:
    conn = store._conn
    ensure_montage_incident_tables(conn)
    if slot_on_cooldown(conn, slot_id):
        return True
    if not fingerprint:
        row = conn.execute(
            """
            SELECT fingerprint FROM montage_incidents
            WHERE slot_id = ? AND outcome = 'failure'
            ORDER BY id DESC LIMIT 1
            """,
            (slot_id,),
        ).fetchone()
        fingerprint = str(row["fingerprint"]) if row else ""
    if not fingerprint:
        return False
    streak = slot_same_fingerprint_streak(conn, slot_id, fingerprint)
    if streak < SLOT_SAME_FINGERPRINT_MAX:
        return False
    if last_remediation_changed(conn, slot_id, fingerprint):
        return False
    return True


def record_montage_terminal(
    store,
    *,
    job_key: str,
    slug: str,
    outcome: str,
    stdout_log: str = "",
    stderr_log: str = "",
    exit_code: int | None = None,
    timed_out: bool = False,
    worker_crashed: bool = False,
    worker_python: str = "",
    job_dir: Path | None = None,
    pass_number: int = 0,
) -> dict[str, Any]:
    """Record success or failure; apply remediation / escalation on failure."""
    from discovery.config import project_root

    conn = store._conn
    ensure_montage_incident_tables(conn)
    ctx = _slot_context(store, job_key)
    slot_id = int(ctx["id"]) if ctx.get("id") else None
    metrics = parse_timing_metrics(stdout_log)
    sp_fail, br_fail = parse_acquire_counts(job_dir)
    failure: MontageFailure | None = None
    remediation_action = ""
    remediation_result = ""
    fp = ""
    status = "resolved" if outcome == "success" else "open"

    if outcome == "failure":
        failure = synthesize_failure(
            stdout=stdout_log,
            stderr=stderr_log,
            exit_code=exit_code,
            slug=slug,
            timed_out=timed_out,
            worker_crashed=worker_crashed,
        )
        if failure.code not in KNOWN_FAILURE_CODES:
            failure.code = normalize_failure_code(failure.code, log_text=stdout_log)
        fp = failure_fingerprint(
            failure_code=failure.code,
            failure_stage=failure.stage,
            speaker=str(ctx.get("speaker") or ""),
            visual_query=str(ctx.get("visual_direction") or ""),
            details=failure.details,
        )
        if job_dir and job_dir.is_dir():
            remediation_action, remediation_result, _ = apply_remediation_to_job_dir(
                job_dir,
                failure_code=failure.code,
                fingerprint=fp,
            )
        streak = slot_same_fingerprint_streak(conn, slot_id or 0, fp) + 1 if slot_id else 0
        if (
            slot_id
            and streak >= SLOT_SAME_FINGERPRINT_MAX
            and remediation_result != "applied"
            and not last_remediation_changed(conn, slot_id, fp)
        ):
            until = (
                datetime.now(timezone.utc) + timedelta(minutes=COOLDOWN_MINUTES)
            ).replace(microsecond=0).isoformat()
            metrics["cooldown_until"] = until
            status = "cooldown"

    elif outcome == "success":
        fp = "success"
        maybe_resolve_engineering_incidents(conn, project_root())

    det_json = json.dumps(failure.details if failure else {}, ensure_ascii=False)
    rec = IncidentRecord(
        outcome=outcome,
        owner=str(ctx.get("owner") or ""),
        week_start=str(ctx.get("week_start") or ""),
        day=str(ctx.get("day") or ""),
        slot_id=slot_id,
        job_key=job_key,
        slug=slug,
        speaker=str(ctx.get("speaker") or ""),
        visual_query=str(ctx.get("visual_direction") or ""),
        failure_code=failure.code if failure else "",
        failure_stage=failure.stage if failure else "",
        failure_summary=failure.to_summary() if failure else "",
        failure_details_json=det_json,
        fingerprint=fp if outcome == "failure" else "",
        attempt_number=_attempt_number_for_slot(conn, slot_id),
        pass_number=pass_number,
        broll_required=metrics.get("required"),
        broll_usable=metrics.get("clips_usable"),
        downloads_attempted=metrics.get("downloads_attempted"),
        downloads_successful=metrics.get("downloads_successful"),
        failed_speech_ids_count=sp_fail,
        failed_broll_ids_count=br_fail,
        runtime_seconds=metrics.get("wall_seconds"),
        worker_python=worker_python,
        status=status,
        remediation_action=remediation_action,
        remediation_result=remediation_result,
        metrics_json=json.dumps(metrics),
    )
    if outcome == "success" and metrics.get("stage_prepare_speech_sec"):
        rec.speech_duration = metrics.get("stage_prepare_speech_sec")
        rec.speech_valid = True

    incident_id = insert_incident(conn, rec)
    conn.commit()

    eng: dict[str, Any] | None = None
    if outcome == "failure" and fp:
        eng = upsert_engineering_incident(store, fingerprint=fp, failure=failure, slot_id=slot_id)
    return {
        "incident_id": incident_id,
        "fingerprint": fp,
        "failure_code": rec.failure_code,
        "engineering_incident": eng,
    }


def upsert_engineering_incident(
    store,
    *,
    fingerprint: str,
    failure: MontageFailure | None,
    slot_id: int | None,
) -> dict[str, Any] | None:
    from discovery.config import project_root

    conn = store._conn
    ensure_montage_incident_tables(conn)
    stats = fingerprint_stats(conn, fingerprint, hours=24)
    if stats["failure_count_24h"] < ESCALATION_MIN_FAILURES:
        return None
    if stats["unique_slots"] < ESCALATION_MIN_UNIQUE_SLOTS:
        return None

    ts = _now_iso()
    code = failure.code if failure else ""
    stage = failure.stage if failure else ""
    details = {
        "failure_count_24h": stats["failure_count_24h"],
        "unique_slots": stats["unique_slots"],
        "slot_ids": stats["slot_ids"],
        "latest_summary": failure.to_summary() if failure else "",
        "failure_details": failure.details if failure else {},
    }
    conn.execute(
        """
        INSERT INTO montage_engineering_incidents (
            fingerprint, failure_code, failure_stage, severity, status,
            first_seen_at, last_seen_at, failure_count_24h, unique_slots, details_json
        ) VALUES (?, ?, ?, 'engineering', 'active', ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            failure_code = excluded.failure_code,
            failure_stage = excluded.failure_stage,
            last_seen_at = excluded.last_seen_at,
            failure_count_24h = excluded.failure_count_24h,
            unique_slots = excluded.unique_slots,
            details_json = excluded.details_json,
            status = 'active'
        """,
        (
            fingerprint,
            code,
            stage,
            ts,
            ts,
            stats["failure_count_24h"],
            stats["unique_slots"],
            json.dumps(details, ensure_ascii=False),
        ),
    )
    conn.commit()
    payload = build_incident_files(store, fingerprint=fingerprint, root=project_root())
    return payload


def active_engineering_incident(conn) -> dict[str, Any] | None:
    ensure_montage_incident_tables(conn)
    row = conn.execute(
        """
        SELECT * FROM montage_engineering_incidents
        WHERE status = 'active'
        ORDER BY last_seen_at DESC LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def maybe_resolve_engineering_incidents(conn, root: Path) -> None:
    ensure_montage_incident_tables(conn)
    cut = (datetime.now(timezone.utc) - timedelta(hours=RESOLVE_QUIET_HOURS)).replace(
        microsecond=0
    ).isoformat()
    rows = conn.execute(
        "SELECT fingerprint FROM montage_engineering_incidents WHERE status = 'active'"
    ).fetchall()
    for row in rows:
        fp = str(row["fingerprint"])
        recent_fail = conn.execute(
            """
            SELECT COUNT(*) AS n FROM montage_incidents
            WHERE fingerprint = ? AND outcome = 'failure' AND created_at >= ?
            """,
            (fp, cut),
        ).fetchone()
        if recent_fail and int(recent_fail["n"]) > 0:
            continue
        successes = conn.execute(
            """
            SELECT COUNT(*) AS n FROM montage_incidents
            WHERE outcome = 'success' AND created_at >= ?
            """,
            (cut,),
        ).fetchone()
        if successes and int(successes["n"]) >= RESOLVE_MIN_SUCCESS_AFTER:
            conn.execute(
                """
                UPDATE montage_engineering_incidents
                SET status = 'resolved', last_seen_at = ?
                WHERE fingerprint = ?
                """,
                (_now_iso(), fp),
            )
    conn.commit()
    if not active_engineering_incident(conn):
        for name in ("LAST_MONTAGE_INCIDENT.json", "LAST_MONTAGE_INCIDENT.md", "CURSOR_FAILURE_BRIEF.md"):
            path = incidents_dir(root) / name
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass


def build_incident_files(
    store,
    *,
    fingerprint: str,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[1]
    conn = store._conn
    ensure_montage_incident_tables(conn)
    eng = conn.execute(
        "SELECT * FROM montage_engineering_incidents WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    if not eng:
        return {}
    eng_d = dict(eng)
    stats = fingerprint_stats(conn, fingerprint, hours=24)
    recent = conn.execute(
        """
        SELECT job_key, slot_id, slug, speaker, visual_query, failure_summary,
               failure_code, failure_stage, failure_details_json, created_at,
               remediation_action, remediation_result, metrics_json
        FROM montage_incidents
        WHERE fingerprint = ? AND outcome = 'failure'
        ORDER BY id DESC LIMIT 8
        """,
        (fingerprint,),
    ).fetchall()
    code = str(eng_d.get("failure_code") or "")
    likely = CODE_TO_LIKELY_FILES.get(code, CODE_TO_LIKELY_FILES["UNKNOWN_FAILURE"])

    payload = {
        "INCIDENT": True,
        "timestamp": _now_iso(),
        "fingerprint": fingerprint,
        "failure_code": code,
        "failure_stage": eng_d.get("failure_stage"),
        "severity": eng_d.get("severity"),
        "status": eng_d.get("status"),
        "failure_count_24h": stats["failure_count_24h"],
        "unique_slot_count": stats["unique_slots"],
        "affected_slot_ids": stats["slot_ids"],
        "recent_attempts": [dict(r) for r in recent],
        "likely_files": likely,
        "do_not_auto_modify": [
            "quality gates (frame/text/fps)",
            "speaker assignment",
            "caption style",
            "timeout increases without review",
            "source code (.py/.ts/.tsx)",
        ],
    }

    out_dir = incidents_dir(root)
    json_path = out_dir / "LAST_MONTAGE_INCIDENT.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_lines = [
        "# Montage engineering incident",
        "",
        f"**Code:** `{code}`",
        f"**Fingerprint:** `{fingerprint}`",
        f"**Failures (24h):** {stats['failure_count_24h']} across {stats['unique_slots']} slot(s)",
        "",
        "## Affected slots",
        ", ".join(str(x) for x in stats["slot_ids"]) or "(none)",
        "",
        "## Likely files",
        *(f"- `{p}`" for p in likely),
        "",
        "## Recent summaries",
    ]
    for r in recent[:5]:
        md_lines.append(f"- slot {r['slot_id']}: {r['failure_summary']}")
    (out_dir / "LAST_MONTAGE_INCIDENT.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    brief = _cursor_failure_brief(payload, recent, stats)
    (out_dir / "CURSOR_FAILURE_BRIEF.md").write_text(brief, encoding="utf-8")
    payload["incident_path"] = str(json_path)
    return payload


def _cursor_failure_brief(payload: dict[str, Any], recent, stats) -> str:
    code = payload.get("failure_code") or "UNKNOWN"
    lines = [
        "# CURRENT PRODUCTION INCIDENT",
        "",
        "## What is failing",
        f"- Failure code: **{code}**",
        f"- Fingerprint: `{payload.get('fingerprint')}`",
        "",
        "## How often",
        f"- {stats['failure_count_24h']} failures in last 24h",
        f"- {stats['unique_slots']} unique weekly slots",
        "",
        "## Which slots",
        ", ".join(str(x) for x in stats.get("slot_ids") or []) or "(see JSON)",
        "",
        "## Runtime remediation already attempted",
    ]
    for r in recent[:6]:
        lines.append(
            f"- slot {r['slot_id']}: action={r['remediation_action'] or 'none'} "
            f"result={r['remediation_result'] or 'n/a'}"
        )
    lines.extend(
        [
            "",
            "## What NOT to modify (production auto-heal forbidden)",
            "- Frame gate, text gate, FPS floor, speaker, captions, unrelated B-roll",
            "- Any `.py` / `.ts` / `.tsx` from the production pipeline",
            "",
            "## Relevant files",
            *[f"- `{p}`" for p in payload.get("likely_files") or []],
            "",
            "## Recommended diagnostic next step",
            f"Inspect `{code}` paths in logs (`MONTAGE_FAILURE`, `MONTAGE_TIMING_COUNTS`) "
            "for the affected slots; compare timing funnel vs successful baselines in `montage_incidents`.",
            "",
            "## Exact log pointers",
            "Full stdout remains on `cursor_command_jobs.stdout_log` (not duplicated here).",
            "Search job logs for `MONTAGE_FAILURE=` and `MONTAGE_REMEDIATION`.",
        ]
    )
    return "\n".join(lines) + "\n"


def health_incident_summary(store) -> dict[str, Any]:
    conn = store._conn
    ensure_montage_incident_tables(conn)
    eng = active_engineering_incident(conn)
    root = Path(__file__).resolve().parents[1]
    json_path = incidents_dir(root) / "LAST_MONTAGE_INCIDENT.json"
    if not eng:
        return {
            "active_incident": False,
            "incident_failure_code": None,
            "incident_count_24h": 0,
            "incident_unique_slots": 0,
            "incident_last_seen": None,
            "incident_path": str(json_path) if json_path.is_file() else None,
            "incident_message": None,
        }
    fp = str(eng["fingerprint"])
    stats = fingerprint_stats(conn, fp, hours=24)
    code = str(eng.get("failure_code") or "")
    msg = f"Production issue detected: {code.replace('_', ' ').lower()} across {stats['unique_slots']} videos."
    return {
        "active_incident": True,
        "incident_failure_code": code,
        "incident_count_24h": stats["failure_count_24h"],
        "incident_unique_slots": stats["unique_slots"],
        "incident_last_seen": eng.get("last_seen_at"),
        "incident_path": str(json_path) if json_path.is_file() else None,
        "incident_message": msg,
    }


def baseline_report_last_hours(store, hours: float = 12) -> list[dict[str, Any]]:
    conn = store._conn
    ensure_montage_incident_tables(conn)
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT failure_code, fingerprint, slot_id, runtime_seconds, created_at,
               remediation_result, metrics_json
        FROM montage_incidents
        WHERE outcome = 'failure' AND created_at >= ?
        """,
        (cut,),
    ).fetchall()
    if rows:
        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            fp = str(r["fingerprint"] or r["failure_code"])
            g = grouped.setdefault(
                fp,
                {
                    "failure_code": r["failure_code"],
                    "fingerprint": fp,
                    "count": 0,
                    "slots": set(),
                    "runtimes": [],
                    "last": None,
                    "remediated": 0,
                },
            )
            g["count"] += 1
            if r["slot_id"]:
                g["slots"].add(int(r["slot_id"]))
            if r["runtime_seconds"]:
                g["runtimes"].append(float(r["runtime_seconds"]))
            g["last"] = r["created_at"]
            if r["remediation_result"] == "applied":
                g["remediated"] += 1
        out = []
        for g in grouped.values():
            rt = g["runtimes"]
            out.append(
                {
                    "failure_code": g["failure_code"],
                    "fingerprint": g["fingerprint"],
                    "count": g["count"],
                    "unique_slots": len(g["slots"]),
                    "avg_runtime": sum(rt) / len(rt) if rt else None,
                    "last_occurrence": g["last"],
                    "remediation_applied": g["remediated"],
                }
            )
        out.sort(key=lambda x: -x["count"])
        return out

    # Fallback before incidents table backfilled: scan command jobs
    jobs = conn.execute(
        """
        SELECT job_key, error_summary, substr(stdout_log, -6000) AS tail, completed_at
        FROM cursor_command_jobs
        WHERE status = 'failed' AND COALESCE(completed_at, created_at) >= ?
        """,
        (cut,),
    ).fetchall()
    grouped2: dict[str, dict[str, Any]] = {}
    for job in jobs:
        fail = parse_failure_from_log(job["tail"] or "")
        code = normalize_failure_code(
            (fail.code if fail else "") or "",
            log_text=(job["tail"] or "") + (job["error_summary"] or ""),
        )
        fp = f"{code}|legacy"
        g = grouped2.setdefault(fp, {"failure_code": code, "count": 0, "unique_slots": 0, "last": None})
        g["count"] += 1
        g["last"] = job["completed_at"]
    return sorted(
        [
            {
                "failure_code": v["failure_code"],
                "fingerprint": k,
                "count": v["count"],
                "unique_slots": 0,
                "avg_runtime": None,
                "last_occurrence": v["last"],
                "remediation_applied": 0,
            }
            for k, v in grouped2.items()
        ],
        key=lambda x: -x["count"],
    )
