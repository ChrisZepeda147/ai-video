# Keep Stephen + Chris source even on both GitHub remotes.
# Every tick: fetch BOTH remotes, auto-commit local source, merge his
# commits (incoming wins on clash), push origin + chris.
# Never force-push. Never commits .env, downloads/, data/, or used.json.
#
#   powershell -File scripts/github_brother_sync.ps1 tick
#   powershell -File scripts/github_brother_sync.ps1 install
#   powershell -File scripts/github_brother_sync.ps1 uninstall

param(
    [Parameter(Position = 0)]
    [ValidateSet("tick", "install", "uninstall", "status")]
    [string]$Action = "tick",

    [int]$Minutes = 5
)

$ErrorActionPreference = "Continue"
$TaskName = "AiVideoGitHubSync"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\shared_library"
$LogPath = Join-Path $LogDir "github_sync.log"
$LockPath = Join-Path $LogDir "github_sync.lock"
# Task Scheduler /TR breaks on spaces — keep launcher under LocalAppData (no spaces in path).
$SilentVbsDir = Join-Path $env:LOCALAPPDATA "AiVideo"
$SilentVbsPath = Join-Path $SilentVbsDir "github_brother_sync_silent.vbs"
$LegacySilentVbsPath = Join-Path $LogDir "github_brother_sync_silent.vbs"
$StashMessage = "github-brother-sync"
$GitExe = $null

function Get-GitExe {
    if ($script:GitExe) { return $script:GitExe }
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $script:GitExe = $cmd.Source
        return $script:GitExe
    }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles "Git\cmd\git.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe")
    )) {
        if ($candidate -and (Test-Path $candidate)) {
            $script:GitExe = $candidate
            return $script:GitExe
        }
    }
    $script:GitExe = "git"
    return $script:GitExe
}

function Write-SyncLog([string]$Message) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Add-Content -Path $LogPath -Value $line -Encoding utf8
    if ((Get-Item $LogPath).Length -gt 256000) {
        $keep = Get-Content $LogPath -Tail 200
        Set-Content -Path $LogPath -Value $keep -Encoding utf8
    }
}

function ConvertTo-ProcessArgumentString([string[]]$Parts) {
    ($Parts | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        } else {
            $_
        }
    }) -join " "
}

function Invoke-Git {
    param([string[]]$GitArgs)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Get-GitExe
    $psi.Arguments = ConvertTo-ProcessArgumentString(@("-C", $Root) + $GitArgs)
    $psi.WorkingDirectory = $Root
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    $out = @($stdout, $stderr) | Where-Object { $_ } | ForEach-Object { $_.TrimEnd() }
    return [pscustomobject]@{
        Code   = $proc.ExitCode
        Output = ($out -join "`n").Trim()
    }
}

