import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
from discovery.config import default_db_path, load_env, resolve_worker_python
from discovery.command_jobs import _windows_process_alive, reconcile_running_montage_liveness
from discovery.store import DiscoveryStore

load_env()
s = DiscoveryStore(default_db_path())
reconcile_running_montage_liveness(s)
rows = s._conn.execute(
    "SELECT job_key, worker_pid, progress_note, status FROM cursor_command_jobs WHERE status = 'running'"
).fetchall()
print("worker_python", resolve_worker_python())
for r in rows:
    d = dict(r)
    pid = int(d.get("worker_pid") or 0)
    d["alive_now"] = _windows_process_alive(pid) if pid else False
    print("job", d)
slot = s._conn.execute(
    "SELECT id, slot, status, job_key FROM weekly_slots WHERE id = 61"
).fetchone()
print("slot61", dict(slot) if slot else None)
if rows:
    pid = int(rows[0]["worker_pid"] or 0)
    if pid:
        time.sleep(5)
        print("alive_5s", _windows_process_alive(pid))
        time.sleep(25)
        print("alive_30s", _windows_process_alive(pid))
s.close()
