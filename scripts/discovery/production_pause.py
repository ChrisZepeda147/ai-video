"""Pause / cancel active production jobs on this machine (DB + optional process hint)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from discovery.config import default_db_path, project_root
from discovery.store import DiscoveryStore
from discovery.weekly import mark_slot, reconcile_slots


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pause_local_production(
    store,
    *,
    reason: str = "Paused on this PC",
    owner: str | None = None,
) -> dict[str, int | list[str]]:
    """Cancel running/queued command jobs; reset weekly slots waiting on them."""
    msg = reason.strip() or "Paused on this PC"
    jobs = store._conn.execute(
        """
        SELECT job_key FROM cursor_command_jobs
        WHERE status IN ('running', 'queued')
        ORDER BY created_at DESC
        """
    ).fetchall()
    job_keys = [str(r["job_key"]) for r in jobs]
    if job_keys:
        store._conn.executemany(
            """
            UPDATE cursor_command_jobs
            SET status = 'cancelled', error_message = ?, completed_at = ?
            WHERE job_key = ?
            """,
            [(msg, _now_iso(), key) for key in job_keys],
        )

    slot_query = """
        SELECT s.id, s.plan_id, p.owner
        FROM weekly_slots s
        JOIN weekly_plans p ON p.id = s.plan_id
        WHERE s.status IN ('running', 'rerunning')
    """
    slot_args: list = []
    if owner:
        slot_query += " AND p.owner = ?"
        slot_args.append(owner.strip().lower())
    slot_rows = store._conn.execute(slot_query, slot_args).fetchall()
    plan_ids: set[int] = set()
    for row in slot_rows:
        mark_slot(
            store,
            int(row["id"]),
            status="queued",
            job_key=None,
            error=msg,
            reset_job_key=True,
        )
        plan_ids.add(int(row["plan_id"]))

    store._conn.commit()
    reconcile_slots(store)
    return {
        "jobs_cancelled": len(job_keys),
        "job_keys": job_keys,
        "slots_reset": len(slot_rows),
    }


def kill_local_montage_workers(root: Path | None = None) -> int:
    """Stop detached run_direct_job / build_motivation_job / motivational ffmpeg (Windows)."""
    root = root or project_root()
    if sys.platform != "win32":
        return 0
    script = root / "scripts" / "pause_production.ps1"
    if not script.is_file():
        return 0
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-KillOnly",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stdout:
            print(result.stdout.strip())
        return 0 if result.returncode == 0 else result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Pause active video production on this machine.")
    parser.add_argument("--owner", help="Only reset weekly slots for this owner (chris|stephen)")
    parser.add_argument("--reason", default="Paused on this PC")
    args = parser.parse_args()

    store = DiscoveryStore(default_db_path())
    try:
        result = pause_local_production(store, reason=args.reason, owner=args.owner)
    finally:
        store.close()

    print(f"Cancelled {result['jobs_cancelled']} command job(s).")
    if result["job_keys"]:
        for key in result["job_keys"][:12]:
            print(f"  - {key}")
    print(f"Reset {result['slots_reset']} weekly slot(s) to queued.")
    print(f"Repo: {project_root()}")
    print("Run scripts/pause_production.ps1 to kill leftover ffmpeg/python workers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
