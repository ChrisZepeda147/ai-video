#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import content_reuse


REPEAT_SPEECH = (
    "discipline is the only thing that separates winners from losers in this life "
    "you wake up early you do the work you stop making excuses and you build the life "
    "you said you wanted instead of talking about it every night"
)


class SpeechReuseTests(unittest.TestCase):
    def test_fingerprint_is_stable(self) -> None:
        left = content_reuse.speech_fingerprint(REPEAT_SPEECH)
        right = content_reuse.speech_fingerprint(REPEAT_SPEECH.upper() + "!!!")
        self.assertEqual(left["transcript_hash"], right["transcript_hash"])
        self.assertGreater(len(left["transcript_shingles"]), 8)

    def test_repeat_version_on_new_youtube_id(self) -> None:
        catalog = content_reuse.Catalog(
            videos=[
                {
                    "id": "video:aaaaaaaaaaa",
                    "kind": "video",
                    "role": "speech",
                    "title": "Original upload",
                    "youtube_id": "aaaaaaaaaaa",
                    **content_reuse.speech_fingerprint(REPEAT_SPEECH),
                }
            ]
        )
        tweaked = REPEAT_SPEECH.replace("every night", "every single night")
        hits = content_reuse.find_speech_reuse(
            tweaked,
            youtube_id="bbbbbbbbbbb",
            catalog=catalog,
        )
        self.assertTrue(hits)
        self.assertTrue(any("overlap" in hit.reason or "same" in hit.reason for hit in hits))

    def test_different_speech_passes(self) -> None:
        catalog = content_reuse.Catalog(
            videos=[
                {
                    "id": "video:aaaaaaaaaaa",
                    "kind": "video",
                    "role": "speech",
                    "title": "Original upload",
                    "youtube_id": "aaaaaaaaaaa",
                    **content_reuse.speech_fingerprint(REPEAT_SPEECH),
                }
            ]
        )
        other = (
            "the ocean does not care about your schedule the tide comes in and the tide "
            "goes out while fishermen mend nets and gulls argue over scraps of bread"
        )
        hits = content_reuse.find_speech_reuse(other, youtube_id="ccccccccccc", catalog=catalog)
        self.assertEqual(hits, [])

    def test_scan_job_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "downloads" / "motivational" / "demo-job"
            audio = job / "audio"
            audio.mkdir(parents=True)
            (job / "job.json").write_text(
                json.dumps(
                    {
                        "speech_id": "ddddddddddd",
                        "speech_title": "Demo speech",
                        "speech_excerpt": REPEAT_SPEECH,
                    }
                ),
                encoding="utf-8",
            )
            rows = content_reuse.scan_speech_transcripts(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["youtube_id"], "ddddddddddd")
            self.assertEqual(rows[0]["transcript_hash"], content_reuse.speech_fingerprint(REPEAT_SPEECH)["transcript_hash"])

    def test_reset_speeches_keeps_broll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "downloads" / "motivational" / "demo-job"
            audio = jobs / "audio"
            audio.mkdir(parents=True)
            (audio / "speech.mp3").write_bytes(b"x")
            (jobs / "job.json").write_text(
                json.dumps(
                    {
                        "slug": "demo-job",
                        "speech_id": "ddddddddddd",
                        "speech_title": "Demo speech",
                        "speech_excerpt": REPEAT_SPEECH,
                        "broll_ids": ["eeeeeeeeeee"],
                    }
                ),
                encoding="utf-8",
            )
            content_dir = root / "content"
            content_dir.mkdir()
            catalog = content_reuse.Catalog(
                videos=[
                    {
                        "id": "video:ddddddddddd",
                        "kind": "video",
                        "role": "speech",
                        "title": "Demo speech",
                        "youtube_id": "ddddddddddd",
                        "path": "",
                        **content_reuse.speech_fingerprint(REPEAT_SPEECH),
                    },
                    {
                        "id": "video:eeeeeeeeeee",
                        "kind": "video",
                        "title": "eeeeeeeeeee",
                        "youtube_id": "eeeeeeeeeee",
                        "path": "downloads/motivational/demo-job/clips/eeeeeeeeeee_part01.mp4",
                    },
                ]
            )
            content_reuse.save_catalog(catalog, root)

            kept, removed = content_reuse.reset_speeches(root)
            self.assertEqual(len(removed), 1)
            self.assertEqual(removed[0]["youtube_id"], "ddddddddddd")
            self.assertEqual([row["youtube_id"] for row in kept.videos], ["eeeeeeeeeee"])
            self.assertFalse((audio / "speech.mp3").exists())
            job = json.loads((jobs / "job.json").read_text(encoding="utf-8"))
            self.assertNotIn("speech_id", job)
            self.assertEqual(job["broll_ids"], ["eeeeeeeeeee"])
            self.assertNotIn("ddddddddddd", content_reuse.used_youtube_ids(root=root))

    def test_leftover_excerpt_is_not_reuse_without_source_text(self) -> None:
        first = REPEAT_SPEECH
        leftover = (
            "money is a tool not a trophy you stack skills you protect your time "
            "and you walk away from rooms that make you smaller every single week"
        )
        catalog = content_reuse.Catalog(
            videos=[
                {
                    "id": "video:aaaaaaaaaaa:0",
                    "kind": "video",
                    "role": "speech",
                    "title": "Original upload",
                    "youtube_id": "aaaaaaaaaaa",
                    "speech_source_hash": content_reuse.speech_fingerprint(first + " " + leftover)[
                        "transcript_hash"
                    ],
                    **content_reuse.speech_fingerprint(first),
                }
            ]
        )
        hits = content_reuse.find_speech_reuse(leftover, catalog=catalog)
        self.assertEqual(hits, [])

    def test_scan_keeps_two_excerpts_from_same_speech(self) -> None:
        leftover = (
            "money is a tool not a trophy you stack skills you protect your time "
            "and you walk away from rooms that make you smaller every single week"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "downloads" / "motivational"
            for slug, start, text in (
                ("job-one", 0.0, REPEAT_SPEECH),
                ("job-two", 70.0, leftover),
            ):
                job = jobs / slug
                job.mkdir(parents=True)
                (job / "job.json").write_text(
                    json.dumps(
                        {
                            "speech_id": "ddddddddddd",
                            "speech_title": "Demo speech",
                            "speech_excerpt": text,
                            "speech_start": start,
                        }
                    ),
                    encoding="utf-8",
                )
            rows = content_reuse.scan_speech_transcripts(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["id"] for row in rows}, {"video:ddddddddddd:0", "video:ddddddddddd:70000"})


if __name__ == "__main__":
    unittest.main()

