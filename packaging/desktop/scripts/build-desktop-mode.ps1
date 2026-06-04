param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("tauri-local", "tauri-remote", "electron-local", "electron-remote", "all-local", "all")]
    [string]$PackageMode,
    [string]$BackendPort = "",
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [switch]$HideElectronSuffix,
    [switch]$ImportBundledEnv,
    [switch]$RequireTauriUpdater,
    [string]$BundledEnvConfigPath = "packaging\desktop\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}

function Invoke-PackagingScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    & powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    if ($exitCode -ne 0) {
        throw "$ScriptPath failed with exit code $exitCode"
    }
}

function Build-ElectronLocal {
    $arguments = @("-Flavor", "local")
    if (-not [string]::IsNullOrWhiteSpace($BackendPort)) {
        $arguments += @("-BackendPort", $BackendPort)
    }
    if ($SkipInstall) {
        $arguments += "-SkipInstall"
    }
    if ($HideElectronSuffix) {
        $arguments += "-HideElectronSuffix"
    }
    if ($ImportBundledEnv) {
        $arguments += @(
            "-ImportBundledEnv",
            "-BundledEnvConfigPath",
            $BundledEnvConfigPath,
            "-BundledEnvArtifactSuffix",
            $BundledEnvArtifactSuffix
        )
    }

    Invoke-PackagingScript `
        -ScriptPath (Join-Path $scriptDir "build-electron.ps1") `
        -Arguments $arguments
}

function Build-ElectronRemote {
    $arguments = @("-Flavor", "remote", "-ApiUrl", $ApiUrl)
    if ($SkipInstall) {
        $arguments += "-SkipInstall"
    }
    if ($HideElectronSuffix) {
        $arguments += "-HideElectronSuffix"
    }

    Invoke-PackagingScript `
        -ScriptPath (Join-Path $scriptDir "build-electron.ps1") `
        -Arguments $arguments
}

function Build-TauriLocal {
    $arguments = @("-Flavor", "local")
    if ($SkipInstall) {
        $arguments += "-SkipInstall"
    }
    if ($ImportBundledEnv) {
        $arguments += @(
            "-ImportBundledEnv",
            "-BundledEnvConfigPath",
            $BundledEnvConfigPath,
            "-BundledEnvArtifactSuffix",
            $BundledEnvArtifactSuffix
        )
    }
    if ($RequireTauriUpdater) {
        $arguments += "-RequireUpdater"
    }

    Invoke-PackagingScript `
        -ScriptPath (Join-Path $scriptDir "build-tauri.ps1") `
        -Arguments $arguments
}

function Build-TauriRemote {
    $arguments = @("-Flavor", "remote", "-ApiUrl", $ApiUrl)
    if ($SkipInstall) {
        $arguments += "-SkipInstall"
    }

    Invoke-PackagingScript `
        -ScriptPath (Join-Path $scriptDir "build-tauri.ps1") `
        -Arguments $arguments
}

$repoRoot = Resolve-RepoRoot
$scriptDir = $PSScriptRoot

Write-Host "Repo: $repoRoot"
Write-Host "Package mode: $PackageMode"
if ($ImportBundledEnv -and $PackageMode -notin @("electron-local", "tauri-local", "all-local", "all")) {
    throw "Bundled env can only be imported for local package modes."
}

switch ($PackageMode) {
    "electron-local" {
        Build-ElectronLocal
    }
    "electron-remote" {
        Build-ElectronRemote
    }
    "tauri-local" {
        Build-TauriLocal
    }
    "tauri-remote" {
        Build-TauriRemote
    }
    "all-local" {
        Build-ElectronLocal
        Build-TauriLocal
    }
    "all" {
        Build-ElectronLocal
        Build-TauriLocal
        Build-ElectronRemote
        Build-TauriRemote
    }
}
