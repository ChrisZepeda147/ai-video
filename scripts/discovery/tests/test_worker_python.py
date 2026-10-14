"""Weekly worker Python resolution (AI_VIDEO_PYTHON, Store alias guard)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery import config


class TestWorkerPython(unittest.TestCase):
    def test_store_alias_skipped_without_env_file(self) -> None:
        store = (
            r"C:\Users\x\AppData\Local\Microsoft\WindowsApps"
            r"\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"
        )
        with patch.object(config, "_env_file_ai_video_python", return_value=""), patch.object(
            config, "_worker_python_candidates", return_value=[store]
        ), patch.object(config, "_python_can_run_weekly_worker", return_value=True):
            self.assertEqual(config.resolve_worker_python(), "")

    def test_env_file_python_used_when_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = str(Path(tmp) / "python.exe")
            Path(good).write_bytes(b"")
            with patch.object(config, "load_env"), patch.object(
                config, "_env_file_ai_video_python", return_value=good
            ), patch.object(config, "_worker_python_candidates", return_value=[good]), patch.object(
                config, "_python_can_run_weekly_worker", return_value=True
            ):
                self.assertEqual(config.resolve_worker_python(), good)

    def test_invalid_env_file_fails_issue(self) -> None:
        bad = r"C:\missing\python.exe"
        with patch.object(config, "_env_file_ai_video_python", return_value=bad):
            issue = config.resolve_worker_python_issue()
            self.assertIn("not found", issue)

    def test_preflight_uses_same_resolver(self) -> None:
        from discovery.store import DiscoveryStore
        from discovery.weekly import weekly_preflight

        with tempfile.TemporaryDirectory() as tmp:
            store = DiscoveryStore(Path(tmp) / "catalog.sqlite")
            try:
                with patch(
                    "discovery.config.resolve_worker_python", return_value=""
                ), patch(
                    "discovery.config.resolve_worker_python_issue",
                    return_value="AI_VIDEO_PYTHON is not configured",
                ), patch("toolchain_env.check_toolchain", return_value={"ok": True}):
                    pf = weekly_preflight()
                self.assertFalse(pf["ok"])
                self.assertIn("AI_VIDEO_PYTHON", pf["issues"][0])
                self.assertIsNone(pf.get("worker_python"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
