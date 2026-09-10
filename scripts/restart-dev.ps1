# Full refresh: stop API + dashboard, then start both in separate windows.
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

Write-Host "Refreshing ai-video dev stack..."
& (Join-Path $Scripts "stop-dashboard.ps1") -Port 3000

& (Join-Path $Scripts "stop-api.ps1") -Port 8000

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $Scripts "start-api.ps1")
) -WorkingDirectory $Root

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $Scripts "start-dashboard.ps1")
) -WorkingDirectory $Root

Write-Host "Started API (8000) and dashboard (3000) in new terminals."
