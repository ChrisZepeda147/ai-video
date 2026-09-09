"""Automated quality checks before human review."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from discovery.config import (
    generated_assets_root,
    visual_aspect_ratio,
    visual_image_duration,
    visual_min_height,
    visual_min_width,
    visual_prompt_dup_threshold,
)
import content_reuse


@dataclass
class QualityResult:
    passed: bool
    reason: str = ""


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_aspect_ratio(value: str) -> float | None:
    m = re.match(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$", value.strip())
    if not m:
        return None
    w, h = float(m.group(1)), float(m.group(2))
    return w / h if h else None


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def _expected_aspect() -> float | None:
    return _parse_aspect_ratio(visual_aspect_ratio())


def _aspect_ok(width: int, height: int, expected: str | None) -> bool:
    if not expected:
        return True
    target = _parse_aspect_ratio(expected)
    if not target or height == 0:
        return True
    actual = width / height
    return abs(actual - target) <= 0.08


def _path_under_generated(path: Path) -> bool:
    root = generated_assets_root().resolve()
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def run_quality_checks(store, asset: dict) -> QualityResult:
    """Run basic checks; does not use AI vision."""
    local_path = asset.get("local_path")
    if not local_path:
        return QualityResult(False, "missing local_path")

    path = Path(local_path)
    if not path.exists():
        return QualityResult(False, "file does not exist")
    if not path.is_file():
        return QualityResult(False, "local_path is not a file")
    if path.stat().st_size == 0:
        return QualityResult(False, "zero-byte file")

    try:
        with path.open("rb") as f:
            f.read(64)
    except OSError as exc:
        return QualityResult(False, f"file not readable: {exc}")

    if not _path_under_generated(path):
        return QualityResult(False, "path outside assets/generated/")

    asset_type = asset.get("asset_type") or "image"
    width = asset.get("width")
    height = asset.get("height")

    if asset_type == "image":
        dims = _image_dimensions(path)
        if dims:
            width, height = dims
        if width and height:
            if width < visual_min_width() or height < visual_min_height():
                return QualityResult(
                    False,
                    f"resolution too low ({width}x{height})",
                )
            if not _aspect_ok(width, height, asset.get("aspect_ratio") or visual_aspect_ratio()):
                return QualityResult(False, "aspect ratio mismatch")

    duration = asset.get("duration_seconds")
    if asset_type == "video":
        if duration is None or duration <= 0:
            return QualityResult(False, "invalid video duration")
    elif duration is None:
        duration = visual_image_duration()

    sha = _file_sha256(path)
    dup = store.find_visual_asset_by_sha(sha, exclude_id=asset.get("id"))
    if dup:
        return QualityResult(False, f"duplicate file hash (asset {dup})")

    store.update_visual_asset_sha(asset.get("id"), sha)

    prompt = (asset.get("prompt") or "").strip()
    if prompt:
        for other in store.list_visual_assets(limit=500):
            if other.get("id") == asset.get("id"):
                continue
            if (
                asset.get("concept_id") is not None
                and other.get("concept_id") == asset.get("concept_id")
            ):
                continue
            if other.get("status") in {"auto_rejected", "rejected"}:
                continue
            other_prompt = (other.get("prompt") or "").strip()
            if not other_prompt:
                continue
            sim = content_reuse.jaccard(
                content_reuse.tokens(prompt), content_reuse.tokens(other_prompt)
            )
            if sim >= visual_prompt_dup_threshold():
                return QualityResult(
                    False,
                    f"near-duplicate prompt (similarity {sim:.2f}, asset {other.get('id')})",
                )

    return QualityResult(True)
