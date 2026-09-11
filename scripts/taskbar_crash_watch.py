#!/usr/bin/env python3
"""Watch Windows taskbar / Explorer shell crashes. Log the exact fault.

Runs at logon, polls Application Error / Hang events, and snapshots
third-party DLLs inside explorer.exe when the shell dies.

Examples:
  python scripts/taskbar_crash_watch.py report --days 14
  python scripts/taskbar_crash_watch.py install --start
  python scripts/taskbar_crash_watch.py run
  python scripts/taskbar_crash_watch.py uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_NAME = "TaskbarCrashWatch"
DEFAULT_POLL_SEC = 12
GROUP_WINDOW_SEC = 45
HANG_STRIKES_NEEDED = 2
RECOVER_COOLDOWN_SEC = 90
START_HOST_EXE = Path(
    r"C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe"
)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
WATCH_APPS = (
    "explorer.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "runtimebroker.exe",
    "sihost.exe",
    "dwm.exe",
    "textinputhost.exe",
    "shellhost.exe",
    "taskbar.exe",
)
SUSPECT_HINTS = (
    "nvidia",
    "nvui",
    "razer",
    "lghub",
    "crosshair",
    "faceit",
    "nzxt",
    "discord",
    "vanguard",
    "netlimiter",
    "mullvad",
    "overlay",
    "explorerpatcher",
    "startallback",
    "windhawk",
    "translucenttb",
    "displayfusion",
    "powertoys",
)

PS_EVENTS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$Hours = __HOURS__
$MaxEvents = __MAX_EVENTS__
$AfterRecordId = __AFTER_RECORD_ID__
$start = (Get-Date).AddHours(-[Math]::Max($Hours, 1))
$raw = @(Get-WinEvent -FilterHashtable @{
    LogName = 'Application'
    Id = 1000, 1001, 1002
    StartTime = $start
} -MaxEvents $MaxEvents)
$items = foreach ($ev in $raw) {
    if ($AfterRecordId -gt 0 -and [int64]$ev.RecordId -le $AfterRecordId) { continue }
    $xml = [xml]$ev.ToXml()
    $map = @{}
    foreach ($node in @($xml.Event.EventData.Data)) {
        if ($node.Name) { $map[$node.Name] = [string]$node.'#text' }
    }
    [PSCustomObject]@{
        RecordId = [int64]$ev.RecordId
        Time = $ev.TimeCreated.ToString('o')
        EventId = [int]$ev.Id
        Provider = [string]$ev.ProviderName
        AppName = [string]$map.AppName
        ModuleName = [string]$map.ModuleName
        ExceptionCode = [string]$map.ExceptionCode
        FaultingOffset = [string]$map.FaultingOffset
        AppPath = [string]$map.AppPath
        ModulePath = [string]$map.ModulePath
        HangType = [string]$map.HangType
        ProcessId = [string]$map.ProcessId
    }
}
ConvertTo-Json -Compress -Depth 4 -InputObject @($items)
"""

PS_SNAPSHOT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$mods = @()
$pids = @()
Get-Process explorer -ErrorAction SilentlyContinue | ForEach-Object {
    $pids += $_.Id
    foreach ($mod in @($_.Modules)) {
        if (-not $mod.FileName) { continue }
        $mods += $mod.FileName
    }
}
$procs = @(Get-CimInstance Win32_Process | Sort-Object WorkingSetSize -Descending | Select-Object -First 18 | ForEach-Object {
    [PSCustomObject]@{
        Pid = [int]$_.ProcessId
        Name = [string]$_.Name
        Path = [string]$_.ExecutablePath
        WsMb = [int][Math]::Round(($_.WorkingSetSize / 1MB))
    }
})
$hosts = @('explorer','StartMenuExperienceHost','ShellExperienceHost','SearchHost','sihost','dwm','TextInputHost')
$running = @(Get-Process -Name $hosts -ErrorAction SilentlyContinue | ForEach-Object {
    [PSCustomObject]@{ Name = $_.Name; Pid = $_.Id }
})
[PSCustomObject]@{
    ExplorerPids = @($pids)
    Modules = @($mods | Sort-Object -Unique)
    TopProcesses = $procs
    ShellHosts = $running
} | ConvertTo-Json -Compress -Depth 5
"""

PS_EXPLORER_PIDS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$pids = @(Get-Process explorer -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
ConvertTo-Json -Compress -InputObject @($pids)
"""

