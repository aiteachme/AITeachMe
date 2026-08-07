param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("local", "remote")]
    [string]$Flavor,
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [string]$PublicAppUrl = $env:AITEACHME_REMOTE_FRONTEND_URL,
    [switch]$SkipInstall,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\desktop\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled",
    [switch]$RequireUpdater
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")
. (Join-Path $PSScriptRoot "bundled-env-common.ps1")
. (Join-Path $PSScriptRoot "windows-signing-common.ps1")

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$projectVersion = Get-ProjectVersion -RepoRoot $repoRoot
$npm = Resolve-CommandPath @("npm.cmd", "npm")
$tauriLocalUpdaterEndpoints = @("https://github.com/aiteachme/AITeachMe/releases/latest/download/latest-tauri-local.json")

function New-TauriLocalReleaseConfig {
    param(
        [string]$FrontendDir,
        [string]$UpdaterPubkey,
        [string[]]$Endpoints,
        [bool]$EnableUpdater = $false,
        [object]$WindowsSigningConfig = $null
    )

    $configPath = Join-Path $FrontendDir "src-tauri\tauri.local.release.conf.json"
    $bundleConfig = [ordered]@{}
    $bundleConfig["targets"] = @("nsis")
    if ($EnableUpdater) {
        $bundleConfig["createUpdaterArtifacts"] = $true
    }
    $bundleConfig["resources"] = [ordered]@{
        "resources/backend/" = "backend"
    }
    if ($null -ne $WindowsSigningConfig) {
        $bundleConfig["windows"] = $WindowsSigningConfig
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
                endpoints = @($Endpoints)
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

function New-TauriRemoteReleaseConfig {
    param(
        [string]$FrontendDir,
        [object]$WindowsSigningConfig = $null
    )

    $configPath = Join-Path $FrontendDir "src-tauri\tauri.remote.release.conf.json"
    $config = [ordered]@{
        productName = "AiTeachMe Remote"
        identifier = "com.aiteachme.desktop.remote"
        mainBinaryName = "aiteachme-remote"
    }
    if ($null -ne $WindowsSigningConfig) {
        $config["bundle"] = [ordered]@{
            windows = $WindowsSigningConfig
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
    if (-not [string]::IsNullOrWhiteSpace($PublicAppUrl) -and $PublicAppUrl -notmatch "^https?://") {
        throw "Remote public frontend URL must start with http:// or https://: $PublicAppUrl"
    }
}

Assert-RustToolchain
$windowsSigning = Get-AITeachMeWindowsSigningState
Assert-AITeachMeWindowsSigningReady -Signing $windowsSigning
$tauriWindowsSigningConfig = Get-AITeachMeTauriWindowsSigningConfig -Signing $windowsSigning
if ($windowsSigning.Enabled -and $null -eq $tauriWindowsSigningConfig) {
    $message = "Tauri Windows signing is enabled, but Tauri needs AITEACHME_WINDOWS_SIGN_COMMAND or AITEACHME_WINDOWS_CERTIFICATE_THUMBPRINT to sign during bundling."
    if ($windowsSigning.Required) {
        throw $message
    }
    Write-Host $message -ForegroundColor Yellow
}

$apiBaseUrl = if ($Flavor -eq "local") { "" } else { $ApiUrl.TrimEnd("/") }
$publicAppBaseUrl = if ($Flavor -eq "remote" -and -not [string]::IsNullOrWhiteSpace($PublicAppUrl)) {
    $PublicAppUrl.TrimEnd("/")
} else {
    ""
}
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
Write-AITeachMeWindowsSigningSummary -Signing $windowsSigning
if ($Flavor -eq "local") {
    Write-Host "API base URL: dynamic local loopback port (resolved at app startup)"
}
else {
    Write-Host "API base URL: $apiBaseUrl"
    Write-Host "Public app URL: $publicAppBaseUrl"
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
        -Endpoints $tauriLocalUpdaterEndpoints `
        -EnableUpdater $tauriLocalUpdaterEnabled `
        -WindowsSigningConfig $tauriWindowsSigningConfig
    Write-Host "Tauri Windows target: NSIS .exe"
    if ($tauriLocalUpdaterEnabled) {
        Write-Host "Tauri updater endpoints:"
        $tauriLocalUpdaterEndpoints | ForEach-Object {
            Write-Host "  $_"
        }
    }
    else {
        if ($RequireUpdater) {
            throw "Tauri updater is required for this build, but missing environment variable(s): $($missingUpdaterVars -join ', '). Configure TAURI_UPDATER_PUBKEY and TAURI_SIGNING_PRIVATE_KEY before publishing."
        }
        Write-Host "Tauri updater disabled; missing environment variable(s): $($missingUpdaterVars -join ', '). Installer build will continue without updater packages." -ForegroundColor Yellow
    }
    Write-Host "Generated Tauri release config: $generatedConfigPath"
}
elseif ($null -ne $tauriWindowsSigningConfig) {
    $generatedConfigPath = New-TauriRemoteReleaseConfig `
        -FrontendDir $frontendDir `
        -WindowsSigningConfig $tauriWindowsSigningConfig
    $tauriConfigArg = "src-tauri/tauri.remote.release.conf.json"
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
        (Join-Path $repoRoot "packaging\desktop\scripts\prepare-tauri-sidecar.ps1")
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
$previousVitePublicAppUrl = [Environment]::GetEnvironmentVariable("VITE_PUBLIC_APP_URL", "Process")

try {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $apiBaseUrl, "Process")
    [Environment]::SetEnvironmentVariable("VITE_PUBLIC_APP_URL", $publicAppBaseUrl, "Process")

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
    [Environment]::SetEnvironmentVariable("VITE_PUBLIC_APP_URL", $previousVitePublicAppUrl, "Process")
}

Copy-TauriArtifacts -RepoRoot $repoRoot -Flavor "tauri-$Flavor" -ReleaseSuffix $releaseSuffix -IncludeUpdater:$tauriLocalUpdaterEnabled

$releaseDir = Join-Path $repoRoot "packaging\desktop\release"
$tauriInstallers = @(Get-ChildItem -LiteralPath $releaseDir -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like "AiTeachMe-v*-installer$releaseSuffix.*" -and
            $_.Extension -eq ".exe"
    })
foreach ($installer in $tauriInstallers) {
    $tauriUpdaterSignature = "$($installer.FullName).sig"
    if (Test-Path $tauriUpdaterSignature) {
        Write-AITeachMeSignatureStatus `
            -Path $installer.FullName `
            -Description "Tauri updater installer"

        if (($windowsSigning.Enabled -or $windowsSigning.Required) -and -not (Test-AITeachMeSignatureValid -Path $installer.FullName)) {
            throw "Tauri updater installer is not Authenticode signed before updater signature generation: $($installer.FullName). Configure AITEACHME_WINDOWS_SIGN_COMMAND or AITEACHME_WINDOWS_CERTIFICATE_THUMBPRINT so Tauri signs the installer during bundling."
        }

        continue
    }

    Invoke-AITeachMeWindowsSignFile `
        -Signing $windowsSigning `
        -Path $installer.FullName `
        -Description "Tauri release installer" `
        -SkipIfSigned
}
