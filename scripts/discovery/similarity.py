"""Text similarity helpers for concept deduplication."""

from __future__ import annotations

import sys
from pathlib import Path

# Reuse tokenization from production catalog without importing discovery into content_reuse.
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_reuse  # noqa: E402


def concept_text_blob(
    *,
    title: str = "",
    hook_idea: str = "",
    visual_premise: str = "",
    setting: str = "",
    subject: str = "",
    story_premise: str = "",
    variation_family: str = "",
) -> str:
    return " ".join(
        part
        for part in (title, hook_idea, visual_premise, setting, subject, story_premise, variation_family)
        if part
    )


def concept_tokens(**fields: str) -> set[str]:
    return content_reuse.tokens(concept_text_blob(**fields))


def concept_similarity(left: dict[str, str], right: dict[str, str]) -> float:
    return content_reuse.jaccard(concept_tokens(**left), concept_tokens(**right))


def is_too_similar(
    candidate: dict[str, str],
    existing: list[dict[str, str]],
    *,
    threshold: float,
) -> bool:
    for row in existing:
        if concept_similarity(candidate, row) >= threshold:
            return True
    return False
