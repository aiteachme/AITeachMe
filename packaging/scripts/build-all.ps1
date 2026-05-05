param(
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [string]$BackendPort = "",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled",
    [switch]$IncludeTauri,
    [switch]$TauriOnly,
    [switch]$IncludeRemote
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
$bundledEnvArgs = @()
if ($ImportBundledEnv) {
    $bundledEnvArgs += @(
        "-ImportBundledEnv",
        "-BundledEnvConfigPath",
        $BundledEnvConfigPath,
        "-BundledEnvArtifactSuffix",
        $BundledEnvArtifactSuffix
    )
}

$buildTauri = $IncludeTauri -or $TauriOnly

if (-not $TauriOnly) {
    $electronLocalArgs = @($commonArgs + $bundledEnvArgs + @("-Flavor", "local", "-HideElectronSuffix"))
    if (-not [string]::IsNullOrWhiteSpace($BackendPort)) {
        $electronLocalArgs += @("-BackendPort", $BackendPort)
    }

    Invoke-BuildStep `
        -Name "Electron local installer" `
        -Script (Join-Path $scriptDir "build-electron.ps1") `
        -Arguments $electronLocalArgs
}

if ($buildTauri) {
    Invoke-BuildStep `
        -Name "Tauri local installer" `
        -Script (Join-Path $scriptDir "build-tauri.ps1") `
        -Arguments @($commonArgs + $bundledEnvArgs + @("-Flavor", "local"))
}

if ($IncludeRemote) {
    if (-not $TauriOnly) {
        Invoke-BuildStep `
            -Name "Electron remote installer" `
            -Script (Join-Path $scriptDir "build-electron.ps1") `
            -Arguments @($commonArgs + @("-Flavor", "remote", "-ApiUrl", $ApiUrl, "-HideElectronSuffix"))
    }

    if ($buildTauri) {
        Invoke-BuildStep `
            -Name "Tauri remote installer" `
            -Script (Join-Path $scriptDir "build-tauri.ps1") `
            -Arguments @($commonArgs + @("-Flavor", "remote", "-ApiUrl", $ApiUrl))
    }
}

Write-Host ""
Write-Host "All desktop packages generated under:" -ForegroundColor Green
Write-Host "  $(Join-Path $repoRoot "packaging\release")"
