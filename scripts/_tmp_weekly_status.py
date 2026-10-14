from discovery.config import default_db_path, load_env
from discovery.store import DiscoveryStore
from discovery import weekly
from discovery.command_jobs import get_command_job

load_env()
s = DiscoveryStore(default_db_path())
owner = "chris"
backlog = weekly.automation_calendar_days_to_fill(s, owner=owner)
print("backlog", backlog)
print("pass", weekly.get_backlog_pass_state(owner=owner))
for d in backlog:
    print("---", d)
    for row in weekly.slots_for_calendar_day(s, day=d, owner=owner):
        sid = int(row["id"])
        st = weekly._slot_status(s, sid)
        err = (row.get("error_message") or "")[:200]
        jk = row.get("job_key")
        job = get_command_job(s, str(jk)) if jk else None
        jerr = ""
        if job:
            jerr = (job.get("error_message") or job.get("last_error") or "")[:300]
        print(
            f"  slot={row.get('slot')} id={sid} status={st} job={jk}"
        )
        if err:
            print(f"    slot_err={err}")
        if jerr:
            print(f"    job_err={jerr}")
peek = (
    weekly.peek_next_backlog_pass_slot(s, owner=owner, calendar_days=backlog)
    if backlog
    else None
)
if peek:
    print("next_peek", peek[0], "slot", peek[1].get("slot"), "id", peek[1].get("id"))
else:
    print("next_peek None")
print("queue_busy", weekly.production_queue_busy(s, owner=None, heal=True))
print("daemon_alive", weekly.automation_daemon_alive())
# recent mon jobs
rows = s._conn.execute(
    """
    SELECT job_key, status, error_message, progress_note, worker_pid, created_at, completed_at
    FROM cursor_command_jobs
    WHERE job_key LIKE 'cmd_%'
    ORDER BY id DESC LIMIT 8
    """
).fetchall()
print("--- recent jobs")
for r in rows:
    print(dict(r))
s.close()
