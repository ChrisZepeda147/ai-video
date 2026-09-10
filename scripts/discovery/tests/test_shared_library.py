"""Tests for Stephen shared library export/import and Git safety."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from discovery.config import project_root
from discovery.shared_library import (
    build_manifest_from_job,
    export_manifest_package,
    export_stephen_after_register,
    export_stephen_existing,
    find_video_by_manifest_id,
    import_all_stephen_packages,
    import_manifest,
    manifest_id_for,
)
from discovery.shared_library_git import (
    commit_and_push,
    pull_shared_library,
    unrelated_changes,
)
from discovery.store import DiscoveryStore


class SharedLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "test.sqlite"
        self.store = DiscoveryStore(self.db_path)
        self.slug = f"stephen-test-{uuid.uuid4().hex[:8]}"
        self.job_dir = self.root / "downloads" / "motivational" / self.slug
        audio_dir = self.job_dir / "audio"
        clips_dir = self.job_dir / "clips"
        output_dir = self.job_dir / "output"
        audio_dir.mkdir(parents=True)
        clips_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)

        (audio_dir / "speech.mp3").write_bytes(b"stephen-speech-bytes-" + uuid.uuid4().bytes)
        (audio_dir / "subs.en.json3").write_text(
            json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Stay hard."}]}]}),
            encoding="utf-8",
        )
        (clips_dir / "clip_part01.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42stephenclip")
        (output_dir / f"{self.slug}-motivation.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42stephenfinal")
        (self.job_dir / "job.json").write_text(
            json.dumps(
                {
                    "speaker": "Andrew Tate",
                    "speech_title": "Stephen Test Video",
                    "speech_id": "stephen123456",
                    "speech_url": "https://www.youtube.com/watch?v=stephen123456",
                    "audio_duration": 62.0,
                    "broll_ids": ["brollA", "brollB"],
                    "visual_style": "luxury supercar cinematic",
                }
            ),
            encoding="utf-8",
        )
        (self.job_dir / "url.txt").write_text(
            "https://www.youtube.com/watch?v=stephen123456\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    @patch("discovery.shared_library.project_root")
    def test_export_existing_without_rerender(self, mock_root) -> None:
        mock_root.return_value = self.root
        result = export_stephen_existing(self.store, root=self.root)
        self.assertEqual(result["exported"], 1)
        package = self.root / "shared_library" / "stephen" / self.slug
        self.assertTrue((package / "manifest.json").is_file())
        self.assertTrue((package / "final.mp4").is_file())
        self.assertTrue((package / "audio" / "speech.mp3").is_file())
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["owner"], "stephen")
        self.assertEqual(manifest["speaker"], "Andrew Tate")

    @patch("discovery.shared_library.project_root")
    def test_import_registers_owner_and_components(self, mock_root) -> None:
        mock_root.return_value = self.root
        export_stephen_existing(self.store, root=self.root)
        package = self.root / "shared_library" / "stephen" / self.slug
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))

        first = import_manifest(self.store, manifest, package_dir=package, root=self.root)
        self.assertEqual(first["status"], "imported")
        video = self.store._conn.execute(
            "SELECT metadata_json FROM production_library_videos WHERE id = ?",
            (first["video_id"],),
        ).fetchone()
        meta = json.loads(video["metadata_json"])
        self.assertEqual(meta["owner"], "stephen")
        self.assertEqual(meta["shared_library"]["manifest_id"], manifest["manifest_id"])

        components = self.store._conn.execute(
            "SELECT component_type FROM production_video_components WHERE video_id = ?",
            (first["video_id"],),
        ).fetchall()
        types = {row["component_type"] for row in components}
        self.assertIn("audio", types)
        self.assertIn("caption", types)
        self.assertIn("visual", types)

    @patch("discovery.shared_library.project_root")
    def test_duplicate_import_is_idempotent(self, mock_root) -> None:
        mock_root.return_value = self.root
        export_stephen_existing(self.store, root=self.root)
        package = self.root / "shared_library" / "stephen" / self.slug
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        first = import_manifest(self.store, manifest, package_dir=package, root=self.root)
        second = import_manifest(self.store, manifest, package_dir=package, root=self.root)
        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["status"], "already_imported")
        self.assertEqual(first["video_id"], second["video_id"])

    @patch("discovery.shared_library.project_root")
    def test_import_all_and_combination_board(self, mock_root) -> None:
        mock_root.return_value = self.root
        export_stephen_existing(self.store, root=self.root)
        result = import_all_stephen_packages(self.store, root=self.root)
        self.assertEqual(result["imported"], 1)
        from discovery.combinations import list_audio_catalog, list_visual_packs

        audio = list_audio_catalog(self.store)
        packs = list_visual_packs(self.store)
        self.assertGreaterEqual(len(audio), 1)
        self.assertGreaterEqual(len(packs), 1)

    @patch("discovery.shared_library.project_root")
    def test_auto_export_respects_env_flag(self, mock_root) -> None:
        mock_root.return_value = self.root
        manifest = build_manifest_from_job(self.slug, root=self.root)
        self.assertIsNotNone(manifest)
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(export_stephen_after_register(slug=self.slug, root=self.root))
        with patch.dict(os.environ, {"SHARED_LIBRARY_EXPORT_OWNER": "stephen"}):
            exported = export_stephen_after_register(slug=self.slug, root=self.root)
        self.assertIsNotNone(exported)
        self.assertTrue((self.root / "shared_library" / "stephen" / self.slug / "manifest.json").is_file())

    @patch("discovery.shared_library.project_root")
    def test_chris_library_unchanged_when_no_packages(self, mock_root) -> None:
        mock_root.return_value = self.root
        before = self.store._conn.execute("SELECT COUNT(*) AS n FROM production_library_videos").fetchone()["n"]
        result = import_all_stephen_packages(self.store, root=self.root)
        after = self.store._conn.execute("SELECT COUNT(*) AS n FROM production_library_videos").fetchone()["n"]
        self.assertEqual(result["found"], 0)
        self.assertEqual(before, after)

    def test_manifest_id_stable(self) -> None:
        mid = manifest_id_for(owner="stephen", slug="demo", final_hash="abc123")
        self.assertTrue(mid.startswith("stephen:demo:"))

    @patch("discovery.shared_library_git.unrelated_changes", return_value=["scripts/foo.py"])
    def test_git_refuses_unrelated_changes(self, _mock_unrelated) -> None:
        result = commit_and_push("test", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unrelated_changes")

    @patch("discovery.shared_library_git._run_git")
    @patch("discovery.shared_library_git.unrelated_changes", return_value=[])
    def test_git_push_only_shared_library(self, _mock_unrelated, mock_git) -> None:
        def _git_response(*args, **_kwargs):
            cmd = args[0] if args else []
            if cmd == ["diff", "--cached", "--name-only"]:
                return type("R", (), {"returncode": 0, "stdout": "shared_library/stephen/demo/manifest.json\n", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_git.side_effect = _git_response
        with patch("discovery.shared_library_git.project_root", return_value=self.root):
            (self.root / "shared_library" / "stephen" / "demo").mkdir(parents=True)
            (self.root / ".gitattributes").write_text("shared_library/**/*.mp4 filter=lfs\n", encoding="utf-8")
            result = commit_and_push("shared library test", dry_run=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("committed"))
        self.assertTrue(result.get("pushed"))
        git_cmds = [call.args[0][0] for call in mock_git.call_args_list if call.args and call.args[0]]
        self.assertIn("add", git_cmds)
        self.assertIn("commit", git_cmds)
        self.assertIn("push", git_cmds)

    @patch("discovery.shared_library_git._resolve_remote_ref", return_value="origin/main")
    @patch("discovery.shared_library_git._run_git")
    def test_git_pull_ignores_unrelated_local_changes(self, mock_git, _mock_ref) -> None:
        def _git_response(args, **_kwargs):
            cmd = args[0] if args else []
            if cmd == ["fetch", "origin"] or cmd == ["fetch"]:
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if cmd[0:2] == ["checkout", "origin/main"]:
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if cmd[0:2] == ["lfs", "pull"]:
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_git.side_effect = _git_response
        result = pull_shared_library(dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("method"), "scoped_checkout")


class GitAttributesTests(unittest.TestCase):
    def test_gitattributes_has_lfs_for_shared_library(self) -> None:
        attrs = (project_root() / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("shared_library/**/*.mp4 filter=lfs", attrs)
        self.assertIn("shared_library/**/*.mp3 filter=lfs", attrs)


if __name__ == "__main__":
    unittest.main()
