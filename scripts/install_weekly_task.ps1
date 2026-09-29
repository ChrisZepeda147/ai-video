# Install / manage the daily 7am weekly runner (Windows Task Scheduler).
# 7am submits all 3 due slots per owner in one batch (parallel Cursor agents).
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
$SilentVbsDir = Join-Path $env:LOCALAPPDATA "AiVideo"
$SilentVbsPath = Join-Path $SilentVbsDir "weekly_7am_silent.vbs"
$WeeklyPs1 = Join-Path $Root "scripts\weekly_7am.ps1"

function Remove-LegacyExtraTasks {
  foreach ($suffix in @("1000", "1400")) {
    schtasks /Delete /TN "${TaskName}_$suffix" /F 2>$null | Out-Null
  }
}

function Write-WeeklySilentLauncher {
  $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
  New-Item -ItemType Directory -Force -Path $SilentVbsDir | Out-Null
  $cmd = "$powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WeeklyPs1`""
  $escaped = $cmd.Replace('"', '""')
  $rootEsc = $Root.Replace('"', '""')
  @(
    "On Error Resume Next"
    "Set sh = CreateObject(""Wscript.Shell"")"
    "sh.CurrentDirectory = ""$rootEsc"""
    "sh.Run ""$escaped"", 0, False"
  ) -join "`r`n" | Set-Content -Path $SilentVbsPath -Encoding ASCII
  return $SilentVbsPath
}

function Install-WeeklyTask {
  if (-not (Test-Path $WeeklyPs1)) { throw "Missing $WeeklyPs1" }
  . (Join-Path $Root "scripts\dev-common.ps1")
  Import-ApiEnvFile -Root $Root
  $Python = Resolve-PythonExe
  if (-not $Python) { throw "Python not found. Set AI_VIDEO_PYTHON in scripts/.env" }
  Write-Host "Using Python: $Python"

  Remove-LegacyExtraTasks
  $vbs = Write-WeeklySilentLauncher
  $wscript = Join-Path $env:WINDIR "System32\wscript.exe"
  $atParts = $Time.Split(":")
  $hour = [int]$atParts[0]
  $minute = if ($atParts.Length -gt 1) { [int]$atParts[1] } else { 0 }
  $action = New-ScheduledTaskAction -Execute $wscript -Argument "//B //Nologo `"$vbs`""
  $trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.AddHours($hour).AddMinutes($minute))
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Write-Host "installed $TaskName daily $Time (StartWhenAvailable; silent launcher: $vbs)"
  Write-Host "Morning batch: run_weekly_due --all-owners --limit 3 (log: $LogPath)"
}

if ($Status) {
  schtasks /Query /TN $TaskName /FO LIST 2>&1
  exit $LASTEXITCODE
}

if ($Uninstall) {
  schtasks /Delete /TN $TaskName /F 2>$null
  Remove-LegacyExtraTasks
  if (Test-Path $SilentVbsPath) { Remove-Item -Force $SilentVbsPath -ErrorAction SilentlyContinue }
  exit 0
}

Install-WeeklyTask
