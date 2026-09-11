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

    from discovery.config import publishing_oauth_redirect_uri, publishing_owner
    from discovery.publishing.setup import publishing_env_status, publishing_account_matrix, TARGET_ACCOUNTS_PER_OWNER

    env_status = publishing_env_status()
    redirect = env_status["oauth_redirect_uri"]
    checks["publishing"].append(
        _check(
            "OAuth redirect URI",
            "ready",
            redirect,
            fix_hint="Register this exact URL in Google, TikTok, and Meta developer consoles",
        )
    )
    if env_status["mock_provider"]:
        checks["publishing"].append(
            _check(
                "Live OAuth providers",
                "not_configured",
                "DISCOVERY_PUBLISH_PROVIDER=mock",
                fix_hint="Remove or unset DISCOVERY_PUBLISH_PROVIDER for real account connect",
            )
        )
    else:
        checks["publishing"].append(
            _check(
                "Live OAuth providers",
                "ready",
                "Real platform APIs enabled",
            )
        )
    checks["publishing"].append(
        _check(
            "Machine owner",
            "ready",
            publishing_owner(),
            fix_hint="Set PUBLISHING_OWNER=stephen or chris in scripts/.env on each PC",
        )
    )
    internal_key = env_status["internal_key_configured"]
    checks["publishing"].append(
        _check(
            "Videos Link post key",
            "ready" if internal_key else "warning",
            "AI_VIDEO_INTERNAL_KEY set" if internal_key else "Missing — Link post on Videos will fail",
            fix_hint="Set AI_VIDEO_INTERNAL_KEY in scripts/.env and NEXT_PUBLIC_AI_VIDEO_INTERNAL_KEY in web/.env.local",
        )
    )

    for platform, info in env_status["platforms"].items():
        status: CheckStatus = "ready" if info["env_ready"] else "not_configured"
        checks["publishing"].append(
            _check(
                f"{info['label']} app credentials",
                status,
                "Configured in scripts/.env" if info["env_ready"] else f"Missing {', '.join(info['env_keys'])}",
                fix_hint=f"Create developer app — {info['portal_url']}",
            )
        )

    matrix = publishing_account_matrix(store) if store else {}
    for owner in ("stephen", "chris"):
        owner_connected = 0
        owner_target = 0
        for platform in ("youtube", "tiktok", "instagram", "facebook"):
            counts = matrix.get(owner, {}).get(platform, {})
            owner_connected += int(counts.get("connected") or 0)
            owner_target += int(counts.get("target") or TARGET_ACCOUNTS_PER_OWNER)
        ratio_status: CheckStatus = (
            "ready" if owner_connected >= owner_target else "warning" if owner_connected else "not_configured"
        )
        checks["publishing"].append(
            _check(
                f"{owner.title()} connected accounts",
                ratio_status,
                f"{owner_connected}/{owner_target} ({TARGET_ACCOUNTS_PER_OWNER} per platform)",
                fix_hint=f"/accounts → {owner} tab → connect each channel twice where needed",
            )
        )

    # Analytics
    dry = env_status["dry_run"]
    checks["analytics"].append(
        _check(
            "Analytics providers",
            "warning" if dry or env_status["mock_provider"] else "ready",
            "Mock/dry-run mode"
            if dry or env_status["mock_provider"]
            else "Live provider mode",
            fix_hint="Unset DISCOVERY_PUBLISH_PROVIDER and DISCOVERY_PUBLISH_DRY_RUN for real analytics",
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
