param(
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$npm = Resolve-CommandPath @("npm.cmd", "npm")

if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
    throw "Remote API URL is required. Pass -ApiUrl https://your-api.example.com or set AITEACHME_REMOTE_API_URL."
}

if ($ApiUrl -notmatch "^https?://") {
    throw "Remote API URL must start with http:// or https://: $ApiUrl"
}

Assert-RustToolchain

Write-Host "Repo: $repoRoot"
Write-Host "npm: $npm"
Write-Host "Remote API URL: $ApiUrl"

if (-not $SkipInstall) {
    Invoke-External -File $npm -Arguments @("install") -WorkingDirectory $frontendDir
}
else {
    Write-Host "SkipInstall is set; npm install skipped."
}

$previousViteApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL", "Process")
[Environment]::SetEnvironmentVariable("VITE_API_URL", $ApiUrl.TrimEnd("/"), "Process")
try {
    Remove-TauriBundleOutput -RepoRoot $repoRoot
    Invoke-External -File $npm -Arguments @("run", "tauri:build:remote") -WorkingDirectory $frontendDir
}
finally {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $previousViteApiUrl, "Process")
}

Copy-TauriArtifacts -RepoRoot $repoRoot -Flavor "tauri-remote"
