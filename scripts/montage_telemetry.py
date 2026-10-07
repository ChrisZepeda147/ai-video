"""Structured montage failures + machine-readable stage lines for logs/UI."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

MONTAGE_FAILURE_PREFIX = "MONTAGE_FAILURE="
STAGE_RE = re.compile(
    r"^MONTAGE_STAGE=(?P<stage>\S+)\s+status=(?P<status>\S+)(?:\s+(?P<rest>.+))?$"
)
WARNING_PREFIX = "MONTAGE_WARNING="


@dataclass
class MontageFailure:
    pipeline: str = "build_motivation_job"
    slug: str = ""
    stage: str = "ensure_broll_clips"
    code: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    log_tail: str = ""

    def emit_json_line(self) -> str:
        return MONTAGE_FAILURE_PREFIX + json.dumps(asdict(self), ensure_ascii=False)

    def to_summary(self) -> str:
        if self.summary:
            return self.summary
        return f"{self.code}: {self.stage}"


class MontageFailureError(Exception):
    def __init__(self, failure: MontageFailure):
        self.failure = failure
        super().__init__(failure.to_summary())


def emit_stage_line(stage: str, status: str, **kwargs: Any) -> None:
    parts = [f"MONTAGE_STAGE={stage}", f"status={status}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    print(" ".join(str(p) for p in parts))


def emit_warning(code: str, **kwargs: Any) -> None:
    parts = [f"{WARNING_PREFIX}{code}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    print(" ".join(str(p) for p in parts))


def parse_failure_from_log(text: str) -> MontageFailure | None:
    if not text:
        return None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith(MONTAGE_FAILURE_PREFIX):
            continue
        try:
            data = json.loads(line[len(MONTAGE_FAILURE_PREFIX) :])
            return MontageFailure(**data)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def parse_stage_fail_summary(text: str) -> str | None:
    if not text:
        return None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("MONTAGE_STAGE="):
            continue
        match = STAGE_RE.match(line)
        if not match or match.group("status") not in {"fail", "failed"}:
            continue
        rest = (match.group("rest") or "").strip().replace("=", " ")
        stage = match.group("stage")
        if rest:
            return f"{stage}: {rest}"
        return f"Montage failed at {stage}"
    return None


def extract_log_tail(text: str, *, max_chars: int = 4096) -> str:
    if not text:
        return ""
    blob = text.strip()
    if len(blob) <= max_chars:
        return blob
    return blob[-max_chars:]


def resolve_actionable_error(
    stdout: str,
    stderr: str,
    *,
    exit_code: int | None = None,
) -> tuple[str, MontageFailure | None]:
    combined = "\n".join(p for p in (stdout, stderr) if p).strip()
    failure = parse_failure_from_log(combined)
    if failure:
        return failure.to_summary(), failure
    stage_summary = parse_stage_fail_summary(combined)
    if stage_summary:
        return stage_summary, None
    lines = [ln.strip() for ln in combined.splitlines() if ln.strip()]
    noise_prefixes = (
        "Cursor review (default)",
        "=== build ",
        "Job:",
        "Output:",
        "Speaker:",
        "B-roll query:",
        "Reuse policy:",
        "path bins ->",
        "python ->",
        "WARNING: Store stub",
    )
    for line in reversed(lines):
        if any(line.startswith(prefix) for prefix in noise_prefixes):
            continue
        if line.startswith("WARNING:"):
            continue
        if ":" in line or line.startswith("Need ") or "failed" in line.lower():
            return line[:500], None
    if exit_code:
        return f"Montage build exited {exit_code}", None
    tail = extract_log_tail(combined, max_chars=240)
    return tail or "Montage job failed", None
