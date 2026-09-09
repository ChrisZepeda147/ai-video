"""Paths and environment for the viral discovery package."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_REFRESH_COOLDOWN_HOURS = 24
DEFAULT_SEARCH_COOLDOWN_HOURS = 12
YOUTUBE_DETAILS_BATCH_SIZE = 50
HIGH_VIRALITY_SCORE = 70
ANALYSIS_VERSION = "1.0"
DEFAULT_MAX_CONCEPTS_PER_REFERENCE = 12
DEFAULT_CONCEPT_SIMILARITY_THRESHOLD = 0.55
DEFAULT_ANALYTICS_EXPLOIT_RATIO = 0.7

# Age-based metadata refresh defaults (hours)
REFRESH_HOURS_VIRAL = 6
REFRESH_HOURS_RECENT = 24
REFRESH_HOURS_STABLE = 72
REFRESH_HOURS_OLD = 168


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def schema_path() -> Path:
    return project_root() / "discovery" / "schema.sql"


def default_niches_path() -> Path:
    return project_root() / "config" / "niches.json"


def discovery_data_dir() -> Path:
    return project_root() / "data" / "discovery"


def default_db_path() -> Path:
    override = os.environ.get("DISCOVERY_DB_PATH", "").strip()
    if override:
        return Path(override)
    return discovery_data_dir() / "catalog.sqlite"


def load_env() -> None:
    """Load scripts/.env without overriding existing environment variables."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def youtube_api_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "").strip()


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def refresh_cooldown_hours() -> float:
    return _float_env("DISCOVERY_REFRESH_COOLDOWN_HOURS", DEFAULT_REFRESH_COOLDOWN_HOURS)


def search_cooldown_hours() -> float:
    return _float_env("DISCOVERY_SEARCH_COOLDOWN_HOURS", DEFAULT_SEARCH_COOLDOWN_HOURS)


def refresh_hours_viral() -> float:
    return _float_env("DISCOVERY_REFRESH_HOURS_VIRAL", REFRESH_HOURS_VIRAL)


def refresh_hours_recent() -> float:
    return _float_env("DISCOVERY_REFRESH_HOURS_RECENT", REFRESH_HOURS_RECENT)


def refresh_hours_stable() -> float:
    return _float_env("DISCOVERY_REFRESH_HOURS_STABLE", REFRESH_HOURS_STABLE)


def refresh_hours_old() -> float:
    return _float_env("DISCOVERY_REFRESH_HOURS_OLD", REFRESH_HOURS_OLD)


def max_concepts_per_reference() -> int:
    raw = os.environ.get("DISCOVERY_MAX_CONCEPTS_PER_REFERENCE", "").strip()
    if not raw:
        return DEFAULT_MAX_CONCEPTS_PER_REFERENCE
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_CONCEPTS_PER_REFERENCE


def concept_similarity_threshold() -> float:
    return _float_env("DISCOVERY_CONCEPT_SIMILARITY_THRESHOLD", DEFAULT_CONCEPT_SIMILARITY_THRESHOLD)


def prompts_dir() -> Path:
    path = discovery_data_dir() / "prompts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generated_assets_root() -> Path:
    path = project_root() / "assets" / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generation_jobs_dir() -> Path:
    path = project_root() / "data" / "generation_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_media_dir() -> Path:
    path = discovery_data_dir() / "source_media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def publishing_data_dir() -> Path:
    path = project_root() / "data" / "publishing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def publishing_credentials_dir() -> Path:
    path = publishing_data_dir() / "credentials"
    path.mkdir(parents=True, exist_ok=True)
    return path


def publishing_oauth_states_dir() -> Path:
    path = publishing_data_dir() / "oauth_states"
    path.mkdir(parents=True, exist_ok=True)
    return path


def publish_dry_run() -> bool:
    return os.environ.get("DISCOVERY_PUBLISH_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}


DEFAULT_VISUAL_BATCH_MAX = 40
DEFAULT_VISUAL_MAX_PER_REFERENCE = 8
DEFAULT_VISUAL_VARIANTS_PER_CONCEPT = 4
DEFAULT_VISUAL_MAX_USAGE = 5
DEFAULT_VISUAL_MIN_WIDTH = 720
DEFAULT_VISUAL_MIN_HEIGHT = 1280
DEFAULT_VISUAL_ASPECT_RATIO = "9:16"
DEFAULT_VISUAL_IMAGE_DURATION = 3.0
DEFAULT_VISUAL_RECENT_DAYS = 7
DEFAULT_VISUAL_PROMPT_DUP_THRESHOLD = 0.85


def visual_batch_max() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_BATCH_MAX", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_BATCH_MAX


def visual_max_per_reference() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_MAX_PER_REFERENCE", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_MAX_PER_REFERENCE


def visual_max_usage() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_MAX_USAGE", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_MAX_USAGE


def visual_min_width() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_MIN_WIDTH", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_MIN_WIDTH


def visual_min_height() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_MIN_HEIGHT", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_MIN_HEIGHT


def visual_aspect_ratio() -> str:
    return os.environ.get("DISCOVERY_VISUAL_ASPECT_RATIO", DEFAULT_VISUAL_ASPECT_RATIO).strip()


def visual_image_duration() -> float:
    return _float_env("DISCOVERY_VISUAL_IMAGE_DURATION", DEFAULT_VISUAL_IMAGE_DURATION)


def visual_recent_exclude_days() -> int:
    raw = os.environ.get("DISCOVERY_VISUAL_RECENT_DAYS", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_VISUAL_RECENT_DAYS


def visual_prompt_dup_threshold() -> float:
    return _float_env("DISCOVERY_VISUAL_PROMPT_DUP_THRESHOLD", DEFAULT_VISUAL_PROMPT_DUP_THRESHOLD)


def analytics_exploit_ratio() -> float:
    """Fraction of concept guidance from proven patterns (rest is experiments)."""
    return min(1.0, max(0.0, _float_env("DISCOVERY_ANALYTICS_EXPLOIT_RATIO", DEFAULT_ANALYTICS_EXPLOIT_RATIO)))
