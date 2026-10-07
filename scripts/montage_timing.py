"""Lightweight stage timing for production montage runs."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class MontageRunStats:
    downloads_attempted: int = 0
    downloads_successful: int = 0
    clips_raw: int = 0
    clips_usable: int = 0
    distinct_sources: int = 0
    gate_cache_hits: int = 0
    gate_cache_misses: int = 0
    gate_rescan_clips: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class MontageTimer:
    def __init__(self) -> None:
        self._stages: dict[str, float] = {}
        self.stats = MontageRunStats()

    def reset(self) -> None:
        self._stages.clear()
        self.stats = MontageRunStats()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._stages[name] = self._stages.get(name, 0.0) + elapsed

    def add_stage(self, name: str, seconds: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + seconds

    def emit(self) -> None:
        for name in sorted(self._stages.keys()):
            sec = self._stages[name]
            print(f"MONTAGE_TIMING stage={name} seconds={sec:.1f}")
        st = self.stats
        print(
            "MONTAGE_TIMING_COUNTS "
            f"downloads_attempted={st.downloads_attempted} "
            f"downloads_successful={st.downloads_successful} "
            f"clips_raw={st.clips_raw} "
            f"clips_usable={st.clips_usable} "
            f"distinct_sources={st.distinct_sources} "
            f"gate_cache_hits={st.gate_cache_hits} "
            f"gate_cache_misses={st.gate_cache_misses} "
            f"gate_rescan_clips={st.gate_rescan_clips}"
        )
        total = sum(self._stages.values())
        print(f"MONTAGE_TIMING stage=total seconds={total:.1f}")


_TIMER = MontageTimer()


def montage_timer() -> MontageTimer:
    return _TIMER
