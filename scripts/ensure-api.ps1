# Start Discovery API on port 8000 if not already healthy. Use -Restart to kill and reload code.
param(
    [switch]$Restart
)

$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")

Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

if ($Restart) {
    Write-Host "Restarting Discovery API on http://127.0.0.1:8000 ..."
    & (Join-Path $Scripts "stop-api.ps1") -Port 8000 | Out-Null
} elseif (Test-ApiHealthy) {
    Write-Host "Discovery API already running on http://127.0.0.1:8000"
    exit 0
} elseif (Test-ApiPortListening) {
    Write-Host "Port 8000 busy but /health failed — restarting API..."
    & (Join-Path $Scripts "stop-api.ps1") -Port 8000 | Out-Null
} else {
    Write-Host "Starting Discovery API on http://127.0.0.1:8000 ..."
}

$Python = Resolve-PythonExe
if (-not $Python) {
    Write-Error "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON in scripts/.env"
    exit 1
}
Write-Host "Using Python: $Python"
$env:AI_VIDEO_PYTHON = $Python
Start-ApiServer -Root $Root -Python $Python -Background
if (-not (Wait-ApiHealthy -Seconds 45)) {
    Write-Error "Discovery API failed to start. Check data/logs/api-dev.err"
    exit 1
}
