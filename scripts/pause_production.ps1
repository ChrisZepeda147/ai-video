# Pause montage / weekly renders on THIS machine (cancel DB jobs + kill worker processes).
param(
    [switch]$KillOnly
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")
Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

if (-not $KillOnly) {
    $Python = Resolve-PythonExe
    if (-not $Python) {
        Write-Error "Python not found."
        exit 1
    }

    $ownerArg = @()
    if ($args -contains "--owner") {
        $i = [array]::IndexOf($args, "--owner")
        if ($i -ge 0 -and $i + 1 -lt $args.Count) {
            $ownerArg = @("--owner", $args[$i + 1])
        }
    }

    & $Python (Join-Path $Scripts "pause_production.py") @ownerArg
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree -ProcessId $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

$rootEsc = [regex]::Escape($Root)
$killed = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = $_.CommandLine
    if (-not $cmd -or $cmd -notmatch $rootEsc) { return }
    $matchWorker = (
        $cmd -match "build_motivation_job\.py" -or
        $cmd -match "run_direct_job\.py" -or
        $cmd -match "run_weekly_due\.py" -or
        ($cmd -match "ffmpeg" -and $cmd -match "motivational")
    )
    if (-not $matchWorker) { return }
    $pid = [int]$_.ProcessId
    if ($killed -contains $pid) { return }
    Write-Host "Stopping worker PID $pid"
    Stop-ProcessTree -ProcessId $pid
    $killed += $pid
}

if ($killed.Count -gt 0) {
    Write-Host "Stopped $($killed.Count) worker process tree(s)."
} else {
    Write-Host "No matching ffmpeg/montage workers found (DB jobs still cancelled)."
}

Write-Host "Done. Re-run from Weekly or Make Short when ready."
