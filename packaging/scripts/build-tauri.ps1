param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("local", "remote")]
    [string]$Flavor,
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled"
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")
. (Join-Path $PSScriptRoot "bundled-env-common.ps1")

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$npm = Resolve-CommandPath @("npm.cmd", "npm")

if ($Flavor -eq "remote") {
    if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
        throw "Remote API URL is required. Pass -ApiUrl https://your-api.example.com or set AITEACHME_REMOTE_API_URL."
    }

    if ($ApiUrl -notmatch "^https?://") {
        throw "Remote API URL must start with http:// or https://: $ApiUrl"
    }
}

Assert-RustToolchain

$apiBaseUrl = if ($Flavor -eq "local") { "http://127.0.0.1:$BackendPort" } else { $ApiUrl.TrimEnd("/") }
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
Write-Host "API base URL: $apiBaseUrl"
if ($Flavor -eq "local") {
    Write-Host "Backend port: $BackendPort"
}
if ($releaseSuffix) {
    Write-Host "Release suffix: $releaseSuffix"
}
if ($ImportBundledEnv -and $Flavor -ne "local") {
    Write-Host "ImportBundledEnv is only used by local packages with an embedded backend; skipping for tauri-$Flavor." -ForegroundColor Yellow
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
        (Join-Path $repoRoot "packaging\scripts\prepare-tauri-sidecar.ps1"),
        "-BackendPort",
        $BackendPort
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
$previousTauriBackendPort = [Environment]::GetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", "Process")

try {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $apiBaseUrl, "Process")
    if ($Flavor -eq "local") {
        [Environment]::SetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", $BackendPort, "Process")
    }

    Write-Host ""
    Write-Host "==== Generate frontend API client ====" -ForegroundColor Cyan
    Invoke-External -File $npm -Arguments @("exec", "--", "orval", "--config", "orval.config.js") -WorkingDirectory $frontendDir

    Remove-TauriBundleOutput -RepoRoot $repoRoot
    Invoke-External -File $npm -Arguments @("run", "tauri:build:$Flavor") -WorkingDirectory $frontendDir
}
finally {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $previousViteApiUrl, "Process")
    [Environment]::SetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", $previousTauriBackendPort, "Process")
}

Copy-TauriArtifacts -RepoRoot $repoRoot -Flavor "tauri-$Flavor" -ReleaseSuffix $releaseSuffix
