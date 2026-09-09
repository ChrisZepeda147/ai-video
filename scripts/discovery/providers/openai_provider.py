"""OpenAI-backed Creative DNA and concept generation."""

from __future__ import annotations

import json
import os
from typing import Any

from discovery.providers.base import ReferenceContext


class OpenAIAnalysisProvider:
    def __init__(self, *, model: str = "gpt-4o-mini") -> None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def _chat_json(self, system: str, user: str) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.85,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def analyze_reference(self, context: ReferenceContext) -> dict[str, Any]:
        prompt = f"""Analyze this viral short-form video REFERENCE for Creative DNA.

IMPORTANT RULES:
- You only have metadata text (title, description, stats, niches). You did NOT watch the video.
- Split output into observed facts vs inferred creative patterns.
- Mark every visual/camera/lighting claim as inferred unless directly stated in title/description.
- Do not claim specific shots, dialogue, or scenes you cannot verify from text metadata.
- Goal: commercially useful inspiration, not copying the original.

Reference metadata:
{json.dumps(context.__dict__, indent=2)}

Return JSON:
{{
  "observed": {{
    "title": "...",
    "description_summary": "...",
    "format_signals_from_text": ["..."],
    "engagement_context": "..."
  }},
  "inferred": {{
    "genre": "...",
    "hook_type": "...",
    "emotional_trigger": "...",
    "pacing_style": "...",
    "tension_structure": "...",
    "story_structure": "...",
    "setting_type": "...",
    "visual_mood": "...",
    "visual_energy": "...",
    "camera_style": "...",
    "lighting_style": "...",
    "subject_type": "...",
    "ending_style": "...",
    "retention_hypothesis": "..."
  }},
  "transferable_patterns": ["pattern 1", "pattern 2"],
  "avoid_copying": ["exact dialogue", "exact plot", "..."]
}}
"""
        return self._chat_json(
            "You extract Creative DNA from viral video metadata for original content planning.",
            prompt,
        )

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
        performance_block = ""
        if performance_context:
            performance_block = f"""
Optional internal performance guidance (advisory only — do NOT clone prior videos):
{performance_context}
"""
        prompt = f"""Generate {count} ORIGINAL short-form video concepts inspired by Creative DNA.

Preserve viral mechanics (hook logic, pacing feel, tension structure, emotional trigger, format).
Change expressive details (setting, subject, events, imagery, ending, props, characters).

Do NOT copy exact story, dialogue, names, creator identity, logos, or recognizable IP.
Each concept must use a DISTINCT variation_family (e.g. foggy mountain road, empty parking garage).

Target niche: {niche or "general"}
{performance_block}
Reference title: {context.title}
Creative DNA analysis:
{json.dumps(analysis, indent=2)}

Existing concepts to avoid repeating:
{json.dumps(existing_concepts, indent=2)}

Return JSON:
{{
  "concepts": [
    {{
      "title": "...",
      "niche": "{niche or "horror"}",
      "hook_idea": "...",
      "visual_premise": "...",
      "setting": "...",
      "subject": "...",
      "camera_movement": "...",
      "mood": "...",
      "story_premise": "...",
      "variation_family": "...",
      "originality_notes": "what changed vs reference"
    }}
  ]
}}
"""
        data = self._chat_json(
            "You create original short-form concepts from viral Creative DNA without copying.",
            prompt,
        )
        concepts = data.get("concepts") or []
        if not isinstance(concepts, list):
            raise ValueError("Provider returned invalid concepts payload")
        return concepts
