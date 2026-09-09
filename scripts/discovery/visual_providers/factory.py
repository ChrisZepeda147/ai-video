"""Build visual generation provider from environment."""

from __future__ import annotations

import os

from discovery.visual_providers.base import VisualGenerationProvider
from discovery.visual_providers.prompt_export import PromptExportProvider


def build_visual_provider() -> VisualGenerationProvider:
    name = os.environ.get("DISCOVERY_VISUAL_PROVIDER", "prompt-export").strip().lower()
    if name in {"prompt-export", "prompt_export", "export"}:
        return PromptExportProvider()
    # Future: openai, runway, replicate, etc.
    return PromptExportProvider()
