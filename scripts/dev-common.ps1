# Shared helpers for start-dev / start-api / start-dashboard.

function Import-DevPath {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $extra = @(
        "$env:LOCALAPPDATA\Programs\nodejs",
        "$env:ProgramFiles\nodejs",
        "${env:ProgramFiles(x86)}\nodejs",
        "$env:ProgramFiles\Git\cmd"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $env:Path = (@($extra) + @($userPath, $machinePath, $env:Path) | Where-Object { $_ }) -join ';'
}

function Resolve-NpmCmd {
    $fallback = @(
        "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd",
        "$env:ProgramFiles\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd"
    )
    foreach ($path in $fallback) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    return $null
}

function Resolve-NpxCmd {
    $npm = Resolve-NpmCmd
    if ($npm) {
        $npx = Join-Path (Split-Path $npm) "npx.cmd"
        if (Test-Path -LiteralPath $npx) { return $npx }
    }
    $cmd = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    return $null
}

function Test-ApiPortListening {
    param([int]$Port = 8000)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Test-ApiHealthy {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-UsablePythonPath {
    param([string]$Path)
    return $Path -and (Test-Path -LiteralPath $Path) -and ($Path -notmatch "WindowsApps")
}

function Test-PythonApiReady {
    param([string]$PythonExe)
    if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) { return $false }
    & $PythonExe -c "import uvicorn, fastapi" 2>$null
    return $LASTEXITCODE -eq 0
}

function Resolve-PythonExe {
    $try = @()
    if ($env:AI_VIDEO_PYTHON) { $try += $env:AI_VIDEO_PYTHON.Trim() }
    $try += @(
        "$env:LOCALAPPDATA\Python\bin\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $try += $cmd.Source }
    }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $resolved = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1).Trim()
            if ($resolved) { $try += $resolved }
        } catch { }
    }
    foreach ($path in ($try | Select-Object -Unique)) {
        if (-not $path) { continue }
        if (Test-UsablePythonPath $path) { return $path }
        if ($path -match "WindowsApps" -and (Test-PythonApiReady $path)) { return $path }
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

function Get-AgentToolBins {
    $bins = @()
    $pythonExe = $null
    if ($env:AI_VIDEO_PYTHON -and (Test-Path -LiteralPath $env:AI_VIDEO_PYTHON)) {
        $pythonExe = $env:AI_VIDEO_PYTHON
    } else {
        $pythonExe = Resolve-PythonExe
    }
    if ($pythonExe) {
        $bins += (Split-Path -Parent $pythonExe)
        $env:AI_VIDEO_PYTHON = $pythonExe
    }
    if ($env:FFMPEG_DIR -and (Test-Path -LiteralPath $env:FFMPEG_DIR)) {
        $bins += $env:FFMPEG_DIR
    }
    return $bins | Select-Object -Unique
}

function Test-PathListContainsDir {
    param([string]$PathList, [string]$Dir)
    if (-not $Dir) { return $false }
    $want = $Dir.TrimEnd('\')
    foreach ($part in @($PathList -split ';')) {
        if ($part -and ($part.TrimEnd('\') -ieq $want)) { return $true }
    }
    return $false
}

function Import-AgentPythonPath {
    param(
        [string]$Root,
        [switch]$Persist,
        [switch]$NoPersist
    )
    Import-ApiEnvFile -Root $Root
    $bins = @(Get-AgentToolBins)
    foreach ($bin in $bins) {
        $env:Path = "$bin;" + (($env:Path -split ';' | Where-Object { $_ -and ($_ -ne $bin) }) -join ';')
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = "" }
    $missingFromUser = @($bins | Where-Object { -not (Test-PathListContainsDir -PathList $userPath -Dir $_) })
    $doPersist = (-not $NoPersist) -and ($Persist -or ($missingFromUser.Count -gt 0))
    if (-not $doPersist) { return $bins }
    $parts = @($bins) + @($userPath -split ';' | Where-Object { $_ -and ($bins -notcontains $_) })
    [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')
    if ($env:AI_VIDEO_PYTHON) {
        [Environment]::SetEnvironmentVariable('AI_VIDEO_PYTHON', $env:AI_VIDEO_PYTHON, 'User')
    }
    if ($env:FFMPEG_DIR) {
        [Environment]::SetEnvironmentVariable('FFMPEG_DIR', $env:FFMPEG_DIR, 'User')
    }
    return $bins
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

function Wait-ApiHealthy {
    param([int]$Seconds = 45)
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-ApiHealthy) {
            Write-Host "Discovery API ready on http://127.0.0.1:8000"
            return $true
        }
        if ($i -eq 1) {
            Write-Host "Waiting for API (up to ${Seconds}s) before starting dashboard..."
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "API did not become healthy. Check data/logs/api-dev.err"
    return $false
}

function Wait-ApiHealthySoft {
    param([int]$Seconds = 30)
    return Wait-ApiHealthy -Seconds $Seconds
}
