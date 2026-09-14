#!/usr/bin/env python3
"""Move flat downloads/motivational/<slug>/ jobs into YYYY-MM-DD/<slug>/ folders."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import content_reuse
from discovery.config import default_db_path, load_env, project_root
from discovery.motivation_paths import (
    infer_job_folder_date,
    is_date_folder,
    iter_legacy_motivation_job_dirs,
    legacy_motivation_job_rel_prefix,
    motivation_job_rel_prefix,
    motivation_jobs_root,
)
from discovery.store import DiscoveryStore


def _rewrite_prefix_in_db(store: DiscoveryStore, old_prefix: str, new_prefix: str) -> int:
    old = old_prefix.replace("\\", "/").rstrip("/")
    new = new_prefix.replace("\\", "/").rstrip("/")
    if old == new:
        return 0
    updated = 0
    tables: tuple[tuple[str, str], ...] = (
        ("production_library_videos", "final_output_path"),
        ("production_video_components", "local_path"),
        ("production_projects", "output_path"),
    )
    for table, column in tables:
        rows = store._conn.execute(
            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} LIKE ?",
            (old + "%",),
        ).fetchall()
        for row in rows:
            posix = str(row[column] or "").replace("\\", "/")
            if not (posix == old or posix.startswith(old + "/")):
                continue
            rewritten = new + posix[len(old) :]
            store._conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE id = ?",
                (rewritten, int(row["id"])),
            )
            updated += 1
    store._conn.commit()
    return updated


def _rewrite_motivation_job_records(root: Path, old_prefix: str, new_prefix: str) -> int:
    jobs_dir = root / "data" / "motivation_jobs"
    if not jobs_dir.is_dir():
        return 0
    old = old_prefix.replace("\\", "/")
    new = new_prefix.replace("\\", "/")
    count = 0
    for path in jobs_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        output_path = str(payload.get("output_path") or "").replace("\\", "/")
        if output_path.startswith(old):
            payload["output_path"] = new + output_path[len(old) :]
            preview = str(payload.get("preview_url") or "")
            if preview.startswith("/media/" + old):
                payload["preview_url"] = "/media/" + payload["output_path"]
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            count += 1
    return count


def migrate_one(
    job_dir: Path,
    *,
    jobs_root: Path,
    root: Path,
    store: DiscoveryStore | None,
    dry_run: bool,
    force_date: str | None,
) -> dict[str, Any]:
    slug = job_dir.name
    job_date = force_date or infer_job_folder_date(job_dir)
    if not is_date_folder(job_date):
        raise ValueError(f"Invalid job date for {slug}: {job_date}")

    dest = jobs_root / job_date / slug
    old_prefix = legacy_motivation_job_rel_prefix(slug)
    new_prefix = motivation_job_rel_prefix(slug, job_date)

    result: dict[str, Any] = {
        "slug": slug,
        "job_date": job_date,
        "from": job_dir.as_posix(),
        "to": dest.as_posix(),
        "old_prefix": old_prefix,
        "new_prefix": new_prefix,
    }

    if dest.exists():
        result["status"] = "skipped"
        result["reason"] = "destination exists"
        return result

    if dry_run:
        result["status"] = "dry_run"
        return result

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(job_dir), str(dest))

    job_json = dest / "job.json"
    if job_json.is_file():
        try:
            payload = json.loads(job_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["job_date"] = job_date
        job_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    db_updates = 0
    if store is not None:
        db_updates += _rewrite_prefix_in_db(store, old_prefix, new_prefix)
    record_updates = _rewrite_motivation_job_records(root, old_prefix, new_prefix)

    result["status"] = "moved"
    result["db_path_updates"] = db_updates
    result["build_job_record_updates"] = record_updates
    return result


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print moves without changing disk/DB")
    parser.add_argument("--slug", action="append", help="Only migrate these job slugs (repeatable)")
    parser.add_argument(
        "--job-date",
        help="Force YYYY-MM-DD for --slug moves (only valid with a single --slug)",
    )
    parser.add_argument("--skip-db", action="store_true", help="Do not rewrite SQLite paths")
    parser.add_argument("--skip-catalog", action="store_true", help="Skip content/used.json rebuild")
    args = parser.parse_args()

    root = project_root()
    jobs_root = motivation_jobs_root(root)
    legacy = list(iter_legacy_motivation_job_dirs(jobs_root))
    if args.slug:
        wanted = set(args.slug)
        legacy = [path for path in legacy if path.name in wanted]
        missing = wanted - {path.name for path in legacy}
        for slug in sorted(missing):
            print(f"No legacy job folder for slug: {slug}", file=sys.stderr)

    if not legacy:
        print("No legacy motivation job folders to migrate.")
        return 0

    if args.job_date and (len(args.slug or []) != 1):
        print("--job-date requires exactly one --slug", file=sys.stderr)
        return 2
    if args.job_date and not is_date_folder(args.job_date):
        print("--job-date must be YYYY-MM-DD", file=sys.stderr)
        return 2

    store: DiscoveryStore | None = None
    if not args.dry_run and not args.skip_db and default_db_path().is_file():
        store = DiscoveryStore(default_db_path())

    results: list[dict[str, Any]] = []
    try:
        for job_dir in legacy:
            force_date = args.job_date if args.slug and job_dir.name in args.slug else None
            results.append(
                migrate_one(
                    job_dir,
                    jobs_root=jobs_root,
                    root=root,
                    store=store,
                    dry_run=args.dry_run,
                    force_date=force_date,
                )
            )
    finally:
        if store is not None:
            store.close()

    moved = sum(1 for item in results if item.get("status") == "moved")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    print(json.dumps(results, indent=2))
    print(f"Done: {moved} moved, {skipped} skipped, {len(results)} total.")

    if moved and not args.dry_run and not args.skip_catalog:
        content_reuse.rebuild()
        print("Rebuilt content/used.json catalog.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
