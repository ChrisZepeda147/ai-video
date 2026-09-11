#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import taskbar_crash_watch as watch


def _event(**kwargs: object) -> watch.CrashEvent:
    raw = {
        "RecordId": 10,
        "Time": "2026-09-10T11:27:03.0000000-07:00",
        "EventId": 1000,
        "Provider": "Application Error",
        "AppName": "StartMenuExperienceHost.exe",
        "ModuleName": "Windows.UI.Xaml.dll",
        "ExceptionCode": "c0000409",
        "FaultingOffset": "0000000000690cee",
    }
    raw.update(kwargs)
    return watch.parse_event(raw)


class TaskbarCrashWatchTests(unittest.TestCase):
    def test_parses_windows_roundtrip_timestamp(self) -> None:
        event = _event(Time="2026-09-10T11:27:03.0000000-07:00")
        stamp = watch.event_stamp(event)
        self.assertGreater(stamp, 1_700_000_000)

    def test_classifies_xaml_fastfail(self) -> None:
        event = _event()
        self.assertEqual(event.kind, "xaml-fastfail")
        self.assertTrue(watch.is_watched_app(event.app_name))

    def test_classifies_explorer_hang(self) -> None:
        event = _event(
            EventId=1002,
            AppName="explorer.exe",
            ModuleName="",
            ExceptionCode="",
            Provider="Application Hang",
        )
        self.assertEqual(event.kind, "explorer-hang")

    def test_ignores_unrelated_crash(self) -> None:
        self.assertFalse(watch.is_watched_app("chrome.exe"))

    def test_groups_clustered_shell_failures(self) -> None:
        hang = _event(
            RecordId=1,
            Time="2026-09-10T11:26:29.0000000-07:00",
            EventId=1002,
            AppName="explorer.exe",
            ModuleName="",
            ExceptionCode="",
        )
        start = _event(RecordId=2, Time="2026-09-10T11:27:03.0000000-07:00")
        search = _event(
            RecordId=3,
            Time="2026-09-10T11:27:03.0000000-07:00",
            AppName="SearchHost.exe",
        )
        later = _event(
            RecordId=4,
            Time="2026-09-10T12:10:00.0000000-07:00",
            AppName="explorer.exe",
            EventId=1002,
            ModuleName="",
            ExceptionCode="",
        )
        groups = watch.group_events([later, search, hang, start])
        self.assertEqual(len(groups), 2)
        incident = watch.incident_from_group(groups[0])
        self.assertEqual(incident.kind, "xaml-fastfail")
        self.assertEqual(len(incident.events), 3)

    def test_third_party_filters_windows_modules(self) -> None:
        modules = [
            r"C:\Windows\System32\Windows.UI.Xaml.dll",
            r"C:\Program Files\NVIDIA Corporation\NVIDIA App\NvCpl\nvui.dll",
            r"C:\Program Files\Windows Defender\shellext.dll",
        ]
        third = watch.third_party_modules(modules)
        self.assertEqual(third, [modules[1], modules[2]])
        self.assertEqual(watch.suspect_modules(modules), [modules[1]])

    def test_hidden_run_kwargs_hide_console_on_windows(self) -> None:
        kwargs = watch.hidden_run_kwargs()
        if os.name != "nt":
            self.assertEqual(kwargs, {})
            return
        self.assertEqual(kwargs["creationflags"], watch.CREATE_NO_WINDOW)
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)

    def test_seed_record_id_keeps_existing_cursor(self) -> None:
        self.assertEqual(watch.seed_record_id(64465), 64465)

    def test_seed_explorer_pids_resets_after_reboot(self) -> None:
        pids, reset = watch.seed_explorer_pids([12492], [12720])
        self.assertEqual(pids, [12720])
        self.assertTrue(reset)

    def test_seed_explorer_pids_keeps_live_overlap(self) -> None:
        pids, reset = watch.seed_explorer_pids([12720], [12720])
        self.assertEqual(pids, [12720])
        self.assertFalse(reset)

    def test_should_recover_needs_strikes_then_cooldown(self) -> None:
        do_it, strikes = watch.should_recover(True, 0, 2, 0.0, 100.0, 90.0)
        self.assertFalse(do_it)
        self.assertEqual(strikes, 1)
        do_it, strikes = watch.should_recover(True, 1, 2, 0.0, 112.0, 90.0)
        self.assertTrue(do_it)
        self.assertEqual(strikes, 0)
        do_it, strikes = watch.should_recover(True, 1, 2, 100.0, 120.0, 90.0)
        self.assertFalse(do_it)
        do_it, _ = watch.should_recover(False, 3, 2, 0.0, 200.0, 90.0)
        self.assertFalse(do_it)

    def test_run_accepts_log_dir_after_command(self) -> None:
        args = watch.build_parser().parse_args(
            ["run", "--log-dir", r"C:\tmp\watch", "--poll-sec", "9"]
        )
        self.assertEqual(args.command, "run")
        self.assertEqual(args.log_dir, Path(r"C:\tmp\watch"))
        self.assertEqual(args.poll_sec, 9)

    def test_diagnose_is_a_command(self) -> None:
        args = watch.build_parser().parse_args(["diagnose"])
        self.assertEqual(args.command, "diagnose")

    def test_startup_vbs_runs_hidden_pythonw(self) -> None:
        script = Path(r"C:\repo\scripts\taskbar_crash_watch.py")
        log_dir = Path(r"C:\Users\Zev\AppData\Local\TaskbarCrashWatch")
        text = watch.startup_vbs_text(script, log_dir)
        self.assertIn("WScript.Sleep 25000", text)
        self.assertIn("taskbar_crash_watch.py", text)
        self.assertIn("TaskbarCrashWatch", text)
        self.assertIn("--no-auto-recover", text)
        self.assertIn(", 0, False", text)

    def test_run_argv_disables_auto_recover(self) -> None:
        argv = watch.run_argv(
            Path(r"C:\repo\scripts\taskbar_crash_watch.py"),
            Path(r"C:\Users\Zev\AppData\Local\TaskbarCrashWatch"),
        )
        self.assertIn("--no-auto-recover", argv)

    def test_write_incident_logs_dll_names(self) -> None:
        event = _event()
        incident = watch.incident_from_group(
            [event],
            {"SuspectModules": [r"C:\Program Files\NVIDIA Corporation\NVIDIA App\NvCpl\nvui.dll"]},
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            path = watch.write_incident(log_dir, incident)
            payload = json.loads(path.read_text(encoding="utf-8"))
            log = (log_dir / "watch.log").read_text(encoding="utf-8")
            self.assertEqual(payload["kind"], "xaml-fastfail")
            self.assertIn("nvui.dll", log)


if __name__ == "__main__":
    unittest.main()
