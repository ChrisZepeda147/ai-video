"""Process-local monotonic timing for montage runs (top-level vs child stages)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

TOP_LEVEL_STAGES = frozenset({"prepare_speech", "ensure_broll", "render", "register"})


@dataclass
class MontageRunStats:
    downloads_attempted: int = 0
    downloads_successful: int = 0
    clips_raw: int = 0
    clips_usable: int = 0
    distinct_sources: int = 0
    starting_usable: int = 0
    required_clips: int = 0
    gate_cache_hits: int = 0
    gate_cache_misses: int = 0
    gate_rescan_clips: int = 0
    search_cache_hit: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class MontageTimer:
    def __init__(self) -> None:
        self.slug: str = ""
        self._wall_start: float | None = None
        self._top_level: dict[str, float] = {}
        self._child: dict[str, float] = {}
        self.stats = MontageRunStats()

    def reset(self, *, slug: str = "") -> None:
        self.slug = slug
        self._wall_start = time.perf_counter()
        self._top_level.clear()
        self._child.clear()
        self.stats = MontageRunStats()

    @contextmanager
    def stage_top(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._top_level[name] = self._top_level.get(name, 0.0) + elapsed

    @contextmanager
    def stage_child(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._child[name] = self._child.get(name, 0.0) + elapsed

    def add_child(self, name: str, seconds: float) -> None:
        self._child[name] = self._child.get(name, 0.0) + seconds

    def _prefix(self) -> str:
        return f"slug={self.slug} " if self.slug else ""

    def emit(self) -> None:
        prefix = self._prefix()
        for name in ("prepare_speech", "ensure_broll", "render", "register"):
            if name in self._top_level:
                sec = self._top_level[name]
                print(f"MONTAGE_TIMING {prefix}stage={name} seconds={sec:.1f}")
        for name in sorted(self._child.keys()):
            sec = self._child[name]
            print(f"MONTAGE_TIMING {prefix}child={name} seconds={sec:.1f}")
        st = self.stats
        print(
            f"MONTAGE_TIMING_COUNTS {prefix}"
            f"downloads_attempted={st.downloads_attempted} "
            f"downloads_successful={st.downloads_successful} "
            f"clips_raw={st.clips_raw} "
            f"clips_usable={st.clips_usable} "
            f"starting_usable={st.starting_usable} "
            f"required={st.required_clips} "
            f"distinct_sources={st.distinct_sources} "
            f"gate_cache_hits={st.gate_cache_hits} "
            f"gate_cache_misses={st.gate_cache_misses} "
            f"gate_rescan_clips={st.gate_rescan_clips} "
            f"search_cache_hit={int(st.search_cache_hit)}"
        )
        top_sum = sum(self._top_level.values())
        wall = (
            time.perf_counter() - self._wall_start
            if self._wall_start is not None
            else top_sum
        )
        print(f"MONTAGE_TIMING_TOTAL {prefix}wall_seconds={wall:.1f}")
        print(f"MONTAGE_TIMING_TOP_LEVEL_SUM {prefix}seconds={top_sum:.1f}")


_TIMER = MontageTimer()


def montage_timer() -> MontageTimer:
    return _TIMER
