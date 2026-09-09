"""Concept → visual brief → generated asset orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from discovery.config import (
    visual_aspect_ratio,
    visual_image_duration,
    visual_min_height,
    visual_min_width,
)
from discovery.models import VisualAsset
from discovery.visual_paths import asset_filename, asset_output_dir
from discovery.visual_providers.base import VisualGenerationProvider
from discovery.visual_quality import run_quality_checks
from discovery.visual_providers.prompt_export import PromptExportProvider


NEGATIVE_CONSTRAINTS = [
    "no recognizable copyrighted characters",
    "no logos or brand marks",
    "no watermarks",
    "no exact recreation of the reference video",
    "no readable brand names",
    "no recognizable creator likeness",
    "avoid obvious AI artifacts where possible",
    "original production asset only — not scraped footage",
]

VARIANT_MODIFIERS: list[dict[str, str]] = [
    {
        "weather": "cold rain on windshield",
        "vehicle": "sedan interior POV",
        "lighting": "headlight beams cutting through fog",
        "camera_movement": "slow forward drift",
    },
    {
        "weather": "heavy snow on mountain pass",
        "vehicle": "SUV dashboard POV",
        "lighting": "dim blue twilight and taillights ahead",
        "camera_movement": "subtle handheld sway",
    },
    {
        "weather": "dense fog between pine trees",
        "vehicle": "none — empty forest road",
        "lighting": "single distant streetlamp glow",
        "camera_movement": "locked wide shot with slow push-in",
    },
    {
        "weather": "mist over cliffside switchbacks",
        "vehicle": "distant car lights only",
        "lighting": "moonlit rim light on road edge",
        "camera_movement": "slow pan following the curve",
    },
    {
        "weather": "drizzle and wet asphalt reflections",
        "vehicle": "parked car side mirror POV",
        "lighting": "neon spill from off-screen signs",
        "camera_movement": "static with shallow depth of field",
    },
    {
        "weather": "pre-dawn haze",
        "vehicle": "motorcycle helmet visor POV",
        "lighting": "warm sunrise breaking through fog banks",
        "camera_movement": "forward tracking at road level",
    },
]


@dataclass
class VisualBrief:
    scene: str
    subject: str
    environment: str
    camera_angle: str
    camera_movement: str
    lighting: str
    mood: str
    color_direction: str
    visual_energy: str
    composition: str
    duration: float
    aspect_ratio: str
    negative_constraints: list[str] = field(default_factory=list)
    niche: str = ""
    variation_family: str = ""
    concept_id: int | None = None
    reference_id: int | None = None
    variant_index: int = 1
    variant_label: str = ""

    def to_prompt(self) -> str:
        lines = [
            f"Scene: {self.scene}",
            f"Subject: {self.subject}",
            f"Environment: {self.environment}",
            f"Camera angle: {self.camera_angle}",
            f"Camera movement: {self.camera_movement}",
            f"Lighting: {self.lighting}",
            f"Mood: {self.mood}",
            f"Color direction: {self.color_direction}",
            f"Visual energy: {self.visual_energy}",
            f"Composition: {self.composition}",
            f"Duration: {self.duration}s",
            f"Aspect ratio: {self.aspect_ratio}",
            "Constraints: " + "; ".join(self.negative_constraints),
        ]
        if self.variant_label:
            lines.insert(1, f"Variant: {self.variant_label}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _analysis_to_dict(analysis: Any) -> dict[str, Any] | None:
    if analysis is None:
        return None
    if isinstance(analysis, dict):
        return analysis
    payload: dict[str, Any] = {}
    if getattr(analysis, "analysis_json", None):
        payload.update(analysis.analysis_json or {})
    payload.setdefault("visual_mechanic", getattr(analysis, "transferable_patterns", None))
    payload.setdefault("mood", getattr(analysis, "visual_mood", None))
    payload.setdefault("pacing", getattr(analysis, "pacing_style", None) or getattr(analysis, "visual_energy", None))
    payload.setdefault("color_palette", getattr(analysis, "lighting_style", None))
    payload.setdefault("hook_mechanic", getattr(analysis, "hook_type", None))
    return payload


def _parse_dna(dna_json: str | None) -> dict[str, Any]:
    if not dna_json:
        return {}
    try:
        return json.loads(dna_json)
    except json.JSONDecodeError:
        return {}


def _pick_modifier(variant_index: int) -> dict[str, str]:
    idx = (variant_index - 1) % len(VARIANT_MODIFIERS)
    return VARIANT_MODIFIERS[idx]


def concept_to_visual_brief(
    concept: dict[str, Any],
    *,
    analysis: dict[str, Any] | None = None,
    variant_index: int = 1,
) -> VisualBrief:
    """Convert an approved/generated concept into a visual generation brief."""
    dna = _parse_dna((analysis or {}).get("dna_json"))
    hook = concept.get("hook") or concept.get("title") or "isolated tension"
    title = concept.get("title") or hook
    niche = concept.get("niche") or ""
    family = concept.get("variation_family") or "general"
    modifier = _pick_modifier(variant_index)

    visual_mechanic = dna.get("visual_mechanic") or dna.get("hook_mechanic") or hook
    mood = dna.get("mood") or "dread and isolation"
    pacing = dna.get("pacing") or "slow escalation"
    color = dna.get("color_palette") or "desaturated charcoal with cold blue accents"

    scene = f"{family.replace('-', ' ')} — {title}"
    subject = visual_mechanic
    environment = f"{modifier['weather']}; {family.replace('-', ' ')} setting; {niche} niche tone"
    camera_angle = "vertical 9:16 cinematic framing, subject in lower third"
    camera_movement = modifier["camera_movement"]
    lighting = modifier["lighting"]
    visual_energy = pacing
    composition = "strong foreground depth, negative space for text overlay safe zone"

    variant_label = (
        f"v{variant_index}: {modifier['weather']}, {modifier['vehicle']}, {modifier['lighting']}"
    )

    return VisualBrief(
        scene=scene,
        subject=subject,
        environment=environment,
        camera_angle=camera_angle,
        camera_movement=camera_movement,
        lighting=lighting,
        mood=mood,
        color_direction=color,
        visual_energy=visual_energy,
        composition=composition,
        duration=visual_image_duration(),
        aspect_ratio=visual_aspect_ratio(),
        negative_constraints=list(NEGATIVE_CONSTRAINTS),
        niche=niche,
        variation_family=family,
        concept_id=concept.get("id"),
        reference_id=concept.get("reference_id"),
        variant_index=variant_index,
        variant_label=variant_label,
    )


def _seed_for(concept_id: int, variant_index: int) -> str:
    raw = f"{concept_id}:{variant_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def generate_visual_variants(
    store,
    *,
    concept_id: int,
    count: int,
    provider: VisualGenerationProvider | None = None,
) -> list[VisualAsset]:
    """Generate multiple visual variants for one concept."""
    concept = store.get_concept(concept_id)
    if not concept:
        raise ValueError(f"Concept {concept_id} not found")

    analysis_row = store.get_latest_analysis(concept["reference_id"])
    analysis_dict = _analysis_to_dict(analysis_row)
    provider = provider or PromptExportProvider()
    width = visual_min_width()
    height = visual_min_height()
    now = datetime.now(timezone.utc)
    results: list[VisualAsset] = []

    for variant_index in range(1, count + 1):
        brief = concept_to_visual_brief(
            concept, analysis=analysis_dict, variant_index=variant_index
        )
        prompt = brief.to_prompt()
        out_dir = asset_output_dir(
            niche=brief.niche or "general",
            variation_family=brief.variation_family or "general",
            when=now,
        )
        filename = asset_filename(
            concept_id=concept_id,
            variant_index=variant_index,
            asset_type="image",
        )
        output_path = out_dir / filename
        seed = _seed_for(concept_id, variant_index)

        asset_id = store.create_visual_asset(
            concept_id=concept_id,
            reference_id=concept["reference_id"],
            niche=brief.niche,
            variation_family=brief.variation_family,
            asset_type="image",
            provider=provider.provider_name,
            model=provider.model_name,
            prompt=prompt,
            brief_json=json.dumps(brief.to_dict()),
            generation_seed=seed,
            local_path=str(output_path),
            variant_index=variant_index,
            status="generating",
        )

        store.update_visual_asset_status(asset_id, "generating")

        if isinstance(provider, PromptExportProvider):
            generated = provider.generate_image(
                prompt=prompt,
                output_path=output_path,
                width=width,
                height=height,
                seed=seed,
                brief=brief.to_dict(),
            )
        else:
            generated = provider.generate_image(
                prompt=prompt,
                output_path=output_path,
                width=width,
                height=height,
                seed=seed,
            )

        store.update_visual_asset_after_generation(
            asset_id,
            local_path=str(generated.local_path),
            duration_seconds=generated.duration_seconds,
            width=generated.width,
            height=generated.height,
            aspect_ratio=generated.aspect_ratio or visual_aspect_ratio(),
            generated_at=now.isoformat(),
            status="generated",
        )

        asset_row = store.get_visual_asset_dict(asset_id)
        qc = run_quality_checks(store, asset_row or {})
        if qc.passed:
            store.update_visual_asset_status(asset_id, "review")
        else:
            store.update_visual_asset_status(
                asset_id, "auto_rejected", reject_reason=qc.reason
            )

        final = store.get_visual_asset(asset_id)
        if final:
            results.append(final)

    return results
