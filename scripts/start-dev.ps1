# Start full dev stack: FastAPI (8000) first, then Next.js dashboard (3000).
# Dashboard does not start until API /health is ok.
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")

Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

if (Test-ApiHealthy) {
    Write-Host "Discovery API already running on http://127.0.0.1:8000"
} else {
    if (Test-ApiPortListening) {
        Write-Host "Port 8000 is listening but /health failed - restarting API..."
    } else {
        Write-Host "Discovery API not running yet - starting uvicorn..."
    }
    & (Join-Path $Scripts "stop-api.ps1") -Port 8000 | Out-Null
    $Python = Resolve-PythonExe
    if (-not $Python) {
        Write-Error "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON in scripts/.env"
        exit 1
    }
    Write-Host "Using Python: $Python"
    Start-ApiServer -Root $Root -Python $Python -Background
    if (-not (Wait-ApiHealthy -Seconds 45)) {
        Write-Error "Discovery API failed to start. Dashboard will not start. Check data/logs/api-dev.err"
        exit 1
    }
}

Write-Host "Backend healthy. Starting dashboard..."
& (Join-Path $Scripts "start-dashboard.ps1")
