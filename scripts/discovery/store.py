"""SQLite persistence for reference videos and discovery runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from discovery.config import HIGH_VIRALITY_SCORE, schema_path
from discovery.config import visual_max_usage
from discovery.models import (
    AnalyticsPostFeatures,
    AnalyticsPostSnapshot,
    CatalogStats,
    Concept,
    DiscoveryRunStats,
    GenerationJob,
    PerformanceProfile,
    PilotBatch,
    PilotBatchItem,
    ProductionProject,
    PublishingAccount,
    PublishingJob,
    NicheCoverage,
    NicheLink,
    ReferenceAnalysis,
    ReferenceVideo,
    SourceMedia,
    SourceSegment,
    TopReference,
    VisualAsset,
    VisualLibraryStats,
    row_to_analysis,
    row_to_analytics_post_features,
    row_to_analytics_post_snapshot,
    row_to_concept,
    row_to_generation_job,
    row_to_performance_profile,
    row_to_pilot_batch,
    row_to_pilot_batch_item,
    row_to_production_project,
    row_to_publishing_account,
    row_to_publishing_job,
    row_to_reference,
    row_to_source_media,
    row_to_visual_asset,
)
from discovery.scoring import ViralityMetrics, age_hours_since_published


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_start_iso() -> str:
    today = datetime.now(timezone.utc).date()
    return datetime(today.year, today.month, today.day, tzinfo=timezone.utc).isoformat()


class DiscoveryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs sync routes in a thread pool — allow cross-thread use of this connection.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DiscoveryStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def init_schema(self) -> None:
        schema = schema_path()
        if not schema.is_file():
            raise FileNotFoundError(f"Schema not found: {schema}")
        self._conn.executescript(schema.read_text(encoding="utf-8"))
        self._apply_migrations()
        self._conn.commit()

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _apply_migrations(self) -> None:
        migrations = [
            ("reference_videos", "last_refreshed_at", "TEXT"),
            ("reference_videos", "virality_score", "REAL"),
            ("discovery_runs", "run_type", "TEXT NOT NULL DEFAULT 'search'"),
            ("discovery_runs", "niche", "TEXT"),
            ("discovery_runs", "searches_executed", "INTEGER NOT NULL DEFAULT 0"),
            ("discovery_runs", "searches_skipped", "INTEGER NOT NULL DEFAULT 0"),
            ("discovery_runs", "detail_requests", "INTEGER NOT NULL DEFAULT 0"),
            ("discovery_runs", "ids_existing", "INTEGER NOT NULL DEFAULT 0"),
            ("reference_videos", "concepts_generated", "INTEGER NOT NULL DEFAULT 0"),
            ("reference_videos", "concepts_approved", "INTEGER NOT NULL DEFAULT 0"),
            ("reference_videos", "last_concept_generated_at", "TEXT"),
            ("reference_videos", "exhausted", "INTEGER NOT NULL DEFAULT 0"),
            ("reference_videos", "max_concepts", "INTEGER"),
        ]
        for table, column, col_type in migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        visual_migrations = [
            ("visual_assets", "generation_job_id", "INTEGER"),
            ("visual_assets", "source_media_id", "INTEGER"),
        ]
        for table, column, col_type in visual_migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        source_migrations = [
            ("source_media", "download_status", "TEXT"),
            ("source_media", "download_path", "TEXT"),
            ("source_media", "raw_local_path", "TEXT"),
            ("source_media", "transcript_json", "TEXT"),
            ("source_media", "audio_fingerprint", "TEXT"),
            ("source_segments", "transcript_json", "TEXT"),
            ("source_segments", "clip_status", "TEXT"),
        ]
        for table, column, col_type in source_migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        production_migrations = [
            ("production_projects", "origin_type", "TEXT DEFAULT 'reference'"),
            ("production_projects", "reference_id", "INTEGER"),
        ]
        for table, column, col_type in production_migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        publishing_migrations = [
            ("publishing_accounts", "owner", "TEXT NOT NULL DEFAULT 'chris'"),
        ]
        for table, column, col_type in publishing_migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        command_migrations = [
            ("cursor_command_jobs", "error_summary", "TEXT"),
        ]
        for table, column, col_type in command_migrations:
            if not self._column_exists(table, column):
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

        self._migrate_visual_assets_nullable()

    def _migrate_visual_assets_nullable(self) -> None:
        """Recreate visual_assets when concept_id/reference_id are still NOT NULL."""
        row = self._conn.execute(
            "SELECT \"notnull\" FROM pragma_table_info('visual_assets') WHERE name = 'concept_id'"
        ).fetchone()
        if not row or int(row["notnull"]) == 0:
            return
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS visual_assets_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id INTEGER,
                reference_id INTEGER,
                generation_job_id INTEGER,
                source_media_id INTEGER,
                niche TEXT,
                variation_family TEXT,
                asset_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT,
                prompt TEXT NOT NULL,
                brief_json TEXT,
                generation_seed TEXT,
                local_path TEXT,
                file_sha256 TEXT,
                duration_seconds REAL,
                width INTEGER,
                height INTEGER,
                aspect_ratio TEXT,
                variant_index INTEGER NOT NULL DEFAULT 1,
                generated_at TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                approved_at TEXT,
                usage_count INTEGER NOT NULL DEFAULT 0,
                max_usage INTEGER,
                last_used_at TEXT,
                production_asset INTEGER NOT NULL DEFAULT 0,
                reject_reason TEXT
            );
            INSERT INTO visual_assets_new (
                id, concept_id, reference_id, generation_job_id, source_media_id,
                niche, variation_family, asset_type, provider, model, prompt,
                brief_json, generation_seed, local_path, file_sha256,
                duration_seconds, width, height, aspect_ratio, variant_index,
                generated_at, status, approved_at, usage_count, max_usage,
                last_used_at, production_asset, reject_reason
            )
            SELECT
                id, concept_id, reference_id, generation_job_id, source_media_id,
                niche, variation_family, asset_type, provider, model, prompt,
                brief_json, generation_seed, local_path, file_sha256,
                duration_seconds, width, height, aspect_ratio, variant_index,
                generated_at, status, approved_at, usage_count, max_usage,
                last_used_at, production_asset, reject_reason
            FROM visual_assets;
            DROP TABLE visual_assets;
            ALTER TABLE visual_assets_new RENAME TO visual_assets;
            CREATE INDEX IF NOT EXISTS idx_visual_assets_concept
                ON visual_assets (concept_id, variant_index);
            CREATE INDEX IF NOT EXISTS idx_visual_assets_status
                ON visual_assets (status, niche);
            CREATE INDEX IF NOT EXISTS idx_visual_assets_reference
                ON visual_assets (reference_id, status);
            CREATE INDEX IF NOT EXISTS idx_visual_assets_family
                ON visual_assets (variation_family, status);
            CREATE INDEX IF NOT EXISTS idx_visual_assets_sha
                ON visual_assets (file_sha256);
            """
        )

    def get_reference(self, platform: str, external_id: str) -> ReferenceVideo | None:
        row = self._conn.execute(
            """
            SELECT rv.*, rm.virality_score AS metrics_score
            FROM reference_videos rv
            LEFT JOIN reference_metrics rm ON rm.reference_id = rv.id
            WHERE rv.platform = ? AND rv.external_id = ?
            """,
            (platform, external_id),
        ).fetchone()
        if not row:
            return None
        ref = row_to_reference(row)
        if row["metrics_score"] is not None:
            ref.virality_score = float(row["metrics_score"])
        return ref

    def get_reference_id(self, platform: str, external_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM reference_videos WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        ).fetchone()
        return int(row["id"]) if row else None

    def get_references_map(
        self, platform: str, external_ids: list[str]
    ) -> dict[str, sqlite3.Row]:
        if not external_ids:
            return {}
        placeholders = ",".join("?" for _ in external_ids)
        rows = self._conn.execute(
            f"""
            SELECT * FROM reference_videos
            WHERE platform = ? AND external_id IN ({placeholders})
            """,
            [platform, *external_ids],
        ).fetchall()
        return {row["external_id"]: row for row in rows}

    def needs_refresh(self, last_refreshed_at: str | None, *, cooldown_hours: float) -> bool:
        if cooldown_hours <= 0 or not last_refreshed_at:
            return True
        try:
            seen = datetime.fromisoformat(last_refreshed_at)
        except ValueError:
            return True
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - seen >= timedelta(hours=cooldown_hours)

    def metadata_refresh_hours_for_row(self, row: sqlite3.Row) -> float:
        from discovery.refresh import metadata_refresh_hours

        age = age_hours_since_published(row["published_at"])
        return metadata_refresh_hours(age_hours=age)

    def needs_metadata_refresh(self, row: sqlite3.Row) -> bool:
        last = row["last_refreshed_at"] if "last_refreshed_at" in row.keys() else None
        if not last:
            last = row["discovered_at"]
        cooldown = self.metadata_refresh_hours_for_row(row)
        return self.needs_refresh(last, cooldown_hours=cooldown)

    def update_source_query(self, platform: str, external_ids: list[str], source_query: str) -> int:
        if not external_ids:
            return 0
        placeholders = ",".join("?" for _ in external_ids)
        cursor = self._conn.execute(
            f"""
            UPDATE reference_videos
            SET source_query = ?
            WHERE platform = ? AND external_id IN ({placeholders})
            """,
            [source_query, platform, *external_ids],
        )
        self._conn.commit()
        return cursor.rowcount

    def touch_last_seen(self, platform: str, external_ids: list[str], *, when: str | None = None) -> int:
        if not external_ids:
            return 0
        ts = when or now_iso()
        placeholders = ",".join("?" for _ in external_ids)
        cursor = self._conn.execute(
            f"""
            UPDATE reference_videos
            SET last_seen_at = ?
            WHERE platform = ? AND external_id IN ({placeholders})
            """,
            [ts, platform, *external_ids],
        )
        self._conn.commit()
        return cursor.rowcount

    def upsert_reference(
        self,
        ref: ReferenceVideo,
        *,
        is_new: bool,
        refreshed: bool = False,
    ) -> int:
        if ref.production_asset:
            raise ValueError("Reference videos must never be marked as production assets")
        ts = now_iso()
        if is_new:
            cursor = self._conn.execute(
                """
                INSERT INTO reference_videos (
                    platform, external_id, url, title, channel, channel_id, description,
                    duration_sec, view_count, like_count, comment_count, published_at,
                    discovered_at, last_seen_at, last_refreshed_at, thumbnail_url,
                    source_query, production_asset, virality_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    ref.platform,
                    ref.external_id,
                    ref.url,
                    ref.title,
                    ref.channel,
                    ref.channel_id,
                    ref.description,
                    ref.duration_sec,
                    ref.view_count,
                    ref.like_count,
                    ref.comment_count,
                    ref.published_at,
                    ts,
                    ts,
                    ts if refreshed else None,
                    ref.thumbnail_url,
                    ref.source_query,
                    ref.virality_score,
                ),
            )
            ref_id = int(cursor.lastrowid)
        else:
            self._conn.execute(
                """
                UPDATE reference_videos SET
                    url = ?,
                    title = ?,
                    channel = ?,
                    channel_id = ?,
                    description = ?,
                    duration_sec = ?,
                    view_count = ?,
                    like_count = ?,
                    comment_count = ?,
                    published_at = ?,
                    last_seen_at = ?,
                    last_refreshed_at = CASE WHEN ? THEN ? ELSE last_refreshed_at END,
                    thumbnail_url = ?,
                    source_query = COALESCE(?, source_query),
                    virality_score = COALESCE(?, virality_score),
                    production_asset = 0
                WHERE platform = ? AND external_id = ?
                """,
                (
                    ref.url,
                    ref.title,
                    ref.channel,
                    ref.channel_id,
                    ref.description,
                    ref.duration_sec,
                    ref.view_count,
                    ref.like_count,
                    ref.comment_count,
                    ref.published_at,
                    ts,
                    refreshed,
                    ts if refreshed else None,
                    ref.thumbnail_url,
                    ref.source_query,
                    ref.virality_score,
                    ref.platform,
                    ref.external_id,
                ),
            )
            ref_id = self.get_reference_id(ref.platform, ref.external_id)
            if ref_id is None:
                raise RuntimeError(f"Missing reference after update: {ref.external_id}")
        self._conn.commit()
        ref.id = ref_id
        return ref_id

    def save_metrics(self, reference_id: int, metrics: ViralityMetrics) -> None:
        ts = now_iso()
        self._conn.execute(
            """
            INSERT INTO reference_metrics (
                reference_id, virality_score, age_hours, age_days, views_per_day,
                views_per_hour, like_ratio, comment_ratio, velocity_component,
                recency_component, engagement_component, view_count_snapshot,
                like_count_snapshot, comment_count_snapshot, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
                virality_score = excluded.virality_score,
                age_hours = excluded.age_hours,
                age_days = excluded.age_days,
                views_per_day = excluded.views_per_day,
                views_per_hour = excluded.views_per_hour,
                like_ratio = excluded.like_ratio,
                comment_ratio = excluded.comment_ratio,
                velocity_component = excluded.velocity_component,
                recency_component = excluded.recency_component,
                engagement_component = excluded.engagement_component,
                view_count_snapshot = excluded.view_count_snapshot,
                like_count_snapshot = excluded.like_count_snapshot,
                comment_count_snapshot = excluded.comment_count_snapshot,
                scored_at = excluded.scored_at
            """,
            (
                reference_id,
                metrics.virality_score,
                metrics.age_hours,
                metrics.age_days,
                metrics.views_per_day,
                metrics.views_per_hour,
                metrics.like_ratio,
                metrics.comment_ratio,
                metrics.velocity_component,
                metrics.recency_component,
                metrics.engagement_component,
                None,
                None,
                None,
                ts,
            ),
        )
        self._conn.execute(
            "UPDATE reference_videos SET virality_score = ? WHERE id = ?",
            (metrics.virality_score, reference_id),
        )
        self._conn.commit()

    def save_metrics_with_snapshots(
        self,
        reference_id: int,
        metrics: ViralityMetrics,
        *,
        view_count: int | None,
        like_count: int | None,
        comment_count: int | None,
    ) -> None:
        ts = now_iso()
        self._conn.execute(
            """
            INSERT INTO reference_metrics (
                reference_id, virality_score, age_hours, age_days, views_per_day,
                views_per_hour, like_ratio, comment_ratio, velocity_component,
                recency_component, engagement_component, view_count_snapshot,
                like_count_snapshot, comment_count_snapshot, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reference_id) DO UPDATE SET
                virality_score = excluded.virality_score,
                age_hours = excluded.age_hours,
                age_days = excluded.age_days,
                views_per_day = excluded.views_per_day,
                views_per_hour = excluded.views_per_hour,
                like_ratio = excluded.like_ratio,
                comment_ratio = excluded.comment_ratio,
                velocity_component = excluded.velocity_component,
                recency_component = excluded.recency_component,
                engagement_component = excluded.engagement_component,
                view_count_snapshot = excluded.view_count_snapshot,
                like_count_snapshot = excluded.like_count_snapshot,
                comment_count_snapshot = excluded.comment_count_snapshot,
                scored_at = excluded.scored_at
            """,
            (
                reference_id,
                metrics.virality_score,
                metrics.age_hours,
                metrics.age_days,
                metrics.views_per_day,
                metrics.views_per_hour,
                metrics.like_ratio,
                metrics.comment_ratio,
                metrics.velocity_component,
                metrics.recency_component,
                metrics.engagement_component,
                view_count,
                like_count,
                comment_count,
                ts,
            ),
        )
        self._conn.execute(
            "UPDATE reference_videos SET virality_score = ? WHERE id = ?",
            (metrics.virality_score, reference_id),
        )
        self._conn.commit()

    def upsert_niche_link(
        self,
        reference_id: int,
        niche: str,
        relevance_score: float,
        assignment_source: str,
    ) -> bool:
        """Insert or update niche link. Returns True if this was a new link."""
        existing = self._conn.execute(
            "SELECT relevance_score FROM reference_niches WHERE reference_id = ? AND niche = ?",
            (reference_id, niche),
        ).fetchone()
        ts = now_iso()
        if existing:
            new_score = max(float(existing["relevance_score"]), relevance_score)
            self._conn.execute(
                """
                UPDATE reference_niches
                SET relevance_score = ?, assigned_at = ?, assignment_source = ?
                WHERE reference_id = ? AND niche = ?
                """,
                (new_score, ts, assignment_source, reference_id, niche),
            )
            self._conn.commit()
            return False
        self._conn.execute(
            """
            INSERT INTO reference_niches (
                reference_id, niche, relevance_score, assigned_at, assignment_source
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (reference_id, niche, relevance_score, ts, assignment_source),
        )
        self._conn.commit()
        return True

    def get_niches_for_reference(self, reference_id: int) -> list[NicheLink]:
        rows = self._conn.execute(
            """
            SELECT niche, relevance_score, assignment_source
            FROM reference_niches
            WHERE reference_id = ?
            ORDER BY relevance_score DESC
            """,
            (reference_id,),
        ).fetchall()
        return [
            NicheLink(
                niche=row["niche"],
                relevance_score=float(row["relevance_score"]),
                assignment_source=row["assignment_source"],
            )
            for row in rows
        ]

    def is_search_on_cooldown(
        self,
        *,
        platform: str,
        query_normalized: str,
        cooldown_hours: float,
    ) -> bool:
        if cooldown_hours <= 0:
            return False
        row = self._conn.execute(
            """
            SELECT searched_at FROM search_history
            WHERE platform = ? AND query_normalized = ?
            ORDER BY searched_at DESC
            LIMIT 1
            """,
            (platform, query_normalized),
        ).fetchone()
        if not row:
            return False
        return not self.needs_refresh(row["searched_at"], cooldown_hours=cooldown_hours)

    def record_search(
        self,
        *,
        platform: str,
        query_normalized: str,
        niche: str | None,
        run_id: int | None,
        results_count: int,
        ids_new: int,
        ids_existing: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO search_history (
                platform, query_normalized, niche, searched_at, run_id,
                results_count, ids_new, ids_existing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                query_normalized,
                niche,
                now_iso(),
                run_id,
                results_count,
                ids_new,
                ids_existing,
            ),
        )
        self._conn.commit()

    def start_discovery_run(
        self,
        *,
        platform: str,
        source_query: str | None,
        search_limit: int,
        run_type: str = "search",
        niche: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO discovery_runs (
                started_at, platform, source_query, search_limit, status, run_type, niche
            ) VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            (now_iso(), platform, source_query, search_limit, run_type, niche),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def finish_discovery_run(
        self,
        run_id: int,
        *,
        stats: DiscoveryRunStats,
        status: str = "ok",
        error_message: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE discovery_runs SET
                finished_at = ?,
                ids_found = ?,
                ids_new = ?,
                ids_updated = ?,
                ids_skipped_cooldown = ?,
                ids_existing = ?,
                detail_requests = ?,
                searches_executed = ?,
                searches_skipped = ?,
                status = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                stats.ids_found,
                stats.ids_new,
                stats.ids_updated,
                stats.ids_skipped_refresh,
                stats.ids_existing,
                stats.detail_requests,
                stats.searches_executed,
                stats.searches_skipped,
                status,
                error_message,
                run_id,
            ),
        )
        self._conn.commit()

    def list_references(
        self,
        *,
        platform: str | None = None,
        limit: int = 25,
    ) -> list[ReferenceVideo]:
        if platform:
            rows = self._conn.execute(
                """
                SELECT rv.*, COALESCE(rm.virality_score, rv.virality_score) AS virality_score
                FROM reference_videos rv
                LEFT JOIN reference_metrics rm ON rm.reference_id = rv.id
                WHERE rv.platform = ?
                ORDER BY rv.last_seen_at DESC
                LIMIT ?
                """,
                (platform, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT rv.*, COALESCE(rm.virality_score, rv.virality_score) AS virality_score
                FROM reference_videos rv
                LEFT JOIN reference_metrics rm ON rm.reference_id = rv.id
                ORDER BY rv.last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_reference(row) for row in rows]

    def count_concepts(self, *, statuses: tuple[str, ...] | None = None) -> int:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM concepts WHERE status IN ({placeholders})",
                statuses,
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM concepts").fetchone()
        return int(row[0])

    def list_dashboard_references(
        self,
        *,
        niche: str | None = None,
        min_score: float = 0.0,
        limit: int = 25,
        search: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """References for dashboard/API with optional filters."""
        clauses = ["COALESCE(rm.virality_score, rv.virality_score, 0) >= ?"]
        params: list[Any] = [min_score]

        if niche:
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM reference_niches rn
                    WHERE rn.reference_id = rv.id AND rn.niche = ?
                )
                """
            )
            params.append(niche)

        if search:
            term = f"%{search.strip()}%"
            clauses.append("(rv.title LIKE ? OR COALESCE(rv.channel, '') LIKE ?)")
            params.extend([term, term])

        normalized_status = (status or "").strip().lower()
        if normalized_status == "exhausted":
            clauses.append("COALESCE(rv.exhausted, 0) = 1")
        elif normalized_status == "active":
            clauses.append("COALESCE(rv.exhausted, 0) = 0")
        elif normalized_status == "analyzed":
            clauses.append(
                "EXISTS (SELECT 1 FROM reference_analyses ra WHERE ra.reference_id = rv.id)"
            )
        elif normalized_status == "unanalyzed":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM reference_analyses ra WHERE ra.reference_id = rv.id)"
            )

        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT
                rv.*,
                COALESCE(rm.virality_score, rv.virality_score, 0) AS virality_score,
                rm.age_hours,
                rm.age_days,
                rm.views_per_day,
                rm.views_per_hour,
                rm.like_ratio,
                rm.comment_ratio,
                (
                    SELECT COUNT(*) FROM reference_analyses ra
                    WHERE ra.reference_id = rv.id
                ) AS analysis_count
            FROM reference_videos rv
            LEFT JOIN reference_metrics rm ON rm.reference_id = rv.id
            WHERE {where}
            ORDER BY virality_score DESC, rv.last_seen_at DESC, rv.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            ref_id = int(row["id"])
            ref = row_to_reference(row)
            ref.virality_score = float(row["virality_score"] or 0)
            usage = self.get_reference_usage(ref_id)
            results.append(
                {
                    "reference": ref,
                    "metrics": {
                        "virality_score": ref.virality_score,
                        "age_hours": row["age_hours"],
                        "age_days": row["age_days"],
                        "views_per_day": row["views_per_day"],
                        "views_per_hour": row["views_per_hour"],
                        "like_ratio": row["like_ratio"],
                        "comment_ratio": row["comment_ratio"],
                    },
                    "niches": self.get_niches_for_reference(ref_id),
                    "concepts_generated": usage["concepts_generated"],
                    "concepts_approved": usage["concepts_approved"],
                    "exhausted": usage["exhausted"],
                    "has_analysis": int(row["analysis_count"] or 0) > 0,
                    "analysis_count": int(row["analysis_count"] or 0),
                }
            )
        return results

    def list_top_references(
        self,
        *,
        niche: str | None = None,
        min_score: float = 0.0,
        limit: int = 20,
    ) -> list[TopReference]:
        params: list[Any] = [min_score]
        niche_clause = ""
        if niche:
            niche_clause = "AND rn.niche = ?"
            params.append(niche)
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT
                rv.*,
                COALESCE(rm.virality_score, rv.virality_score, 0) AS virality_score,
                rm.age_hours, rm.age_days, rm.views_per_day, rm.views_per_hour,
                rm.like_ratio, rm.comment_ratio
            FROM reference_videos rv
            INNER JOIN reference_metrics rm ON rm.reference_id = rv.id
            {"INNER JOIN reference_niches rn ON rn.reference_id = rv.id" if niche else ""}
            WHERE rm.virality_score >= ?
            {niche_clause}
            ORDER BY rm.virality_score DESC, rm.views_per_day DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        results: list[TopReference] = []
        for row in rows:
            ref = row_to_reference(row)
            ref.virality_score = float(row["virality_score"])
            ref_id = int(row["id"])
            metrics = {
                "age_hours": row["age_hours"],
                "age_days": row["age_days"],
                "views_per_day": row["views_per_day"],
                "views_per_hour": row["views_per_hour"],
                "like_ratio": row["like_ratio"],
                "comment_ratio": row["comment_ratio"],
                "virality_score": ref.virality_score,
            }
            results.append(
                TopReference(
                    reference=ref,
                    metrics=metrics,
                    niches=self.get_niches_for_reference(ref_id),
                )
            )
        return results

    def get_reference_by_id(self, reference_id: int) -> ReferenceVideo | None:
        row = self._conn.execute(
            """
            SELECT rv.*, COALESCE(rm.virality_score, rv.virality_score) AS virality_score
            FROM reference_videos rv
            LEFT JOIN reference_metrics rm ON rm.reference_id = rv.id
            WHERE rv.id = ?
            """,
            (reference_id,),
        ).fetchone()
        return row_to_reference(row) if row else None

    def get_reference_bundle(self, reference_id: int) -> dict[str, Any] | None:
        ref = self.get_reference_by_id(reference_id)
        if ref is None:
            return None
        metrics_row = self._conn.execute(
            "SELECT * FROM reference_metrics WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        metrics = dict(metrics_row) if metrics_row else {}
        return {
            "reference": ref,
            "niches": self.get_niches_for_reference(reference_id),
            "metrics": metrics,
        }

    def get_reference_usage(self, reference_id: int) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT concepts_generated, concepts_approved, last_concept_generated_at,
                   exhausted, max_concepts, production_asset
            FROM reference_videos WHERE id = ?
            """,
            (reference_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Reference not found: {reference_id}")
        return {
            "concepts_generated": int(row["concepts_generated"] or 0),
            "concepts_approved": int(row["concepts_approved"] or 0),
            "last_concept_generated_at": row["last_concept_generated_at"],
            "exhausted": bool(row["exhausted"]),
            "max_concepts": row["max_concepts"],
            "production_asset": bool(row["production_asset"]),
        }

    def mark_reference_exhausted(self, reference_id: int) -> None:
        self._conn.execute(
            "UPDATE reference_videos SET exhausted = 1 WHERE id = ?",
            (reference_id,),
        )
        self._conn.commit()

    def record_concepts_generated(self, reference_id: int, count: int) -> None:
        if count <= 0:
            return
        self._conn.execute(
            """
            UPDATE reference_videos
            SET concepts_generated = concepts_generated + ?,
                last_concept_generated_at = ?
            WHERE id = ?
            """,
            (count, now_iso(), reference_id),
        )
        self._conn.commit()

    def save_analysis(
        self,
        *,
        reference_id: int,
        provider: str,
        model: str | None,
        analysis_version: str,
        analysis_json: dict[str, Any],
        genre: str | None = None,
        hook_type: str | None = None,
        emotional_trigger: str | None = None,
        pacing_style: str | None = None,
        tension_structure: str | None = None,
        story_structure: str | None = None,
        setting_type: str | None = None,
        visual_mood: str | None = None,
        visual_energy: str | None = None,
        camera_style: str | None = None,
        lighting_style: str | None = None,
        subject_type: str | None = None,
        ending_style: str | None = None,
        transferable_patterns: str | None = None,
        avoid_copying: str | None = None,
    ) -> ReferenceAnalysis:
        import json

        ts = now_iso()
        cursor = self._conn.execute(
            """
            INSERT INTO reference_analyses (
                reference_id, analyzed_at, provider, model, analysis_version,
                genre, hook_type, emotional_trigger, pacing_style, tension_structure,
                story_structure, setting_type, visual_mood, visual_energy, camera_style,
                lighting_style, subject_type, ending_style, transferable_patterns,
                avoid_copying, analysis_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                ts,
                provider,
                model,
                analysis_version,
                genre,
                hook_type,
                emotional_trigger,
                pacing_style,
                tension_structure,
                story_structure,
                setting_type,
                visual_mood,
                visual_energy,
                camera_style,
                lighting_style,
                subject_type,
                ending_style,
                transferable_patterns,
                avoid_copying,
                json.dumps(analysis_json),
            ),
        )
        self._conn.commit()
        analysis_id = int(cursor.lastrowid)
        row = self._conn.execute(
            "SELECT * FROM reference_analyses WHERE id = ?",
            (analysis_id,),
        ).fetchone()
        return row_to_analysis(row)

    def get_latest_analysis(self, reference_id: int) -> ReferenceAnalysis | None:
        row = self._conn.execute(
            """
            SELECT * FROM reference_analyses
            WHERE reference_id = ?
            ORDER BY analyzed_at DESC, id DESC
            LIMIT 1
            """,
            (reference_id,),
        ).fetchone()
        return row_to_analysis(row) if row else None

    def list_analyses(self, reference_id: int) -> list[ReferenceAnalysis]:
        rows = self._conn.execute(
            """
            SELECT * FROM reference_analyses
            WHERE reference_id = ?
            ORDER BY analyzed_at DESC, id DESC
            """,
            (reference_id,),
        ).fetchall()
        return [row_to_analysis(row) for row in rows]

    def save_concept(
        self,
        *,
        reference_id: int,
        analysis_id: int,
        niche: str,
        title: str,
        hook_idea: str = "",
        visual_premise: str = "",
        setting: str = "",
        subject: str = "",
        camera_movement: str = "",
        mood: str = "",
        story_premise: str = "",
        variation_family: str = "",
        originality_notes: str = "",
        status: str = "generated",
    ) -> Concept:
        ts = now_iso()
        cursor = self._conn.execute(
            """
            INSERT INTO concepts (
                reference_id, analysis_id, niche, title, hook_idea, visual_premise,
                setting, subject, camera_movement, mood, story_premise, variation_family,
                originality_notes, status, production_asset, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                reference_id,
                analysis_id,
                niche,
                title,
                hook_idea,
                visual_premise,
                setting,
                subject,
                camera_movement,
                mood,
                story_premise,
                variation_family,
                originality_notes,
                status,
                ts,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM concepts WHERE id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        return row_to_concept(row)

    def get_concept_row(self, concept_id: int) -> Concept | None:
        row = self._conn.execute(
            "SELECT * FROM concepts WHERE id = ?",
            (concept_id,),
        ).fetchone()
        return row_to_concept(row) if row else None

    def list_concepts(
        self,
        *,
        reference_id: int | None = None,
        niche: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Concept]:
        clauses: list[str] = []
        params: list[Any] = []
        if reference_id is not None:
            clauses.append("reference_id = ?")
            params.append(reference_id)
        if niche:
            clauses.append("niche = ?")
            params.append(niche)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT * FROM concepts
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [row_to_concept(row) for row in rows]

    def _adjust_concepts_approved(self, reference_id: int, delta: int) -> None:
        if delta == 0:
            return
        self._conn.execute(
            """
            UPDATE reference_videos
            SET concepts_approved = MAX(0, COALESCE(concepts_approved, 0) + ?)
            WHERE id = ?
            """,
            (delta, reference_id),
        )

    def update_concept_status(self, concept_id: int, new_status: str) -> Concept:
        allowed = {"generated", "shortlisted", "approved", "rejected"}
        if new_status not in allowed:
            raise ValueError(f"Invalid concept status: {new_status}")

        concept = self.get_concept_row(concept_id)
        if concept is None:
            raise ValueError(f"Concept not found: {concept_id}")

        old_status = concept.status
        if old_status == new_status:
            return concept

        valid_transitions = {
            ("generated", "shortlisted"),
            ("generated", "approved"),
            ("generated", "rejected"),
            ("shortlisted", "approved"),
            ("shortlisted", "rejected"),
            ("approved", "rejected"),
        }
        if (old_status, new_status) not in valid_transitions:
            raise ValueError(
                f"Invalid concept status transition: {old_status} -> {new_status}"
            )

        self._conn.execute(
            "UPDATE concepts SET status = ? WHERE id = ?",
            (new_status, concept_id),
        )
        if new_status == "approved" and old_status != "approved":
            self._adjust_concepts_approved(concept.reference_id, 1)
        elif old_status == "approved" and new_status != "approved":
            self._adjust_concepts_approved(concept.reference_id, -1)
        self._conn.commit()
        updated = self.get_concept_row(concept_id)
        assert updated is not None
        return updated

    def shortlist_concepts(self, concept_ids: list[int]) -> list[int]:
        updated: list[int] = []
        for concept_id in concept_ids:
            try:
                self.update_concept_status(concept_id, "shortlisted")
                updated.append(concept_id)
            except ValueError:
                continue
        return updated

    def approve_concepts(self, concept_ids: list[int]) -> list[int]:
        updated: list[int] = []
        for concept_id in concept_ids:
            concept = self.get_concept_row(concept_id)
            if concept is None:
                continue
            if concept.status == "approved":
                updated.append(concept_id)
                continue
            try:
                self.update_concept_status(concept_id, "approved")
                updated.append(concept_id)
            except ValueError:
                continue
        return updated

    def reject_concepts(self, concept_ids: list[int]) -> list[int]:
        updated: list[int] = []
        for concept_id in concept_ids:
            concept = self.get_concept_row(concept_id)
            if concept is None:
                continue
            if concept.status == "rejected":
                updated.append(concept_id)
                continue
            try:
                self.update_concept_status(concept_id, "rejected")
                updated.append(concept_id)
            except ValueError:
                continue
        return updated

    def list_concept_dicts(
        self,
        *,
        reference_id: int | None = None,
        niche: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, str]]:
        return [
            {
                "title": c.title,
                "hook_idea": c.hook_idea or "",
                "visual_premise": c.visual_premise or "",
                "setting": c.setting or "",
                "subject": c.subject or "",
                "story_premise": c.story_premise or "",
                "variation_family": c.variation_family or "",
            }
            for c in self.list_concepts(reference_id=reference_id, niche=niche, limit=limit)
        ]

    def get_concept(self, concept_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM concepts WHERE id = ?",
            (concept_id,),
        ).fetchone()
        if not row:
            return None
        concept = row_to_concept(row)
        return {
            "id": concept.id,
            "reference_id": concept.reference_id,
            "analysis_id": concept.analysis_id,
            "niche": concept.niche,
            "title": concept.title,
            "hook": concept.hook_idea,
            "hook_idea": concept.hook_idea,
            "visual_premise": concept.visual_premise,
            "setting": concept.setting,
            "subject": concept.subject,
            "variation_family": concept.variation_family,
            "status": concept.status,
        }

    def list_concepts_for_visual_batch(
        self,
        *,
        niche: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = [
            "c.status IN ('generated', 'shortlisted', 'approved')",
            "COALESCE(rv.exhausted, 0) = 0",
        ]
        params: list[Any] = []
        if niche:
            clauses.append("c.niche = ?")
            params.append(niche)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT c.*, COALESCE(rm.virality_score, 0) AS virality_score
            FROM concepts c
            JOIN reference_videos rv ON rv.id = c.reference_id
            LEFT JOIN reference_metrics rm ON rm.reference_id = c.reference_id
            WHERE {where}
            ORDER BY virality_score DESC, c.created_at DESC, c.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self.get_concept(int(row["id"])) for row in rows if row]

    def create_visual_asset(
        self,
        *,
        concept_id: int | None,
        reference_id: int | None,
        niche: str | None,
        variation_family: str | None,
        asset_type: str,
        provider: str,
        model: str | None,
        prompt: str,
        brief_json: str | None = None,
        generation_seed: str | None = None,
        local_path: str | None = None,
        variant_index: int = 1,
        status: str = "queued",
        max_usage: int | None = None,
        generation_job_id: int | None = None,
        source_media_id: int | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO visual_assets (
                concept_id, reference_id, generation_job_id, source_media_id,
                niche, variation_family, asset_type,
                provider, model, prompt, brief_json, generation_seed, local_path,
                variant_index, status, production_asset, max_usage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                concept_id,
                reference_id,
                generation_job_id,
                source_media_id,
                niche,
                variation_family,
                asset_type,
                provider,
                model,
                prompt,
                brief_json,
                generation_seed,
                local_path,
                variant_index,
                status,
                max_usage,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_visual_asset(self, asset_id: int) -> VisualAsset | None:
        row = self._conn.execute(
            "SELECT * FROM visual_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        return row_to_visual_asset(row) if row else None

    def get_visual_asset_dict(self, asset_id: int) -> dict[str, Any] | None:
        asset = self.get_visual_asset(asset_id)
        if not asset:
            return None
        return {
            "id": asset.id,
            "concept_id": asset.concept_id,
            "reference_id": asset.reference_id,
            "niche": asset.niche,
            "variation_family": asset.variation_family,
            "asset_type": asset.asset_type,
            "provider": asset.provider,
            "model": asset.model,
            "prompt": asset.prompt,
            "brief_json": asset.brief_json,
            "generation_seed": asset.generation_seed,
            "local_path": asset.local_path,
            "file_sha256": asset.file_sha256,
            "duration_seconds": asset.duration_seconds,
            "width": asset.width,
            "height": asset.height,
            "aspect_ratio": asset.aspect_ratio,
            "variant_index": asset.variant_index,
            "generated_at": asset.generated_at,
            "status": asset.status,
            "approved_at": asset.approved_at,
            "usage_count": asset.usage_count,
            "max_usage": asset.max_usage,
            "last_used_at": asset.last_used_at,
            "production_asset": asset.production_asset,
            "reject_reason": asset.reject_reason,
            "generation_job_id": asset.generation_job_id,
            "source_media_id": asset.source_media_id,
        }

    def find_visual_asset_by_job_path(self, generation_job_id: int, local_path: str) -> VisualAsset | None:
        row = self._conn.execute(
            """
            SELECT * FROM visual_assets
            WHERE generation_job_id = ? AND local_path = ?
            LIMIT 1
            """,
            (generation_job_id, local_path),
        ).fetchone()
        return row_to_visual_asset(row) if row else None

    def list_visual_assets_by_generation_job(self, generation_job_id: int) -> list[VisualAsset]:
        rows = self._conn.execute(
            "SELECT * FROM visual_assets WHERE generation_job_id = ? ORDER BY id",
            (generation_job_id,),
        ).fetchall()
        return [row_to_visual_asset(row) for row in rows]

    def list_visual_assets(
        self,
        *,
        status: str | None = None,
        niche: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if niche:
            clauses.append("niche = ?")
            params.append(niche)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT * FROM visual_assets
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [row_to_visual_asset(row).__dict__ for row in rows]

    def update_visual_asset_status(
        self,
        asset_id: int,
        status: str,
        *,
        reject_reason: str | None = None,
    ) -> None:
        if status in {"approved"}:
            raise ValueError("Use approve_visual_assets() to approve")
        production = 0
        self._conn.execute(
            """
            UPDATE visual_assets
            SET status = ?, reject_reason = ?, production_asset = ?
            WHERE id = ?
            """,
            (status, reject_reason, production, asset_id),
        )
        self._conn.commit()

    def update_visual_asset_after_generation(
        self,
        asset_id: int,
        *,
        local_path: str,
        duration_seconds: float | None,
        width: int | None,
        height: int | None,
        aspect_ratio: str | None,
        generated_at: str,
        status: str = "generated",
    ) -> None:
        self._conn.execute(
            """
            UPDATE visual_assets
            SET local_path = ?, duration_seconds = ?, width = ?, height = ?,
                aspect_ratio = ?, generated_at = ?, status = ?
            WHERE id = ?
            """,
            (
                local_path,
                duration_seconds,
                width,
                height,
                aspect_ratio,
                generated_at,
                status,
                asset_id,
            ),
        )
        self._conn.commit()

    def update_visual_asset_sha(self, asset_id: int | None, sha: str) -> None:
        if asset_id is None:
            return
        self._conn.execute(
            "UPDATE visual_assets SET file_sha256 = ? WHERE id = ?",
            (sha, asset_id),
        )
        self._conn.commit()

    def find_visual_asset_by_sha(
        self, sha: str, *, exclude_id: int | None = None
    ) -> int | None:
        if exclude_id is not None:
            row = self._conn.execute(
                """
                SELECT id FROM visual_assets
                WHERE file_sha256 = ? AND id != ?
                LIMIT 1
                """,
                (sha, exclude_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM visual_assets WHERE file_sha256 = ? LIMIT 1",
                (sha,),
            ).fetchone()
        return int(row["id"]) if row else None

    def approve_visual_assets(self, asset_ids: list[int]) -> list[int]:
        approved: list[int] = []
        ts = now_iso()
        for asset_id in asset_ids:
            row = self.get_visual_asset(asset_id)
            if not row:
                continue
            if row.status not in {"review", "generated"}:
                continue
            max_usage = row.max_usage if row.max_usage is not None else visual_max_usage()
            self._conn.execute(
                """
                UPDATE visual_assets
                SET status = 'approved', production_asset = 1, approved_at = ?,
                    max_usage = ?, reject_reason = NULL
                WHERE id = ?
                """,
                (ts, max_usage, asset_id),
            )
            approved.append(asset_id)
        self._conn.commit()
        return approved

    def reject_visual_assets(self, asset_ids: list[int]) -> list[int]:
        rejected: list[int] = []
        for asset_id in asset_ids:
            row = self.get_visual_asset(asset_id)
            if not row:
                continue
            if row.status in {"rejected", "auto_rejected"}:
                continue
            self._conn.execute(
                """
                UPDATE visual_assets
                SET status = 'rejected', production_asset = 0, reject_reason = COALESCE(reject_reason, 'human rejected')
                WHERE id = ?
                """,
                (asset_id,),
            )
            rejected.append(asset_id)
        self._conn.commit()
        return rejected

    def list_visual_assets_for_review(self, *, limit: int = 100) -> list[VisualAsset]:
        rows = self._conn.execute(
            """
            SELECT * FROM visual_assets
            WHERE status = 'review'
            ORDER BY generated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_visual_asset(row) for row in rows]

    def list_approved_visual_assets(
        self,
        *,
        niche: str | None = None,
        variation_family: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["status = 'approved'", "production_asset = 1"]
        params: list[Any] = []
        if niche:
            clauses.append("niche = ?")
            params.append(niche)
        if variation_family:
            clauses.append("variation_family = ?")
            params.append(variation_family)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT * FROM visual_assets WHERE {where} ORDER BY usage_count ASC, id ASC",
            params,
        ).fetchall()
        return [row_to_visual_asset(row).__dict__ for row in rows]

    def increment_visual_asset_usage(self, asset_id: int) -> None:
        row = self.get_visual_asset(asset_id)
        if not row:
            return
        usage = row.usage_count + 1
        ts = now_iso()
        status = row.status
        max_usage = row.max_usage
        if max_usage is not None and usage >= max_usage:
            status = "exhausted"
            production = 0
        else:
            production = 1 if row.status == "approved" else 0
        self._conn.execute(
            """
            UPDATE visual_assets
            SET usage_count = ?, last_used_at = ?, status = ?, production_asset = ?
            WHERE id = ?
            """,
            (usage, ts, status, production, asset_id),
        )
        self._conn.commit()

    def visual_library_stats(self) -> VisualLibraryStats:
        def _count(status: str | None = None) -> int:
            if status:
                return int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM visual_assets WHERE status = ?",
                        (status,),
                    ).fetchone()[0]
                )
            return int(self._conn.execute("SELECT COUNT(*) FROM visual_assets").fetchone()[0])

        generated = _count("generated") + _count("review") + _count("approved")
        waiting = _count("review")
        approved = _count("approved")
        rejected = _count("rejected")
        auto_rejected = _count("auto_rejected")
        production = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM visual_assets WHERE production_asset != 0"
            ).fetchone()[0]
        )
        duration_row = self._conn.execute(
            """
            SELECT COALESCE(SUM(duration_seconds), 0)
            FROM visual_assets
            WHERE status = 'approved' AND production_asset = 1
            """
        ).fetchone()
        total_duration = float(duration_row[0] or 0)
        avg_usage = float(
            self._conn.execute(
                """
                SELECT COALESCE(AVG(usage_count), 0)
                FROM visual_assets
                WHERE status = 'approved'
                """
            ).fetchone()[0]
            or 0
        )
        niche_rows = self._conn.execute(
            """
            SELECT niche, COUNT(*) AS cnt
            FROM visual_assets
            WHERE status IN ('review', 'approved', 'generated')
            GROUP BY niche
            """
        ).fetchall()
        family_rows = self._conn.execute(
            """
            SELECT variation_family, COUNT(*) AS cnt
            FROM visual_assets
            WHERE status IN ('review', 'approved', 'generated')
            GROUP BY variation_family
            """
        ).fetchall()
        return VisualLibraryStats(
            generated=generated,
            waiting_review=waiting,
            approved=approved,
            rejected=rejected,
            auto_rejected=auto_rejected,
            production_assets=production,
            total_usable_duration=round(total_duration, 2),
            average_usage_count=round(avg_usage, 2),
            by_niche={row["niche"] or "unknown": int(row["cnt"]) for row in niche_rows},
            by_family={
                row["variation_family"] or "unknown": int(row["cnt"]) for row in family_rows
            },
        )

    def catalog_stats(self) -> CatalogStats:
        total = int(self._conn.execute("SELECT COUNT(*) FROM reference_videos").fetchone()[0])
        youtube = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM reference_videos WHERE platform = 'youtube'"
            ).fetchone()[0]
        )
        today = today_start_iso()
        added_today = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM reference_videos WHERE discovered_at >= ?",
                (today,),
            ).fetchone()[0]
        )
        high_virality = int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM reference_metrics
                WHERE virality_score >= ?
                """,
                (HIGH_VIRALITY_SCORE,),
            ).fetchone()[0]
        )
        runs = int(self._conn.execute("SELECT COUNT(*) FROM discovery_runs").fetchone()[0])
        searches_today = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM search_history WHERE searched_at >= ?",
                (today,),
            ).fetchone()[0]
        )
        detail_requests_today = int(
            self._conn.execute(
                """
                SELECT COALESCE(SUM(detail_requests), 0) FROM discovery_runs
                WHERE started_at >= ?
                """,
                (today,),
            ).fetchone()[0]
        )
        production = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM reference_videos WHERE production_asset != 0"
            ).fetchone()[0]
        )
        search_totals = self._conn.execute(
            """
            SELECT COALESCE(SUM(ids_new), 0), COALESCE(SUM(ids_existing), 0), COUNT(*)
            FROM search_history
            """
        ).fetchone()
        ids_new_total = int(search_totals[0])
        ids_existing_total = int(search_totals[1])
        search_count = int(search_totals[2])
        unique_per_search = (ids_new_total / search_count) if search_count else 0.0

        niche_rows = self._conn.execute(
            """
            SELECT niche, COUNT(DISTINCT reference_id) AS cnt
            FROM reference_niches
            GROUP BY niche
            ORDER BY niche
            """
        ).fetchall()
        niche_coverage = [
            NicheCoverage(niche=row["niche"], reference_count=int(row["cnt"])) for row in niche_rows
        ]

        return CatalogStats(
            total_references=total,
            references_added_today=added_today,
            high_virality_references=high_virality,
            discovery_runs=runs,
            searches_today=searches_today,
            detail_requests_today=detail_requests_today,
            production_assets=production,
            unique_refs_per_search=round(unique_per_search, 2),
            duplicate_refs_encountered=ids_existing_total,
            niche_coverage=niche_coverage,
            youtube_references=youtube,
        )

    # --- Source media ---

    def create_source_media(
        self,
        *,
        title: str,
        source_mode: str,
        media_type: str,
        reference_id: int | None = None,
        platform: str | None = None,
        external_id: str | None = None,
        url: str | None = None,
        local_path: str | None = None,
        transcript: str | None = None,
        transcript_hash: str | None = None,
        duration_sec: float | None = None,
        rights_confidence: float | None = None,
        monetization_confidence: float | None = None,
        reuse_confidence: float | None = None,
        seen_as_reference: bool = False,
        actually_used_in_content: bool = False,
        reuse_explanations_json: str | None = None,
        risk_explanations_json: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO source_media (
                reference_id, platform, external_id, url, title, media_type, source_mode,
                local_path, transcript, transcript_hash, duration_sec,
                rights_confidence, monetization_confidence, reuse_confidence,
                seen_as_reference, actually_used_in_content,
                reuse_explanations_json, risk_explanations_json,
                production_asset, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                reference_id,
                platform,
                external_id,
                url,
                title,
                media_type,
                source_mode,
                local_path,
                transcript,
                transcript_hash,
                duration_sec,
                rights_confidence,
                monetization_confidence,
                reuse_confidence,
                1 if seen_as_reference else 0,
                1 if actually_used_in_content else 0,
                reuse_explanations_json,
                risk_explanations_json,
                now_iso(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_source_media(self, source_media_id: int) -> SourceMedia | None:
        row = self._conn.execute(
            "SELECT * FROM source_media WHERE id = ?",
            (source_media_id,),
        ).fetchone()
        return row_to_source_media(row) if row else None

    def list_source_media_by_external(
        self, platform: str | None, external_id: str | None
    ) -> list[SourceMedia]:
        if not platform or not external_id:
            return []
        rows = self._conn.execute(
            """
            SELECT * FROM source_media
            WHERE platform = ? AND external_id = ?
            ORDER BY id DESC
            """,
            (platform, external_id),
        ).fetchall()
        return [row_to_source_media(row) for row in rows]

    def list_source_media_by_transcript_hash(self, t_hash: str) -> list[SourceMedia]:
        if not t_hash:
            return []
        rows = self._conn.execute(
            "SELECT * FROM source_media WHERE transcript_hash = ? ORDER BY id DESC",
            (t_hash,),
        ).fetchall()
        return [row_to_source_media(row) for row in rows]

    def update_source_media_download(
        self,
        source_media_id: int,
        *,
        status: str,
        download_path: str | None = None,
        raw_local_path: str | None = None,
        local_path: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE source_media
            SET download_status = ?, download_path = COALESCE(?, download_path),
                raw_local_path = COALESCE(?, raw_local_path),
                local_path = COALESCE(?, local_path)
            WHERE id = ?
            """,
            (status, download_path, raw_local_path, local_path, source_media_id),
        )
        self._conn.commit()

    def update_source_media_transcript(
        self,
        source_media_id: int,
        *,
        transcript: str,
        transcript_hash: str,
        reuse_confidence: float,
        rights_confidence: float,
        monetization_confidence: float,
        reuse_explanations_json: str,
        risk_explanations_json: str,
        transcript_json: str | None = None,
        audio_fingerprint: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE source_media
            SET transcript = ?, transcript_hash = ?,
                transcript_json = COALESCE(?, transcript_json),
                audio_fingerprint = COALESCE(?, audio_fingerprint),
                reuse_confidence = ?, rights_confidence = ?, monetization_confidence = ?,
                reuse_explanations_json = ?, risk_explanations_json = ?
            WHERE id = ?
            """,
            (
                transcript,
                transcript_hash,
                transcript_json,
                audio_fingerprint,
                reuse_confidence,
                rights_confidence,
                monetization_confidence,
                reuse_explanations_json,
                risk_explanations_json,
                source_media_id,
            ),
        )
        self._conn.commit()

    def mark_source_media_used(self, source_media_id: int) -> None:
        self._conn.execute(
            "UPDATE source_media SET actually_used_in_content = 1 WHERE id = ?",
            (source_media_id,),
        )
        self._conn.commit()

    def create_source_segment(
        self,
        *,
        source_media_id: int,
        start_sec: float | None,
        end_sec: float | None,
        transcript: str | None,
        local_path: str | None,
        rights_confidence: float | None,
        monetization_confidence: float | None,
        reuse_confidence: float | None,
        clip_status: str | None = None,
        transcript_json: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO source_segments (
                source_media_id, start_sec, end_sec, transcript, transcript_json, local_path,
                clip_status, rights_confidence, monetization_confidence, reuse_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_media_id,
                start_sec,
                end_sec,
                transcript,
                transcript_json,
                local_path,
                clip_status,
                rights_confidence,
                monetization_confidence,
                reuse_confidence,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def update_source_segment_clip(
        self,
        segment_id: int,
        *,
        local_path: str,
        clip_status: str = "clipped",
    ) -> None:
        self._conn.execute(
            "UPDATE source_segments SET local_path = ?, clip_status = ? WHERE id = ?",
            (local_path, clip_status, segment_id),
        )
        self._conn.commit()

    def get_source_segment(self, segment_id: int) -> SourceSegment | None:
        row = self._conn.execute(
            "SELECT * FROM source_segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if not row:
            return None
        keys = row.keys()
        return SourceSegment(
            id=int(row["id"]),
            source_media_id=int(row["source_media_id"]),
            start_sec=row["start_sec"],
            end_sec=row["end_sec"],
            transcript=row["transcript"],
            transcript_json=row["transcript_json"] if "transcript_json" in keys else None,
            local_path=row["local_path"],
            clip_status=row["clip_status"] if "clip_status" in keys else None,
            rights_confidence=row["rights_confidence"],
            monetization_confidence=row["monetization_confidence"],
            reuse_confidence=row["reuse_confidence"],
        )

    # --- Generation jobs ---

    def create_generation_job(
        self,
        *,
        job_key: str,
        origin_type: str,
        image_count: int,
        video_count: int,
        aspect_ratio: str,
        status: str,
        created_at: str,
        style: str | None = None,
        niche: str | None = None,
        prompt_summary: str | None = None,
        reference_id: int | None = None,
        concept_id: int | None = None,
        source_media_id: int | None = None,
        job_json_path: str | None = None,
        cursor_prompt_path: str | None = None,
        output_dir: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO generation_jobs (
                job_key, origin_type, reference_id, concept_id, source_media_id,
                image_count, video_count, style, aspect_ratio, niche, prompt_summary,
                status, job_json_path, cursor_prompt_path, output_dir, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_key,
                origin_type,
                reference_id,
                concept_id,
                source_media_id,
                image_count,
                video_count,
                style,
                aspect_ratio,
                niche,
                prompt_summary,
                status,
                job_json_path,
                cursor_prompt_path,
                output_dir,
                created_at,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_generation_job(self, job_id: int) -> GenerationJob | None:
        row = self._conn.execute(
            "SELECT * FROM generation_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return row_to_generation_job(row) if row else None

    def get_generation_job_by_key(self, job_key: str) -> GenerationJob | None:
        row = self._conn.execute(
            "SELECT * FROM generation_jobs WHERE job_key = ?",
            (job_key,),
        ).fetchone()
        return row_to_generation_job(row) if row else None

    def list_generation_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[GenerationJob]:
        if status:
            rows = self._conn.execute(
                """
                SELECT * FROM generation_jobs
                WHERE status = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM generation_jobs
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_generation_job(row) for row in rows]

    def update_generation_job_status(
        self,
        job_id: int,
        *,
        status: str,
        completed_at: str | None = None,
        imported_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE generation_jobs
            SET status = ?, completed_at = COALESCE(?, completed_at),
                imported_at = COALESCE(?, imported_at),
                error_message = ?
            WHERE id = ?
            """,
            (status, completed_at, imported_at, error_message, job_id),
        )
        self._conn.commit()

    def list_visual_assets_for_review_extended(
        self,
        *,
        asset_type: str | None = None,
        limit: int = 100,
    ) -> list[VisualAsset]:
        clauses = ["status = 'review'"]
        params: list[Any] = []
        if asset_type:
            clauses.append("asset_type = ?")
            params.append(asset_type)
        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT * FROM visual_assets
            WHERE {where}
            ORDER BY generated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [row_to_visual_asset(row) for row in rows]

    # --- Production projects ---

    def create_production_project(
        self,
        *,
        slug: str,
        title: str,
        niche: str | None,
        origin_type: str = "reference",
        reference_id: int | None = None,
        source_media_id: int | None = None,
        source_segment_id: int | None = None,
        concept_id: int | None = None,
        format_profile: str,
        hook_text: str | None,
        caption_preset: str,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO production_projects (
                slug, title, niche, origin_type, reference_id,
                source_media_id, source_segment_id, concept_id,
                format_profile, hook_text, caption_preset, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """,
            (
                slug,
                title,
                niche,
                origin_type,
                reference_id,
                source_media_id,
                source_segment_id,
                concept_id,
                format_profile,
                hook_text,
                caption_preset,
                now_iso(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_production_project(self, project_id: int) -> ProductionProject | None:
        row = self._conn.execute(
            "SELECT * FROM production_projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return row_to_production_project(row) if row else None

    def get_production_project_by_slug(self, slug: str) -> ProductionProject | None:
        row = self._conn.execute(
            "SELECT * FROM production_projects WHERE slug = ?",
            (slug,),
        ).fetchone()
        return row_to_production_project(row) if row else None

    def list_production_projects(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ProductionProject]:
        if status:
            rows = self._conn.execute(
                """
                SELECT * FROM production_projects WHERE status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM production_projects ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row_to_production_project(row) for row in rows]

    def update_production_project_timeline(
        self, project_id: int, timeline_json: str, *, status: str = "ready"
    ) -> None:
        self._conn.execute(
            "UPDATE production_projects SET timeline_json = ?, status = ? WHERE id = ?",
            (timeline_json, status, project_id),
        )
        self._conn.commit()

    def update_production_project_status(
        self,
        project_id: int,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE production_projects SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, project_id),
        )
        self._conn.commit()

    def update_production_project_rendered(
        self,
        project_id: int,
        *,
        output_path: str,
        duration_sec: float,
        monetization_confidence: float,
        rights_confidence: float,
        reuse_confidence: float,
        risk_explanations_json: str,
        status: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE production_projects
            SET output_path = ?, duration_sec = ?, monetization_confidence = ?,
                rights_confidence = ?, reuse_confidence = ?,
                risk_explanations_json = ?, status = ?, rendered_at = ?
            WHERE id = ?
            """,
            (
                output_path,
                duration_sec,
                monetization_confidence,
                rights_confidence,
                reuse_confidence,
                risk_explanations_json,
                status,
                now_iso(),
                project_id,
            ),
        )
        self._conn.commit()

    def delete_production_project(self, project_id: int) -> bool:
        project = self.get_production_project(project_id)
        if not project:
            return False
        self._conn.execute(
            "DELETE FROM production_project_visuals WHERE project_id = ?",
            (project_id,),
        )
        self._conn.execute(
            "DELETE FROM production_projects WHERE id = ?",
            (project_id,),
        )
        self._conn.commit()
        return True

    def set_project_visuals(self, project_id: int, visual_asset_ids: list[int]) -> None:
        self._conn.execute(
            "DELETE FROM production_project_visuals WHERE project_id = ?",
            (project_id,),
        )
        for order, asset_id in enumerate(visual_asset_ids):
            self._conn.execute(
                """
                INSERT OR IGNORE INTO production_project_visuals (project_id, visual_asset_id, sort_order)
                VALUES (?, ?, ?)
                """,
                (project_id, asset_id, order),
            )
        self._conn.commit()

    def list_project_visual_assets(self, project_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT va.* FROM production_project_visuals pv
            JOIN visual_assets va ON va.id = pv.visual_asset_id
            WHERE pv.project_id = ? AND va.status = 'approved'
            ORDER BY pv.sort_order ASC
            """,
            (project_id,),
        ).fetchall()
        return [row_to_visual_asset(row).__dict__ for row in rows]

    def list_approved_visual_assets_global(self, *, limit: int = 100) -> list[VisualAsset]:
        rows = self._conn.execute(
            """
            SELECT * FROM visual_assets WHERE status = 'approved'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_visual_asset(row) for row in rows]

    def list_source_media_with_transcript(
        self,
        *,
        exclude_id: int | None = None,
        limit: int = 200,
    ) -> list[SourceMedia]:
        if exclude_id:
            rows = self._conn.execute(
                """
                SELECT * FROM source_media
                WHERE transcript IS NOT NULL AND transcript != '' AND id != ?
                ORDER BY id DESC LIMIT ?
                """,
                (exclude_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM source_media
                WHERE transcript IS NOT NULL AND transcript != ''
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_source_media(row) for row in rows]

    # --- Publishing accounts & jobs ---

    def create_publishing_account(
        self,
        *,
        platform: str,
        display_name: str,
        platform_account_id: str | None,
        username: str | None,
        niche: str | None,
        auth_status: str,
        posting_available: bool,
        owner: str = "chris",
        capabilities_json: str | None = None,
        audit_note: str | None = None,
        token_expires_at: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO publishing_accounts (
                platform, display_name, owner, platform_account_id, username, niche,
                enabled, auth_status, token_expires_at, capabilities_json,
                posting_available, audit_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                display_name,
                owner,
                platform_account_id,
                username,
                niche,
                auth_status,
                token_expires_at,
                capabilities_json,
                1 if posting_available else 0,
                audit_note,
                now_iso(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def update_publishing_account_credentials_ref(self, account_id: int, credentials_ref: str) -> None:
        self._conn.execute(
            "UPDATE publishing_accounts SET credentials_ref = ? WHERE id = ?",
            (credentials_ref, account_id),
        )
        self._conn.commit()

    def update_publishing_account_status(
        self,
        account_id: int,
        *,
        auth_status: str,
        posting_available: bool,
        username: str | None = None,
        platform_account_id: str | None = None,
        capabilities_json: str | None = None,
        audit_note: str | None = None,
        token_expires_at: str | None = None,
        last_verified: bool = False,
        enabled: bool | None = None,
    ) -> None:
        fields = ["auth_status = ?", "posting_available = ?"]
        params: list[Any] = [auth_status, 1 if posting_available else 0]
        if username is not None:
            fields.append("username = ?")
            params.append(username)
        if platform_account_id is not None:
            fields.append("platform_account_id = ?")
            params.append(platform_account_id)
        if capabilities_json is not None:
            fields.append("capabilities_json = ?")
            params.append(capabilities_json)
        if audit_note is not None:
            fields.append("audit_note = ?")
            params.append(audit_note)
        if token_expires_at is not None:
            fields.append("token_expires_at = ?")
            params.append(token_expires_at)
        if last_verified:
            fields.append("last_verified_at = ?")
            params.append(now_iso())
        if enabled is not None:
            fields.append("enabled = ?")
            params.append(1 if enabled else 0)
        params.append(account_id)
        self._conn.execute(
            f"UPDATE publishing_accounts SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def get_publishing_account(self, account_id: int) -> PublishingAccount | None:
        row = self._conn.execute(
            "SELECT * FROM publishing_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        return row_to_publishing_account(row) if row else None

    def list_publishing_accounts(
        self,
        *,
        platform: str | None = None,
        owner: str | None = None,
        enabled_only: bool = False,
    ) -> list[PublishingAccount]:
        clauses = []
        params: list[Any] = []
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if owner:
            clauses.append("owner = ?")
            params.append(owner)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM publishing_accounts {where} ORDER BY owner, platform, display_name",
            params,
        ).fetchall()
        return [row_to_publishing_account(row) for row in rows]

    def delete_publishing_account(self, account_id: int) -> None:
        self._conn.execute("DELETE FROM publishing_accounts WHERE id = ?", (account_id,))
        self._conn.commit()

    def set_account_default(self, niche: str, platform: str, account_id: int | None) -> None:
        col = {"youtube": "youtube_account_id", "tiktok": "tiktok_account_id", "instagram": "instagram_account_id"}.get(
            platform
        )
        if not col:
            raise ValueError(f"Unsupported platform for defaults: {platform}")
        self._conn.execute(
            f"""
            INSERT INTO publishing_account_defaults (niche, {col})
            VALUES (?, ?)
            ON CONFLICT(niche) DO UPDATE SET {col} = excluded.{col}
            """,
            (niche, account_id),
        )
        self._conn.commit()

    def get_account_defaults(self, niche: str) -> dict[str, int | None]:
        row = self._conn.execute(
            "SELECT * FROM publishing_account_defaults WHERE niche = ?",
            (niche,),
        ).fetchone()
        if not row:
            return {"youtube": None, "tiktok": None, "instagram": None}
        return {
            "youtube": row["youtube_account_id"],
            "tiktok": row["tiktok_account_id"],
            "instagram": row["instagram_account_id"],
        }

    def create_publishing_job(
        self,
        *,
        production_project_id: int,
        account_id: int,
        platform: str,
        idempotency_key: str,
        title: str | None,
        caption: str | None,
        hashtags: str | None,
        metadata_json: str | None,
        scheduled_at: str | None,
        timezone: str | None,
        status: str,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO publishing_jobs (
                production_project_id, account_id, platform, idempotency_key,
                title, caption, hashtags, metadata_json, scheduled_at, timezone,
                status, attempts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                production_project_id,
                account_id,
                platform,
                idempotency_key,
                title,
                caption,
                hashtags,
                metadata_json,
                scheduled_at,
                timezone,
                status,
                now_iso(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_publishing_job(self, job_id: int) -> PublishingJob | None:
        row = self._conn.execute("SELECT * FROM publishing_jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_publishing_job(row) if row else None

    def get_publishing_job_by_key(self, idempotency_key: str) -> PublishingJob | None:
        row = self._conn.execute(
            "SELECT * FROM publishing_jobs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row_to_publishing_job(row) if row else None

    def list_publishing_jobs(
        self,
        *,
        status: str | None = None,
        production_project_id: int | None = None,
        limit: int = 100,
    ) -> list[PublishingJob]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if production_project_id:
            clauses.append("production_project_id = ?")
            params.append(production_project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM publishing_jobs {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [row_to_publishing_job(row) for row in rows]

    def list_due_publishing_jobs(self, *, before_iso: str, limit: int = 20) -> list[PublishingJob]:
        rows = self._conn.execute(
            """
            SELECT * FROM publishing_jobs
            WHERE status = 'scheduled' AND scheduled_at IS NOT NULL AND scheduled_at <= ?
            ORDER BY scheduled_at ASC LIMIT ?
            """,
            (before_iso, limit),
        ).fetchall()
        return [row_to_publishing_job(row) for row in rows]

    def update_publishing_job_status(self, job_id: int, status: str) -> None:
        self._conn.execute("UPDATE publishing_jobs SET status = ? WHERE id = ?", (status, job_id))
        self._conn.commit()

    def claim_publishing_job(self, job_id: int, *, from_statuses: tuple[str, ...]) -> bool:
        placeholders = ",".join("?" for _ in from_statuses)
        cursor = self._conn.execute(
            f"""
            UPDATE publishing_jobs SET status = 'publishing'
            WHERE id = ? AND status IN ({placeholders})
            """,
            (job_id, *from_statuses),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def increment_publishing_job_attempts(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE publishing_jobs SET attempts = attempts + 1 WHERE id = ?",
            (job_id,),
        )
        self._conn.commit()

    def complete_publishing_job(
        self,
        job_id: int,
        *,
        status: str,
        platform_post_id: str | None,
        platform_url: str | None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE publishing_jobs
            SET status = ?, platform_post_id = ?, platform_url = ?, published_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (status, platform_post_id, platform_url, now_iso(), job_id),
        )
        self._conn.commit()

    def fail_publishing_job(self, job_id: int, error_message: str) -> None:
        self._conn.execute(
            "UPDATE publishing_jobs SET status = 'failed', error_message = ? WHERE id = ?",
            (error_message, job_id),
        )
        self._conn.commit()

    def record_project_published(
        self,
        production_project_id: int,
        *,
        account_id: int,
        platform: str,
        platform_url: str | None,
    ) -> None:
        _ = (production_project_id, account_id, platform, platform_url)

    def list_published_jobs_for_project(self, production_project_id: int) -> list[PublishingJob]:
        rows = self._conn.execute(
            """
            SELECT * FROM publishing_jobs
            WHERE production_project_id = ? AND status IN ('published', 'processing')
            ORDER BY published_at DESC
            """,
            (production_project_id,),
        ).fetchall()
        return [row_to_publishing_job(row) for row in rows]

    # --- Analytics ---

    def upsert_analytics_post_features(
        self,
        *,
        publishing_job_id: int,
        production_project_id: int,
        account_id: int,
        platform: str,
        niche: str | None,
        hook_formula: str | None,
        features_json: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO analytics_post_features (
                publishing_job_id, production_project_id, account_id, platform,
                niche, features_json, hook_formula, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(publishing_job_id) DO UPDATE SET
                features_json = excluded.features_json,
                hook_formula = excluded.hook_formula,
                niche = excluded.niche
            """,
            (
                publishing_job_id,
                production_project_id,
                account_id,
                platform,
                niche,
                features_json,
                hook_formula,
                now_iso(),
            ),
        )
        self._conn.commit()

    def get_analytics_post_features(self, publishing_job_id: int) -> AnalyticsPostFeatures | None:
        row = self._conn.execute(
            "SELECT * FROM analytics_post_features WHERE publishing_job_id = ?",
            (publishing_job_id,),
        ).fetchone()
        return row_to_analytics_post_features(row) if row else None

    def insert_analytics_snapshot(
        self,
        *,
        publishing_job_id: int,
        production_project_id: int,
        account_id: int,
        platform: str,
        platform_post_id: str | None,
        metrics: dict[str, Any],
        performance: dict[str, Any],
    ) -> int:
        import json

        cursor = self._conn.execute(
            """
            INSERT INTO analytics_post_snapshots (
                publishing_job_id, production_project_id, account_id, platform,
                platform_post_id, snapshot_at, views, likes, comments, shares, saves,
                watch_time_sec, avg_watch_duration_sec, completion_rate, retention,
                followers_gained, impressions, click_through_rate, revenue, raw_json,
                performance_score, performance_tier, views_vs_account_median,
                velocity_views_per_day
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                publishing_job_id,
                production_project_id,
                account_id,
                platform,
                platform_post_id,
                now_iso(),
                metrics.get("views"),
                metrics.get("likes"),
                metrics.get("comments"),
                metrics.get("shares"),
                metrics.get("saves"),
                metrics.get("watch_time_sec"),
                metrics.get("avg_watch_duration_sec"),
                metrics.get("completion_rate"),
                metrics.get("retention"),
                metrics.get("followers_gained"),
                metrics.get("impressions"),
                metrics.get("click_through_rate"),
                metrics.get("revenue"),
                json.dumps(metrics.get("raw") or {}),
                performance.get("performance_score"),
                performance.get("performance_tier"),
                performance.get("views_vs_account_median"),
                performance.get("velocity_views_per_day"),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_latest_analytics_snapshot(self, publishing_job_id: int) -> AnalyticsPostSnapshot | None:
        row = self._conn.execute(
            """
            SELECT * FROM analytics_post_snapshots
            WHERE publishing_job_id = ?
            ORDER BY snapshot_at DESC LIMIT 1
            """,
            (publishing_job_id,),
        ).fetchone()
        return row_to_analytics_post_snapshot(row) if row else None

    def list_analytics_snapshots_for_job(self, publishing_job_id: int, *, limit: int = 50) -> list[AnalyticsPostSnapshot]:
        rows = self._conn.execute(
            """
            SELECT * FROM analytics_post_snapshots
            WHERE publishing_job_id = ?
            ORDER BY snapshot_at ASC LIMIT ?
            """,
            (publishing_job_id, limit),
        ).fetchall()
        return [row_to_analytics_post_snapshot(row) for row in rows]

    def list_published_jobs_for_analytics(
        self,
        *,
        account_id: int | None = None,
        limit: int = 100,
    ) -> list[PublishingJob]:
        clauses = ["status IN ('published', 'processing')", "platform_post_id IS NOT NULL"]
        params: list[Any] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT * FROM publishing_jobs
            WHERE {where}
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [row_to_publishing_job(row) for row in rows]

    def list_latest_post_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT s.*, f.features_json, f.hook_formula, f.niche AS feature_niche,
                   j.title, j.published_at, j.platform_url, j.production_project_id
            FROM analytics_post_snapshots s
            INNER JOIN (
                SELECT publishing_job_id, MAX(snapshot_at) AS max_at
                FROM analytics_post_snapshots GROUP BY publishing_job_id
            ) latest ON latest.publishing_job_id = s.publishing_job_id AND latest.max_at = s.snapshot_at
            LEFT JOIN analytics_post_features f ON f.publishing_job_id = s.publishing_job_id
            LEFT JOIN publishing_jobs j ON j.id = s.publishing_job_id
            ORDER BY COALESCE(s.performance_score, -1) DESC, COALESCE(s.views, 0) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "snapshot_id": int(row["id"]),
                    "publishing_job_id": int(row["publishing_job_id"]),
                    "production_project_id": int(row["production_project_id"]),
                    "account_id": int(row["account_id"]),
                    "platform": row["platform"],
                    "platform_post_id": row["platform_post_id"],
                    "snapshot_at": row["snapshot_at"],
                    "views": row["views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"],
                    "performance_score": row["performance_score"],
                    "performance_tier": row["performance_tier"],
                    "velocity_views_per_day": row["velocity_views_per_day"],
                    "views_vs_account_median": row["views_vs_account_median"],
                    "hook_formula": row["hook_formula"],
                    "niche": row["feature_niche"],
                    "features": row["features_json"],
                    "title": row["title"],
                    "published_at": row["published_at"],
                    "platform_url": row["platform_url"],
                }
            )
        return results

    def list_analytics_posts_with_latest(
        self,
        *,
        niche: str | None = None,
        account_id: int | None = None,
        platform: str | None = None,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.list_latest_post_snapshots(limit=limit * 3)
        filtered: list[dict[str, Any]] = []
        account_owner_cache: dict[int, str | None] = {}
        for row in rows:
            if niche and (row.get("niche") or "").lower() != niche.lower():
                continue
            if account_id is not None and int(row["account_id"]) != account_id:
                continue
            if platform and row.get("platform") != platform:
                continue
            if owner:
                aid = int(row["account_id"])
                if aid not in account_owner_cache:
                    account = self.get_publishing_account(aid)
                    account_owner_cache[aid] = account.owner if account else None
                if account_owner_cache.get(aid) != owner:
                    continue
            filtered.append(row)
            if len(filtered) >= limit:
                break
        return filtered

    def get_account_analytics_baseline(self, account_id: int, *, lookback: int = 20) -> dict[str, float]:
        rows = self._conn.execute(
            """
            SELECT s.views, s.likes, s.comments, s.shares, s.saves
            FROM analytics_post_snapshots s
            INNER JOIN (
                SELECT publishing_job_id, MAX(snapshot_at) AS max_at
                FROM analytics_post_snapshots GROUP BY publishing_job_id
            ) latest ON latest.publishing_job_id = s.publishing_job_id AND latest.max_at = s.snapshot_at
            WHERE s.account_id = ?
            ORDER BY s.snapshot_at DESC LIMIT ?
            """,
            (account_id, lookback),
        ).fetchall()
        views: list[float] = []
        engagements: list[float] = []
        for row in rows:
            v = float(row["views"] or 0)
            views.append(v)
            if v > 0:
                eng = (
                    float(row["likes"] or 0)
                    + float(row["comments"] or 0)
                    + float(row["shares"] or 0)
                    + float(row["saves"] or 0)
                ) / v
                engagements.append(eng)
        from discovery.analytics.scoring import median

        return {
            "median_views": median(views) if views else 1000.0,
            "median_engagement": median(engagements) if engagements else 0.03,
            "sample_size": len(views),
        }

    def upsert_performance_profile(
        self,
        *,
        niche: str,
        account_id: int | None,
        profile: dict[str, Any],
        sample_size: int,
    ) -> None:
        import json

        existing = self.get_performance_profile(niche, account_id=account_id)
        payload = json.dumps(profile)
        ts = now_iso()
        if existing:
            self._conn.execute(
                """
                UPDATE performance_profiles
                SET profile_json = ?, sample_size = ?, updated_at = ?
                WHERE id = ?
                """,
                (payload, sample_size, ts, existing.id),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO performance_profiles (niche, account_id, profile_json, sample_size, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (niche, account_id, payload, sample_size, ts),
            )
        self._conn.commit()

    def get_performance_profile(
        self,
        niche: str,
        *,
        account_id: int | None = None,
    ) -> PerformanceProfile | None:
        row = self._conn.execute(
            """
            SELECT * FROM performance_profiles
            WHERE niche = ? AND (
                (? IS NULL AND account_id IS NULL) OR account_id = ?
            )
            """,
            (niche, account_id, account_id),
        ).fetchone()
        return row_to_performance_profile(row) if row else None

    def analytics_overview(
        self,
        *,
        platform: str | None = None,
        account_id: int | None = None,
        owner: str | None = None,
        niche: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        rows = self.list_analytics_posts_with_latest(
            niche=niche,
            account_id=account_id,
            platform=platform,
            owner=owner,
            limit=500,
        )
        total_views = sum(int(r.get("views") or 0) for r in rows)
        scores = [float(r["performance_score"]) for r in rows if r.get("performance_score") is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None
        breakout = [r for r in rows if r.get("performance_tier") == "breakout"]
        under = [r for r in rows if r.get("performance_tier") == "underperforming"]
        cutoff_7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        views_7d = sum(
            int(r.get("views") or 0)
            for r in rows
            if (r.get("published_at") or "") >= cutoff_7
        )
        views_30d = sum(
            int(r.get("views") or 0)
            for r in rows
            if (r.get("published_at") or "") >= cutoff_30
        )
        return {
            "total_published_posts": len(rows),
            "total_views": total_views,
            "views_last_7_days": views_7d,
            "views_last_30_days": views_30d,
            "average_performance_score": avg_score,
            "breakout_count": len(breakout),
            "underperforming_count": len(under),
            "posts_with_metrics": len([r for r in rows if r.get("views") is not None]),
        }

    # --- Pilot batches ---

    def create_pilot_batch(
        self,
        *,
        slug: str,
        name: str,
        niche: str | None,
        account_id: int | None,
        batch_size: int,
        config_json: str | None,
        status: str = "planning",
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO pilot_batches (
                slug, name, niche, account_id, batch_size, status, config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (slug, name, niche, account_id, batch_size, status, config_json, now_iso()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_pilot_batch(self, batch_id: int) -> PilotBatch | None:
        row = self._conn.execute("SELECT * FROM pilot_batches WHERE id = ?", (batch_id,)).fetchone()
        return row_to_pilot_batch(row) if row else None

    def get_pilot_batch_by_slug(self, slug: str) -> PilotBatch | None:
        row = self._conn.execute("SELECT * FROM pilot_batches WHERE slug = ?", (slug,)).fetchone()
        return row_to_pilot_batch(row) if row else None

    def list_pilot_batches(self, *, status: str | None = None, limit: int = 20) -> list[PilotBatch]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM pilot_batches WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM pilot_batches ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row_to_pilot_batch(row) for row in rows]

    def update_pilot_batch_status(
        self,
        batch_id: int,
        status: str,
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
        error_message: str | None = None,
    ) -> None:
        fields = ["status = ?"]
        params: list[Any] = [status]
        if started_at:
            fields.append("started_at = ?")
            params.append(started_at)
        if completed_at:
            fields.append("completed_at = ?")
            params.append(completed_at)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)
        params.append(batch_id)
        self._conn.execute(
            f"UPDATE pilot_batches SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def create_pilot_batch_item(
        self,
        *,
        batch_id: int,
        sort_order: int,
        slot_label: str | None,
        strategy: str,
        format_profile: str | None,
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO pilot_batch_items (
                batch_id, sort_order, slot_label, strategy, format_profile,
                status, stages_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', '{}', ?)
            """,
            (batch_id, sort_order, slot_label, strategy, format_profile, now_iso()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_pilot_batch_item(self, item_id: int) -> PilotBatchItem | None:
        row = self._conn.execute("SELECT * FROM pilot_batch_items WHERE id = ?", (item_id,)).fetchone()
        return row_to_pilot_batch_item(row) if row else None

    def list_pilot_batch_items(self, batch_id: int) -> list[PilotBatchItem]:
        rows = self._conn.execute(
            "SELECT * FROM pilot_batch_items WHERE batch_id = ? ORDER BY sort_order, id",
            (batch_id,),
        ).fetchall()
        return [row_to_pilot_batch_item(row) for row in rows]

    def update_pilot_batch_item(self, item_id: int, **fields: Any) -> None:
        allowed = {
            "reference_id",
            "source_media_id",
            "concept_id",
            "generation_job_id",
            "production_project_id",
            "publishing_job_id",
            "status",
            "stages_json",
            "error_stage",
            "error_message",
            "notes",
        }
        updates = []
        params: list[Any] = []
        for key, value in fields.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(value)
        if not updates:
            return
        params.append(item_id)
        self._conn.execute(
            f"UPDATE pilot_batch_items SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self._conn.commit()
