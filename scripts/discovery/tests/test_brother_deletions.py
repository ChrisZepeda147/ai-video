"""Tests for cross-brother deletion log."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from discovery.brother_deletions import (
    append_deletion_record,
    apply_shared_deletions,
    deletions_path,
    load_deletion_log,
)


class BrotherDeletionsTests(unittest.TestCase):
    def test_append_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_deletion_record(owner="stephen", slug="foo-bar", manifest_id="stephen:foo:abc", root=root)
            append_deletion_record(owner="stephen", slug="foo-bar", manifest_id="stephen:foo:abc", root=root)
            data = load_deletion_log(root)
            self.assertEqual(len(data["deletions"]), 1)
            self.assertTrue(deletions_path(root).is_file())

    @patch("discovery.brother_deletions.delete_video")
    @patch("discovery.brother_deletions.find_video_by_manifest_id")
    def test_apply_deletion_removes_video(self, mock_find, mock_delete) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared_library").mkdir(parents=True)
            deletions_path(root).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "deletions": [
                            {
                                "owner": "stephen",
                                "slug": "test-slug",
                                "manifest_id": "stephen:test-slug:deadbeef",
                                "deleted_at": "2026-01-01T00:00:00+00:00",
                                "deleted_by": "stephen",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            mock_find.return_value = {"id": 99}
            store = MagicMock()
            result = apply_shared_deletions(store, root=root)
            self.assertEqual(result["removed_videos"], 1)
            mock_delete.assert_called_once_with(store, 99)


if __name__ == "__main__":
    unittest.main()
