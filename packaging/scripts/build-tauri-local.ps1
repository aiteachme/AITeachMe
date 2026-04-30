param(
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$npm = Resolve-CommandPath @("npm.cmd", "npm")

Assert-RustToolchain

Write-Host "Repo: $repoRoot"
Write-Host "npm: $npm"
Write-Host "Backend port: $BackendPort"

if (-not $SkipInstall) {
    Invoke-External -File $npm -Arguments @("install") -WorkingDirectory $frontendDir
}
else {
    Write-Host "SkipInstall is set; npm install skipped."
}

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

$previousViteApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL", "Process")
$previousTauriBackendPort = [Environment]::GetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", "Process")
[Environment]::SetEnvironmentVariable("VITE_API_URL", "http://127.0.0.1:$BackendPort", "Process")
[Environment]::SetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", $BackendPort, "Process")
try {
    Remove-TauriBundleOutput -RepoRoot $repoRoot
    Invoke-External -File $npm -Arguments @("run", "tauri:build:local") -WorkingDirectory $frontendDir
}
finally {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $previousViteApiUrl, "Process")
    [Environment]::SetEnvironmentVariable("AITEACHME_TAURI_BACKEND_PORT", $previousTauriBackendPort, "Process")
}

Copy-TauriArtifacts -RepoRoot $repoRoot -Flavor "tauri-local"
