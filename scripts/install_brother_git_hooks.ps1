# Install post-commit hook: auto push origin + chris after each commit on main.
param([switch]$Uninstall)

$Root = Split-Path -Parent $PSScriptRoot
$HookDir = Join-Path $Root ".git\hooks"
$HookPath = Join-Path $HookDir "post-commit"
$Source = Join-Path $Root "scripts\git-hooks\post-commit"

if ($Uninstall) {
    if (Test-Path $HookPath) { Remove-Item -Force $HookPath }
    Write-Host "removed post-commit hook"
    exit 0
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Error "Not a git repo: $Root"
    exit 1
}
New-Item -ItemType Directory -Force -Path $HookDir | Out-Null
Copy-Item -Path $Source -Destination $HookPath -Force
Write-Host "installed post-commit -> push origin + chris on main"
