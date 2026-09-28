# Daily 7am weekly runner — real Python from scripts/.env, logs to data/logs/weekly-7am.log
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Scripts = $PSScriptRoot

. (Join-Path $Scripts "dev-common.ps1")
Set-Location $Root
Import-ApiEnvFile -Root $Root
Import-DevPath

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "weekly-7am.log"

$Python = Resolve-PythonExe
if (-not $Python) {
    $msg = "{0}  weekly_7am: Python not found (set AI_VIDEO_PYTHON in scripts/.env)" -f (Get-Date -Format "o")
    Add-Content -Path $LogPath -Value $msg -Encoding UTF8
    exit 1
}

$Runner = Join-Path $Scripts "run_weekly_due.py"
$stamp = Get-Date -Format "o"
Add-Content -Path $LogPath -Value "`n$stamp  weekly_7am start python=$Python" -Encoding UTF8

& $Python $Runner --retry-failed --all-owners --serial --wait-complete --limit 3 2>&1 |
    ForEach-Object { Add-Content -Path $LogPath -Value $_ -Encoding UTF8 }

$code = $LASTEXITCODE
$end = Get-Date -Format "o"
Add-Content -Path $LogPath -Value "$end  weekly_7am exit=$code" -Encoding UTF8
exit $code