PS_DIAGNOSE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ver = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$files = @(
  'C:\Windows\System32\Windows.UI.Xaml.dll',
  'C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe',
  'C:\Windows\explorer.exe'
) | ForEach-Object {
  $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($_)
  [PSCustomObject]@{ Path = $_; FileVersion = $vi.FileVersion }
}
$pkg = Get-AppxPackage Microsoft.Windows.StartMenuExperienceHost
$exp = @(Get-Process explorer)
$nvui = @()
foreach ($p in $exp) {
  $nvui += @($p.Modules | Where-Object { $_.FileName -match 'nvui|NVIDIA App\\' } | ForEach-Object { $_.FileName })
}
$hosts = @('explorer','StartMenuExperienceHost','SearchHost','ShellExperienceHost','sihost') | ForEach-Object {
  $p = Get-Process $_ -ErrorAction SilentlyContinue
  if ($p) { [PSCustomObject]@{ Name = $_.ToString(); Pid = $p.Id; Responding = [bool]$p.Responding; Start = $p.StartTime.ToString('o') } }
}
$nvc = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'nvcontainer|NVIDIA App' } | ForEach-Object {
  [PSCustomObject]@{ Pid = $_.ProcessId; Name = $_.Name; Command = $_.CommandLine }
})
Add-Type -AssemblyName System.Windows.Forms
$screens = @([System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
  [PSCustomObject]@{ Primary = $_.Primary; Bounds = $_.Bounds.ToString(); Working = $_.WorkingArea.ToString() }
})
$monitors = @(Get-CimInstance WmiMonitorID -Namespace root\wmi | ForEach-Object {
  $name = ($_.UserFriendlyName | Where-Object { $_ } | ForEach-Object { [char]$_ }) -join ''
  [PSCustomObject]@{ Name = $name; Active = $_.Active }
})
$events = @()
$raw = @(Get-WinEvent -FilterHashtable @{ LogName='Application'; Id=1000,1002; StartTime=(Get-Date).AddHours(-8) } -MaxEvents 12)
foreach ($ev in $raw) {
  $xml = [xml]$ev.ToXml()
  $map = @{}
  foreach ($node in @($xml.Event.EventData.Data)) { if ($node.Name) { $map[$node.Name] = [string]$node.'#text' } }
  $app = $map.AppName; if (-not $app) { $app = ($ev.Message -split "`n")[0] }
  $events += [PSCustomObject]@{
    Time = $ev.TimeCreated.ToString('o'); Id = $ev.Id; App = $app
    Module = $map.ModuleName; Code = $map.ExceptionCode; Offset = $map.FaultingOffset
  }
}
[PSCustomObject]@{
  Build = $ver.CurrentBuild; UBR = $ver.UBR; DisplayVersion = $ver.DisplayVersion
  Files = $files
  StartPackage = $(if ($pkg) { "$($pkg.Version) $($pkg.Status)" } else { 'MISSING' })
  ExplorerResponding = -not [bool]($exp | Where-Object { -not $_.Responding })
  NvuiInExplorer = @($nvui | Select-Object -Unique)
  Hosts = $hosts
  Nvidia = $nvc
  Screens = $screens
  Monitors = $monitors
  RecentEvents = $events
} | ConvertTo-Json -Compress -Depth 6
"""


@dataclass
class CrashEvent:
    record_id: int
    time: str
    event_id: int
    provider: str
    app_name: str
    module_name: str
    exception_code: str
    faulting_offset: str
    app_path: str = ""
    module_path: str = ""
    hang_type: str = ""
    process_id: str = ""
    kind: str = ""
    source: str = "event"

    def app_key(self) -> str:
        return (self.app_name or "").strip().lower()


@dataclass
class Incident:
    started_at: str
    kind: str
    events: list[CrashEvent] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def add(self, event: CrashEvent) -> None:
        self.events.append(event)
        if event.kind == "xaml-fastfail":
            self.kind = "xaml-fastfail"
        elif event.kind == "explorer-hang" and self.kind not in {"xaml-fastfail"}:
            self.kind = "explorer-hang"


def default_log_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "TaskbarCrashWatch"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_event(raw: dict[str, Any], source: str = "event") -> CrashEvent:
    event = CrashEvent(
        record_id=int(raw.get("RecordId") or 0),
        time=str(raw.get("Time") or ""),
        event_id=int(raw.get("EventId") or 0),
        provider=str(raw.get("Provider") or ""),
        app_name=str(raw.get("AppName") or ""),
        module_name=str(raw.get("ModuleName") or ""),
        exception_code=str(raw.get("ExceptionCode") or "").lower(),
        faulting_offset=str(raw.get("FaultingOffset") or ""),
        app_path=str(raw.get("AppPath") or ""),
        module_path=str(raw.get("ModulePath") or ""),
        hang_type=str(raw.get("HangType") or ""),
        process_id=str(raw.get("ProcessId") or ""),
        source=source,
    )
    event.kind = classify_event(event)
    return event


def classify_event(event: CrashEvent) -> str:
    app = event.app_key()
    module = (event.module_name or "").lower()
    code = (event.exception_code or "").lower().removeprefix("0x")
    if event.source == "pid":
        return "explorer-restart"
    if event.event_id == 1002 and app == "explorer.exe":
        return "explorer-hang"
    if "windows.ui.xaml.dll" in module and code.endswith("c0000409"):
        return "xaml-fastfail"
    if event.event_id == 1002:
        return "app-hang"
    if event.event_id == 1000:
        return "app-crash"
    return "other"


def is_watched_app(app_name: str) -> bool:
    return (app_name or "").strip().lower() in WATCH_APPS


def third_party_modules(modules: list[str]) -> list[str]:
    hits: list[str] = []
    for path in modules:
        low = path.lower()
        if "\\windows\\" in low or "\\microsoft\\" in low:
            continue
        hits.append(path)
    return hits


def suspect_modules(modules: list[str]) -> list[str]:
    hits: list[str] = []
    for path in third_party_modules(modules):
        low = path.lower()
        if any(token in low for token in SUSPECT_HINTS):
            hits.append(path)
    return hits


def pythonw_path() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        return exe
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return exe


def hidden_run_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {
        "startupinfo": startup,
        "creationflags": CREATE_NO_WINDOW,
    }


def run_powershell(script: str, timeout: int = 25) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w",
        suffix=".ps1",
        delete=False,
        encoding="utf-8",
        newline="\n",
    )
    handle.write(script)
    handle.close()
    path = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **hidden_run_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"powershell timed out after {timeout}s") from exc
    finally:
        path.unlink(missing_ok=True)
    if result.returncode != 0 and not result.stdout.strip():
        err = (result.stderr or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(err)
    return result.stdout.strip()


def load_json_list(text: str) -> list[Any]:
    if not text:
        return []
    data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def fetch_events(hours: int, max_events: int, after_record_id: int = 0) -> list[CrashEvent]:
    script = (
        PS_EVENTS
        .replace("__HOURS__", str(int(hours)))
        .replace("__MAX_EVENTS__", str(int(max_events)))
        .replace("__AFTER_RECORD_ID__", str(int(after_record_id)))
    )
    try:
        raw_items = load_json_list(run_powershell(script, timeout=40))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bad event json: {exc}") from exc
    events = [parse_event(item) for item in raw_items if isinstance(item, dict)]
    return [event for event in events if is_watched_app(event.app_name)]


def explorer_pids() -> list[int]:
    raw = load_json_list(run_powershell(PS_EXPLORER_PIDS, timeout=12))
    pids: list[int] = []
    for item in raw:
        try:
            pids.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(pids)


def take_snapshot() -> dict[str, Any]:
    raw = run_powershell(PS_SNAPSHOT, timeout=20)
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        return {"error": "bad snapshot json"}
    modules = [str(item) for item in data.get("Modules") or []]
    data["ThirdPartyModules"] = third_party_modules(modules)
    data["SuspectModules"] = suspect_modules(modules)
    return data


def restart_event(old_pids: list[int], new_pids: list[int]) -> CrashEvent:
    return parse_event(
        {
            "RecordId": 0,
            "Time": utc_now(),
            "EventId": 0,
            "Provider": "taskbar-crash-watch",
            "AppName": "explorer.exe",
            "ModuleName": "",
            "ExceptionCode": "",
            "FaultingOffset": "",
            "ProcessId": f"{old_pids}->{new_pids}",
        },
        source="pid",
    )


def event_stamp(event: CrashEvent) -> float:
    if not event.time:
        return time.time()
    text = event.time.replace("Z", "+00:00")
    if "." in text:
        head, rest = text.split(".", 1)
        digits = ""
        tz = ""
        for char in rest:
            if char.isdigit():
                digits += char
                continue
            tz = rest[len(digits):]
            break
        text = f"{head}.{digits[:6]}{tz}"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


def group_events(events: list[CrashEvent], window_sec: int = GROUP_WINDOW_SEC) -> list[list[CrashEvent]]:
    if not events:
        return []
    ordered = sorted(events, key=event_stamp)
    groups: list[list[CrashEvent]] = [[ordered[0]]]
    for event in ordered[1:]:
        gap = event_stamp(event) - event_stamp(groups[-1][-1])
        if gap <= window_sec:
            groups[-1].append(event)
            continue
        groups.append([event])
    return groups


def incident_from_group(events: list[CrashEvent], snapshot: dict[str, Any] | None = None) -> Incident:
    kinds = [event.kind for event in events]
    kind = "mixed"
    if "xaml-fastfail" in kinds:
        kind = "xaml-fastfail"
    elif "explorer-hang" in kinds:
        kind = "explorer-hang"
    elif "explorer-restart" in kinds:
        kind = "explorer-restart"
    elif kinds:
        kind = kinds[0]
    return Incident(
        started_at=events[0].time or utc_now(),
        kind=kind,
        events=events,
        snapshot=snapshot or {},
    )


def format_event_line(event: CrashEvent) -> str:
    bits = [event.kind, event.app_name or "?"]
    if event.module_name:
        bits.append(event.module_name)
    if event.exception_code:
        bits.append(event.exception_code)
    if event.faulting_offset:
        bits.append(f"off={event.faulting_offset}")
    return " ".join(bits)


def write_incident(log_dir: Path, incident: Incident) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = log_dir / "incidents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}-{incident.kind}.json"
    payload = {
        "started_at": incident.started_at,
        "kind": incident.kind,
        "events": [asdict(event) for event in incident.events],
        "snapshot": incident.snapshot,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    line = (
        f"{utc_now()}  {incident.kind}  "
        + "; ".join(format_event_line(event) for event in incident.events)
    )
    suspects = incident.snapshot.get("SuspectModules") or incident.snapshot.get("ThirdPartyModules") or []
    if suspects:
        line += "  dlls=" + ", ".join(Path(item).name for item in suspects[:8])
    append_log(log_dir, line)
    return path


def append_log(log_dir: Path, line: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "watch.log").open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def load_state(log_dir: Path) -> dict[str, Any]:
    path = log_dir / "state.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(log_dir: Path, state: dict[str, Any]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def summarize_events(events: list[CrashEvent]) -> list[str]:
    counts: dict[str, int] = {}
    for event in events:
        key = f"{event.kind} | {event.app_name or '?'} | {event.module_name or '-'}"
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"{count:3d}  {label}" for label, count in ranked]


def cmd_report(log_dir: Path, days: int) -> int:
    hours = max(days, 1) * 24
    events = fetch_events(hours=hours, max_events=200, after_record_id=0)
    print(f"log dir: {log_dir}")
    print(f"watched shell events in last {days}d: {len(events)}")
    print("")
    if not events:
        print("no explorer / start / search crash events.")
        return 0
    print("pattern counts")
    for line in summarize_events(events):
        print(line)
    print("")
    print("latest 8")
    for event in events[:8]:
        when = event.time[:19] if event.time else "?"
        print(f"  {when}  {format_event_line(event)}")
    print("")
    snapshot = take_snapshot()
    third = snapshot.get("ThirdPartyModules") or []
    suspects = snapshot.get("SuspectModules") or []
    print("explorer third-party DLLs now")
    if not third:
        print("  (none)")
    for path in third:
        print(f"  {path}")
    if suspects:
        print("")
        print("suspect overlays / injectors now")
        for path in suspects:
            print(f"  {path}")
    print("")
    print("read: explorer hang + Start/Search/Shell crash in Windows.UI.Xaml.dll c0000409")
    print("that is the XAML shell stack, not a random app.")
    print(f"next crash dumps a snapshot under {log_dir / 'incidents'}")
    return 0


def cmd_run(log_dir: Path, poll_sec: int, auto_recover: bool = True) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(log_dir)
    last_record = int(state.get("last_record_id") or 0)
    live_pids = explorer_pids()
    known_pids, reset_pids = seed_explorer_pids(
        [int(item) for item in state.get("explorer_pids") or []],
        live_pids,
    )
    if reset_pids:
        append_log(log_dir, f"{utc_now()}  seed-pids  stale={state.get('explorer_pids')}  live={live_pids}")
    if last_record <= 0:
        last_record = seed_record_id(0)
        append_log(log_dir, f"{utc_now()}  seed-record  last_record_id={last_record}")
    append_log(
        log_dir,
        f"{utc_now()}  watch-start  pids={known_pids}  auto_recover={auto_recover}  python={sys.executable}",
    )
    save_state(
        log_dir,
        {
            "last_record_id": last_record,
            "explorer_pids": known_pids,
            "started_at": utc_now(),
        },
    )
    pending: list[CrashEvent] = []
    recover_state = {"strikes": 0, "last_recover": 0.0, "auto": auto_recover}
    try:
        while True:
            pending, last_record, known_pids = poll_once(
                log_dir,
                pending,
                last_record,
                known_pids,
                recover_state,
            )
            time.sleep(max(poll_sec, 5))
    except KeyboardInterrupt:
        append_log(log_dir, f"{utc_now()}  watch-stop")
        return 0


def seed_explorer_pids(stored: list[int], live: list[int]) -> tuple[list[int], bool]:
    """Reuse stored PIDs unless they all died (reboot / new session)."""
    if not stored:
        return live, False
    if not live:
        return stored, False
    if any(pid in live for pid in stored):
        return stored, False
    return live, True


def should_recover(
    hanging: bool,
    strikes: int,
    need: int,
    last_recover: float,
    now: float,
    cooldown: float,
) -> tuple[bool, int]:
    """Need N hung polls, then honor cooldown so we do not restart-loop."""
    if not hanging:
        return False, 0
    next_strikes = strikes + 1
    if next_strikes < need:
        return False, next_strikes
    if last_recover and (now - last_recover) < cooldown:
        return False, next_strikes
    return True, 0


def explorer_is_hanging() -> bool:
    script = r"""
