# Full refresh: stop both, start API first, wait until healthy, then dashboard.
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")
Import-ApiEnvFile -Root $Root
Import-DevPath

Write-Host "Refreshing ai-video dev stack..."
& (Join-Path $Scripts "stop-dashboard.ps1") -Port 3000
& (Join-Path $Scripts "stop-api.ps1") -Port 8000

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $Scripts "start-api.ps1")
) -WorkingDirectory $Root

if (-not (Wait-ApiHealthy -Seconds 45)) {
    Write-Error "Discovery API failed to start. Dashboard will not start. Check data/logs/api-dev.err"
    exit 1
}

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $Scripts "start-dashboard.ps1")
) -WorkingDirectory $Root

Write-Host "Started API (8000) then dashboard (3000) in new terminals."
