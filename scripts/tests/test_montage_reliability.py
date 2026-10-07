#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_clips_montage as montage
import build_motivation_job as job
from broll_usable import BrollInventory, measure_usable_broll
from discovery.montage_job_errors import command_job_error_summary
from montage_telemetry import MontageFailure, resolve_actionable_error


class MontageReliabilityTests(unittest.TestCase):
    def test_driven_pacing_does_not_require_beat_count_files(self) -> None:
        for duration in (60.0, 76.0, 90.0):
            needed = montage.unique_clips_required(
                target_duration=duration,
                segment_length=montage.segment_length_for_duration(duration),
                layout="single",
                driven_pacing=True,
                subject="Porsche 911 exterior cinematic 60fps",
            )
            beats = montage.estimate_montage_beats(
                target_duration=duration,
                segment_length=montage.segment_length_for_duration(duration),
                driven_pacing=True,
                subject="Porsche 911 exterior cinematic 60fps",
            )
            self.assertGreaterEqual(needed, 3)
            self.assertLessEqual(needed, 8)
            self.assertGreater(beats, needed)
            self.assertLess(needed, 20)

    def test_raw_vs_gated_readiness(self) -> None:
        clips_dir = Path("test-raw-gated-broll")
        clips_dir.mkdir(exist_ok=True)
        try:
            for idx in range(10):
                (clips_dir / f"vid_part{idx:02d}.mp4").write_bytes(b"x")
            gate_calls = {"n": 0}

            def gate_fn(paths: list[Path]) -> list[Path]:
                gate_calls["n"] += 1
                return paths[:3]

            inv = measure_usable_broll(clips_dir, required=6, gate_fn=gate_fn)
            self.assertEqual(inv.raw, 10)
            self.assertEqual(inv.usable_count, 3)
            self.assertFalse(inv.satisfies_count())
        finally:
            for p in clips_dir.glob("*"):
                p.unlink(missing_ok=True)
            clips_dir.rmdir()

    def test_one_source_can_satisfy_when_count_met(self) -> None:
        inv = BrollInventory(raw=4, usable=[Path("a_part01.mp4")] * 6, required=6)
        self.assertTrue(inv.satisfies_count())
        self.assertEqual(inv.distinct_sources, 1)

    def test_gate_cache_skips_rescan(self) -> None:
        clip = Path("test-gate-cache-clip.mp4")
        clip.write_bytes(b"clip-bytes")
        jobs_root = Path("test-gate-cache-root")
        try:
            patches = (
                patch("build_motivation_job.probe_duration", return_value=12.0),
                patch("build_clips_montage.probe_fps", return_value=60.0),
                patch(
                    "build_motivation_job.longest_clean_span",
                    return_value=(0.0, 12.0),
                ),
            )
            with patches[0], patches[1], patches[2], patch(
                "build_motivation_job.scan_clip_local",
                return_value=[MagicMock(start=0.0, end=12.0, score=1.0)],
            ):
                job.filter_broll_clip_list(
                    [clip],
                    subject="mountain sunrise cinematic",
                    frame_gate=True,
                    use_vision=False,
                    jobs_root=jobs_root,
                )
            with patches[0], patches[1], patches[2], patch(
                "build_motivation_job.scan_clip_local"
            ) as scan:
                kept = job.filter_broll_clip_list(
                    [clip],
                    subject="mountain sunrise cinematic",
                    frame_gate=True,
                    use_vision=False,
                    jobs_root=jobs_root,
                )
                scan.assert_not_called()
            self.assertEqual(len(kept), 1)
        finally:
            clip.unlink(missing_ok=True)
            import shutil

            shutil.rmtree(jobs_root, ignore_errors=True)

    def test_retry_excludes_failed_source_ids(self) -> None:
        import broll_acquire_state

        job_dir = Path("test-acquire-exclude")
        job_dir.mkdir(exist_ok=True)
        try:
            broll_acquire_state.record_failed_source(job_dir, "badvideo12")
            state = broll_acquire_state.load_state(job_dir)
            exclude = set(state["failed_source_ids"])
            batch = [
                MagicMock(video_id="badvideo12"),
                MagicMock(video_id="goodvideo99"),
            ]
            with patch(
                "build_motivation_job._discover_broll_candidates_for_search",
                return_value=batch,
            ):
                filtered = job._discover_candidates_for_query(
                    "mountain sunrise",
                    limit=5,
                    subject="mountain sunrise",
                    min_views=0,
                    min_duration=0,
                    reuse_policy="allow",
                    exclude_source_ids=exclude,
                )
            self.assertEqual([item.video_id for item in filtered], ["goodvideo99"])
        finally:
            state_file = job_dir / "broll_acquire.json"
            if state_file.is_file():
                state_file.unlink()
            job_dir.rmdir()

    def test_structured_failure_summary_for_weekly(self) -> None:
        failure = MontageFailure(
            slug="weekly-chris-tue-1",
            code="BROLL_INSUFFICIENT",
            summary="B-roll insufficient: need 6 usable clips, have 3 after gate from 2 sources.",
        )
        log = failure.emit_json_line() + "\nother noise"
        job_row = {
            "error_summary": failure.summary,
            "stdout_log": log,
            "error_message": "=== build 1/1 ===\nCursor review (default): keeping clips/",
        }
        self.assertEqual(
            command_job_error_summary(job_row),
            failure.summary,
        )

    def test_resolve_actionable_error_ignores_startup_noise(self) -> None:
        log = (
            "=== build 1/1 (weekly-chris-tue-1) ===\n"
            "Cursor review (default): keeping clips/ for agent inspection.\n"
            "Job: weekly-chris-tue-1\n"
            "MONTAGE_STAGE=ensure_broll status=fail needed=6 have=3 sources=2\n"
        )
        summary, _ = resolve_actionable_error(log, "")
        self.assertIn("ensure_broll", summary)
        self.assertNotIn("Cursor review", summary)

    def test_broaden_query_preserves_subject(self) -> None:
        from broll_search_query import broaden_broll_query_ladder

        ladder = broaden_broll_query_ladder("foggy mountain sunrise cinematic drone")
        joined = " ".join(ladder).lower()
        self.assertIn("mountain", joined)
        self.assertNotIn("yacht", joined)


if __name__ == "__main__":
    unittest.main()
