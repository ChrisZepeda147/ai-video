# Start full dev stack: FastAPI (8000) + Next.js dashboard (3000).
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

function Wait-ApiHealthy {
    param([int]$Seconds = 45)
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-ApiHealthy) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
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

    Write-Host "Waiting for API health..."
    if (-not (Wait-ApiHealthy)) {
        Write-Error "API did not become ready on port 8000. Check the API terminal for errors."
        exit 1
    }
    Write-Host "Discovery API is ready."
}

& (Join-Path $Scripts "start-dashboard.ps1")
