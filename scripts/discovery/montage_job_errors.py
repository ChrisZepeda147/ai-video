"""Resolve human-facing montage errors for Weekly + command jobs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from discovery.config import project_root


def _telemetry():
    scripts = project_root() / "scripts"
    path = str(scripts)
    if path not in sys.path:
        sys.path.insert(0, path)
    import montage_telemetry  # noqa: WPS433

    return montage_telemetry


def command_job_error_summary(job: dict[str, Any] | None) -> str:
    if not job:
        return "Job failed"
    summary = str(job.get("error_summary") or "").strip()
    if summary:
        return summary[:500]
    telemetry = _telemetry()
    text, _failure = telemetry.resolve_actionable_error(
        str(job.get("stdout_log") or ""),
        str(job.get("stderr_log") or ""),
    )
    return (text or str(job.get("error_message") or "Job failed"))[:500]