$p = Get-Process explorer -ErrorAction SilentlyContinue
if (-not $p) { 'missing'; exit 0 }
if (@($p) | Where-Object { -not $_.Responding }) { 'hanging' } else { 'ok' }
"""
    try:
        return run_powershell(script, timeout=12).strip().lower() == "hanging"
    except RuntimeError:
        return False


def start_host_running() -> bool:
    script = "if (Get-Process StartMenuExperienceHost -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }"
    try:
        return run_powershell(script, timeout=12).strip().lower() == "yes"
    except RuntimeError:
        return False


def recover_shell() -> str:
    start_exe = str(START_HOST_EXE).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process | Where-Object {{
  $_.Name -eq 'NVIDIA App.exe' -or
  ($_.Name -eq 'nvcontainer.exe' -and $_.CommandLine -match 'plugins\\User|NVIDIA App')
}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}
$exp = Get-Process explorer
$hung = [bool]($exp | Where-Object {{ -not $_.Responding }})
if ($hung -or -not $exp) {{
  taskkill /F /IM explorer.exe | Out-Null
  Start-Sleep -Seconds 2
  if (-not (Get-Process explorer)) {{ Start-Process explorer.exe }}
  Start-Sleep -Seconds 2
}}
if (-not (Get-Process StartMenuExperienceHost)) {{
  if (Test-Path '{start_exe}') {{ Start-Process '{start_exe}' }}
}}
$exp2 = Get-Process explorer
$start = Get-Process StartMenuExperienceHost
'explorer={{0}}/{{1}} start={{2}}' -f $(if ($exp2) {{ $exp2.Id }} else {{ 'none' }}), $(if ($exp2) {{ $exp2.Responding }} else {{ 'n/a' }}), $(if ($start) {{ $start.Id }} else {{ 'none' }})
"""
    return run_powershell(script, timeout=40).strip()


