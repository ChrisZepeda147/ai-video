"""Mock visual provider for tests."""

from __future__ import annotations

from pathlib import Path

from discovery.config import visual_aspect_ratio, visual_image_duration
from discovery.visual_providers.base import GeneratedVisual
from discovery.visual_providers.placeholder import write_placeholder_image


class MockVisualProvider:
    provider_name = "mock"
    model_name = "mock-visual-v1"
    supports_video = False
    supports_image = True

    def __init__(self, *, prompt_suffix: str = "") -> None:
        self.prompt_suffix = prompt_suffix
        self.calls: list[dict] = []

    def generate_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        seed: str | None = None,
    ) -> GeneratedVisual:
        self.calls.append(
            {
                "prompt": prompt,
                "output_path": output_path,
                "width": width,
                "height": height,
                "seed": seed,
            }
        )
        full_prompt = f"{prompt}{self.prompt_suffix}"
        write_placeholder_image(output_path, width=width, height=height, seed=seed or str(output_path))
        return GeneratedVisual(
            local_path=output_path,
            asset_type="image",
            provider=self.provider_name,
            model=self.model_name,
            prompt=full_prompt,
            generation_seed=seed,
            duration_seconds=visual_image_duration(),
            width=width,
            height=height,
            aspect_ratio=visual_aspect_ratio(),
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
        raise NotImplementedError("MockVisualProvider does not generate video")
