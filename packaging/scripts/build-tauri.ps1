param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("local", "remote")]
    [string]$Flavor,
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled"
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")
. (Join-Path $PSScriptRoot "bundled-env-common.ps1")

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$npm = Resolve-CommandPath @("npm.cmd", "npm")
$defaultTauriLocalUpdaterEndpoint = "https://github.com/aiteachme/AITeachMe/releases/latest/download/latest-tauri-local.json"
$configuredTauriLocalUpdaterEndpoint = [Environment]::GetEnvironmentVariable("AITEACHME_TAURI_LOCAL_UPDATER_ENDPOINT", "Process")
$tauriLocalUpdaterEndpoint = if ([string]::IsNullOrWhiteSpace($configuredTauriLocalUpdaterEndpoint)) {
    $defaultTauriLocalUpdaterEndpoint
}
else {
    $configuredTauriLocalUpdaterEndpoint.Trim()
}

function New-TauriLocalReleaseConfig {
    param(
        [string]$FrontendDir,
        [string]$UpdaterPubkey,
        [string]$Endpoint,
        [bool]$EnableUpdater = $false
    )

    $configPath = Join-Path $FrontendDir "src-tauri\tauri.local.release.conf.json"
    $bundleConfig = [ordered]@{}
    if ($EnableUpdater) {
        $bundleConfig["createUpdaterArtifacts"] = $true
    }
    $bundleConfig["resources"] = [ordered]@{
        "resources/backend/" = "backend"
    }

    $config = [ordered]@{
        productName = "AiTeachMe Local"
        identifier = "com.aiteachme.desktop.local"
        mainBinaryName = "aiteachme-local"
        build = [ordered]@{
            devUrl = "http://127.0.0.1:5181"
        }
        bundle = $bundleConfig
    }

    if ($EnableUpdater) {
        $config["plugins"] = [ordered]@{
            updater = [ordered]@{
                pubkey = $UpdaterPubkey
                endpoints = @($Endpoint)
                windows = [ordered]@{
                    installMode = "passive"
                }
            }
        }
    }

    $configJson = $config | ConvertTo-Json -Depth 8

    Write-Utf8NoBomFile -Path $configPath -Content ($configJson + [Environment]::NewLine)
    return $configPath
}

if ($Flavor -eq "remote") {
    if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
        throw "Remote API URL is required. Pass -ApiUrl https://your-api.example.com or set AITEACHME_REMOTE_API_URL."
    }

    if ($ApiUrl -notmatch "^https?://") {
        throw "Remote API URL must start with http:// or https://: $ApiUrl"
    }
}

Assert-RustToolchain

$apiBaseUrl = if ($Flavor -eq "local") { "" } else { $ApiUrl.TrimEnd("/") }
$releaseSuffix = if ($Flavor -eq "local") {
    Get-AITeachMeInstallerReleaseSuffix `
        -Bundled:$ImportBundledEnv `
        -Tauri `
        -BundledEnvArtifactSuffix $BundledEnvArtifactSuffix
}
else {
    Get-AITeachMeInstallerReleaseSuffix -Remote -Tauri
}

Write-Host "Repo: $repoRoot"
Write-Host "Flavor: tauri-$Flavor"
Write-Host "npm: $npm"
if ($Flavor -eq "local") {
    Write-Host "API base URL: dynamic local loopback port (resolved at app startup)"
}
else {
    Write-Host "API base URL: $apiBaseUrl"
}
if ($releaseSuffix) {
    Write-Host "Release suffix: $releaseSuffix"
}
if ($ImportBundledEnv -and $Flavor -ne "local") {
    Write-Host "ImportBundledEnv is only used by local packages with an embedded backend; skipping for tauri-$Flavor." -ForegroundColor Yellow
}

$tauriLocalUpdaterEnabled = $false
$tauriConfigArg = if ($Flavor -eq "local") { "src-tauri/tauri.local.release.conf.json" } else { "src-tauri/tauri.remote.conf.json" }
if ($Flavor -eq "local") {
    $updaterPubkey = [Environment]::GetEnvironmentVariable("TAURI_UPDATER_PUBKEY", "Process")
    $signingPrivateKey = [Environment]::GetEnvironmentVariable("TAURI_SIGNING_PRIVATE_KEY", "Process")
    $missingUpdaterVars = @()
    if ([string]::IsNullOrWhiteSpace($updaterPubkey)) {
        $missingUpdaterVars += "TAURI_UPDATER_PUBKEY"
    }
    if ([string]::IsNullOrWhiteSpace($signingPrivateKey)) {
        $missingUpdaterVars += "TAURI_SIGNING_PRIVATE_KEY"
    }
    $tauriLocalUpdaterEnabled = $missingUpdaterVars.Count -eq 0
    $trimmedUpdaterPubkey = if ([string]::IsNullOrWhiteSpace($updaterPubkey)) { "" } else { $updaterPubkey.Trim() }

    $generatedConfigPath = New-TauriLocalReleaseConfig `
        -FrontendDir $frontendDir `
        -UpdaterPubkey $trimmedUpdaterPubkey `
        -Endpoint $tauriLocalUpdaterEndpoint `
        -EnableUpdater $tauriLocalUpdaterEnabled
    if ($tauriLocalUpdaterEnabled) {
        Write-Host "Tauri updater endpoint: $tauriLocalUpdaterEndpoint"
    }
    else {
        Write-Host "Tauri updater disabled; missing environment variable(s): $($missingUpdaterVars -join ', '). Installer build will continue without updater packages." -ForegroundColor Yellow
    }
    Write-Host "Generated Tauri release config: $generatedConfigPath"
}

if (-not $SkipInstall) {
    Invoke-External -File $npm -Arguments @("install") -WorkingDirectory $frontendDir
}
else {
    Write-Host "SkipInstall is set; npm install skipped."
}

if ($Flavor -eq "local") {
    $prepareArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $repoRoot "packaging\scripts\prepare-tauri-sidecar.ps1")
    )
    if ($SkipInstall) {
        $prepareArgs += "-SkipInstall"
    }
    if ($ImportBundledEnv) {
        $prepareArgs += @("-ImportBundledEnv", "-BundledEnvConfigPath", $BundledEnvConfigPath)
    }
    Invoke-External -File "powershell" -Arguments $prepareArgs -WorkingDirectory $repoRoot
}

$previousViteApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL", "Process")

try {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $apiBaseUrl, "Process")

    Write-Host ""
    Write-Host "==== Generate frontend API client ====" -ForegroundColor Cyan
    Invoke-External -File $npm -Arguments @("exec", "--", "orval", "--config", "orval.config.js") -WorkingDirectory $frontendDir

    Remove-TauriBundleOutput -RepoRoot $repoRoot
    $tauriBuildArgs = @("exec", "--", "tauri", "build", "--config", $tauriConfigArg)
    if ($Flavor -eq "local") {
        $tauriBuildArgs += @("--features", "local-backend")
    }
    Invoke-External -File $npm -Arguments $tauriBuildArgs -WorkingDirectory $frontendDir
}
finally {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $previousViteApiUrl, "Process")
}

Copy-TauriArtifacts -RepoRoot $repoRoot -Flavor "tauri-$Flavor" -ReleaseSuffix $releaseSuffix -IncludeUpdater:$tauriLocalUpdaterEnabled
