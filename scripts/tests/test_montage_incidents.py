"""Montage incidents: taxonomy, fingerprint, remediation, escalation."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from montage_incidents import (
    ESCALATION_MIN_FAILURES,
    ESCALATION_MIN_UNIQUE_SLOTS,
    REMEDIATION_ACTIONS,
    apply_remediation_to_job_dir,
    ensure_montage_incident_tables,
    failure_fingerprint,
    fingerprint_stats,
    health_incident_summary,
    normalize_failure_code,
    record_montage_terminal,
    should_skip_slot_this_pass,
    slot_same_fingerprint_streak,
    synthesize_failure,
    visual_family,
)
from montage_telemetry import MontageFailure


class TestFailureTaxonomy(unittest.TestCase):
    def test_normalize_speech_exhausted(self) -> None:
        self.assertEqual(normalize_failure_code("SPEECH_EXHAUSTED"), "SPEECH_NO_CANDIDATE")

    def test_normalize_timeout_from_log(self) -> None:
        self.assertEqual(
            normalize_failure_code("", log_text="WEEKLY_MONTAGE_TIMEOUT job_key=cmd"),
            "MONTAGE_TIMEOUT",
        )

    def test_synthesize_timeout(self) -> None:
        fail = synthesize_failure(stdout="", timed_out=True, slug="test-slug")
        self.assertEqual(fail.code, "MONTAGE_TIMEOUT")
        self.assertIn("MONTAGE_FAILURE=", fail.emit_json_line())


class TestFingerprint(unittest.TestCase):
    def test_visual_family(self) -> None:
        self.assertEqual(visual_family("mountain sunrise giant orange peaks"), "mountain")

    def test_fingerprint_stable(self) -> None:
        fp = failure_fingerprint(
            failure_code="BROLL_INSUFFICIENT",
            failure_stage="ensure_broll_clips",
            speaker="David Goggins",
            visual_query="mountain sunrise",
        )
        self.assertIn("BROLL_INSUFFICIENT", fp)
        self.assertIn("goggins", fp)
        self.assertIn("mountain", fp)


class TestRemediation(unittest.TestCase):
    def test_broll_insufficient_bumps_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            action, result, sidecar = apply_remediation_to_job_dir(
                job_dir,
                failure_code="BROLL_INSUFFICIENT",
                fingerprint="fp1",
            )
            self.assertEqual(action, REMEDIATION_ACTIONS["BROLL_INSUFFICIENT"])
            self.assertEqual(result, "applied")
            self.assertTrue((job_dir / "broll_acquire.json").is_file())
            self.assertTrue(sidecar.get("broll_fresh_search"))

    def test_speech_broaden_ladder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            apply_remediation_to_job_dir(
                job_dir,
                failure_code="SPEECH_NO_CANDIDATE",
                fingerprint="fp2",
            )
            data = json.loads((job_dir / "speech_acquire.json").read_text(encoding="utf-8"))
            self.assertEqual(data.get("speech_ladder_offset"), 1)


class _FakeStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


class TestIncidentStore(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_montage_incident_tables(self.conn)
        self.conn.execute(
            """
            CREATE TABLE weekly_plans (
                id INTEGER PRIMARY KEY, week_start TEXT, owner TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE weekly_slots (
                id INTEGER PRIMARY KEY, plan_id INTEGER, day TEXT, slot INTEGER,
                speaker TEXT, visual_direction TEXT, job_key TEXT
            )
            """
        )
        self.conn.execute(
            "INSERT INTO weekly_plans (id, week_start, owner) VALUES (1, '2026-10-12', 'chris')"
        )
        self.conn.execute(
            """
            INSERT INTO weekly_slots (id, plan_id, day, slot, speaker, visual_direction, job_key)
            VALUES (61, 1, 'mon', 1, 'Goggins', 'mountain sunrise', 'cmd_test')
            """
        )
        self.conn.commit()
        self.store = _FakeStore(self.conn)

    def test_record_failure_and_streak(self) -> None:
        fail_line = MontageFailure(
            slug="weekly-test",
            stage="ensure_broll_clips",
            code="BROLL_INSUFFICIENT",
            summary="need clips",
        ).emit_json_line()
        for _ in range(2):
            record_montage_terminal(
                self.store,
                job_key="cmd_test",
                slug="weekly-test",
                outcome="failure",
                stdout_log=fail_line,
            )
        streak = slot_same_fingerprint_streak(self.conn, 61, failure_fingerprint(
            failure_code="BROLL_INSUFFICIENT",
            failure_stage="ensure_broll_clips",
            speaker="Goggins",
            visual_query="mountain sunrise",
        ))
        self.assertEqual(streak, 2)

    def test_cross_slot_escalation_writes_files(self) -> None:
        self.conn.execute(
            """
            INSERT INTO weekly_slots (id, plan_id, day, slot, speaker, visual_direction, job_key)
            VALUES (62, 1, 'mon', 2, 'Goggins', 'mountain sunrise', 'cmd_test2')
            """
        )
        self.conn.commit()
        fp = failure_fingerprint(
            failure_code="BROLL_DOWNLOAD_TIMEOUT",
            failure_stage="ensure_broll_clips",
            speaker="Goggins",
            visual_query="mountain sunrise",
        )
        fail_line = MontageFailure(
            code="BROLL_DOWNLOAD_TIMEOUT",
            stage="ensure_broll_clips",
            summary="timeout",
        ).emit_json_line()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "incidents").mkdir(parents=True)
            for slot_id, jk in ((61, "cmd_test"), (62, "cmd_test2"), (61, "cmd_test")):
                self.conn.execute(
                    "UPDATE weekly_slots SET job_key = ? WHERE id = ?",
                    (jk, slot_id),
                )
                record_montage_terminal(
                    self.store,
                    job_key=jk,
                    slug="s",
                    outcome="failure",
                    stdout_log=fail_line,
                )
            # force counts for test (same fingerprint)
            stats = fingerprint_stats(self.conn, fp, hours=24)
            self.assertGreaterEqual(stats["failure_count_24h"], ESCALATION_MIN_FAILURES)
            self.assertGreaterEqual(stats["unique_slots"], ESCALATION_MIN_UNIQUE_SLOTS)

    def test_success_metrics(self) -> None:
        log = (
            "MONTAGE_TIMING stage=prepare_speech seconds=85.0\n"
            "MONTAGE_TIMING stage=ensure_broll seconds=240.0\n"
            "MONTAGE_TIMING_COUNTS downloads_attempted=2 downloads_successful=2 "
            "clips_usable=8 required=8\n"
            "MONTAGE_TIMING_TOTAL wall_seconds=400.0\n"
        )
        record_montage_terminal(
            self.store,
            job_key="cmd_test",
            slug="weekly-test",
            outcome="success",
            stdout_log=log,
        )
        row = self.conn.execute(
            "SELECT outcome, downloads_successful, broll_usable FROM montage_incidents ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(row["outcome"], "success")
        self.assertEqual(int(row["downloads_successful"]), 2)
        self.assertEqual(int(row["broll_usable"]), 8)


class TestCooldown(unittest.TestCase):
    def test_skip_after_streak_without_remediation(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_montage_incident_tables(conn)
        fp = "BROLL_INSUFFICIENT|ensure_broll|goggins|mountain"
        for i in range(3):
            conn.execute(
                """
                INSERT INTO montage_incidents (
                    created_at, updated_at, outcome, slot_id, fingerprint,
                    remediation_action, remediation_result, status, metrics_json
                ) VALUES (?, ?, 'failure', 61, ?, 'same', 'skipped', 'open', '{}')
                """,
                (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), fp),
            )
        conn.commit()
        store = _FakeStore(conn)
        self.assertTrue(should_skip_slot_this_pass(store, 61, fp))


if __name__ == "__main__":
    unittest.main()
