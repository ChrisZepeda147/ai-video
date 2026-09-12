# Interactive OAuth env setup — paste keys from YOUR developer portals.
# Usage: .\scripts\setup-oauth-env.ps1
# Redirect URI for all platforms: http://localhost:3000/accounts/callback

$ErrorActionPreference = "Stop"
$envPath = Join-Path $PSScriptRoot ".env"
$redirectUri = "http://localhost:3000/accounts/callback"

Write-Host ""
Write-Host "Social OAuth setup (YouTube + TikTok)" -ForegroundColor Cyan
Write-Host "Redirect URI (register this everywhere):" -ForegroundColor Yellow
Write-Host "  $redirectUri" -ForegroundColor White
Write-Host ""
Write-Host "I cannot create keys for you — they must come from YOUR accounts:" -ForegroundColor DarkGray
Write-Host "  YouTube: https://console.cloud.google.com/apis/credentials" -ForegroundColor DarkGray
Write-Host "  TikTok:  https://developers.tiktok.com/" -ForegroundColor DarkGray
Write-Host ""

$open = Read-Host "Open those URLs in browser now? [Y/n]"
if ($open -ne "n" -and $open -ne "N") {
    Start-Process "https://console.cloud.google.com/apis/credentials"
    Start-Sleep -Milliseconds 800
    Start-Process "https://developers.tiktok.com/"
}

Write-Host ""
Write-Host "--- YouTube (Google Cloud OAuth client) ---" -ForegroundColor Cyan
Write-Host "1. Enable YouTube Data API v3"
Write-Host "2. OAuth consent screen -> add your Gmail as test user"
Write-Host "3. Create OAuth client (Web) -> redirect: $redirectUri"
Write-Host ""
$ytId = Read-Host "Paste YOUTUBE_CLIENT_ID (or Enter to skip)"
$ytSecret = ""
if ($ytId.Trim()) {
    $ytSecret = Read-Host "Paste YOUTUBE_CLIENT_SECRET"
}

Write-Host ""
Write-Host "--- TikTok (developer app -> Login Kit) ---" -ForegroundColor Cyan
Write-Host "1. Create app -> add Login Kit"
Write-Host "2. Redirect URI: $redirectUri"
Write-Host ""
$ttKey = Read-Host "Paste TIKTOK_CLIENT_KEY (or Enter to skip)"
$ttSecret = ""
if ($ttKey.Trim()) {
    $ttSecret = Read-Host "Paste TIKTOK_CLIENT_SECRET"
}

function Set-EnvLine {
    param(
        [string[]]$Lines,
        [string]$Key,
        [string]$Value
    )
    $pattern = "^\s*$([regex]::Escape($Key))\s*="
    $newLine = "$Key=$Value"
    $found = $false
    $out = @()
    foreach ($line in $Lines) {
        if ($line -match $pattern) {
            if ($Value) {
                $out += $newLine
            }
            $found = $true
        } elseif ($line -match "^\s*#\s*$([regex]::Escape($Key))\s*=") {
            if ($Value) {
                $out += $newLine
            } else {
                $out += $line
            }
            $found = $true
        } else {
            $out += $line
        }
    }
    if (-not $found -and $Value) {
        $out += $newLine
    }
    return ,$out
}

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envPath
    Write-Host "Created scripts/.env from .env.example" -ForegroundColor Yellow
}

$lines = Get-Content -LiteralPath $envPath -Encoding UTF8

if ($ytId.Trim()) {
    $lines = Set-EnvLine -Lines $lines -Key "YOUTUBE_CLIENT_ID" -Value $ytId.Trim()
    $lines = Set-EnvLine -Lines $lines -Key "YOUTUBE_CLIENT_SECRET" -Value $ytSecret.Trim()
    $lines = Set-EnvLine -Lines $lines -Key "YOUTUBE_REDIRECT_URI" -Value $redirectUri
    Write-Host "YouTube keys saved." -ForegroundColor Green
}

if ($ttKey.Trim()) {
    $lines = Set-EnvLine -Lines $lines -Key "TIKTOK_CLIENT_KEY" -Value $ttKey.Trim()
    $lines = Set-EnvLine -Lines $lines -Key "TIKTOK_CLIENT_SECRET" -Value $ttSecret.Trim()
    $lines = Set-EnvLine -Lines $lines -Key "TIKTOK_REDIRECT_URI" -Value $redirectUri
    Write-Host "TikTok keys saved." -ForegroundColor Green
}

$lines = Set-EnvLine -Lines $lines -Key "PUBLISHING_OAUTH_REDIRECT_BASE" -Value "http://localhost:3000"
$lines | Set-Content -LiteralPath $envPath -Encoding UTF8

Write-Host ""
Write-Host "Done. Restart dev stack:" -ForegroundColor Green
Write-Host "  npm run dev" -ForegroundColor White
Write-Host "Then Accounts -> Connect YouTube / TikTok" -ForegroundColor White
Write-Host ""
