# Start the Next.js dashboard (port 3000). Always refreshes — kills stale dev servers first.
$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "web"
$Port = 3000

& (Join-Path $PSScriptRoot "stop-dashboard.ps1") -Port $Port

Set-Location $Web

$EnvFile = Join-Path $Web ".env.local"
$Example = Join-Path $Web ".env.example"
if (-not (Test-Path $EnvFile) -and (Test-Path $Example)) {
    Copy-Item $Example $EnvFile
    Write-Host "Created web/.env.local from .env.example"
}

if (-not (Test-Path "node_modules") -or $env:AI_VIDEO_FORCE_NPM_INSTALL -eq "1") {
    Write-Host "Installing dashboard npm deps..."
    npm install
} else {
    Write-Host "Dashboard npm deps OK (skipping npm install)."
}

Write-Host "Starting dashboard at http://localhost:$Port"
npx next dev -p $Port