function Test-SourcePath([string]$Path) {
    $rel = $Path.Replace("\", "/").Trim()
    $name = Split-Path $rel -Leaf
    if ($name -eq ".env" -or $name -eq ".env.local" -or $name -eq "credentials.json") { return $false }
    if ($rel -eq "scripts/.env") { return $false }
    if ($rel.StartsWith("downloads/") -or $rel.StartsWith("data/") -or $rel.StartsWith("notes/")) { return $false }
    if ($rel -eq "content/used.json") { return $false }
    return (
        $rel.StartsWith("scripts/") -or
        $rel.StartsWith("web/") -or
        $rel.StartsWith("api/") -or
        $rel.StartsWith(".cursor/")
    )
}

function Get-PorcelainPath([string]$Line) {
    $body = $Line.Substring(3).Trim()
    if ($body -match " -> ") { $body = ($body -split " -> ", 2)[1] }
    return $body.Replace("\", "/")
}

function Commit-SourceChanges {
    $status = Invoke-Git @("status", "--porcelain")
    if (-not $status.Output) {
        return @{ Committed = $false; Files = @() }
    }
    $files = @()
    foreach ($line in ($status.Output -split "`n")) {
        if (-not $line.Trim()) { continue }
        $path = Get-PorcelainPath $line
        if (Test-SourcePath $path) { $files += $path }
    }
    if ($files.Count -eq 0) {
        return @{ Committed = $false; Files = @() }
    }
    foreach ($path in $files) {
        $add = Invoke-Git @("add", "--", $path)
        if ($add.Code -ne 0) { throw "git add $path failed: $($add.Output)" }
    }
    $commit = Invoke-Git @("commit", "-m", "brother sync: auto checkpoint")
    if ($commit.Code -ne 0) {
        if ($commit.Output -match "nothing to commit") {
            return @{ Committed = $false; Files = @() }
        }
        throw "git commit failed: $($commit.Output)"
    }
    return @{ Committed = $true; Files = $files }
}

function Merge-Incoming([string]$Remote) {
    $ref = "$Remote/main"
    $exists = Invoke-Git @("rev-parse", "--verify", $ref)
    if ($exists.Code -ne 0) {
        return @{ Ok = $true; Merged = $false; Reason = "missing $ref" }
    }
    $state = Get-AheadBehind $ref
    if ($state.Behind -le 0) {
        return @{ Ok = $true; Merged = $false; Behind = 0 }
    }

    $merge = Invoke-Git @("merge", "--no-edit", $ref)
    if ($merge.Code -eq 0) {
        return @{ Ok = $true; Merged = $true; Strategy = "merge"; Behind = $state.Behind }
    }
    [void](Invoke-Git @("merge", "--abort"))

    $theirs = Invoke-Git @("merge", "-X", "theirs", "--no-edit", $ref)
    if ($theirs.Code -eq 0) {
        Write-SyncLog ("fetch  {0}  {1} commit(s) kept incoming on clash" -f $Remote, $state.Behind)
        return @{ Ok = $true; Merged = $true; Strategy = "theirs"; Behind = $state.Behind }
    }
    [void](Invoke-Git @("merge", "--abort"))
    return @{ Ok = $false; Error = $theirs.Output; Behind = $state.Behind }
}

function Get-AheadBehind([string]$Ref) {
    $behind = Invoke-Git @("rev-list", "--count", "HEAD..$Ref")
    $ahead = Invoke-Git @("rev-list", "--count", "$Ref..HEAD")
    $b = 0; $a = 0
    if ($behind.Code -eq 0) { [void][int]::TryParse($behind.Output, [ref]$b) }
    if ($ahead.Code -eq 0) { [void][int]::TryParse($ahead.Output, [ref]$a) }
    return @{ Behind = $b; Ahead = $a }
}

function Write-SilentLauncher {
    $script = Join-Path $PSScriptRoot "github_brother_sync.ps1"
    $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    New-Item -ItemType Directory -Force -Path $SilentVbsDir | Out-Null
    if (Test-Path $LegacySilentVbsPath) {
        Remove-Item -Force $LegacySilentVbsPath -ErrorAction SilentlyContinue
    }
    $cmd = "$powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" tick"
    $escaped = $cmd.Replace('"', '""')
    $rootEsc = $Root.Replace('"', '""')
    @(
        "On Error Resume Next"
        "Set sh = CreateObject(""Wscript.Shell"")"
        "sh.CurrentDirectory = ""$rootEsc"""
        "sh.Run ""$escaped"", 0, False"
    ) -join "`r`n" | Set-Content -Path $SilentVbsPath -Encoding ASCII
    return $SilentVbsPath
}

function Set-ScheduledTaskHidden([string]$Name) {
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $folder = $svc.GetFolder("\")
    $task = $folder.GetTask($Name)
    $def = $task.Definition
    $def.Settings.Hidden = $true
    [void]$folder.RegisterTaskDefinition($Name, $def, 4, $null, $null, 3, $null)
}

function Install-SyncTask {
    $vbs = Write-SilentLauncher
    $wscript = Join-Path $env:WINDIR "System32\wscript.exe"
    $tr = "`"$wscript`" //B //Nologo `"$vbs`""
    # /TR must be one argv — repo path has spaces (e.g. Youtube AI).
    $create = & schtasks.exe @(
        "/Create", "/TN", $TaskName, "/SC", "MINUTE", "/MO", "$Minutes",
        "/RL", "LIMITED", "/F", "/TR", $tr
    ) 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks create failed: $create"
    }
    try {
        Set-ScheduledTaskHidden $TaskName
    } catch {
        Write-SyncLog "warn  could not mark task Hidden: $_"
    }
    Write-Host "installed $TaskName every $Minutes min (silent)"
    Write-Host "log: $LogPath"
}

function Uninstall-SyncTask {
    schtasks /Delete /TN $TaskName /F | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "removed $TaskName"
    } else {
        Write-Host "task not found"
    }
    foreach ($p in @($SilentVbsPath, $LegacySilentVbsPath)) {
        if (Test-Path $p) {
            Remove-Item -Force $p -ErrorAction SilentlyContinue
        }
    }
}

function Show-SyncStatus {
    $query = schtasks /Query /TN $TaskName /FO LIST 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host $query
    } else {
        Write-Host "scheduled task: not installed"
    }
    if (Test-Path $LogPath) {
        Write-Host "last log lines:"
        Get-Content $LogPath -Tail 8
    }
}

