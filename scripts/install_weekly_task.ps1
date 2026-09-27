# Install / manage the daily 7am weekly runner (Windows Task Scheduler).
# 7am submits all 3 due slots in one batch (parallel Cursor agents).
param(
  [string]$Time = "07:00",
  [string]$TaskName = "AiVideoWeekly7am",
  [string]$Owner = "",
  [switch]$Uninstall,
  [switch]$Status
)

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "weekly-7am.log"

function Remove-LegacyExtraTasks {
  foreach ($suffix in @("1000", "1400")) {
    schtasks /Delete /TN "${TaskName}_$suffix" /F 2>$null | Out-Null
  }
}

if ($Status) {
  schtasks /Query /TN $TaskName /FO LIST 2>&1
  exit $LASTEXITCODE
}

if ($Uninstall) {
  schtasks /Delete /TN $TaskName /F 2>$null
  Remove-LegacyExtraTasks
  exit 0
}

. (Join-Path $Root "scripts\dev-common.ps1")
$Python = Resolve-PythonExe
if (-not $Python) { throw "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON in scripts/.env" }
Write-Host "Using Python: $Python"

Remove-LegacyExtraTasks

$Runner = Join-Path $Root "scripts\run_weekly_due.py"
$RunnerArgs = " --retry-failed --morning-batch --limit 3"
if ($Owner -ne "") { $RunnerArgs += " --owner $Owner" }

$Launcher = Join-Path $Root "scripts\weekly_7am.cmd"
$LauncherBody = @"
@echo off
cd /d `"$Root`"
`"$Python`" `"$Runner`"$RunnerArgs >> `"$LogPath`" 2>&1
"@
Set-Content -Path $Launcher -Value $LauncherBody -Encoding Ascii

$Create = schtasks /Create /TN $TaskName /SC DAILY /ST $Time /RL LIMITED /F /TR "`"$Launcher`""
if ($LASTEXITCODE -ne 0) { throw "schtasks create failed: $Create" }

Write-Host "installed $TaskName daily $Time (log: $LogPath)"
Write-Host "Morning batch: submits 3 due slots at $Time (parallel agents)."
