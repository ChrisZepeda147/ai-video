# Start the FastAPI discovery backend (port 8000). Kills stale API first.
$Root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "stop-api.ps1") -Port 8000
Set-Location $Root

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($userPath -or $machinePath) {
    $env:Path = @($userPath, $machinePath, $env:Path) -join ';'
}

function Resolve-PythonExe {
    if ($env:AI_VIDEO_PYTHON -and (Test-Path -LiteralPath $env:AI_VIDEO_PYTHON)) {
        return $env:AI_VIDEO_PYTHON
    }
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
            return $cmd.Source
        }
    }
    $fallback = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($path in $fallback) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    $storeMatches = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WindowsApps" -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'PythonSoftwareFoundation' } |
        Sort-Object FullName -Descending
    if ($storeMatches) {
        return $storeMatches[0].FullName
    }
    return $null
}

$Python = Resolve-PythonExe
if (-not $Python) {
    Write-Error "Python not found. Install Python 3.11+ or set AI_VIDEO_PYTHON to your python.exe path."
    exit 1
}

Write-Host "Using Python: $Python"
$envFile = Join-Path $Root "scripts\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or $line -notmatch '=') { return }
        $name, $value = $line.Split('=', 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& $Python -m pip install -r requirements-api.txt -q
if (Test-Path "scripts/requirements-youtube.txt") {
    & $Python -m pip install -r scripts/requirements-youtube.txt -q
}
& $Python -m uvicorn api.main:app --reload --port 8000
