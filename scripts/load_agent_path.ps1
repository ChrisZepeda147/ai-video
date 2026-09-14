# Put scripts/.env Python + ffmpeg in front of PATH.
# Windows Store python.exe stubs lose after this.
#
# Same-process only. Nested `powershell -File` dies and PATH dies with it.
#   . .\scripts\load_agent_path.ps1; python scripts/foo.py
# Optional: run a command inside this process
#   powershell -File scripts/load_agent_path.ps1 -Run 'python scripts/foo.py'
param(
    [switch]$Persist,
    [switch]$NoPersist,
    [string]$Run
)

$Root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot "dev-common.ps1")
$importArgs = @{ Root = $Root }
if ($Persist) { $importArgs.Persist = $true }
if ($NoPersist) { $importArgs.NoPersist = $true }
$bins = Import-AgentPythonPath @importArgs
$python = Get-Command python -ErrorAction SilentlyContinue
$source = if ($python) { $python.Source } else { "missing" }

if (-not $Run) {
    Write-Host "python -> $source"
    if ($bins) {
        Write-Host ("path bins -> " + ($bins -join "; "))
    }
    if ($source -match "WindowsApps") {
        Write-Warning "Store stub still first. Re-run with -Persist, then open a new shell."
    }
    if ($MyInvocation.InvocationName -ne '.') {
        Write-Warning "PATH only exists in this process. Next 'python' after this script still fails. Dot-source instead: . .\scripts\load_agent_path.ps1; python ..."
    }
    return
}

cmd.exe /c $Run
$code = $LASTEXITCODE
if ($MyInvocation.InvocationName -ne '.') {
    exit $code
}
