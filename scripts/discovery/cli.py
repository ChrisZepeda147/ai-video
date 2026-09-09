#!/usr/bin/env python3
"""
CLI for metadata-only viral reference discovery.

REFERENCE VIDEO != PRODUCTION ASSET

Examples:
  python -m discovery.cli ingest youtube --query "creepy story" --limit 25
  python -m discovery.cli discover --all --max-searches 20
  python -m discovery.cli top --niche horror --min-score 70 --limit 25
  python -m discovery.cli stats
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from discovery.config import (
    default_db_path,
    default_niches_path,
    load_env,
    search_cooldown_hours,
)
from discovery.analyze import analyze_reference
from discovery.concepts import generate_concepts_for_reference, select_top_reference_id
from discovery.engine import ingest_youtube_search, run_multi_niche_discovery
from discovery.niches import enabled_niches
from discovery.providers.base import ProviderError
from discovery.providers.factory import build_analysis_provider
from discovery.store import DiscoveryStore
from discovery.visual_batch import run_visual_batch
from discovery.visuals import generate_visual_variants
from discovery.visual_providers.factory import build_visual_provider


def _format_views(value: int | None) -> str:
    if value is None:
        return "?"
    return f"{value:,}"


def _format_age(age_days: float | None, age_hours: float | None) -> str:
    if age_days is not None and age_days >= 1:
        return f"{age_days:.1f}d"
    if age_hours is not None:
        return f"{age_hours:.0f}h"
    return "?"


def cmd_ingest_youtube(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        stats = ingest_youtube_search(
            store,
            query=args.query,
            limit=args.limit,
            shorts_only=args.shorts_only,
            niche=args.niche,
            force_search=args.force,
            search_cooldown_hours_override=args.search_cooldown_hours,
        )
    if stats.searches_skipped:
        print(f"Search skipped (cooldown): {args.query!r}")
        print("Use --force to run anyway.")
        return 0
    print(f"Ingest complete for query: {args.query!r}")
    print(f"  Found:              {stats.ids_found}")
    print(f"  New:                {stats.ids_new}")
    print(f"  Updated:            {stats.ids_updated}")
    print(f"  Existing in DB:     {stats.ids_existing}")
    print(f"  Skipped refresh:    {stats.ids_skipped_refresh}")
    print(f"  Detail requests:    {stats.detail_requests}")
    print(f"  Niche links added:  {stats.niche_links_added}")
    print(f"  Database:           {args.db}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    if not args.all:
        print("Use discover --all (other modes coming later).", file=sys.stderr)
        return 1
    with DiscoveryStore(args.db) as store:
        result = run_multi_niche_discovery(
            store,
            max_searches=args.max_searches,
            per_search_limit=args.limit,
            shorts_only=args.shorts_only,
            force_search=args.force,
            niches_config_path=args.niches,
        )
    print("Multi-niche discovery complete")
    print(f"  Searches executed:        {result.searches_executed}")
    print(f"  Skipped (search cooldown): {result.searches_skipped_cooldown}")
    print(f"  Skipped (global limit):   {result.searches_skipped_limit}")
    print(f"  Skipped (niche cap):      {result.searches_skipped_niche_cap}")
    print(f"  New references:           {result.ids_new}")
    print(f"  Updated references:       {result.ids_updated}")
    print(f"  Existing encountered:     {result.ids_existing}")
    print(f"  Detail requests:          {result.detail_requests}")
    if result.skipped_terms:
        print("\n  Skipped terms:")
        for term in result.skipped_terms[:15]:
            print(f"    - {term}")
        if len(result.skipped_terms) > 15:
            print(f"    ... and {len(result.skipped_terms) - 15} more")
    print(f"\n  Database: {args.db}")
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rows = store.list_top_references(
            niche=args.niche,
            min_score=args.min_score,
            limit=args.limit,
        )
    if not rows:
        print("No references match.")
        return 0
    label = f"niche={args.niche}" if args.niche else "all niches"
    print(f"Top references ({label}, min_score={args.min_score}):\n")
    for i, item in enumerate(rows, 1):
        ref = item.reference
        metrics = item.metrics
        niche_text = ", ".join(
            f"{n.niche}={n.relevance_score:.2f}" for n in item.niches
        ) or "(none)"
        print(
            f"  {i}. [{ref.virality_score:.1f}] {ref.title}"
        )
        print(
            f"     {_format_views(ref.view_count)} views | "
            f"age {_format_age(metrics.get('age_days'), metrics.get('age_hours'))} | "
            f"{metrics.get('views_per_day') or '?'} views/day"
        )
        print(f"     niches: {niche_text}")
        print(f"     {ref.external_id} — {ref.url}")
        print()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        refs = store.list_references(platform=args.platform, limit=args.limit)
    if not refs:
        print("No references in catalog.")
        return 0
    print(f"References ({len(refs)} shown, newest first):\n")
    for ref in refs:
        score = f"{ref.virality_score:.1f}" if ref.virality_score is not None else "?"
        print(
            f"  [{ref.platform}] {ref.external_id}  "
            f"score={score} | {_format_views(ref.view_count)} views"
        )
        print(f"    {ref.title}")
        print(f"    {ref.channel or 'unknown channel'} — {ref.url}")
        if ref.source_query:
            print(f"    query: {ref.source_query}")
        print()
    return 0


def _provider_from_args(args: argparse.Namespace):
    return build_analysis_provider(
        provider=getattr(args, "provider", "auto"),
        model=getattr(args, "model", "gpt-4o-mini"),
        prompt_export=getattr(args, "prompt_export", False),
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        provider = _provider_from_args(args)
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    with DiscoveryStore(args.db) as store:
        analysis = analyze_reference(store, args.reference_id, provider)
    print(f"Creative DNA saved for reference {args.reference_id}")
    print(f"  Analysis id:    {analysis.id}")
    print(f"  Provider:       {analysis.provider} ({analysis.model})")
    print(f"  Version:        {analysis.analysis_version}")
    print(f"  Hook type:      {analysis.hook_type}")
    print(f"  Emotional:      {analysis.emotional_trigger}")
    print(f"  Pacing:         {analysis.pacing_style}")
    print(f"  Setting type:   {analysis.setting_type}")
    return 0


def cmd_concepts(args: argparse.Namespace) -> int:
    try:
        provider = _provider_from_args(args)
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    with DiscoveryStore(args.db) as store:
        reference_id = args.reference_id
        if args.top_reference:
            reference_id = select_top_reference_id(
                store,
                niche=args.niche,
                min_score=args.min_score,
            )
            print(f"Selected top reference id {reference_id} (niche={args.niche}, min_score={args.min_score})")
        if reference_id is None:
            print("Provide --reference-id or --top-reference.", file=sys.stderr)
            return 1
        result = generate_concepts_for_reference(
            store,
            reference_id=reference_id,
            count=args.count,
            provider=provider,
            niche=args.niche,
            ensure_analysis=not args.no_auto_analyze,
        )
    print(f"Concept generation for reference {result.reference_id}")
    print(f"  Analysis id:         {result.analysis_id}")
    print(f"  Requested:           {result.requested}")
    print(f"  Stored:              {result.stored}")
    print(f"  Rejected (similar):  {result.rejected_similar}")
    print(f"  Skipped (exhausted): {result.skipped_exhaustion}")
    for concept in result.concepts:
        print(f"\n  [{concept.id}] {concept.title}")
        print(f"      family: {concept.variation_family}")
        print(f"      hook:   {concept.hook_idea}")
    return 0


def cmd_concepts_list(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        concepts = store.list_concepts(reference_id=args.reference_id, limit=args.limit)
    if not concepts:
        print("No concepts found.")
        return 0
    print(f"Concepts for reference {args.reference_id} ({len(concepts)} shown):\n")
    for concept in concepts:
        print(f"  [{concept.id}] {concept.status} — {concept.title}")
        print(f"      niche:  {concept.niche}")
        print(f"      family: {concept.variation_family}")
        print(f"      hook:   {concept.hook_idea}")
        print(f"      setting:{concept.setting}")
        print()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        stats = store.catalog_stats()
        visual = store.visual_library_stats()
        niches = enabled_niches(args.niches)
    coverage = {item.niche: item.reference_count for item in stats.niche_coverage}

    print("DISCOVERY DATABASE")
    print(f"  Database:                 {args.db}")
    print(f"  Total references:         {stats.total_references}")
    print(f"  References added today:   {stats.references_added_today}")
    print(f"  High-virality references: {stats.high_virality_references} (score >= 70)")
    print(f"  Discovery runs:           {stats.discovery_runs}")
    print(f"  Searches today:           {stats.searches_today}")
    print(f"  Detail requests today:    {stats.detail_requests_today}")
    print(f"  Production assets:        {stats.production_assets}  (must stay 0)")
    print()
    print("EFFICIENCY")
    print(f"  Unique refs per search:   {stats.unique_refs_per_search}")
    print(f"  Duplicate refs seen:      {stats.duplicate_refs_encountered}")
    print()
    print("NICHE COVERAGE")
    for name in sorted(niches.keys()):
        count = coverage.get(name, 0)
        print(f"  {name.capitalize():14} {count}")
    print()
    print("VISUAL LIBRARY")
    print(f"  Generated:                {visual.generated}")
    print(f"  Waiting review:           {visual.waiting_review}")
    print(f"  Approved:                 {visual.approved}")
    print(f"  Rejected:                 {visual.rejected}")
    print(f"  Auto rejected:            {visual.auto_rejected}")
    print(f"  Production assets:        {visual.production_assets}")
    print(f"  Total usable duration:    {visual.total_usable_duration}s")
    print(f"  Average usage count:      {visual.average_usage_count}")
    print()
    print("BY NICHE")
    for name in sorted(niches.keys()):
        count = visual.by_niche.get(name, 0)
        print(f"  {name.capitalize():14} {count}")
    if visual.by_family:
        print()
        print("BY FAMILY")
        for family, count in sorted(visual.by_family.items()):
            print(f"  {family:20} {count}")
    return 0


def cmd_visuals(args: argparse.Namespace) -> int:
    provider = build_visual_provider()
    with DiscoveryStore(args.db) as store:
        assets = generate_visual_variants(
            store,
            concept_id=args.concept_id,
            count=args.count,
            provider=provider,
        )
    print(f"Visual generation for concept {args.concept_id}")
    print(f"  Variants requested: {args.count}")
    print(f"  Assets created:     {len(assets)}")
    for asset in assets:
        print(f"\n  [{asset.id}] v{asset.variant_index} — {asset.status}")
        print(f"      family: {asset.variation_family}")
        print(f"      path:   {asset.local_path}")
        if asset.status == "review":
            print("      -> ready for human review")
        elif asset.status == "auto_rejected":
            print(f"      reason: {asset.reject_reason}")
    return 0


def cmd_visual_batch(args: argparse.Namespace) -> int:
    provider = build_visual_provider()
    with DiscoveryStore(args.db) as store:
        assets = run_visual_batch(
            store,
            niche=args.niche,
            count=args.count,
            variants_per_concept=args.variants_per_concept,
            provider=provider,
        )
    print(f"Visual batch complete (niche={args.niche or 'all'})")
    print(f"  Target assets:   {args.count}")
    print(f"  Assets created:  {len(assets)}")
    review = sum(1 for a in assets if a.status == "review")
    auto_rejected = sum(1 for a in assets if a.status == "auto_rejected")
    print(f"  Waiting review:  {review}")
    print(f"  Auto rejected:   {auto_rejected}")
    return 0


def cmd_visual_review_list(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        assets = store.list_visual_assets_for_review(limit=args.limit)
    if not assets:
        print("No visual assets waiting for review.")
        return 0
    print(f"Visual assets waiting review ({len(assets)} shown):\n")
    for asset in assets:
        print(f"  [{asset.id}] {asset.niche} / {asset.variation_family} — v{asset.variant_index}")
        print(f"      concept: {asset.concept_id}  ref: {asset.reference_id}")
        print(f"      path:    {asset.local_path}")
        print()
    return 0


def cmd_visual_approve(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        approved = store.approve_visual_assets(args.asset_id)
    if not approved:
        print("No assets approved (check ids and status=review).", file=sys.stderr)
        return 1
    print(f"Approved {len(approved)} asset(s): {', '.join(str(i) for i in approved)}")
    print("  production_asset=true for approved generated visuals only")
    return 0


def cmd_visual_reject(args: argparse.Namespace) -> int:
    with DiscoveryStore(args.db) as store:
        rejected = store.reject_visual_assets(args.asset_id)
    if not rejected:
        print("No assets rejected.", file=sys.stderr)
        return 1
    print(f"Rejected {len(rejected)} asset(s): {', '.join(str(i) for i in rejected)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Metadata-only viral reference discovery (never downloads video files).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db_path(),
        help=f"SQLite catalog path (default: {default_db_path()})",
    )
    parser.add_argument(
        "--niches",
        type=Path,
        default=default_niches_path(),
        help=f"Niche config JSON (default: {default_niches_path()})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest references from a platform")
    ingest_sub = ingest.add_subparsers(dest="platform", required=True)

    yt = ingest_sub.add_parser("youtube", help="Ingest YouTube metadata only")
    yt.add_argument("--query", required=True, help="Search query")
    yt.add_argument("--limit", type=int, default=25, help="Max videos per search (default: 25)")
    yt.add_argument("--niche", default=None, help="Primary niche label for this search")
    yt.add_argument(
        "--shorts-only",
        action="store_true",
        help="Focus on Shorts (API: short duration + <=60s filter after metadata)",
    )
    yt.add_argument(
        "--force",
        action="store_true",
        help="Bypass search cooldown for this query",
    )
    yt.add_argument(
        "--search-cooldown-hours",
        type=float,
        default=None,
        help="Override search cooldown hours",
    )
    yt.set_defaults(func=cmd_ingest_youtube)

    discover = sub.add_parser("discover", help="Run multi-niche discovery")
    discover.add_argument(
        "--all",
        action="store_true",
        help="Discover across all enabled niches",
    )
    discover.add_argument(
        "--max-searches",
        type=int,
        default=20,
        help="Global cap on searches for this run (default: 20)",
    )
    discover.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max videos collected per search (default: 15)",
    )
    discover.add_argument("--shorts-only", action="store_true", default=True)
    discover.add_argument("--no-shorts-only", action="store_false", dest="shorts_only")
    discover.add_argument("--force", action="store_true", help="Bypass search cooldowns")
    discover.set_defaults(func=cmd_discover)

    top = sub.add_parser("top", help="Show top references by virality score")
    top.add_argument("--niche", default=None, help="Filter by niche")
    top.add_argument("--min-score", type=float, default=0.0, help="Minimum virality score")
    top.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    top.set_defaults(func=cmd_top)

    listed = sub.add_parser("list", help="List stored references")
    listed.add_argument("--limit", type=int, default=25, help="Max rows to show (default: 25)")
    listed.add_argument("--platform", default=None, help="Filter by platform, e.g. youtube")
    listed.set_defaults(func=cmd_list)

    stats = sub.add_parser("stats", help="Show catalog statistics")
    stats.set_defaults(func=cmd_stats)

    analyze = sub.add_parser("analyze", help="Extract Creative DNA from a reference")
    analyze.add_argument("--reference-id", type=int, required=True)
    analyze.add_argument("--provider", default="auto", choices=("auto", "openai", "prompt_export"))
    analyze.add_argument("--model", default="gpt-4o-mini")
    analyze.add_argument("--prompt-export", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    concepts = sub.add_parser("concepts", help="Generate original concepts from Creative DNA")
    concepts.add_argument("--reference-id", type=int, default=None)
    concepts.add_argument("--top-reference", action="store_true")
    concepts.add_argument("--niche", default=None)
    concepts.add_argument("--min-score", type=float, default=70.0)
    concepts.add_argument("--count", type=int, default=10)
    concepts.add_argument("--provider", default="auto", choices=("auto", "openai", "prompt_export"))
    concepts.add_argument("--model", default="gpt-4o-mini")
    concepts.add_argument("--prompt-export", action="store_true")
    concepts.add_argument(
        "--no-auto-analyze",
        action="store_true",
        help="Require an existing analysis; do not analyze automatically",
    )
    concepts.set_defaults(func=cmd_concepts)

    concepts_list = sub.add_parser("concepts-list", help="List generated concepts")
    concepts_list.add_argument("--reference-id", type=int, required=True)
    concepts_list.add_argument("--limit", type=int, default=50)
    concepts_list.set_defaults(func=cmd_concepts_list)

    visuals = sub.add_parser("visuals", help="Generate visual variants for one concept")
    visuals.add_argument("--concept-id", type=int, required=True)
    visuals.add_argument("--count", type=int, default=4)
    visuals.set_defaults(func=cmd_visuals)

    visual_batch = sub.add_parser("visual-batch", help="Weekly batch visual generation")
    visual_batch.add_argument("--niche", default=None)
    visual_batch.add_argument("--count", type=int, default=40)
    visual_batch.add_argument("--variants-per-concept", type=int, default=1)
    visual_batch.set_defaults(func=cmd_visual_batch)

    visual_review = sub.add_parser("visual-review-list", help="Assets waiting human review")
    visual_review.add_argument("--limit", type=int, default=100)
    visual_review.set_defaults(func=cmd_visual_review_list)

    visual_approve = sub.add_parser("visual-approve", help="Approve generated visual assets")
    visual_approve.add_argument("--asset-id", type=int, nargs="+", required=True)
    visual_approve.set_defaults(func=cmd_visual_approve)

    visual_reject = sub.add_parser("visual-reject", help="Reject generated visual assets")
    visual_reject.add_argument("--asset-id", type=int, nargs="+", required=True)
    visual_reject.set_defaults(func=cmd_visual_reject)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_env()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "limit") and args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if hasattr(args, "max_searches") and args.max_searches is not None and args.max_searches < 1:
        parser.error("--max-searches must be at least 1")
    if hasattr(args, "count") and args.count is not None and args.count < 1:
        parser.error("--count must be at least 1")

    if hasattr(args, "search_cooldown_hours") and args.search_cooldown_hours is None:
        args.search_cooldown_hours = search_cooldown_hours()

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
