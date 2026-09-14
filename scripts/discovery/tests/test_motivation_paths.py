"""Tests for dated motivation job folder layout."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discovery.motivation_paths import (
    default_job_date,
    iter_motivation_job_dirs,
    job_dir_for,
    resolve_job_dir,
)


class MotivationPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs_root = Path(self.tmp.name) / "motivational"
        self.jobs_root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_new_job_uses_date_folder(self) -> None:
        day = default_job_date()
        path = job_dir_for("demo-slug", self.jobs_root, job_date=day)
        self.assertEqual(path, self.jobs_root / day / "demo-slug")

    def test_resolve_prefers_dated_over_legacy(self) -> None:
        slug = "same-slug"
        legacy = self.jobs_root / slug
        legacy.mkdir()
        (legacy / "job.json").write_text("{}", encoding="utf-8")

        dated = job_dir_for(slug, self.jobs_root, job_date="2026-09-13")
        dated.mkdir(parents=True)
        (dated / "job.json").write_text("{}", encoding="utf-8")

        resolved = resolve_job_dir(slug, self.jobs_root)
        self.assertEqual(resolved, dated)

    def test_iter_includes_legacy_and_dated(self) -> None:
        legacy = self.jobs_root / "legacy-job"
        legacy.mkdir()
        (legacy / "output").mkdir()

        dated = job_dir_for("dated-job", self.jobs_root, job_date="2026-09-13")
        dated.mkdir(parents=True)
        (dated / "output").mkdir()

        names = {p.name for p in iter_motivation_job_dirs(self.jobs_root)}
        self.assertEqual(names, {"legacy-job", "dated-job"})


if __name__ == "__main__":
    unittest.main()
