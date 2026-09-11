# Shared helpers for start-dev / start-api / start-dashboard.

function Test-ApiHealthy {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Resolve-PythonExe {
    if ($env:AI_VIDEO_PYTHON -and (Test-Path -LiteralPath $env:AI_VIDEO_PYTHON)) {
        return $env:AI_VIDEO_PYTHON
    }
    $fallback = @(
        "$env:LOCALAPPDATA\Python\bin\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($path in $fallback) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source) -and ($cmd.Source -notmatch "WindowsApps")) {
            return $cmd.Source
        }
    }
    $storeMatches = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WindowsApps" -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'PythonSoftwareFoundation' } |
        Sort-Object FullName -Descending
    if ($storeMatches) {
        return $storeMatches[0].FullName
    }
    return $null
}

function Import-ApiEnvFile {
    param([string]$Root)
    $envFile = Join-Path $Root "scripts\.env"
    if (-not (Test-Path $envFile)) { return }
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

function Test-ApiPythonDeps {
    param([string]$Python)
    if ($env:AI_VIDEO_FORCE_PIP -eq "1") { return $false }
    & $Python -c "import uvicorn, fastapi" 2>$null
    return $LASTEXITCODE -eq 0
}

function Install-ApiPythonDeps {
    param(
        [string]$Python,
        [string]$Root
    )
    if (Test-ApiPythonDeps -Python $Python) {
        Write-Host "Python API deps OK (skipping pip install)."
        return
    }
    Write-Host "Installing Python API deps (first run or after requirements change)..."
    Set-Location $Root
    & $Python -m pip install -r requirements-api.txt -q
    if (Test-Path "scripts/requirements-youtube.txt") {
        & $Python -m pip install -r scripts/requirements-youtube.txt -q
    }
}

function Start-ApiServer {
    param(
        [string]$Root,
        [string]$Python,
        [switch]$Background
    )
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Import-ApiEnvFile -Root $Root
    Install-ApiPythonDeps -Python $Python -Root $Root

    $uvicornArgs = @("-m", "uvicorn", "api.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000")
    Write-Host "$Python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000"
    if ($Background) {
        $logDir = Join-Path $Root "data/logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $logFile = Join-Path $logDir "api-dev.log"
        $errFile = Join-Path $logDir "api-dev.err"
        Write-Host "API log: $logFile"
        Start-Process -FilePath $Python -ArgumentList $uvicornArgs -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput $logFile -RedirectStandardError $errFile | Out-Null
        return
    }
    & $Python @uvicornArgs
}

function Wait-ApiHealthySoft {
    param([int]$Seconds = 30)
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-ApiHealthy) {
            Write-Host "Discovery API ready on http://127.0.0.1:8000"
            return $true
        }
        if ($i -eq 1) {
            Write-Host "Waiting for API (up to ${Seconds}s)..."
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "API still starting - dashboard will load; refresh if you see an offline banner."
    return $false
}
