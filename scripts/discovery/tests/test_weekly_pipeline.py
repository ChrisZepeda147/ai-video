"""Weekly direct montage batch lifecycle, preflight, and stale-job rules."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

from discovery import weekly
from discovery.command_jobs import create_command_job, now_iso, reconcile_stale_command_jobs
from discovery.command_montage import parse_montage_command
from discovery.motivation_command_brief import compose_from_slot
from discovery.store import DiscoveryStore

MONTAGE_CMD = """
Make a new 9:16 motivational Short using the luxury-clips-montage workflow.
Run `python scripts/build_motivation_job.py` with appropriate flags.
Owner account: chris
Search for audio: David Goggins motivational speech
Visual / B-roll search: ocean drone cinematic
Default target length: 60–90 seconds unless extra instructions override.
"""


class TestWeeklyPipeline(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DiscoveryStore(Path(tmp.name) / "catalog.sqlite")
        self.addCleanup(self.store.close)

    def test_preflight_ok_without_cursor_agent(self) -> None:
        toolchain = {"ok": True, "ffmpeg": True, "ffprobe": True, "yt_dlp": True}
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "discovery.cursor_bridge.agent_available", return_value=False
        ), patch("toolchain_env.check_toolchain", return_value=toolchain):
            result = weekly.weekly_preflight()
        self.assertTrue(result["ok"])
        self.assertFalse(result["agent_available"])

    def test_weekly_brief_blank_extra_reuse_allow(self) -> None:
        brief = compose_from_slot(
            {"speaker": "David Goggins", "visual_direction": "ocean", "owner": "chris", "week_start": "2026-09-28", "day": "mon", "slot": 1},
        )
        plan = parse_montage_command(brief)
        assert plan is not None
        self.assertEqual(plan["reuse_policy"], "allow")

    def test_extra_never_used_require_new(self) -> None:
        text = MONTAGE_CMD + "\nExtra instructions:\nNever use anything we've used before.\n"
        plan = parse_montage_command(text)
        assert plan is not None
        self.assertEqual(plan["reuse_policy"], "require_new")

    def test_stale_reconcile_does_not_fail_young_empty_stdout_montage(self) -> None:
        create_command_job(self.store, user_command=MONTAGE_CMD)
        row = self.store._conn.execute(
            "SELECT job_key FROM cursor_command_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        job_key = str(row["job_key"])
        ts = datetime.now(timezone.utc).isoformat()
        self.store._conn.execute(
            """
            UPDATE cursor_command_jobs
            SET status = 'running', started_at = ?, stdout_log = ''
            WHERE job_key = ?
            """,
            (ts, job_key),
        )
        self.store._conn.commit()
        result = reconcile_stale_command_jobs(self.store)
        self.assertEqual(result["stale_failed"], 0)
        st = self.store._conn.execute(
            "SELECT status FROM cursor_command_jobs WHERE job_key = ?", (job_key,)
        ).fetchone()
        self.assertEqual(st["status"], "running")

    @patch("discovery.command_montage.spawn_direct_montage_job")
    def test_slot_lifecycle_running_before_render(self, _spawn) -> None:
        toolchain = {"ok": True}
        at_spawn: list[dict] = []

        def spawn_side_effect(store, job_key):
            row = store._conn.execute(
                "SELECT status, job_key FROM weekly_slots WHERE slot = 1"
            ).fetchone()
            at_spawn.append({"status": row["status"], "job_key": row["job_key"]})
            self.store._conn.execute(
                """
                UPDATE cursor_command_jobs
                SET status = 'completed', completed_at = ?
                WHERE job_key = ?
                """,
                (now_iso(), job_key),
            )
            self.store._conn.commit()

        _spawn.side_effect = spawn_side_effect

        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v1"},
                {"day": "mon", "slot": 2, "speaker": "B", "visual_direction": "v2"},
                {"day": "mon", "slot": 3, "speaker": "C", "visual_direction": "v3"},
            ],
        )
        slots = weekly.due_slots(self.store, day="2026-09-28", owner="chris")
        slot1 = slots[0]

        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ):
            weekly.weekly_submit_command(
                self.store,
                user_command=weekly.slot_command_text(slot1),
                slot_id=int(slot1["id"]),
                wait_montage=True,
                wait_timeout_sec=120,
            )

        self.assertEqual(len(at_spawn), 1)
        self.assertEqual(at_spawn[0]["status"], "running")
        self.assertTrue(str(at_spawn[0]["job_key"] or "").startswith("cmd_"))
        row = self.store._conn.execute(
            "SELECT status, job_key FROM weekly_slots WHERE id = ?", (slot1["id"],)
        ).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertTrue(str(row["job_key"] or "").startswith("cmd_"))
        _spawn.assert_called_once()
        job = self.store._conn.execute(
            "SELECT status FROM cursor_command_jobs WHERE job_key = ?", (row["job_key"],)
        ).fetchone()
        self.assertEqual(job["status"], "completed")

        others = self.store._conn.execute(
            "SELECT job_key FROM weekly_slots WHERE plan_id = ? AND slot IN (2, 3)",
            (slot1["plan_id"],),
        ).fetchall()
        for o in others:
            self.assertFalse(str(o["job_key"] or "").strip())

    def test_serial_three_and_continue_after_failure(self) -> None:
        toolchain = {"ok": True}
        calls: list[int] = []
        attempts: dict[int, int] = {}

        def submit(store, user_command, slot_id=None, **_kw):
            sid = int(slot_id or 0)
            calls.append(sid)
            attempts[sid] = attempts.get(sid, 0) + 1
            slot_one = self.store._conn.execute(
                "SELECT id FROM weekly_slots WHERE slot = 1"
            ).fetchone()
            slot_one_id = int(slot_one["id"]) if slot_one else -1
            if sid == slot_one_id and attempts[sid] == 1:
                weekly.mark_slot(store, sid, status="failed", error="boom")
                raise RuntimeError("boom")
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            weekly.mark_slot(store, sid, status="running", job_key=job_key)
            self.store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            self.store._conn.commit()
            weekly._sync_slot_from_job(store, sid, job_key)
            return {"job_key": job_key, "status": "completed"}

        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v1"},
                {"day": "mon", "slot": 2, "speaker": "B", "visual_direction": "v2"},
                {"day": "mon", "slot": 3, "speaker": "C", "visual_direction": "v3"},
            ],
        )
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ), patch("discovery.weekly._slot_retry_sleep_sec", return_value=0):
            result = weekly.run_weekly_due_batch(
                self.store,
                day="2026-09-28",
                owner="chris",
                limit=3,
                submit_fn=submit,
            )
        self.assertEqual(result["count"], 3)
        slot_one_id = int(
            self.store._conn.execute("SELECT id FROM weekly_slots WHERE slot = 1").fetchone()["id"]
        )
        slot_two_id = int(
            self.store._conn.execute("SELECT id FROM weekly_slots WHERE slot = 2").fetchone()["id"]
        )
        self.assertGreaterEqual(calls.count(slot_one_id), 2)
        first_slot_two = calls.index(slot_two_id)
        self.assertEqual(first_slot_two, 1)
        self.assertEqual(calls[0], slot_one_id)
        failed = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE slot = 1"
        ).fetchone()
        self.assertEqual(failed["status"], "done")

    def test_fill_day_requeues_failed_until_done(self) -> None:
        toolchain = {"ok": True}
        attempts: dict[int, int] = {}

        slot_one_id = None

        def submit(store, user_command, slot_id=None, **_kw):
            nonlocal slot_one_id
            sid = int(slot_id or 0)
            if slot_one_id is None:
                row = store._conn.execute(
                    "SELECT id FROM weekly_slots WHERE slot = 1"
                ).fetchone()
                slot_one_id = int(row["id"]) if row else sid
            attempts[sid] = attempts.get(sid, 0) + 1
            if sid == slot_one_id and attempts[sid] == 1:
                weekly.mark_slot(store, sid, status="failed", error="boom")
                raise RuntimeError("boom")
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            weekly.mark_slot(store, sid, status="running", job_key=job_key)
            self.store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            self.store._conn.commit()
            weekly._sync_slot_from_job(store, sid, job_key)
            return {"job_key": job_key, "status": "completed"}

        weekly.save_slots(
            self.store,
            week_start="2026-10-12",
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v1"},
                {"day": "mon", "slot": 2, "speaker": "B", "visual_direction": "v2"},
                {"day": "mon", "slot": 3, "speaker": "C", "visual_direction": "v3"},
            ],
        )
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ), patch("discovery.weekly.weekly_submit_command", side_effect=submit):
            result = weekly.run_weekly_fill_day(
                self.store,
                day="2026-10-12",
                owner="chris",
            )
        self.assertTrue(result.get("complete"))
        stats = result.get("today_stats") or {}
        self.assertEqual(int(stats.get("done") or 0), 3)
        self.assertGreaterEqual(
            attempts.get(slot_one_id or 0, 0),
            2,
        )

    def test_automation_backlog_mon_before_tue(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-10-12",
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v1"},
                {"day": "tue", "slot": 1, "speaker": "B", "visual_direction": "v2"},
            ],
        )
        mon = weekly.slot_date("2026-10-12", "mon")
        tue = weekly.slot_date("2026-10-12", "tue")
        backlog = weekly.automation_calendar_days_to_fill(
            self.store,
            owner="chris",
            through=__import__("datetime").date.fromisoformat(tue),
        )
        self.assertEqual(backlog, [mon, tue])


class TestWeeklyRoundRobin(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DiscoveryStore(Path(tmp.name) / "catalog.sqlite")
        self.addCleanup(self.store.close)
        self.rr_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.rr_dir.cleanup)
        self.rr_path = Path(self.rr_dir.name) / "weekly-round-robin.json"
        self.rr_patch = patch("discovery.weekly._round_robin_state_path", return_value=self.rr_path)
        self.rr_patch.start()
        self.addCleanup(self.rr_patch.stop)

    def _save_three(self, week_start: str = "2026-10-12") -> dict[int, int]:
        weekly.save_slots(
            self.store,
            week_start=week_start,
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v1"},
                {"day": "mon", "slot": 2, "speaker": "B", "visual_direction": "v2"},
                {"day": "mon", "slot": 3, "speaker": "C", "visual_direction": "v3"},
            ],
        )
        out: dict[int, int] = {}
        for n in (1, 2, 3):
            row = self.store._conn.execute(
                "SELECT id FROM weekly_slots WHERE slot = ?", (n,)
            ).fetchone()
            out[n] = int(row["id"])
        return out

    def _slot_id(self, slot_no: int) -> int:
        row = self.store._conn.execute(
            "SELECT id FROM weekly_slots WHERE slot = ?", (slot_no,)
        ).fetchone()
        return int(row["id"])

    def _apply_preflight(self, stack: ExitStack) -> None:
        toolchain = {"ok": True}
        stack.enter_context(
            patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe")
        )
        stack.enter_context(patch("toolchain_env.check_toolchain", return_value=toolchain))
        stack.enter_context(patch("discovery.weekly.production_queue_busy", return_value=False))

    def test_failed_v1_waits_for_v2_v3_before_retry(self) -> None:
        ids = self._save_three()
        calls: list[int] = []

        def submit(store, user_command, slot_id=None, **_kw):
            sid = int(slot_id or 0)
            calls.append(sid)
            if sid == ids[1]:
                weekly.prepare_slot_for_retry(store, sid, error="fail v1")
                return {"job_key": "cmd_x", "status": "failed"}
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            weekly.mark_slot(store, sid, status="running", job_key=job_key)
            store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            store._conn.commit()
            weekly._sync_slot_from_job(store, sid, job_key)
            return {"job_key": job_key, "status": "completed"}

        day = weekly.slot_date("2026-10-12", "mon")
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            for _ in range(4):
                weekly.weekly_automation_tick(self.store, day=day, owner="chris")

        self.assertGreaterEqual(len(calls), 4)
        self.assertEqual(calls[0], ids[1])
        self.assertEqual(calls[1], ids[2])
        self.assertEqual(calls[2], ids[3])
        self.assertEqual(calls[3], ids[1])

    def test_done_slots_skipped_on_later_passes(self) -> None:
        ids = self._save_three()
        weekly.mark_slot(self.store, ids[2], status="done")
        calls: list[int] = []

        def submit(store, user_command, slot_id=None, **_kw):
            calls.append(int(slot_id or 0))
            weekly.prepare_slot_for_retry(store, int(slot_id or 0), error="nope")
            return {"job_key": "cmd_x", "status": "failed"}

        day = weekly.slot_date("2026-10-12", "mon")
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            for _ in range(4):
                weekly.weekly_automation_tick(self.store, day=day, owner="chris")

        self.assertNotIn(ids[2], calls)
        self.assertEqual(calls[:2], [ids[1], ids[3]])

    def test_two_failures_then_success_rotates(self) -> None:
        ids = self._save_three()
        calls: list[int] = []

        def submit(store, user_command, slot_id=None, **_kw):
            sid = int(slot_id or 0)
            calls.append(sid)
            if sid in {ids[1], ids[2]}:
                weekly.prepare_slot_for_retry(store, sid, error="fail")
                return {"job_key": "cmd_x", "status": "failed"}
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            weekly.mark_slot(store, sid, status="running", job_key=job_key)
            store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            store._conn.commit()
            weekly._sync_slot_from_job(store, sid, job_key)
            return {"job_key": job_key, "status": "completed"}

        day = weekly.slot_date("2026-10-12", "mon")
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            for _ in range(5):
                weekly.weekly_automation_tick(self.store, day=day, owner="chris")

        self.assertEqual(calls[:3], [ids[1], ids[2], ids[3]])
        self.assertEqual(calls[3], ids[1])
        self.assertEqual(calls[4], ids[2])

    def test_all_fail_repeatedly_keeps_going(self) -> None:
        ids = self._save_three()
        n_ticks = 12

        def submit(store, user_command, slot_id=None, **_kw):
            weekly.prepare_slot_for_retry(store, int(slot_id or 0), error="fail")
            return {"job_key": "cmd_x", "status": "failed"}

        day = weekly.slot_date("2026-10-12", "mon")
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            for _ in range(n_ticks):
                result = weekly.weekly_automation_tick(self.store, day=day, owner="chris")
                self.assertEqual(result.get("action"), "attempted")

        for n in (1, 2, 3):
            st = self.store._conn.execute(
                "SELECT status FROM weekly_slots WHERE slot = ?", (n,)
            ).fetchone()
            self.assertEqual(str(st["status"]), "queued")

    def test_assets_persist_across_round_robin_retries(self) -> None:
        from discovery.config import project_root
        from discovery.motivation_paths import default_job_date, job_dir_for, motivation_jobs_root

        ids = self._save_three()
        root = project_root()
        job_dir = job_dir_for(
            "weekly-chris-2026-10-12-mon-1",
            motivation_jobs_root(root),
            job_date=default_job_date(),
        )
        job_dir.mkdir(parents=True, exist_ok=True)
        sidecar = job_dir / "broll_acquire.json"
        sidecar.write_text('{"failed_source_ids": ["xyz"]}', encoding="utf-8")

        def submit(store, user_command, slot_id=None, **_kw):
            if int(slot_id or 0) == ids[1]:
                weekly.prepare_slot_for_retry(store, ids[1], error="fail")
            return {"job_key": "cmd_x", "status": "failed"}

        day = weekly.slot_date("2026-10-12", "mon")
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            weekly.weekly_automation_tick(self.store, day=day, owner="chris")
            weekly.weekly_automation_tick(self.store, day=day, owner="chris")

        self.assertTrue(sidecar.is_file())
        self.assertIn("xyz", sidecar.read_text(encoding="utf-8"))

    def test_api_restart_resumes_round_robin_cursor(self) -> None:
        ids = self._save_three()
        day = weekly.slot_date("2026-10-12", "mon")
        calls: list[int] = []

        def submit(store, user_command, slot_id=None, **_kw):
            calls.append(int(slot_id or 0))
            weekly.prepare_slot_for_retry(store, int(slot_id or 0), error="fail")
            return {"job_key": "cmd_x", "status": "failed"}

        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            weekly.weekly_automation_tick(self.store, day=day, owner="chris")
        self.assertEqual(calls, [ids[1]])
        self.assertEqual(weekly.get_round_robin_cursor(owner="chris", day=day), 2)

        calls.clear()
        with ExitStack() as stack:
            self._apply_preflight(stack)
            stack.enter_context(
                patch("discovery.weekly.weekly_submit_command", side_effect=submit)
            )
            weekly.weekly_automation_tick(self.store, day=day, owner="chris")
        self.assertEqual(calls, [ids[2]])


class TestWeeklyDaemonLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DiscoveryStore(Path(tmp.name) / "catalog.sqlite")
        self.addCleanup(self.store.close)
        weekly.stop_weekly_automation()
        weekly.repair_stale_automation_state()

    def tearDown(self) -> None:
        weekly.stop_weekly_automation()
        import time

        time.sleep(0.05)
        weekly.repair_stale_automation_state()

    def test_stale_flag_starts_new_daemon(self) -> None:
        weekly._automation_running = True  # noqa: SLF001
        weekly._automation_thread = None  # noqa: SLF001
        toolchain = {"ok": True}
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ), patch("discovery.production_pause.is_production_paused", return_value=False):
            out = weekly.ensure_weekly_automation_started()
        self.assertTrue(out.get("started"))
        self.assertTrue(weekly.automation_daemon_alive())
        weekly.stop_weekly_automation()

    def test_live_daemon_not_duplicated(self) -> None:
        toolchain = {"ok": True}
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ), patch("discovery.production_pause.is_production_paused", return_value=False):
            first = weekly.ensure_weekly_automation_started()
            second = weekly.ensure_weekly_automation_started()
        self.assertTrue(first.get("started"))
        self.assertEqual(second.get("reason"), "automation_already_running")
        self.assertTrue(weekly.automation_daemon_alive())
        weekly.stop_weekly_automation()

    def test_daemon_finally_clears_state(self) -> None:
        import time

        toolchain = {"ok": True}
        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ), patch("discovery.production_pause.is_production_paused", return_value=True):
            weekly.ensure_weekly_automation_started()
        time.sleep(0.3)
        self.assertFalse(weekly.automation_daemon_alive())
        self.assertFalse(weekly._automation_running)  # noqa: SLF001

    def test_day_status_not_7am_failed_when_queued(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-10-12",
            owner="chris",
            slots=[{"day": "wed", "slot": 1, "speaker": "J", "visual_direction": "v"}],
        )
        day = weekly.slot_date("2026-10-12", "wed")
        with patch("discovery.weekly.past_morning_cutoff", return_value=True), patch(
            "discovery.weekly.automation_daemon_alive", return_value=True
        ):
            st = weekly.day_morning_status(self.store, day=day, owner="chris")
        self.assertEqual(st["outcome"], "in_progress")
        self.assertNotIn("7am", st.get("status_line") or "")

    def test_health_peek_has_no_submit_side_effect(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-10-12",
            owner="chris",
            slots=[{"day": "wed", "slot": 1, "speaker": "J", "visual_direction": "v"}],
        )
        day = weekly.slot_date("2026-10-12", "wed")
        before = weekly.get_round_robin_cursor(owner="chris", day=day)
        snap = weekly.automation_health_snapshot(self.store, owner="chris")
        after = weekly.get_round_robin_cursor(owner="chris", day=day)
        self.assertEqual(before, after)
        self.assertIsNotNone(snap.get("next_slot_id"))


if __name__ == "__main__":
    unittest.main()
