"""Tests for Stephen + Chris source sync allowlist and rebase safety."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from discovery.brother_code_sync import (
    CHECKPOINT_MESSAGE,
    is_source_path,
    source_paths_from_porcelain,
    sync_source_code,
)


class SourcePathTests(unittest.TestCase):
    def test_allows_scripts_and_web(self) -> None:
        self.assertTrue(is_source_path("scripts/shared_library_sync.py"))
        self.assertTrue(is_source_path("web/lib/types.ts"))
        self.assertTrue(is_source_path(".cursor/rules/brother-sync.mdc"))
        self.assertTrue(is_source_path("scripts/.env.example"))

    def test_denies_secrets_and_local_data(self) -> None:
        self.assertFalse(is_source_path("scripts/.env"))
        self.assertFalse(is_source_path("downloads/motivational/job/output/a.mp4"))
        self.assertFalse(is_source_path("data/shared_library/sync_state.json"))
        self.assertFalse(is_source_path("content/used.json"))
        self.assertFalse(is_source_path("notes/taskbar-outage.md"))

    def test_porcelain_filters_to_source(self) -> None:
        lines = [
            " M scripts/foo.py",
            " M scripts/.env",
            "?? notes/x.md",
            " M web/app/page.tsx",
        ]
        self.assertEqual(
            source_paths_from_porcelain(lines),
            ["scripts/foo.py", "web/app/page.tsx"],
        )


class SyncSourceCodeTests(unittest.TestCase):
    @patch("discovery.brother_code_sync.code_sync_enabled", return_value=False)
    def test_disabled_skips(self, _enabled) -> None:
        result = sync_source_code()
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])

    @patch("discovery.brother_code_sync.git_repo_status")
    @patch("discovery.brother_code_sync.source_paths_from_porcelain", return_value=["scripts/foo.py"])
    @patch("discovery.brother_code_sync.fetch_both", return_value={"ok": True, "fetched": ["origin"], "errors": []})
    def test_dry_run_does_not_commit(self, _fetch, _paths, mock_status) -> None:
        mock_status.return_value = {"commits_behind": 1, "commits_ahead": 0}
        result = sync_source_code(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["would_commit"], ["scripts/foo.py"])

    @patch("discovery.brother_code_sync.git_repo_status")
    @patch("discovery.brother_code_sync._push_both")
    @patch("discovery.brother_code_sync._rebase_onto")
    @patch("discovery.brother_code_sync._ref_exists", return_value=True)
    @patch("discovery.brother_code_sync._stash_if_dirty")
    @patch("discovery.brother_code_sync._auto_commit_source")
    @patch("discovery.brother_code_sync.fetch_both", return_value={"ok": True, "fetched": ["origin", "chris"], "errors": []})
    def test_rebase_conflict_does_not_push(
        self,
        _fetch,
        mock_commit,
        mock_stash,
        _exists,
        mock_rebase,
        mock_push,
        mock_status,
    ) -> None:
        mock_commit.return_value = {"ok": True, "committed": False}
        mock_stash.return_value = {"ok": True, "stashed": False}
        mock_rebase.return_value = {
            "ok": False,
            "conflict": True,
            "error": "conflict in scripts/foo.py",
        }
        mock_status.return_value = {"commits_behind": 1}
        result = sync_source_code()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("conflict"))
        mock_push.assert_not_called()

    @patch("discovery.brother_code_sync._run_git")
    @patch("discovery.brother_code_sync.source_paths_from_porcelain", return_value=["scripts/foo.py"])
    @patch("discovery.brother_code_sync.code_auto_commit_enabled", return_value=True)
    def test_auto_commit_uses_checkpoint_message(self, _enabled, _paths, mock_git) -> None:
        def _git(args, **_kwargs):
            if args[:2] == ["diff", "--cached"]:
                return type("R", (), {"returncode": 0, "stdout": "scripts/foo.py\n", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_git.side_effect = _git
        from discovery.brother_code_sync import _auto_commit_source

        result = _auto_commit_source()
        self.assertTrue(result["ok"])
        self.assertTrue(result["committed"])
        commit_calls = [call.args[0] for call in mock_git.call_args_list]
        self.assertIn(["commit", "-m", CHECKPOINT_MESSAGE], commit_calls)


if __name__ == "__main__":
    unittest.main()
