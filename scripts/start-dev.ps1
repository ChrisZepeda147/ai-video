# Start full dev stack: FastAPI (8000) + Next.js dashboard (3000).
# Dashboard starts immediately - do not block on API health (site works with offline banner).
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")

Set-Location $Root
Import-ApiEnvFile -Root $Root

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($userPath -or $machinePath) {
    $env:Path = @($userPath, $machinePath, $env:Path) -join ';'
}

if (Test-ApiHealthy) {
    Write-Host "Discovery API already running on http://127.0.0.1:8000"
} else {
    Write-Host "Discovery API not healthy - starting uvicorn..."
    & (Join-Path $Scripts "stop-api.ps1") -Port 8000 | Out-Null
    $Python = Resolve-PythonExe
    if (-not $Python) {
        Write-Error "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON in scripts/.env"
        exit 1
    }
    Write-Host "Using Python: $Python"
    Start-ApiServer -Root $Root -Python $Python -Background
    if (-not (Wait-ApiHealthySoft -Seconds 20)) {
        Write-Host "API did not become healthy. Check data/logs/api-dev.err"
    }
}

& (Join-Path $Scripts "start-dashboard.ps1")
