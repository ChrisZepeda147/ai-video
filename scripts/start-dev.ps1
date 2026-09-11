# Start full dev stack: FastAPI (8000) + Next.js dashboard (3000).
# Dashboard starts immediately - do not block on API health (site works with offline banner).
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

function Test-ApiHealthy {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

Set-Location $Root

if (Test-ApiHealthy) {
    Write-Host "Discovery API already running on http://127.0.0.1:8000"
} else {
    Write-Host "Starting Discovery API in a background terminal..."
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $Scripts "start-api.ps1")
    ) -WorkingDirectory $Root
    Write-Host "API still starting on http://127.0.0.1:8000 - dashboard will open now."
    Write-Host "If API terminal shows errors, fix Python/deps there; the site still loads."
}

& (Join-Path $Scripts "start-dashboard.ps1")
