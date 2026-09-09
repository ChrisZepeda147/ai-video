"""System readiness checks before a real pilot run."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from discovery.config import default_db_path, generation_jobs_dir, project_root
from discovery.store import DiscoveryStore

CheckStatus = Literal["ready", "warning", "not_configured"]


def _check(label: str, status: CheckStatus, detail: str, *, fix_hint: str | None = None) -> dict[str, Any]:
    return {"label": label, "status": status, "detail": detail, "fix_hint": fix_hint}


def run_preflight(store: DiscoveryStore | None = None) -> dict[str, Any]:
    """Return grouped readiness checks — optional integrations warn, never hard-fail."""
    checks: dict[str, list[dict[str, Any]]] = {
        "core": [],
        "ai_media": [],
        "publishing": [],
        "analytics": [],
    }

    # Core
    py_ok = sys.version_info >= (3, 11)
    checks["core"].append(
        _check(
            "Python environment",
            "ready" if py_ok else "warning",
            f"{sys.version_info.major}.{sys.version_info.minor}",
            fix_hint="Use Python 3.11+",
        )
    )
    try:
        import fastapi  # noqa: F401

        checks["core"].append(_check("FastAPI", "ready", f"v{fastapi.__version__}"))
    except ImportError:
        checks["core"].append(
            _check("FastAPI", "not_configured", "Not installed", fix_hint="pip install -r requirements-api.txt")
        )

    ffmpeg = shutil.which("ffmpeg")
    checks["core"].append(
        _check(
            "FFmpeg",
            "ready" if ffmpeg else "not_configured",
            ffmpeg or "Not found on PATH",
            fix_hint="Install FFmpeg and add to PATH",
        )
    )

    ytdlp = shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if not ytdlp:
        try:
            import yt_dlp  # noqa: F401

            ytdlp = "python module"
        except ImportError:
            ytdlp = None
    checks["core"].append(
        _check(
            "yt-dlp",
            "ready" if ytdlp else "not_configured",
            str(ytdlp or "Not installed"),
            fix_hint="pip install yt-dlp",
        )
    )

    db_path = default_db_path()
    db_ok = db_path.is_file()
    if store is None and db_ok:
        try:
            with DiscoveryStore(db_path) as s:
                store = s
        except Exception:
            db_ok = False
    elif store is not None:
        db_ok = True
    checks["core"].append(
        _check(
            "Discovery database",
            "ready" if db_ok else "not_configured",
            str(db_path),
            fix_hint="Start API once or run discovery ingest to create catalog.sqlite",
        )
    )

    jobs_dir = generation_jobs_dir()
    checks["core"].append(
        _check(
            "Generation jobs path",
            "ready" if jobs_dir.is_dir() else "warning",
            str(jobs_dir),
            fix_hint="Directory is created on first generation job",
        )
    )

    # AI / media
    checks["ai_media"].append(
        _check(
            "Cursor generation workflow",
            "ready" if jobs_dir.is_dir() else "warning",
            "Generation jobs write CURSOR_GENERATION_PROMPT.md handoffs",
        )
    )

    whisper_mode = os.environ.get("DISCOVERY_TRANSCRIPTION_PROVIDER", "mock").strip().lower()
    if whisper_mode == "whisper_local":
        try:
            import whisper  # noqa: F401

            checks["ai_media"].append(_check("Whisper (local)", "ready", "openai-whisper available"))
        except ImportError:
            checks["ai_media"].append(
                _check(
                    "Whisper (local)",
                    "not_configured",
                    "DISCOVERY_TRANSCRIPTION_PROVIDER=whisper_local but package missing",
                    fix_hint="pip install openai-whisper",
                )
            )
    else:
        checks["ai_media"].append(
            _check(
                "Whisper / transcription",
                "warning",
                f"Using '{whisper_mode}' provider (mock OK for dev)",
                fix_hint="Set DISCOVERY_TRANSCRIPTION_PROVIDER=whisper_local for real ASR",
            )
        )

    fpcalc = shutil.which("fpcalc")
    checks["ai_media"].append(
        _check(
            "fpcalc / Chromaprint",
            "ready" if fpcalc else "warning",
            fpcalc or "Optional — audio fingerprint reuse detection degraded",
            fix_hint="Install Chromaprint fpcalc for stronger audio reuse checks",
        )
    )

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    checks["ai_media"].append(
        _check(
            "OpenAI API key",
            "ready" if openai_key else "warning",
            "Configured" if openai_key else "Not set — Creative DNA/concepts need key or prompt export",
            fix_hint="Add OPENAI_API_KEY to scripts/.env",
        )
    )

    # Publishing
    yt_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    yt_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    yt_oauth = "ready" if yt_id and yt_secret else "not_configured"
    checks["publishing"].append(
        _check(
            "YouTube OAuth",
            yt_oauth,
            "Client ID + secret configured" if yt_oauth == "ready" else "Missing YOUTUBE_CLIENT_ID/SECRET",
            fix_hint="Create Google Cloud OAuth app with YouTube upload scope",
        )
    )

    accounts: list[Any] = []
    if store:
        accounts = store.list_publishing_accounts()
    yt_accounts = [a for a in accounts if a.platform == "youtube"]
    if yt_accounts:
        connected = [a for a in yt_accounts if a.auth_status == "connected"]
        checks["publishing"].append(
            _check(
                "YouTube accounts",
                "ready" if connected else "warning",
                f"{len(connected)} connected / {len(yt_accounts)} total",
                fix_hint="Connect via /accounts and complete OAuth",
            )
        )
    else:
        checks["publishing"].append(
            _check(
                "YouTube accounts",
                "not_configured",
                "No YouTube accounts connected",
                fix_hint="Connect your first account on /accounts",
            )
        )

    tt_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    checks["publishing"].append(
        _check(
            "TikTok",
            "ready" if tt_key else "warning",
            "Developer app configured" if tt_key else "Not configured — optional for first pilot",
        )
    )

    meta_id = os.environ.get("META_APP_ID", "").strip()
    checks["publishing"].append(
        _check(
            "Instagram / Meta",
            "ready" if meta_id else "warning",
            "Meta app configured" if meta_id else "Not configured — optional for first pilot",
        )
    )

    # Analytics
    dry = os.environ.get("DISCOVERY_PUBLISH_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    checks["analytics"].append(
        _check(
            "Analytics providers",
            "warning" if dry else "ready",
            "Mock/dry-run mode" if dry else "Live provider mode",
            fix_hint="Unset DISCOVERY_PUBLISH_DRY_RUN for real analytics after publish",
        )
    )

    published_count = 0
    last_refresh = None
    if store:
        jobs = store.list_published_jobs_for_analytics(limit=500)
        published_count = len(jobs)
        snapshots = store.list_latest_post_snapshots(limit=1)
        if snapshots:
            last_refresh = snapshots[0].get("snapshot_at")

    checks["analytics"].append(
        _check(
            "Published posts detected",
            "ready" if published_count else "warning",
            f"{published_count} posts with platform IDs",
        )
    )
    checks["analytics"].append(
        _check(
            "Last analytics refresh",
            "ready" if last_refresh else "warning",
            last_refresh or "Never — run analytics-refresh after first publish",
            fix_hint="python -m discovery.analytics_cli analytics-refresh --force",
        )
    )

    all_checks = [c for group in checks.values() for c in group]
    summary = {
        "ready": sum(1 for c in all_checks if c["status"] == "ready"),
        "warning": sum(1 for c in all_checks if c["status"] == "warning"),
        "not_configured": sum(1 for c in all_checks if c["status"] == "not_configured"),
        "pilot_ready": all(c["status"] != "not_configured" for c in checks["core"]),
    }

    return {"summary": summary, "groups": checks, "project_root": str(project_root())}
