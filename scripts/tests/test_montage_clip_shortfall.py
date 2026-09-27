"""Montage clip-count shortfall vs download floor."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_clips_montage import (  # noqa: E402
    MAX_CLIP_SHORTFALL,
    _montage_clip_requirement,
    min_clips_to_render,
)


def test_min_clips_to_render_allows_two_short():
    needed = 27
    assert min_clips_to_render(needed) == needed - MAX_CLIP_SHORTFALL
    ok, budget = _montage_clip_requirement(needed, 26)
    assert ok is True
    assert budget == 1


def test_montage_rejects_large_shortfall():
    ok, budget = _montage_clip_requirement(27, 24)
    assert ok is False
    assert budget == 0


def test_montage_exact_count_no_reuse():
    ok, budget = _montage_clip_requirement(27, 27)
    assert ok is True
    assert budget == 0


if __name__ == "__main__":
    test_min_clips_to_render_allows_two_short()
    test_montage_rejects_large_shortfall()
    test_montage_exact_count_no_reuse()
    print("ok")
