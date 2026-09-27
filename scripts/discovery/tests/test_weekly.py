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
        import os

        os.environ["CURSOR_BRIDGE_DRY_RUN"] = "1"
        self.addCleanup(os.environ.pop, "CURSOR_BRIDGE_DRY_RUN", None)
        weekly.save_slots(
            self.store,
            week_start="2026-09-28",
            owner="chris",
            slots=[{"day": "mon", "slot": 1, "speaker": "A", "visual_direction": "v"}],
        )
        self.store._conn.execute(
            """
            INSERT INTO cursor_command_jobs
                (job_key, user_command, enriched_prompt, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("cmd_busy", "x", "x", "running", "2026-09-28T00:00:00"),
        )
        self.store._conn.commit()
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
        import os

        os.environ["CURSOR_BRIDGE_DRY_RUN"] = "1"
        self.addCleanup(os.environ.pop, "CURSOR_BRIDGE_DRY_RUN", None)
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

        def fake_submit(store, user_command, agent_model=None):
            calls.append(1)
            return {"job_key": f"cmd_{len(calls):06d}"}

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


if __name__ == "__main__":
    unittest.main()