function Sync-Tick {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $lock = $null
    try {
        $lock = [System.IO.File]::Open($LockPath, "OpenOrCreate", "ReadWrite", "None")
    } catch {
        Write-SyncLog "skip  lock held"
        Write-Host "another sync is running"
        exit 0
    }

    $stashed = $false
    $exitCode = 0
    try {
        $fetchErrors = @()
        foreach ($remote in @("origin", "chris")) {
            $fetch = Invoke-Git @("fetch", $remote)
            if ($fetch.Code -ne 0) {
                $fetchErrors += ("{0}: {1}" -f $remote, $fetch.Output)
            } else {
                Write-SyncLog "fetch  $remote  ok"
            }
        }
        if ($fetchErrors.Count -eq 2) { throw "git fetch failed: $($fetchErrors -join ' | ')" }

        $checkpoint = Commit-SourceChanges
        if ($checkpoint.Committed) {
            Write-SyncLog ("commit  {0}" -f ($checkpoint.Files -join ", "))
        }

        $dirty = (Invoke-Git @("status", "--porcelain")).Output
        if ($dirty) {
            $stash = Invoke-Git @("stash", "push", "-u", "-m", $StashMessage)
            if ($stash.Code -ne 0) { throw "git stash failed: $($stash.Output)" }
            $stashed = $true
        }

        foreach ($remote in @("origin", "chris")) {
            $merged = Merge-Incoming $remote
            if (-not $merged.Ok) { throw "merge $remote/main failed: $($merged.Error)" }
            if ($merged.Merged) {
                Write-SyncLog "merged  $remote  $($merged.Behind) commit(s)  $($merged.Strategy)"
            }
        }

        $pushed = @()
        foreach ($remote in @("origin", "chris")) {
            $has = Invoke-Git @("remote", "get-url", $remote)
            if ($has.Code -ne 0) { continue }
            $state = Get-AheadBehind "$remote/main"
            if ($state.Ahead -le 0) { continue }
            $push = Invoke-Git @("push", $remote, "HEAD:main")
            if ($push.Code -ne 0) { throw "git push $remote failed: $($push.Output)" }
            $pushed += $remote
        }

        $final = Get-AheadBehind "origin/main"
        $msg = "ok  behind=$($final.Behind) ahead=$($final.Ahead) pushed=$($pushed -join ',')"
        Write-SyncLog $msg
        Write-Host $msg
        if ($final.Behind -gt 0 -or $final.Ahead -gt 0) { $exitCode = 2 }
    } catch {
        Write-SyncLog "fail  $_"
        Write-Host $_
        $exitCode = 2
    } finally {
        if ($stashed) {
            $pop = Invoke-Git @("stash", "pop")
            if ($pop.Code -ne 0) {
                Write-SyncLog "stash-pop-fail  $($pop.Output)"
            }
        }
        if ($lock) { $lock.Close() }
    }
    exit $exitCode
}

switch ($Action) {
    "install" { Install-SyncTask }
    "uninstall" { Uninstall-SyncTask }
    "status" { Show-SyncStatus }
    default { Sync-Tick }
}
