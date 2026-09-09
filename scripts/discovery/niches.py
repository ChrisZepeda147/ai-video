"""Niche configuration loading and keyword-based relevance scoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from discovery.config import default_niches_path

WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass
class NicheConfig:
    name: str
    enabled: bool = True
    search_terms: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    maximum_searches_per_discovery_run: int = 3


def normalize_query(query: str) -> str:
    return " ".join(WORD_RE.findall(query.lower()))


def load_niches_config(path: Path | None = None) -> dict[str, NicheConfig]:
    config_path = path or default_niches_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"Niche config not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    niches: dict[str, NicheConfig] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        niches[name] = NicheConfig(
            name=name,
            enabled=bool(item.get("enabled", True)),
            search_terms=[str(x) for x in item.get("search_terms") or []],
            keywords=[str(x).lower() for x in item.get("keywords") or []],
            negative_keywords=[str(x).lower() for x in item.get("negative_keywords") or []],
            maximum_searches_per_discovery_run=int(
                item.get("maximum_searches_per_discovery_run") or 3
            ),
        )
    return niches


def enabled_niches(path: Path | None = None) -> dict[str, NicheConfig]:
    return {name: cfg for name, cfg in load_niches_config(path).items() if cfg.enabled}


def _text_blob(*parts: str | None) -> str:
    return " ".join(p.lower() for p in parts if p)


def score_niche_relevance(
    niche: NicheConfig,
    *,
    query: str | None,
    title: str | None,
    description: str | None,
) -> float:
    """
    Keyword/query relevance in 0–1 range. No AI — rules only.
    """
    blob = _text_blob(title, description, query)
    norm_query = normalize_query(query or "")

    score = 0.0

    for term in niche.search_terms:
        if normalize_query(term) == norm_query:
            score = max(score, 0.95)
        elif normalize_query(term) in norm_query or norm_query in normalize_query(term):
            score = max(score, 0.88)

    if niche.name in blob or niche.name in norm_query:
        score = max(score, 0.82)

    keyword_hits = sum(1 for kw in niche.keywords if kw in blob)
    if keyword_hits:
        score = max(score, min(0.55 + keyword_hits * 0.08, 0.90))

    negative_hits = sum(1 for nkw in niche.negative_keywords if nkw in blob)
    if negative_hits:
        score *= max(0.2, 1.0 - negative_hits * 0.35)

    return round(min(1.0, max(0.0, score)), 3)


def assign_niches_for_reference(
    niches: dict[str, NicheConfig],
    *,
    query: str | None,
    title: str | None,
    description: str | None,
    primary_niche: str | None = None,
    min_score: float = 0.5,
) -> list[tuple[str, float, str]]:
    """
    Return list of (niche_name, relevance_score, assignment_source).
    A reference may match multiple niches.
    """
    results: list[tuple[str, float, str]] = []
    for name, cfg in niches.items():
        if not cfg.enabled:
            continue
        score = score_niche_relevance(cfg, query=query, title=title, description=description)
        if primary_niche and name == primary_niche and score < 0.85:
            score = max(score, 0.90)
        if score >= min_score:
            source = "search_term" if primary_niche == name else "keyword_rules"
            results.append((name, score, source))
    results.sort(key=lambda item: item[1], reverse=True)
    return results
