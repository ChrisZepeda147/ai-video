"""Tests for brother code auto-pull."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from discovery.brother_code_sync import (
    _pull_is_due,
    auto_pull_enabled,
    maybe_auto_brother_code_pull,
)
from discovery.shared_library_git import safe_ff_pull


class BrotherCodeSyncTests(unittest.TestCase):
    def test_auto_pull_enabled_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(auto_pull_enabled())
        with patch.dict("os.environ", {"BROTHER_AUTO_PULL": "0"}):
            self.assertFalse(auto_pull_enabled())

    def test_pull_is_due_without_last(self) -> None:
        self.assertTrue(_pull_is_due({}))

    def test_pull_is_due_recent(self) -> None:
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertFalse(_pull_is_due({"last_brother_sync_at": recent}, interval_minutes=60))

    @patch("discovery.brother_code_sync.save_sync_state")
    @patch("discovery.brother_code_sync.load_sync_state")
    @patch("discovery.brother_code_sync.sync_source_code")
    @patch("discovery.brother_code_sync.pull_and_import")
    @patch("discovery.brother_code_sync.export_enabled", return_value=False)
    @patch("discovery.brother_code_sync.import_all_shared_packages")
    def test_maybe_auto_pull_imports_on_chris(
        self,
        mock_import,
        _export,
        mock_pull_import,
        mock_code,
        mock_load,
        mock_save,
    ) -> None:
        mock_load.return_value = {}
        mock_pull_import.return_value = {"import": {"imported": 0}}
        mock_code.return_value = {"ok": True, "pull": {"pulled": True, "message": "Pulled 2 commit(s)"}}
        mock_import.return_value = {"imported": 1}
        store = MagicMock()
        result = maybe_auto_brother_code_pull(store, force=True)
        self.assertIsNotNone(result)
        assert result is not None
        mock_pull_import.assert_called_once()
        mock_import.assert_called_once_with(store)
        mock_save.assert_called_once()

    @patch("discovery.shared_library_git.git_repo_status")
    @patch("discovery.shared_library_git._run_git")
    def test_safe_ff_pull_skips_dirty(self, mock_run, mock_status) -> None:
        fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.return_value = fetch
        mock_status.return_value = {"commits_behind": 3, "branch": "main"}
        with patch(
            "discovery.shared_library_git.git_porcelain",
            return_value=[" M scripts/foo.py"],
        ):
            result = safe_ff_pull()
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "dirty_working_tree")
        mock_run.assert_called_once()

    @patch("discovery.shared_library_git.git_repo_status")
    @patch("discovery.shared_library_git._run_git")
    def test_safe_ff_pull_up_to_date(self, mock_run, mock_status) -> None:
        fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.return_value = fetch
        mock_status.return_value = {"commits_behind": 0}
        with patch("discovery.shared_library_git.git_porcelain", return_value=[]):
            result = safe_ff_pull()
        self.assertFalse(result.get("pulled"))
        self.assertEqual(result.get("reason"), "up_to_date")


if __name__ == "__main__":
    unittest.main()
