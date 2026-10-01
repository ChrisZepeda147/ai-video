"""Tests for weekly 7am plans (tables, Sunday feed, due query)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discovery import weekly
from discovery.store import DiscoveryStore


class TestWeekly(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DiscoveryStore(Path(tmp.name) / "catalog.sqlite")
        self.addCleanup(self.store.close)

    def test_save_and_due(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[
                {"day": "mon", "slot": 1, "speaker": "David Goggins", "visual_direction": "ocean"},
                {"day": "mon", "slot": 2, "speaker": "Jocko", "visual_direction": "gym"},
                {"day": "tue", "slot": 1, "speaker": "Tate", "visual_direction": "cars"},
            ],
        )
        due = weekly.due_slots(self.store, day="2026-09-28", owner="chris")
        self.assertEqual(len(due), 2)
        self.assertEqual(due[0]["speaker"], "David Goggins")
        other = weekly.due_slots(self.store, day="2026-09-29", owner="chris")
        self.assertEqual(len(other), 1)

    def test_owners_separate(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        due = weekly.due_slots(self.store, day="2026-09-28", owner="stephen")
        self.assertEqual(due, [])

    def test_reconcile_marks_done(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        slot = weekly.due_slots(self.store, day="2026-09-28", owner="chris")[0]
        self.store._conn.execute(
            """
            INSERT INTO cursor_command_jobs
                (job_key, user_command, enriched_prompt, status, production_video_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("cmd_000099", "x", "x", "completed", None, "2026-09-28T00:00:00"),
        )
        self.store._conn.commit()
        weekly.mark_slot(self.store, int(slot["id"]), status="running", job_key="cmd_000099")
        result = weekly.reconcile_slots(self.store)
        self.assertEqual(result, {"reconciled_done": 1, "reconciled_failed": 0})
        row = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE id = ?", (slot["id"],)
        ).fetchone()
        self.assertEqual(row["status"], "done")

    def test_brief_includes_style_refs(self) -> None:
        brief = weekly.build_slot_brief(
            {"speaker": "Tate", "visual_direction": "yacht", "owner": "chris"},
            image_paths=["downloads/weekly/chris/2026-09-28/images/a.jpg"],
        )
        self.assertIn("Style-ref", brief)
        self.assertIn("a.jpg", brief)
        self.assertIn("record combination usage", brief)

    def test_brief_includes_images_to_make(self) -> None:
        brief = weekly.build_slot_brief(
            {"speaker": "Tate", "visual_direction": "yacht", "image_prompt": "black 911, night fog"},
            image_paths=[],
        )
        self.assertIn("Images to make", brief)
        self.assertIn("dark-luxury-still", brief)

    def test_weekly_model_default(self) -> None:
        import os

        os.environ.pop("WEEKLY_AGENT_MODEL", None)
        self.assertEqual(weekly.weekly_agent_model(), "composer-2.5-fast")

    def test_zombie_reconcile_keeps_queued_rerunning_without_job(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        slot = weekly.due_slots(self.store, day="2026-09-28", owner="chris")[0]
        weekly.mark_slot(self.store, int(slot["id"]), status="rerunning", job_key=None, reset_job_key=True)
        weekly.reconcile_zombie_weekly_slots(self.store)
        row = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE id = ?", (slot["id"],)
        ).fetchone()
        self.assertEqual(row["status"], "queued")
        self.assertEqual(len(weekly.due_slots(self.store, day="2026-09-28", owner="chris")), 1)

    def test_requeue_failed_slot(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        slot = weekly.due_slots(self.store, day="2026-09-28", owner="chris")[0]
        weekly.mark_slot(self.store, int(slot["id"]), status="failed", error="boom")
        self.assertFalse(weekly.requeue_slot(self.store, int(slot["id"]) + 9999))
        self.assertTrue(weekly.requeue_slot(self.store, int(slot["id"])))
        due = weekly.due_slots(self.store, day="2026-09-28", owner="chris")
        self.assertEqual(len(due), 1)

    def test_run_batch_defers_when_command_running(self) -> None:
        from discovery.command_jobs import now_iso

        toolchain = {"ok": True}
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        ts = now_iso()
        self.store._conn.execute(
            """
            INSERT INTO cursor_command_jobs
                (job_key, user_command, enriched_prompt, status, created_at, started_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("cmd_busy", "x", "x", "running", ts, ts),
        )
        self.store._conn.commit()
        from unittest.mock import patch

        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ):
            result = weekly.run_weekly_due_batch(
                self.store,
                day="2026-09-28",
                owner="chris",
                dry_run=False,
                serial=True,
                submit_fn=lambda *a, **k: {"job_key": "should_not_run"},
            )
        self.assertTrue(result["deferred"])
        self.assertEqual(result["count"], 0)

    def test_save_preserves_done_status(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        slot = weekly.due_slots(self.store, day="2026-09-28", owner="chris")[0]
        weekly.mark_slot(self.store, int(slot["id"]), status="done")
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        row = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE id = ?", (slot["id"],)
        ).fetchone()
        self.assertEqual(row["status"], "done")

    def test_morning_batch_submits_three(self) -> None:
        from discovery.command_jobs import create_command_job, now_iso

        toolchain = {"ok": True}
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
        calls: list[int] = []

        def fake_submit(store, user_command, slot_id=None, **_kw):
            calls.append(int(slot_id or 0))
            record = create_command_job(store, user_command=user_command)
            job_key = str(record["job_key"])
            if slot_id is not None:
                weekly.mark_slot(store, int(slot_id), status="running", job_key=job_key)
            store._conn.execute(
                "UPDATE cursor_command_jobs SET status = 'completed', completed_at = ? WHERE job_key = ?",
                (now_iso(), job_key),
            )
            store._conn.commit()
            if slot_id is not None:
                weekly._sync_slot_from_job(store, int(slot_id), job_key)
            return {"job_key": job_key, "status": "completed"}

        from unittest.mock import patch

        with patch("discovery.config.resolve_python_exe", return_value="C:/Python/python.exe"), patch(
            "toolchain_env.check_toolchain", return_value=toolchain
        ):
            result = weekly.run_weekly_due_batch(
                self.store,
                day="2026-09-28",
                owner="chris",
                limit=3,
                serial=False,
                submit_fn=fake_submit,
            )
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(calls), 3)

    def test_run_batch_dry_run(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        result = weekly.run_weekly_due_batch(
            self.store, day="2026-09-28", owner="chris", dry_run=True
        )
        self.assertEqual(result["due_count"], 1)

    def test_restart_day_cancels_job_and_requeues_slot(self) -> None:
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "wed", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        slot = self.store._conn.execute(
            "SELECT id FROM weekly_slots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.store._conn.execute(
            """
            INSERT INTO cursor_command_jobs
                (job_key, user_command, enriched_prompt, status, created_at, started_at)
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            ("cmd_stuck", "x", "x", "2026-10-01T00:00:00", "2026-10-01T00:00:00"),
        )
        self.store._conn.commit()
        weekly.mark_slot(self.store, int(slot["id"]), status="running", job_key="cmd_stuck")
        from unittest.mock import patch

        def fake_batch(*_a, **_k):
            return {"count": 0}

        with patch("discovery.production_pause.kill_local_montage_workers", return_value=0), patch(
            "discovery.weekly.run_weekly_due_batch", side_effect=fake_batch
        ) as mock_run:
            out = weekly.restart_weekly_day_batch(
                self.store,
                day="2026-09-30",
                owner="chris",
                run_after=True,
                kill_workers=False,
            )
        self.assertEqual(out["jobs_cancelled"], 1)
        self.assertEqual(out["slots_reset"], 1)
        st = self.store._conn.execute(
            "SELECT status FROM weekly_slots WHERE id = ?", (slot["id"],)
        ).fetchone()
        self.assertEqual(st["status"], "queued")
        job = self.store._conn.execute(
            "SELECT status FROM cursor_command_jobs WHERE job_key = 'cmd_stuck'"
        ).fetchone()
        self.assertEqual(job["status"], "cancelled")
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
