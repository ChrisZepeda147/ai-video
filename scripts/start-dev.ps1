# Start full dev stack: FastAPI (8000) first, then Next.js dashboard (3000).
# Dashboard does not start until API /health is ok.
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")

Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

# Dual-push after commit + background GitHub merge task (Stephen/Chris stay on same code).
$HookPath = Join-Path $Root ".git\hooks\post-commit"
if (-not (Test-Path $HookPath)) {
    & (Join-Path $Scripts "install_brother_git_hooks.ps1") | Out-Null
}
$GhSync = Join-Path $Scripts "github_brother_sync.ps1"
if (Test-Path $GhSync) {
    $task = schtasks /Query /TN "AiVideoGitHubSync" /FO LIST 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing GitHub brother sync (every 5 min, pull+merge both remotes)..."
        try {
            & $GhSync install -Minutes 5 | Out-Null
        } catch {
            Write-Warning "GitHub brother sync task not installed: $_ (dev stack will still start)"
        }
    }
}

$WeeklyInstall = Join-Path $Scripts "install_weekly_task.ps1"
if (Test-Path $WeeklyInstall) {
    $weeklyVbs = Join-Path $env:LOCALAPPDATA "AiVideo\weekly_7am_silent.vbs"
    schtasks /Query /TN "AiVideoWeekly7am" /FO LIST 2>$null | Out-Null
    $needsWeekly = ($LASTEXITCODE -ne 0) -or -not (Test-Path -LiteralPath $weeklyVbs)
    if ($needsWeekly) {
        Write-Host "Installing/updating weekly 7am task (3 videos per owner)..."
        try {
            & $WeeklyInstall | Out-Null
        } catch {
            Write-Warning "Weekly 7am task not installed: $_"
        }
    }
}

# Always restart API so npm run dev picks up latest Python/API code (matches start-api.ps1).
Write-Host "Restarting Discovery API on http://127.0.0.1:8000 ..."
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

Write-Host "Backend healthy. Starting dashboard..."
& (Join-Path $Scripts "start-dashboard.ps1")
