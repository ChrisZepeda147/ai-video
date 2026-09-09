"""Prompt-export provider — writes brief + placeholder image (always available)."""

from __future__ import annotations

import json
from pathlib import Path

from discovery.config import visual_aspect_ratio, visual_image_duration
from discovery.visual_providers.base import GeneratedVisual
from discovery.visual_providers.placeholder import write_placeholder_image


class PromptExportProvider:
    provider_name = "prompt-export"
    model_name = "prompt-export-v1"
    supports_video = False
    supports_image = True

    def generate_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        seed: str | None = None,
        brief: dict | None = None,
    ) -> GeneratedVisual:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_placeholder_image(output_path, width=width, height=height, seed=seed)
        sidecar = output_path.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt": prompt,
                    "seed": seed,
                    "brief": brief or {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        prompt_path = output_path.with_suffix(".prompt.txt")
        prompt_path.write_text(prompt, encoding="utf-8")
        return GeneratedVisual(
            local_path=output_path,
            asset_type="image",
            provider=self.provider_name,
            model=self.model_name,
            prompt=prompt,
            generation_seed=seed,
            duration_seconds=visual_image_duration(),
            width=width,
            height=height,
            aspect_ratio=visual_aspect_ratio(),
            metadata={"sidecar": str(sidecar), "prompt_file": str(prompt_path)},
        )

    def generate_video(
        self,
        *,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        duration_seconds: float,
        seed: str | None = None,
    ) -> GeneratedVisual:
        raise NotImplementedError("PromptExportProvider does not generate video yet")
