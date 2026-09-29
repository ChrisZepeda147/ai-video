"""Weekly direct montage batch lifecycle, preflight, and stale-job rules."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
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
        fail_first = {"n": 0}

        def submit(store, user_command, slot_id=None, **_kw):
            calls.append(int(slot_id or 0))
            fail_first["n"] += 1
            if fail_first["n"] == 1:
                weekly.mark_slot(store, int(slot_id), status="failed", error="boom")
                raise RuntimeError("boom")
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            weekly.mark_slot(store, int(slot_id), status="running", job_key=job_key)
            self.store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            self.store._conn.commit()
            weekly._sync_slot_from_job(store, int(slot_id), job_key)
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
        ):
            result = weekly.run_weekly_due_batch(
                self.store,
                day="2026-09-28",
                owner="chris",
                limit=3,
                submit_fn=submit,
            )
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(set(calls)), 3)
        failed = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE slot = 1"
        ).fetchone()
        self.assertEqual(failed["status"], "failed")


if __name__ == "__main__":
    unittest.main()
