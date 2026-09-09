"""Quick Workbench — natural language find/create wrappers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from discovery.analytics.workbench_context import enrich_workbench_query
from discovery.generation_jobs import create_generation_job
from discovery.reuse_detection import check_global_reuse
from discovery.risk_scoring import score_source_media
from discovery.source_media import create_source_media


STOPWORDS = {
    "a", "an", "the", "that", "we", "have", "not", "used", "before", "find", "about",
    "create", "make", "images", "image", "video", "videos", "clips", "clip", "and",
    "or", "unused", "never", "get", "rich", "advice", "breakup", "motivational", "audio",
}


@dataclass
class SourceCandidate:
    reference_id: int | None = None
    title: str = ""
    url: str = ""
    platform: str = "youtube"
    external_id: str = ""
    transcript_snippet: str = ""
    duration_sec: float | None = None
    virality_score: float | None = None
    reuse_confidence: float = 0.0
    rights_confidence: float = 50.0
    monetization_confidence: float = 50.0
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    explanations: list[str] = field(default_factory=list)


def _extract_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9']+", query.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


def find_source_candidates(store, query: str, *, limit: int = 10, niche: str | None = None) -> list[SourceCandidate]:
    """Search reference catalog and score reuse/risk for workbench Find Source."""
    enriched_query, _meta = enrich_workbench_query(store, query, niche=niche)
    keywords = _extract_keywords(enriched_query)
    search = " ".join(keywords) if keywords else enriched_query
    rows = store.list_dashboard_references(search=search, limit=limit * 3)

    candidates: list[SourceCandidate] = []
    for row in rows:
        ref = row if isinstance(row, dict) else row.__dict__
        ref_id = ref.get("id") or ref.get("reference_id")
        if not ref_id:
            continue
        title = ref.get("title") or ""
        description = ref.get("description") or ""
        transcript = f"{title}. {description}"[:2000]
        reuse = check_global_reuse(
            store,
            platform=ref.get("platform") or "youtube",
            external_id=ref.get("external_id"),
            transcript=transcript,
            reference_id=int(ref_id),
        )
        risk = score_source_media(
            source_mode="audio" if "audio" in query.lower() else "video",
            media_type="audio" if "audio" in query.lower() else "video",
            platform=ref.get("platform"),
            has_transcript=bool(description),
            reuse_report=reuse,
        )

        if "unused" in query.lower() or "never used" in query.lower():
            if reuse.actually_used_in_content and reuse.reuse_confidence >= 50:
                continue

        candidates.append(
            SourceCandidate(
                reference_id=int(ref_id),
                title=title,
                url=ref.get("url") or "",
                platform=ref.get("platform") or "youtube",
                external_id=ref.get("external_id") or "",
                transcript_snippet=transcript[:400],
                duration_sec=ref.get("duration_sec"),
                virality_score=ref.get("virality_score"),
                reuse_confidence=reuse.reuse_confidence,
                rights_confidence=risk.rights_confidence,
                monetization_confidence=risk.monetization_confidence,
                seen_as_reference=reuse.seen_as_reference,
                actually_used_in_content=reuse.actually_used_in_content,
                explanations=reuse.explanations,
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def _parse_counts_from_query(query: str) -> tuple[int, int]:
    image_count = 0
    video_count = 0
    img_match = re.search(r"(\d+)\s*(?:beautiful|realistic|creepy|luxury|nighttime|moving)?\s*(?:ai\s*)?(?:images?|stills?)", query, re.I)
    vid_match = re.search(r"(\d+)\s*(?:moving\s*)?(?:ai\s*)?(?:video|videos|clips?)", query, re.I)
    if img_match:
        image_count = int(img_match.group(1))
    if vid_match:
        video_count = int(vid_match.group(1))
    if image_count == 0 and video_count == 0:
        image_count = 6
    return image_count, video_count


def _parse_style(query: str) -> str:
    q = query.lower()
    if "luxury" in q or "supercar" in q or "mansion" in q:
        return "luxury"
    if "creepy" in q or "horror" in q or "scary" in q:
        return "horror"
    if "relationship" in q or "breakup" in q or "lonely" in q:
        return "relationship"
    if "motivat" in q or "discipline" in q or "grind" in q:
        return "motivation"
    return "cinematic"


def create_freeform_job(store, query: str, *, image_count: int | None = None, video_count: int | None = None, style: str | None = None):
    parsed_images, parsed_videos = _parse_counts_from_query(query)
    images = image_count if image_count is not None else parsed_images
    videos = video_count if video_count is not None else parsed_videos
    resolved_style = style or _parse_style(query)
    return create_generation_job(
        store,
        origin_type="freeform",
        prompt_summary=query.strip(),
        image_count=images,
        video_count=videos,
        style=resolved_style,
    )


def workbench_create_from_candidate(
    store,
    candidate: SourceCandidate,
    *,
    source_mode: str = "audio",
    image_count: int = 0,
    video_count: int = 0,
):
    source_result = create_source_media(
        store,
        title=candidate.title,
        source_mode=source_mode,
        reference_id=candidate.reference_id,
        platform=candidate.platform,
        external_id=candidate.external_id,
        url=candidate.url,
        transcript=candidate.transcript_snippet,
        duration_sec=candidate.duration_sec,
    )
    job_result = None
    if image_count or video_count:
        job_result = create_generation_job(
            store,
            origin_type="source_media",
            prompt_summary=candidate.title,
            image_count=image_count,
            video_count=video_count,
            source_media_id=source_result.source.id,
            reference_id=candidate.reference_id,
        )
    return {"source": source_result, "job": job_result}
