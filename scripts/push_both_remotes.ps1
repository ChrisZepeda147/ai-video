# After a local commit on main: push to origin + chris so the other machine picks it up via auto-sync.
param([switch]$Quiet)

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "push-both-remotes.log"

function Write-Log([string]$Msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Msg
    Add-Content -Path $LogPath -Value $line -Encoding utf8
    if (-not $Quiet) { Write-Host $Msg }
}

Set-Location $Root
$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
if ($branch -ne "main") {
    Write-Log "skip  branch=$branch (not main)"
    exit 0
}

$remotes = @("origin", "chris")
$pushed = @()
foreach ($remote in $remotes) {
    $url = git remote get-url $remote 2>$null
    if (-not $url) { continue }
    $push = git push $remote HEAD:main 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "fail  $remote  $push"
        exit 1
    }
    $pushed += $remote
}
Write-Log ("ok  pushed " + ($pushed -join ", "))
exit 0
