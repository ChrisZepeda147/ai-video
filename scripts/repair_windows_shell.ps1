# Requires elevation. Tiny11 / KB5072911 fix: register XAML packages, restart SiHost.
# Do not run while Explorer is hung. Do not restart Explorer.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/repair_windows_shell.ps1 [-RegisterOnly]

param(
    [string]$LogDir = $(Join-Path $env:LOCALAPPDATA "TaskbarCrashWatch"),
    [switch]$RegisterOnly
)

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$logFile = Join-Path $LogDir "repair.log"

function Write-RepairLog([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Stop-NvidiaUserContainer {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "NVIDIA App.exe" -or
        ($_.Name -eq "nvcontainer.exe" -and $_.CommandLine -match "plugins\\User|NVIDIA App")
    } | ForEach-Object {
        Write-RepairLog "kill-nvidia pid=$($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Register-ShellPackage([string]$Manifest) {
    if (-not (Test-Path $Manifest)) {
        Write-RepairLog "missing $Manifest"
        return
    }
    Write-RepairLog "register $Manifest"
    try {
        Add-AppxPackage -Register -DisableDevelopmentMode -Path $Manifest -ErrorAction Stop
        Write-RepairLog "register-ok $Manifest"
    } catch {
        Write-RepairLog "register-fail $Manifest  $($_.Exception.Message)"
    }
}

if (-not (Test-IsAdmin)) {
    Write-RepairLog "relaunch-elevated"
    $self = $MyInvocation.MyCommand.Path
    $arg = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $self, "-LogDir", $LogDir
    )
    if ($RegisterOnly) { $arg += "-RegisterOnly" }
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arg | Out-Null
    exit 0
}

Write-RepairLog ("elevated-repair-start  registerOnly={0}" -f [bool]$RegisterOnly)

$exp = Get-Process explorer -ErrorAction SilentlyContinue
if ($exp -and @($exp | Where-Object { -not $_.Responding }).Count -gt 0) {
    Write-RepairLog "ABORT explorer hung. Reboot first. Do not restart Explorer."
    exit 2
}

if (-not $RegisterOnly) {
    Stop-NvidiaUserContainer
}

$manifests = @(
    "C:\Windows\SystemApps\Microsoft.UI.Xaml.CBS_8wekyb3d8bbwe\AppxManifest.xml",
    "C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\appxmanifest.xml",
    "C:\Windows\SystemApps\MicrosoftWindows.Client.Core_cw5n1h2txyewy\appxmanifest.xml",
    "C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\AppxManifest.xml",
    "C:\Windows\SystemApps\ShellExperienceHost_cw5n1h2txyewy\AppxManifest.xml"
)
foreach ($manifest in $manifests) {
    Register-ShellPackage $manifest
}

$pkg = Get-AppxPackage -Name Microsoft.Windows.StartMenuExperienceHost
if ($pkg) {
    Write-RepairLog ("start-package  version={0}  status={1}" -f $pkg.Version, $pkg.Status)
} else {
    Write-RepairLog "start-package  MISSING"
}

if (-not $RegisterOnly) {
    Write-RepairLog "restart-sihost"
    Get-Process sihost -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    if (-not (Get-Process sihost -ErrorAction SilentlyContinue)) {
        Start-Process "$env:WINDIR\System32\sihost.exe"
        Start-Sleep -Seconds 2
    }
}

$exp = Get-Process explorer -ErrorAction SilentlyContinue
$start = Get-Process StartMenuExperienceHost -ErrorAction SilentlyContinue
Write-RepairLog ("shell  explorer={0}/{1}  start={2}" -f $(if ($exp) { $exp.Id } else { "none" }), $(if ($exp) { $exp.Responding } else { "n/a" }), $(if ($start) { $start.Id } else { "none" }))
Write-RepairLog "elevated-repair-done"
