"""Build analysis providers based on environment and flags."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from discovery.config import discovery_data_dir
from discovery.providers.base import AnalysisProvider, ProviderError, ReferenceContext
from discovery.providers.openai_provider import OpenAIAnalysisProvider


class PromptExportProvider:
    """Writes LLM prompts to disk when no API key is available."""

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or (discovery_data_dir() / "prompts")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def provider_name(self) -> str:
        return "prompt_export"

    @property
    def model_name(self) -> str:
        return "manual"

    def _write_prompt(self, kind: str, reference_id: int, payload: dict[str, Any]) -> None:
        path = self.output_dir / f"{kind}_ref{reference_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        raise ProviderError(
            f"No AI provider configured. Wrote {kind} prompt to {path}. "
            "Set OPENAI_API_KEY or use --provider openai after adding a key."
        )

    def analyze_reference(self, context: ReferenceContext) -> dict[str, Any]:
        self._write_prompt("analyze", context.reference_id, {"context": context.__dict__})
        return {}

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
        self._write_prompt(
            "concepts",
            context.reference_id,
            {
                "context": context.__dict__,
                "analysis": analysis,
                "count": count,
                "niche": niche,
                "existing_concepts": existing_concepts,
                "performance_context": performance_context,
            },
        )
        return []


def build_analysis_provider(
    *,
    provider: str = "auto",
    model: str = "gpt-4o-mini",
    prompt_export: bool = False,
) -> AnalysisProvider:
    if provider == "prompt_export" or prompt_export:
        return PromptExportProvider()
    if provider == "openai":
        return OpenAIAnalysisProvider(model=model)
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY", "").strip():
            return OpenAIAnalysisProvider(model=model)
        raise ProviderError(
            "No AI provider available. Set OPENAI_API_KEY in scripts/.env "
            "or pass --prompt-export to write manual prompt files."
        )
    raise ProviderError(f"Unknown provider: {provider}")
