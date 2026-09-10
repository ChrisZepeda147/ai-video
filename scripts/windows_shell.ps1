#Requires -Version 5.1
<#
  Keep the Windows 11 shell alive on mixed-DPI setups.

  Win11 taskbar chrome is XAML. A ghost 4K TV (or any off-grid display)
  makes StartMenuExperienceHost crash; Explorer then hangs and the bar
  stays empty. NinjaTrader (and other WPF apps) can retrigger that when
  they enumerate every connected output.

  Examples:
    powershell -File scripts/windows_shell.ps1 status
    powershell -File scripts/windows_shell.ps1 restore
    powershell -File scripts/windows_shell.ps1 detach --match TCL
    powershell -File scripts/windows_shell.ps1 watch --match TCL
    powershell -File scripts/windows_shell.ps1 install --match TCL
    powershell -File scripts/windows_shell.ps1 set-dpi --exe "C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'restore', 'detach', 'watch', 'install', 'uninstall', 'set-dpi')]
    [string]$Command = 'status',

    [string]$Match = 'TCL',
    [string]$Exe = 'C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe',
    [ValidateSet('DPIUNAWARE', 'HIGHDPIAWARE')]
    [string]$DpiMode = 'DPIUNAWARE',
    [int]$IntervalSeconds = 20,
    [string]$TaskName = 'WindowsShellKeepAlive',
    [switch]$NoGpuReset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class WinShellNative {
    public const int ENUM_CURRENT_SETTINGS = -1;
    public const uint CDS_UPDATEREGISTRY = 0x00000001;
    public const uint CDS_NORESET = 0x10000000;
    public const int DM_POSITION = 0x00000020;
    public const int DM_PELSWIDTH = 0x00080000;
    public const int DM_PELSHEIGHT = 0x00100000;
    public const uint DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001;
    public const uint DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const byte VK_SHIFT = 0x10;
    public const byte VK_CONTROL = 0x11;
    public const byte VK_LWIN = 0x5B;
    public const byte VK_B = 0x42;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public uint StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public int dmPositionX;
        public int dmPositionY;
        public int dmDisplayOrientation;
        public int dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
        public int dmICMMethod;
        public int dmICMIntent;
        public int dmMediaType;
        public int dmDitherType;
        public int dmReserved1;
        public int dmReserved2;
        public int dmPanningWidth;
        public int dmPanningHeight;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplayDevices(string lpDevice, uint iDevNum, ref DISPLAY_DEVICE lpDisplayDevice, uint dwFlags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplaySettings(string lpszDeviceName, int iModeNum, ref DEVMODE lpDevMode);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int ChangeDisplaySettingsEx(string lpszDeviceName, ref DEVMODE lpDevMode, IntPtr hwnd, uint dwflags, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int ChangeDisplaySettingsEx(string lpszDeviceName, IntPtr lpDevMode, IntPtr hwnd, uint dwflags, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    public static extern bool IsHungAppWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}
'@

function Get-DisplayTargets {
    $targets = @()
    $adapterIndex = 0
    while ($true) {
        $adapter = New-Object WinShellNative+DISPLAY_DEVICE
        $adapter.cb = [Runtime.InteropServices.Marshal]::SizeOf($adapter)
        if (-not [WinShellNative]::EnumDisplayDevices($null, $adapterIndex, [ref]$adapter, 0)) { break }

        $monitorIndex = 0
        $sawMonitor = $false
        while ($true) {
            $monitor = New-Object WinShellNative+DISPLAY_DEVICE
            $monitor.cb = [Runtime.InteropServices.Marshal]::SizeOf($monitor)
            if (-not [WinShellNative]::EnumDisplayDevices($adapter.DeviceName, $monitorIndex, [ref]$monitor, 0)) { break }
            $sawMonitor = $true
            $mode = New-Object WinShellNative+DEVMODE
            $mode.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($mode)
            $hasMode = [WinShellNative]::EnumDisplaySettings($adapter.DeviceName, [WinShellNative]::ENUM_CURRENT_SETTINGS, [ref]$mode)
            $targets += [pscustomobject]@{
                Adapter      = $adapter.DeviceName
                AdapterName  = $adapter.DeviceString
                Monitor      = $monitor.DeviceString
                DeviceId     = $monitor.DeviceID
                Attached     = [bool]($adapter.StateFlags -band [WinShellNative]::DISPLAY_DEVICE_ATTACHED_TO_DESKTOP)
                Primary      = [bool]($adapter.StateFlags -band [WinShellNative]::DISPLAY_DEVICE_PRIMARY_DEVICE)
                Width        = if ($hasMode) { $mode.dmPelsWidth } else { 0 }
                Height       = if ($hasMode) { $mode.dmPelsHeight } else { 0 }
                X            = if ($hasMode) { $mode.dmPositionX } else { 0 }
                Y            = if ($hasMode) { $mode.dmPositionY } else { 0 }
            }
            $monitorIndex++
        }
        if (-not $sawMonitor) {
            $targets += [pscustomobject]@{
                Adapter      = $adapter.DeviceName
                AdapterName  = $adapter.DeviceString
                Monitor      = ''
                DeviceId     = $adapter.DeviceID
                Attached     = [bool]($adapter.StateFlags -band [WinShellNative]::DISPLAY_DEVICE_ATTACHED_TO_DESKTOP)
                Primary      = [bool]($adapter.StateFlags -band [WinShellNative]::DISPLAY_DEVICE_PRIMARY_DEVICE)
                Width        = 0
                Height       = 0
                X            = 0
                Y            = 0
            }
        }
        $adapterIndex++
    }
    $targets
}

function Get-MatchedDisplays {
    param([string]$Pattern)
    Get-DisplayTargets | Where-Object {
        $_.Monitor -match $Pattern -or $_.DeviceId -match $Pattern -or $_.AdapterName -match $Pattern
    }
}

function Dismount-MatchedDisplays {
    param([string]$Pattern)
    $hits = @(Get-MatchedDisplays -Pattern $Pattern | Where-Object { $_.Attached -and -not $_.Primary })
    if (-not $hits) {
        Write-Host "No attached non-primary display matched '$Pattern'."
        return 0
    }
    foreach ($hit in $hits) {
        Write-Host ("Detaching {0} ({1}) {2}x{3} at {4},{5}" -f $hit.Adapter, $hit.Monitor, $hit.Width, $hit.Height, $hit.X, $hit.Y)
        $mode = New-Object WinShellNative+DEVMODE
        $mode.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($mode)
        $mode.dmFields = [WinShellNative]::DM_POSITION -bor [WinShellNative]::DM_PELSWIDTH -bor [WinShellNative]::DM_PELSHEIGHT
        $mode.dmPelsWidth = 0
        $mode.dmPelsHeight = 0
        $mode.dmPositionX = 0
        $mode.dmPositionY = 0
        $code = [WinShellNative]::ChangeDisplaySettingsEx($hit.Adapter, [ref]$mode, [IntPtr]::Zero, ([WinShellNative]::CDS_UPDATEREGISTRY -bor [WinShellNative]::CDS_NORESET), [IntPtr]::Zero)
        if ($code -ne 0) {
            Write-Host "ChangeDisplaySettingsEx queued result=$code for $($hit.Adapter)"
        }
    }
    [WinShellNative]::ChangeDisplaySettingsEx($null, [IntPtr]::Zero, [IntPtr]::Zero, 0, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 400
    return $hits.Count
}

function Send-GpuReset {
    Write-Host "Sending Ctrl+Win+Shift+B (GPU reset)"
    foreach ($key in @([WinShellNative]::VK_CONTROL, [WinShellNative]::VK_LWIN, [WinShellNative]::VK_SHIFT, [WinShellNative]::VK_B)) {
        [WinShellNative]::keybd_event($key, 0, 0, [UIntPtr]::Zero)
    }
    Start-Sleep -Milliseconds 80
    foreach ($key in @([WinShellNative]::VK_B, [WinShellNative]::VK_SHIFT, [WinShellNative]::VK_LWIN, [WinShellNative]::VK_CONTROL)) {
        [WinShellNative]::keybd_event($key, 0, [WinShellNative]::KEYEVENTF_KEYUP, [UIntPtr]::Zero)
    }
    Start-Sleep -Seconds 2
}

function Stop-ShellProcesses {
    $names = @(
        'SearchHost',
        'ShellExperienceHost',
        'StartMenuExperienceHost',
        'ShellHost',
        'RuntimeBroker',
        'explorer'
    )
    foreach ($name in $names) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "Stopping $($_.Name) pid=$($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
}

function Start-Shell {
    if (-not (Get-Process -Name explorer -ErrorAction SilentlyContinue)) {
        Start-Process explorer.exe
    }
    Start-Sleep -Seconds 3
    $hostExe = Join-Path $env:WINDIR 'SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe'
    if (Test-Path $hostExe) {
        if (-not (Get-Process -Name StartMenuExperienceHost -ErrorAction SilentlyContinue)) {
            Start-Process $hostExe
        }
    }
    Start-Sleep -Seconds 2
}

function Get-ShellStatus {
    $procs = Get-Process explorer, StartMenuExperienceHost, ShellExperienceHost, SearchHost -ErrorAction SilentlyContinue
    $tray = [WinShellNative]::FindWindow('Shell_TrayWnd', $null)
    $hung = $false
    if ($tray -ne [IntPtr]::Zero) {
        $hung = [WinShellNative]::IsHungAppWindow($tray)
    }
    [pscustomobject]@{
        Explorer          = [bool]($procs | Where-Object Name -eq 'explorer')
        StartHost         = [bool]($procs | Where-Object Name -eq 'StartMenuExperienceHost')
        ShellExperience   = [bool]($procs | Where-Object Name -eq 'ShellExperienceHost')
        SearchHost        = [bool]($procs | Where-Object Name -eq 'SearchHost')
        TrayWindow        = ($tray -ne [IntPtr]::Zero)
        TrayHung          = $hung
    }
}

function Show-Status {
    $status = Get-ShellStatus
    $status | Format-List | Out-String | Write-Host
    Write-Host "Displays:"
    Get-DisplayTargets | Format-Table Adapter, Monitor, Attached, Primary, Width, Height, X, Y -AutoSize | Out-String | Write-Host
}

function Invoke-Restore {
    param([string]$Pattern)
    Write-Host "Do not press the Windows key while this runs."
    Dismount-MatchedDisplays -Pattern $Pattern | Out-Null
    if (-not $NoGpuReset) {
        Send-GpuReset
    }
    Stop-ShellProcesses
    Start-Shell
    $status = Get-ShellStatus
    $status | Format-List | Out-String | Write-Host
    if (-not $status.StartHost) {
        Write-Host "Start host still down. If hover shows a spinner, sign out. Do not wipe Start LocalState."
        return 1
    }
    Write-Host "Shell restored. Leave Start closed for a minute."
    return 0
}

function Install-KeepAlive {
    param([string]$Pattern, [string]$Name)
    $scriptPath = $PSCommandPath
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" watch --Match `"$Pattern`" --IntervalSeconds $IntervalSeconds"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $Name
    Write-Host "Installed and started task '$Name' (detach '$Pattern' at logon, then watch)."
}

function Uninstall-KeepAlive {
    param([string]$Name)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed task '$Name'."
}

function Set-DpiCompat {
    param([string]$Path, [string]$Mode)
    if (-not (Test-Path $Path)) {
        throw "Exe not found: $Path"
    }
    $layers = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
    if (-not (Test-Path $layers)) {
        New-Item $layers -Force | Out-Null
    }
    $value = "~ $Mode"
    New-ItemProperty -Path $layers -Name $Path -Value $value -PropertyType String -Force | Out-Null
    Write-Host "Set DPI compat for $Path -> $value"
    Write-Host "Restart that app for the flag to apply."
}

switch ($Command) {
    'status' { Show-Status }
    'detach' { Dismount-MatchedDisplays -Pattern $Match | Out-Null }
    'restore' { exit (Invoke-Restore -Pattern $Match) }
    'watch' {
        Write-Host "Watching for '$Match' every ${IntervalSeconds}s. Ctrl+C to stop."
        while ($true) {
            try { Dismount-MatchedDisplays -Pattern $Match | Out-Null } catch { Write-Host $_ }
            Start-Sleep -Seconds $IntervalSeconds
        }
    }
    'install' { Install-KeepAlive -Pattern $Match -Name $TaskName }
    'uninstall' { Uninstall-KeepAlive -Name $TaskName }
    'set-dpi' { Set-DpiCompat -Path $Exe -DpiMode $DpiMode }
}
