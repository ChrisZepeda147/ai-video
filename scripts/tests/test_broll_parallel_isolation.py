#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broll_acquire_workspace import cleanup_workspace, finalize_parts, source_workspace


class BrollParallelIsolationTests(unittest.TestCase):
    def test_finalize_moves_only_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            clips_dir = job_dir / "clips"
            ws_a = source_workspace(job_dir, "sourceA")
            ws_b = source_workspace(job_dir, "sourceB")
            ws_a.mkdir(parents=True)
            ws_b.mkdir(parents=True)
            part_a = ws_a / "sourceA_part01.mp4"
            part_b = ws_b / "sourceB_part01.mp4"
            part_a.write_bytes(b"a")
            part_b.write_bytes(b"b")
            moved = finalize_parts(ws_a, clips_dir, "sourceA")
            self.assertEqual(len(moved), 1)
            self.assertTrue((clips_dir / "sourceA_part01.mp4").is_file())
            self.assertTrue(part_b.is_file())
            self.assertFalse(ws_a.exists())

    def test_parallel_workers_do_not_share_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            ids = ["alphaVid12345", "betaVid123456"]
            paths = [source_workspace(job_dir, vid) for vid in ids]
            for path in paths:
                path.mkdir(parents=True, exist_ok=True)
            self.assertNotEqual(paths[0], paths[1])

    def test_early_finisher_inventory_scoped_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            clips_dir = job_dir / "clips"
            ws_a = source_workspace(job_dir, "sourceA")
            ws_b = source_workspace(job_dir, "sourceB")
            ws_a.mkdir(parents=True)
            ws_b.mkdir(parents=True)
            (ws_a / "sourceA_part01.mp4").write_bytes(b"a")
            (ws_b / "sourceB_part01.mp4").write_bytes(b"b")
            gate_calls: list[str] = []

            def gate_fn(paths: list[Path]) -> list[Path]:
                gate_calls.extend(p.name for p in paths)
                return paths

            gate_fn(sorted(ws_a.glob("sourceA_part*.mp4")))
            finalize_parts(ws_a, clips_dir, "sourceA")

            def writer_b() -> None:
                time.sleep(0.05)
                (ws_b / "sourceB_part01.mp4").write_bytes(b"b2")

            thread = threading.Thread(target=writer_b)
            thread.start()
            gate_fn(sorted(ws_b.glob("sourceB_part*.mp4")))
            thread.join()
            self.assertEqual(gate_calls, ["sourceA_part01.mp4", "sourceB_part01.mp4"])
            self.assertFalse((clips_dir / "sourceB_part01.mp4").exists())

    def test_download_uses_isolated_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            clips_dir = job_dir / "clips"
            clips_dir.mkdir(parents=True)
            from youtube_popular_downloader import VideoCandidate
            import build_motivation_job as job

            candidate = VideoCandidate(
                video_id="isoVid123456",
                title="Lake",
                url="https://youtu.be/isoVid123456",
                channel="c",
                view_count=1,
                duration_seconds=900.0,
                published_at=None,
                source="search",
                fps=60.0,
            )
            workspace = source_workspace(job_dir, candidate.video_id)
            def _fake_dl(_candidate, *, output_dir, **_k):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"{_candidate.video_id}_part01.mp4").write_bytes(b"x")
                return {"status": "ok", "video_id": _candidate.video_id}

            def _fake_worker(**kwargs):
                ws = source_workspace(job_dir, candidate.video_id)
                ws.mkdir(parents=True, exist_ok=True)
                (ws / f"{candidate.video_id}_part01.mp4").write_bytes(b"x")
                return {
                    "ok": True,
                    "video_id": candidate.video_id,
                    "workspace": str(ws),
                }

            with patch(
                "build_motivation_job.inspect_usable_formats",
                return_value=(True, None, {"height": 1080, "fps": 60.0}),
            ), patch(
                "build_motivation_job.run_broll_source_subprocess",
                side_effect=_fake_worker,
            ) as worker, patch(
                "build_motivation_job.filter_broll_clip_list",
                side_effect=lambda paths, **_: paths,
            ):
                job.download_broll_candidates(
                    clips_dir,
                    [candidate],
                    clip_length=24,
                    max_parts=3,
                    job_dir=job_dir,
                    frame_gate=False,
                    raise_if_empty=False,
                )
                self.assertTrue(worker.called)
                self.assertTrue((clips_dir / f"{candidate.video_id}_part01.mp4").is_file())
            cleanup_workspace(workspace)


if __name__ == "__main__":
    unittest.main()
