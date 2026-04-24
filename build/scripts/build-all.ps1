param(
    [string]$ApiUrl = "https://aiteachme.onrender.com",
    [switch]$SkipInstall,
    [string]$BackendPort = "8010"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Invoke-BuildStep {
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "==== $Name ====" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode"
    }
}

$repoRoot = Resolve-RepoRoot
$scriptDir = $PSScriptRoot

$commonArgs = @()
if ($SkipInstall) {
    $commonArgs += "-SkipInstall"
}

Invoke-BuildStep `
    -Name "Electron local installer and portable" `
    -Script (Join-Path $scriptDir "build-electron-local.ps1") `
    -Arguments @($commonArgs + @("-BackendPort", $BackendPort))

Invoke-BuildStep `
    -Name "Electron remote installer and portable" `
    -Script (Join-Path $scriptDir "build-electron-remote.ps1") `
    -Arguments @($commonArgs + @("-ApiUrl", $ApiUrl))

Invoke-BuildStep `
    -Name "Tauri local installer and direct package" `
    -Script (Join-Path $scriptDir "build-tauri-local.ps1") `
    -Arguments @($commonArgs + @("-BackendPort", $BackendPort))

Invoke-BuildStep `
    -Name "Tauri remote installer and direct package" `
    -Script (Join-Path $scriptDir "build-tauri-remote.ps1") `
    -Arguments @($commonArgs + @("-ApiUrl", $ApiUrl))

Write-Host ""
Write-Host "All desktop packages generated under:" -ForegroundColor Green
Write-Host "  $(Join-Path $repoRoot "build\artifacts")"
