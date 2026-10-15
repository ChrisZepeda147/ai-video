"""Ad-hoc weekly B-roll validation metrics (not part of production pipeline)."""
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "discovery" / "catalog.sqlite"
FROM_KEY = sys.argv[1] if len(sys.argv) > 1 else "cmd_001076"


def metrics(row) -> dict:
    log = row["stdout_log"] or ""
    m = {"job": row["job_key"], "slot": row["slot_id"] or row["slug"], "status": row["status"]}
    pre = re.search(
        r"BROLL_PREFILTER search_results=(\d+) after_title_match=(\d+) after_prefilter=(\d+)",
        log,
    )
    if pre:
        m["search_results"] = int(pre.group(1))
        m["after_prefilter"] = int(pre.group(3))
    tc = re.search(
        r"downloads_attempted=(\d+) downloads_successful=(\d+) clips_raw=(\d+) clips_usable=(\d+)",
        log,
    )
    if tc:
        m["downloads_attempted"] = int(tc.group(1))
        m["downloads_successful"] = int(tc.group(2))
        m["parts_created"] = int(tc.group(3))
        m["final_usable"] = int(tc.group(4))
    m["timeouts"] = log.count("BROLL_SOURCE_TIMEOUT")
    m["no_50fps"] = log.count("reason=no_50fps_format")
    if row["runtime_seconds"]:
        m["runtime_s"] = row["runtime_seconds"]
    elif row["started_at"] and row["completed_at"]:
        s = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(row["completed_at"]).replace("Z", "+00:00"))
        m["runtime_s"] = round((e - s).total_seconds(), 1)
    m["result"] = "render_ok" if row["final_output_path"] else row["status"]
    tids = set(re.findall(r"BROLL_SOURCE_TIMEOUT id=(\S+)", log))
    m["timeout_stages"] = [
        ln.strip()
        for ln in log.splitlines()
        if any(t in ln for t in tids) and ("BROLL_STAGE" in ln or "BROLL_SOURCE_TIMEOUT" in ln)
    ]
    return m


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT j.job_key, j.status, j.started_at, j.completed_at, j.stdout_log,
               j.final_output_path, i.slot_id, i.slug, i.runtime_seconds
        FROM cursor_command_jobs j
        LEFT JOIN montage_incidents i ON i.job_key = j.job_key
        WHERE j.job_key >= ?
        ORDER BY j.job_key
        """,
        (FROM_KEY,),
    ).fetchall()
    conn.close()
    terminal = [r for r in rows if r["status"] in ("completed", "failed")]
    print(json.dumps({"from": FROM_KEY, "terminal": len(terminal), "total": len(rows)}, indent=2))
    for r in terminal:
        print(json.dumps(metrics(r), indent=2))


if __name__ == "__main__":
    main()
