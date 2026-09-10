# Stop any Next.js dev server on the dashboard port and clear stale locks.
param(
    [int]$Port = 3000
)

$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "web"
$Stopped = @()

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree -ProcessId $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

# Kill anything listening on the dashboard port.
$Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($Conn in $Connections) {
    $ProcId = [int]$Conn.OwningProcess
    if ($ProcId -gt 0 -and $Stopped -notcontains $ProcId) {
        Write-Host "Stopping process on port ${Port}: PID $ProcId"
        Stop-ProcessTree -ProcessId $ProcId
        $Stopped += $ProcId
    }
}

# Next 16 tracks a running dev PID — kill it if still alive.
$DevDir = Join-Path $Web ".next\dev"
$PidFile = Join-Path $DevDir "pid"
if (Test-Path $PidFile) {
    $OldPid = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
    if ($OldPid -match '^\d+$') {
        $OldPidInt = [int]$OldPid.Trim()
        if ($OldPidInt -gt 0 -and $Stopped -notcontains $OldPidInt) {
            Write-Host "Stopping stale Next dev PID $OldPidInt"
            Stop-ProcessTree -ProcessId $OldPidInt
            $Stopped += $OldPidInt
        }
    }
}

# Remove lock files so a fresh dev server can start.
foreach ($LockPath in @(
    (Join-Path $DevDir "lock"),
    $PidFile
)) {
    if (Test-Path $LockPath) {
        Remove-Item $LockPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($Stopped.Count -gt 0) {
    Start-Sleep -Seconds 1
    Write-Host "Dashboard port $Port cleared ($($Stopped.Count) process(es) stopped)."
} else {
    Write-Host "Dashboard port $Port is free."
}
