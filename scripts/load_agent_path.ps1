# Put scripts/.env Python + ffmpeg in front of PATH.
# Windows Store python.exe stubs lose after this.
param(
    [switch]$Persist
)

$Root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "dev-common.ps1")
$bins = Import-AgentPythonPath -Root $Root -Persist:$Persist
$python = Get-Command python -ErrorAction SilentlyContinue
$source = if ($python) { $python.Source } else { "missing" }
Write-Host "python -> $source"
if ($bins) {
    Write-Host ("path bins -> " + ($bins -join "; "))
}
if ($source -match "WindowsApps") {
    Write-Warning "Store stub still first. Re-run with -Persist, then open a new shell."
}
