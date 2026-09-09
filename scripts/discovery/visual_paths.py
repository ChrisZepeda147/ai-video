"""Filesystem layout for generated visual assets."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from discovery.config import generated_assets_root

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    slug = SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or "untitled"


def iso_week_folder(when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def asset_output_dir(
    *,
    niche: str,
    variation_family: str,
    when: datetime | None = None,
) -> Path:
    root = generated_assets_root()
    path = root / iso_week_folder(when) / slugify(niche) / slugify(variation_family)
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_filename(*, concept_id: int, variant_index: int, asset_type: str) -> str:
    ext = "mp4" if asset_type == "video" else "png"
    return f"concept{concept_id:04d}_v{variant_index:02d}.{ext}"
