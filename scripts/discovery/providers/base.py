"""Provider protocol for analysis and concept generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when no usable AI provider is configured."""


@dataclass
class ReferenceContext:
    reference_id: int
    platform: str
    external_id: str
    url: str
    title: str
    description: str | None
    channel: str | None
    duration_sec: float | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    published_at: str | None
    source_query: str | None
    virality_score: float | None
    niches: list[dict[str, Any]]
    metrics: dict[str, Any]


class AnalysisProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def analyze_reference(self, context: ReferenceContext) -> dict[str, Any]:
        """Return Creative DNA analysis JSON."""

    def generate_concepts(
        self,
        *,
        context: ReferenceContext,
        analysis: dict[str, Any],
        count: int,
        niche: str | None,
        existing_concepts: list[dict[str, str]],
        performance_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return list of concept dicts."""
