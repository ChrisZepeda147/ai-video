"""Global reuse detection — reference seen vs actually used in our content."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import content_reuse  # noqa: E402


def normalize_transcript(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def transcript_hash(text: str) -> str:
    normalized = normalize_transcript(text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def audio_fingerprint(local_path: str | None) -> str:
    """Lightweight fingerprint when full chromaprint is unavailable."""
    if not local_path:
        return ""
    path = Path(local_path)
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(65536))
    return digest.hexdigest()


def chromaprint_fingerprint(local_path: str | None) -> str:
    """Chromaprint via fpcalc when available; empty string on missing tool."""
    if not local_path:
        return ""
    path = Path(local_path)
    if not path.is_file():
        return ""
    import shutil
    import subprocess

    if not shutil.which("fpcalc"):
        return ""
    try:
        result = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        payload = json.loads(result.stdout)
        fp = payload.get("fingerprint")
        return str(fp) if fp else ""
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return ""


@dataclass
class PriorUse:
    kind: str
    id: str
    title: str
    account: str = ""
    path: str = ""
    score: float = 1.0


@dataclass
class ReuseReport:
    seen_as_reference: bool = False
    actually_used_in_content: bool = False
    reuse_confidence: float = 0.0
    prior_uses: list[PriorUse] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seen_as_reference": self.seen_as_reference,
            "actually_used_in_content": self.actually_used_in_content,
            "reuse_confidence": round(self.reuse_confidence, 1),
            "prior_uses": [
                {
                    "kind": p.kind,
                    "id": p.id,
                    "title": p.title,
                    "account": p.account,
                    "path": p.path,
                    "score": round(p.score, 3),
                }
                for p in self.prior_uses
            ],
            "explanations": self.explanations,
        }


def _catalog_hits(
    *,
    platform: str | None,
    external_id: str | None,
    transcript: str | None,
    local_audio_path: str | None,
) -> list[PriorUse]:
    hits: list[PriorUse] = []
    catalog = content_reuse.current_catalog()

    if external_id:
        for video in catalog.videos:
            vid = video.get("youtube_id") or video.get("id") or ""
            if vid and vid == external_id:
                hits.append(
                    PriorUse(
                        kind="video",
                        id=str(vid),
                        title=video.get("title") or video.get("path") or vid,
                        account=video.get("account") or "",
                        path=video.get("path") or "",
                        score=1.0,
                    )
                )

    norm = normalize_transcript(transcript or "")
    t_hash = transcript_hash(transcript or "")
    if norm:
        for story in catalog.stories:
            story_text = " ".join(
                part
                for part in (
                    story.get("title") or "",
                    story.get("hook") or "",
                    story.get("text") or "",
                )
                if part
            )
            if not story_text:
                continue
            sim = content_reuse.jaccard(
                content_reuse.tokens(norm),
                content_reuse.tokens(story_text),
            )
            if sim >= 0.45:
                hits.append(
                    PriorUse(
                        kind="story",
                        id=story.get("id") or story.get("path") or "story",
                        title=story.get("title") or story.get("path") or "story",
                        path=story.get("path") or "",
                        score=sim,
                    )
                )
            story_hash = transcript_hash(story_text)
            if t_hash and story_hash and t_hash == story_hash:
                hits.append(
                    PriorUse(
                        kind="story",
                        id=story.get("id") or story.get("path") or "story",
                        title=story.get("title") or "Exact transcript match",
                        path=story.get("path") or "",
                        score=1.0,
                    )
                )

    fp = chromaprint_fingerprint(local_audio_path) or audio_fingerprint(local_audio_path)
    if fp:
        for video in catalog.videos:
            if video.get("file_hash") == fp or video.get("audio_fingerprint") == fp:
                hits.append(
                    PriorUse(
                        kind="video",
                        id=video.get("youtube_id") or video.get("path") or "video",
                        title=video.get("title") or video.get("path") or "video",
                        account=video.get("account") or "",
                        path=video.get("path") or "",
                        score=0.95,
                    )
                )

    if platform and external_id:
        pass  # platform id handled above via youtube_id

    return hits


def check_global_reuse(
    store,
    *,
    platform: str | None = None,
    external_id: str | None = None,
    transcript: str | None = None,
    local_audio_path: str | None = None,
    reference_id: int | None = None,
) -> ReuseReport:
    """Check whether content was seen as reference and/or used in our videos."""
    report = ReuseReport()
    explanations: list[str] = []

    if reference_id is not None:
        ref = store.get_reference_by_id(reference_id)
        if ref:
            report.seen_as_reference = True
            explanations.append(f"Linked to reference #{reference_id}: {ref.title}")

    if platform and external_id:
        existing_ref_id = store.get_reference_id(platform, external_id)
        if existing_ref_id:
            report.seen_as_reference = True
            explanations.append(f"Platform ID {platform}:{external_id} already in reference catalog")

    rows = store.list_source_media_by_external(platform, external_id) if platform and external_id else []
    for row in rows:
        if row.actually_used_in_content:
            report.actually_used_in_content = True
            explanations.append(f"Source media #{row.id} marked used in our content")

    t_hash = transcript_hash(transcript or "")
    if t_hash:
        for row in store.list_source_media_by_transcript_hash(t_hash):
            if row.actually_used_in_content:
                report.actually_used_in_content = True
                explanations.append(f"Transcript hash match with used source #{row.id}")
            elif row.external_id and row.external_id != external_id:
                report.prior_uses.append(
                    PriorUse(
                        kind="source_media",
                        id=str(row.id),
                        title=row.title,
                        path=row.local_path or "",
                        score=1.0,
                    )
                )
                explanations.append(
                    f"Same transcript hash on different source #{row.id} ({row.external_id})"
                )

    norm = normalize_transcript(transcript or "")
    if len(norm) >= 24:
        for row in store.list_source_media_with_transcript(exclude_id=None, limit=200):
            if external_id and row.external_id == external_id:
                continue
            if not row.transcript:
                continue
            sim = content_reuse.jaccard(
                content_reuse.tokens(norm),
                content_reuse.tokens(normalize_transcript(row.transcript)),
            )
            if sim >= 0.55:
                report.prior_uses.append(
                    PriorUse(
                        kind="source_media",
                        id=str(row.id),
                        title=row.title,
                        path=row.local_path or "",
                        score=sim,
                    )
                )
                channel_note = f" on {row.external_id}" if row.external_id else ""
                explanations.append(
                    f"Fuzzy transcript match ({sim:.0%}) with source #{row.id}{channel_note}"
                )
                if row.actually_used_in_content:
                    report.actually_used_in_content = True

    fp = chromaprint_fingerprint(local_audio_path) or audio_fingerprint(local_audio_path)
    if fp:
        for row in store.list_source_media_with_transcript(limit=200):
            if row.audio_fingerprint and row.audio_fingerprint == fp:
                if row.external_id != external_id:
                    report.prior_uses.append(
                        PriorUse(
                            kind="source_media",
                            id=str(row.id),
                            title=row.title,
                            path=row.local_path or "",
                            score=0.95,
                        )
                    )
                    explanations.append(
                        f"Audio fingerprint match with source #{row.id} (possibly re-uploaded audio)"
                    )
                if row.actually_used_in_content:
                    report.actually_used_in_content = True

    catalog_hits = _catalog_hits(
        platform=platform,
        external_id=external_id,
        transcript=transcript,
        local_audio_path=local_audio_path,
    )
    if catalog_hits:
        report.actually_used_in_content = True
        for hit in catalog_hits:
            report.prior_uses.append(hit)
            explanations.append(
                f"Previously used in {hit.kind} '{hit.title}' (score {hit.score:.0%})"
            )

    if report.actually_used_in_content and report.prior_uses:
        report.reuse_confidence = min(
            100.0,
            max(h.score for h in report.prior_uses) * 100,
        )
    elif report.actually_used_in_content:
        report.reuse_confidence = 85.0
    elif report.seen_as_reference:
        report.reuse_confidence = 15.0
        explanations.append("Seen as reference only — not confirmed used in finished content")
    else:
        report.reuse_confidence = 0.0
        explanations.append("No prior use detected in catalog")

    report.explanations = explanations
    return report


def reuse_explanations_json(report: ReuseReport) -> str:
    return json.dumps(report.to_dict())