def cmd_recover(log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = recover_shell()
    except RuntimeError as exc:
        append_log(log_dir, f"{utc_now()}  recover-fail  {exc}")
        print(f"recover failed: {exc}")
        return 1
    append_log(log_dir, f"{utc_now()}  recover  {result}")
    print(result)
    return 0


def seed_record_id(last_record: int) -> int:
    if last_record > 0:
        return last_record
    try:
        existing = fetch_events(hours=2, max_events=60, after_record_id=0)
    except RuntimeError:
        return 0
    if not existing:
        return 0
    return max(event.record_id for event in existing)


def maybe_auto_recover(log_dir: Path, recover_state: dict[str, Any]) -> None:
    if not recover_state.get("auto"):
        return
    hanging = explorer_is_hanging()
    start_ok = start_host_running()
    now = time.time()
    do_it, strikes = should_recover(
        hanging,
        int(recover_state.get("strikes") or 0),
        HANG_STRIKES_NEEDED,
        float(recover_state.get("last_recover") or 0),
        now,
        RECOVER_COOLDOWN_SEC,
    )
    recover_state["strikes"] = strikes
    if hanging:
        append_log(log_dir, f"{utc_now()}  explorer-unresponsive  strikes={strikes}")
    missing_start = (not hanging) and (not start_ok)
    if missing_start:
        last = float(recover_state.get("last_recover") or 0)
        if last and (now - last) < RECOVER_COOLDOWN_SEC:
            return
        do_it = True
        append_log(log_dir, f"{utc_now()}  start-host-missing")
    if not do_it:
        return
    try:
        result = recover_shell()
    except RuntimeError as exc:
        append_log(log_dir, f"{utc_now()}  recover-fail  {exc}")
        return
    recover_state["last_recover"] = now
    recover_state["strikes"] = 0
    append_log(log_dir, f"{utc_now()}  recover  {result}")


def poll_once(
    log_dir: Path,
    pending: list[CrashEvent],
    last_record: int,
    known_pids: list[int],
    recover_state: dict[str, Any] | None = None,
) -> tuple[list[CrashEvent], int, list[int]]:
    try:
        fresh = fetch_events(hours=2, max_events=60, after_record_id=last_record)
    except RuntimeError as exc:
        append_log(log_dir, f"{utc_now()}  event-poll-error  {exc}")
        fresh = []
    for event in fresh:
        last_record = max(last_record, event.record_id)
        pending.append(event)
    try:
        current_pids = explorer_pids()
    except RuntimeError:
        current_pids = known_pids
    if known_pids and current_pids and current_pids != known_pids:
        pending.append(restart_event(known_pids, current_pids))
    if current_pids:
        known_pids = current_pids
    pending, flushed = split_ready_groups(pending)
    for group in flushed:
        try:
            snapshot = take_snapshot()
        except RuntimeError as exc:
            snapshot = {"error": str(exc)}
        path = write_incident(log_dir, incident_from_group(group, snapshot))
        append_log(log_dir, f"{utc_now()}  wrote  {path}")
    if recover_state is not None:
        maybe_auto_recover(log_dir, recover_state)
    save_state(
        log_dir,
        {
            "last_record_id": last_record,
            "explorer_pids": known_pids,
            "updated_at": utc_now(),
        },
    )
    return pending, last_record, known_pids


def split_ready_groups(pending: list[CrashEvent]) -> tuple[list[CrashEvent], list[list[CrashEvent]]]:
    if not pending:
        return [], []
    groups = group_events(pending)
    now = time.time()
    ready: list[list[CrashEvent]] = []
    keep: list[CrashEvent] = []
    for group in groups:
        age = now - event_stamp(group[-1])
        if age >= GROUP_WINDOW_SEC:
            ready.append(group)
            continue
        keep.extend(group)
    return keep, ready


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_vbs_path() -> Path:
    return startup_dir() / f"{TASK_NAME}.vbs"


def run_argv(script: Path, log_dir: Path) -> list[str]:
    return [
        str(pythonw_path()),
        str(script),
        "run",
        "--log-dir",
        str(log_dir),
        "--poll-sec",
        str(DEFAULT_POLL_SEC),
    ]


def vbs_quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def startup_vbs_text(script: Path, log_dir: Path) -> str:
    command = " ".join(vbs_quote(part) for part in run_argv(script, log_dir))
    return (
        "On Error Resume Next\r\n"
        "WScript.Sleep 25000\r\n"
        'Set sh = CreateObject("Wscript.Shell")\r\n'
        f"sh.CurrentDirectory = {vbs_quote(str(script.parent))}\r\n"
        f"sh.Run {vbs_quote(command)}, 0, False\r\n"
    )


def cmd_install(script: Path, log_dir: Path, start: bool) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    vbs = startup_vbs_path()
    vbs.parent.mkdir(parents=True, exist_ok=True)
    vbs.write_text(startup_vbs_text(script, log_dir), encoding="utf-8")
    print(f"startup launcher: {vbs}")
    print(f"logs: {log_dir}")
    _try_register_task(script, log_dir)
    if start:
        return cmd_start(script, log_dir)
    return 0


def _try_register_task(script: Path, log_dir: Path) -> None:
    exe = str(pythonw_path())
    args = " ".join(f'"{part}"' if " " in part else part for part in run_argv(script, log_dir)[1:])
    create = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
            "/TR",
            f'"{exe}" {args}',
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if create.returncode == 0:
        print(f"also registered scheduled task: {TASK_NAME}")
        return
    print("scheduled task skipped (no admin). Startup folder still runs it.")


def cmd_uninstall() -> int:
    vbs = startup_vbs_path()
    if vbs.exists():
        vbs.unlink()
        print(f"removed startup launcher: {vbs}")
    else:
        print("no startup launcher found")
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        print(f"removed scheduled task: {TASK_NAME}")
    return 0


def cmd_start(script: Path, log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    argv = run_argv(script, log_dir)
    subprocess.Popen(
        argv,
        cwd=str(script.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    )
    print(f"started watcher: {argv[0]}")
    print(f"logs: {log_dir / 'watch.log'}")
    return 0


def cmd_diagnose(log_dir: Path) -> int:
    """Snapshot versions, package, NVIDIA inject, displays. Does not restart the shell."""
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = run_powershell(PS_DIAGNOSE, timeout=45)
        data = json.loads(raw) if raw else {}
    except (RuntimeError, json.JSONDecodeError) as exc:
        append_log(log_dir, f"{utc_now()}  diagnose-fail  {exc}")
        print(f"diagnose failed: {exc}")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir / "incidents" / f"{stamp}-diagnose.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    append_log(log_dir, f"{utc_now()}  diagnose  {path}")
    print(f"build {data.get('DisplayVersion')} {data.get('Build')}.{data.get('UBR')}")
    print(f"start package: {data.get('StartPackage')}")
    print(f"explorer responding: {data.get('ExplorerResponding')}")
    print(f"nvui in explorer: {data.get('NvuiInExplorer') or 'none'}")
    print("files:")
    for item in data.get("Files") or []:
        print(f"  {item.get('FileVersion')}  {item.get('Path')}")
    print("monitors:")
    for item in data.get("Monitors") or []:
        print(f"  {item.get('Name')}  active={item.get('Active')}")
    print(f"wrote {path}")
    print("read notes/taskbar-outage.md before changing the shell")
    return 0


def cmd_status(log_dir: Path) -> int:
    vbs = startup_vbs_path()
    print(f"startup launcher: {vbs}  ({'yes' if vbs.exists() else 'missing'})")
    query = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if query.returncode == 0:
        print(query.stdout.strip())
    else:
        print("scheduled task: not registered")
    log = log_dir / "watch.log"
    print(f"log dir: {log_dir}")
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("last log lines:")
        for line in lines[-12:]:
            print(f"  {line}")
    incidents = sorted((log_dir / "incidents").glob("*.json")) if (log_dir / "incidents").exists() else []
    print(f"incident files: {len(incidents)}")
    return 0 if vbs.exists() or query.returncode == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--log-dir",
        type=Path,
        default=default_log_dir(),
        help="Log folder (default: %%LOCALAPPDATA%%\\TaskbarCrashWatch)",
    )
    parser = argparse.ArgumentParser(
        description="Monitor Explorer / taskbar crashes.",
        parents=[shared],
    )
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", parents=[shared], help="Summarize recent shell crashes now.")
    report.add_argument("--days", type=int, default=14)
    run = sub.add_parser("run", parents=[shared], help="Stay resident and log crashes.")
    run.add_argument("--poll-sec", type=int, default=DEFAULT_POLL_SEC)
    run.add_argument(
        "--no-auto-recover",
        action="store_true",
        help="Log hangs only. Do not restart Explorer / Start host.",
    )
    install = sub.add_parser("install", parents=[shared], help="Install hidden Startup-folder watcher.")
    install.add_argument("--start", action="store_true", help="Start the watcher now.")
    sub.add_parser("uninstall", parents=[shared], help="Remove Startup launcher and scheduled task.")
    sub.add_parser("start", parents=[shared], help="Start the watcher now.")
    sub.add_parser("status", parents=[shared], help="Show install state + recent log lines.")
    sub.add_parser("recover", parents=[shared], help="Restart hung Explorer and Start host now.")
    sub.add_parser("diagnose", parents=[shared], help="Snapshot versions / NVIDIA / displays. No restart.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_dir = args.log_dir.expanduser()
    script = Path(__file__).resolve()
    if args.command == "report":
        return cmd_report(log_dir, args.days)
    if args.command == "run":
        return cmd_run(log_dir, args.poll_sec, auto_recover=not args.no_auto_recover)
    if args.command == "install":
        return cmd_install(script, log_dir, args.start)
    if args.command == "uninstall":
        return cmd_uninstall()
    if args.command == "start":
        return cmd_start(script, log_dir)
    if args.command == "status":
        return cmd_status(log_dir)
    if args.command == "recover":
        return cmd_recover(log_dir)
    if args.command == "diagnose":
        return cmd_diagnose(log_dir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
