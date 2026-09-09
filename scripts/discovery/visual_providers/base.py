"""Visual generation provider protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class GeneratedVisual:
    local_path: Path
    asset_type: str
    provider: str
    model: str
    prompt: str
    generation_seed: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    metadata: dict[str, Any] | None = None


class VisualGenerationProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def supports_video(self) -> bool: ...

    @property
    def supports_image(self) -> bool: ...

    def generate_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        seed: str | None = None,
    ) -> GeneratedVisual: ...

    def generate_video(
        self,
        *,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        duration_seconds: float,
        seed: str | None = None,
    ) -> GeneratedVisual: ...
