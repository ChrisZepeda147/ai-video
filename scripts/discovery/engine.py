"""
Discovery orchestration — metadata-only reference ingestion.

REFERENCE VIDEO != PRODUCTION ASSET
Never downloads MP4s or calls production pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discovery.config import search_cooldown_hours
from discovery.models import DiscoveryRunStats, MultiDiscoverResult, ReferenceVideo
from discovery.niches import (
    NicheConfig,
    assign_niches_for_reference,
    enabled_niches,
    load_niches_config,
    normalize_query,
)
from discovery.scoring import compute_virality_metrics
from discovery.sources.youtube import (
    YOUTUBE_PLATFORM,
    YouTubeClient,
    build_youtube_client,
    is_short_duration,
)
from discovery.store import DiscoveryStore


@dataclass
class IngestOptions:
    query: str
    limit: int = 25
    shorts_only: bool = False
    niche: str | None = None
    force_search: bool = False
    search_cooldown_hours: float | None = None
    parent_run_id: int | None = None
    record_search: bool = True


def _score_and_persist_reference(
    store: DiscoveryStore,
    ref: ReferenceVideo,
    *,
    is_new: bool,
    refreshed: bool,
    niches: dict[str, NicheConfig],
    primary_niche: str | None,
    query: str,
) -> tuple[int, int]:
    metrics = compute_virality_metrics(
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
        published_at=ref.published_at,
    )
    ref.virality_score = metrics.virality_score
    ref_id = store.upsert_reference(ref, is_new=is_new, refreshed=refreshed)
    store.save_metrics_with_snapshots(
        ref_id,
        metrics,
        view_count=ref.view_count,
        like_count=ref.like_count,
        comment_count=ref.comment_count,
    )
    niche_links = 0
    assignments = assign_niches_for_reference(
        niches,
        query=query,
        title=ref.title,
        description=ref.description,
        primary_niche=primary_niche,
    )
    for niche_name, score, source in assignments:
        if store.upsert_niche_link(ref_id, niche_name, score, source):
            niche_links += 1
    return ref_id, niche_links


def ingest_youtube_search(
    store: DiscoveryStore,
    *,
    query: str,
    limit: int,
    shorts_only: bool,
    client: YouTubeClient | None = None,
    niche: str | None = None,
    force_search: bool = False,
    search_cooldown_hours_override: float | None = None,
    parent_run_id: int | None = None,
    record_search: bool = True,
    niches_config_path: Path | None = None,
) -> DiscoveryRunStats:
    """
    Search YouTube, fetch metadata in batches, persist references.

    Never downloads video files.
    """
    opts = IngestOptions(
        query=query,
        limit=limit,
        shorts_only=shorts_only,
        niche=niche,
        force_search=force_search,
        search_cooldown_hours=search_cooldown_hours_override,
        parent_run_id=parent_run_id,
        record_search=record_search,
    )
    return _ingest_search(store, client or build_youtube_client(), opts, niches_config_path)


def _ingest_search(
    store: DiscoveryStore,
    client: YouTubeClient,
    opts: IngestOptions,
    niches_config_path: Path | None,
) -> DiscoveryRunStats:
    stats = DiscoveryRunStats()
    norm_query = normalize_query(opts.query)
    cooldown = (
        opts.search_cooldown_hours
        if opts.search_cooldown_hours is not None
        else search_cooldown_hours()
    )

    if (
        opts.record_search
        and not opts.force_search
        and store.is_search_on_cooldown(
            platform=YOUTUBE_PLATFORM,
            query_normalized=norm_query,
            cooldown_hours=cooldown,
        )
    ):
        stats.searches_skipped = 1
        return stats

    niches = load_niches_config(niches_config_path)
    run_id = opts.parent_run_id
    if run_id is None:
        run_id = store.start_discovery_run(
            platform=YOUTUBE_PLATFORM,
            source_query=opts.query,
            search_limit=opts.limit,
            run_type="search",
            niche=opts.niche,
        )

    stats.searches_executed = 1

    try:
        video_ids = client.search_video_ids(
            query=opts.query,
            limit=opts.limit,
            shorts_only=opts.shorts_only,
        )
        stats.ids_found = len(video_ids)
        existing = store.get_references_map(YOUTUBE_PLATFORM, video_ids)
        stats.ids_existing = len(existing)

        to_fetch: list[str] = []
        skipped_refresh: list[str] = []

        for video_id in video_ids:
            row = existing.get(video_id)
            if row and not store.needs_metadata_refresh(row):
                skipped_refresh.append(video_id)
            else:
                to_fetch.append(video_id)

        stats.ids_skipped_refresh = len(skipped_refresh)
        if skipped_refresh:
            store.touch_last_seen(YOUTUBE_PLATFORM, skipped_refresh)
            store.update_source_query(YOUTUBE_PLATFORM, skipped_refresh, opts.query)

        refs: list[ReferenceVideo] = []
        if to_fetch:
            refs = client.fetch_video_details(to_fetch)
            if type(client).__name__ == "YtDlpClient":
                stats.detail_requests = len(to_fetch)
            else:
                stats.detail_requests = max(1, (len(to_fetch) + 49) // 50)

        for ref in refs:
            ref.source_query = opts.query

        if opts.shorts_only:
            refs = [ref for ref in refs if is_short_duration(ref.duration_sec)]

        existing_ids = set(existing.keys())
        niche_links_total = 0

        for ref in refs:
            is_new = ref.external_id not in existing_ids
            _, links = _score_and_persist_reference(
                store,
                ref,
                is_new=is_new,
                refreshed=True,
                niches=niches,
                primary_niche=opts.niche,
                query=opts.query,
            )
            niche_links_total += links
            if is_new:
                stats.ids_new += 1
                existing_ids.add(ref.external_id)
            else:
                stats.ids_updated += 1

        # Assign niches for skipped-refresh rows without API call
        for video_id in skipped_refresh:
            row = existing[video_id]
            ref = ReferenceVideo(
                platform=row["platform"],
                external_id=row["external_id"],
                url=row["url"],
                title=row["title"],
                description=row["description"],
                source_query=opts.query,
            )
            ref_id = int(row["id"])
            assignments = assign_niches_for_reference(
                niches,
                query=opts.query,
                title=row["title"],
                description=row["description"],
                primary_niche=opts.niche,
            )
            for niche_name, score, source in assignments:
                if store.upsert_niche_link(ref_id, niche_name, score, source):
                    niche_links_total += 1

        stats.niche_links_added = niche_links_total

        if opts.record_search:
            store.record_search(
                platform=YOUTUBE_PLATFORM,
                query_normalized=norm_query,
                niche=opts.niche,
                run_id=run_id,
                results_count=stats.ids_found,
                ids_new=stats.ids_new,
                ids_existing=stats.ids_existing,
            )

        if opts.parent_run_id is None:
            store.finish_discovery_run(run_id, stats=stats, status="ok")
        return stats
    except Exception as exc:
        if opts.parent_run_id is None:
            store.finish_discovery_run(run_id, stats=stats, status="error", error_message=str(exc))
        raise


def run_multi_niche_discovery(
    store: DiscoveryStore,
    *,
    max_searches: int,
    per_search_limit: int = 15,
    shorts_only: bool = True,
    force_search: bool = False,
    niches_config_path: Path | None = None,
    client: YouTubeClient | None = None,
) -> MultiDiscoverResult:
    """
    Run enabled niches with global search cap and search cooldown deduplication.
    """
    niches = enabled_niches(niches_config_path)
    yt = client or build_youtube_client()
    result = MultiDiscoverResult()
    run_id = store.start_discovery_run(
        platform=YOUTUBE_PLATFORM,
        source_query=None,
        search_limit=per_search_limit,
        run_type="multi_niche",
    )
    result.run_id = run_id

    niche_search_counts: dict[str, int] = {name: 0 for name in niches}
    seen_queries: set[str] = set()

    try:
        for niche_name, cfg in niches.items():
            for term in cfg.search_terms:
                if result.searches_executed >= max_searches:
                    result.searches_skipped_limit += 1
                    result.skipped_terms.append(f"{niche_name}:{term} (global limit)")
                    continue
                if niche_search_counts[niche_name] >= cfg.maximum_searches_per_discovery_run:
                    result.searches_skipped_niche_cap += 1
                    result.skipped_terms.append(f"{niche_name}:{term} (niche cap)")
                    continue

                norm = normalize_query(term)
                if norm in seen_queries:
                    result.searches_skipped_cooldown += 1
                    result.skipped_terms.append(f"{niche_name}:{term} (duplicate in run)")
                    continue
                seen_queries.add(norm)

                stats = ingest_youtube_search(
                    store,
                    query=term,
                    limit=per_search_limit,
                    shorts_only=shorts_only,
                    client=yt,
                    niche=niche_name,
                    force_search=force_search,
                    parent_run_id=run_id,
                    record_search=True,
                    niches_config_path=niches_config_path,
                )

                if stats.searches_skipped:
                    result.searches_skipped_cooldown += 1
                    result.skipped_terms.append(f"{niche_name}:{term} (search cooldown)")
                    continue

                result.searches_executed += 1
                niche_search_counts[niche_name] += 1
                result.ids_new += stats.ids_new
                result.ids_updated += stats.ids_updated
                result.ids_existing += stats.ids_existing
                result.detail_requests += stats.detail_requests

        aggregate = DiscoveryRunStats(
            ids_found=result.ids_new + result.ids_updated + result.ids_existing,
            ids_new=result.ids_new,
            ids_updated=result.ids_updated,
            ids_existing=result.ids_existing,
            detail_requests=result.detail_requests,
            searches_executed=result.searches_executed,
            searches_skipped=(
                result.searches_skipped_cooldown
                + result.searches_skipped_limit
                + result.searches_skipped_niche_cap
            ),
        )
        store.finish_discovery_run(run_id, stats=aggregate, status="ok")
        return result
    except Exception as exc:
        aggregate = DiscoveryRunStats(
            searches_executed=result.searches_executed,
            searches_skipped=result.searches_skipped_cooldown,
        )
        store.finish_discovery_run(run_id, stats=aggregate, status="error", error_message=str(exc))
        raise
