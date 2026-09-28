# Start the FastAPI discovery backend (port 8000) in this terminal (reload on).
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")

& (Join-Path $Scripts "stop-api.ps1") -Port 8000
Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

$Python = Resolve-PythonExe
if (-not $Python) {
    Write-Error "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON to your python.exe path."
    exit 1
}

Write-Host "Using Python: $Python"
$env:AI_VIDEO_PYTHON = $Python
Start-ApiServer -Root $Root -Python $Python
