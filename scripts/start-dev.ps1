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

& (Join-Path $Scripts "ensure-api.ps1") -Restart
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not (Test-ApiHealthy)) {
    Write-Error "Discovery API is not healthy after ensure-api. Check data/logs/api-dev.err"
    exit 1
}

Write-Host "Backend healthy. Starting dashboard..."
& (Join-Path $Scripts "start-dashboard.ps1")
