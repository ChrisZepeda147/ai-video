# Stop FastAPI on port 8000 (and uvicorn reloader child).
param(
    [int]$Port = 8000
)

$Stopped = @()

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessTree -ProcessId $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

$Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($Conn in $Connections) {
    $ProcId = [int]$Conn.OwningProcess
    if ($ProcId -gt 0 -and $Stopped -notcontains $ProcId) {
        Write-Host "Stopping API on port ${Port}: PID $ProcId"
        Stop-ProcessTree -ProcessId $ProcId
        $Stopped += $ProcId
    }
}

if ($Stopped.Count -gt 0) {
    Start-Sleep -Seconds 1
    Write-Host "API port $Port cleared ($($Stopped.Count) process(es) stopped)."
} else {
    Write-Host "API port $Port is free."
}
