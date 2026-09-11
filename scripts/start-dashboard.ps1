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

$NodeModules = Join-Path $Web "node_modules"
$LockFile = Join-Path $Web "package-lock.json"
if (-not (Test-Path $NodeModules)) {
    Write-Host "Installing dashboard dependencies (first run)..."
    npm install
} elseif ((Test-Path $LockFile) -and (Get-Item $LockFile).LastWriteTime -gt (Get-Item $NodeModules).LastWriteTime) {
    Write-Host "package-lock.json changed - refreshing dashboard dependencies..."
    npm install
}

Write-Host "Starting dashboard at http://localhost:${Port}"
Write-Host "Open http://localhost:${Port}/create for Make Short"
npx next dev -p $Port