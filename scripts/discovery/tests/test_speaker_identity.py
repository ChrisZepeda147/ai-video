"""Tests for speaker inference and correction memory."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discovery.production_library import register_video
from discovery.speaker_identity import (
    get_correction,
    infer_speaker,
    resolve_registration_speaker,
    save_correction,
    update_video_speaker,
)
from discovery.store import DiscoveryStore


class SpeakerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DiscoveryStore(Path(self.tmp.name) / "test.sqlite")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_infer_jocko_from_title(self) -> None:
        self.assertEqual(
            infer_speaker("JOCKO WILLINK - Motivation", "Motivation Channel"),
            "Jocko Willink",
        )

    def test_infer_goggins(self) -> None:
        self.assertEqual(infer_speaker("David Goggins - Stay Hard", ""), "David Goggins")

    def test_resolve_prefers_inferred_over_intended(self) -> None:
        speaker, meta = resolve_registration_speaker(
            self.store,
            intended="David Goggins",
            title="Jocko Willink: Discipline",
            channel="Jocko Podcast",
            transcript="Get after it.",
            youtube_id="abc12345678",
        )
        self.assertEqual(speaker, "Jocko Willink")
        self.assertEqual(meta.get("search_intent"), "David Goggins")

    def test_correction_memory_overrides_inference(self) -> None:
        save_correction(
            self.store,
            source_external_id="xyz98765432",
            speaker="Jocko Willink",
        )
        speaker, meta = resolve_registration_speaker(
            self.store,
            intended="David Goggins",
            title="Some random title",
            youtube_id="xyz98765432",
        )
        self.assertEqual(speaker, "Jocko Willink")
        self.assertEqual(meta.get("speaker_source"), "correction_memory")
        self.assertEqual(get_correction(self.store, "xyz98765432"), "Jocko Willink")

    def test_update_video_speaker_remembers(self) -> None:
        video = register_video(
            self.store,
            title="Motivation clip",
            speaker="David Goggins",
            source_external_id="vid12345678",
            source_url="https://www.youtube.com/watch?v=vid12345678",
            final_output_path="downloads/test/final.mp4",
            copy_final_to_library=False,
        )
        updated = update_video_speaker(
            self.store,
            int(video["id"]),
            "Jocko Willink",
            remember=True,
        )
        self.assertEqual(updated.get("speaker"), "Jocko Willink")
        self.assertEqual(get_correction(self.store, "vid12345678"), "Jocko Willink")


if __name__ == "__main__":
    unittest.main()
