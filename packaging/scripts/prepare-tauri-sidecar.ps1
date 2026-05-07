param(
    [switch]$SkipInstall,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")

$repoRoot = Resolve-RepoRoot
$backendDir = Join-Path $repoRoot "backend"
$tauriBinariesDir = Join-Path $repoRoot "frontend\src-tauri\binaries"
$tauriBackendResourcesDir = Join-Path $repoRoot "frontend\src-tauri\resources\backend"
$python = Resolve-PythonCommand $repoRoot
$targetTriple = Get-RustHostTriple

Write-Host "Repo: $repoRoot"
Write-Host "Python: $($python.File) $($python.PrefixArgs -join ' ')"
Write-Host "Tauri sidecar target: $targetTriple"
Write-Host "Backend port: dynamic local loopback port (resolved at app startup)"

. (Join-Path $PSScriptRoot "bundled-env-common.ps1")
$bundledEnvConfigPath = Initialize-BundledEnvConfig `
    -RepoRoot $repoRoot `
    -ImportBundledEnv:$ImportBundledEnv `
    -BundledEnvConfigPath $BundledEnvConfigPath
if ($bundledEnvConfigPath) {
    Write-Host "Bundled env: $bundledEnvConfigPath"
}

if (-not $SkipInstall) {
    Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "-e", ".") -WorkingDirectory $backendDir
    Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "pyinstaller") -WorkingDirectory $backendDir
}
else {
    Write-Host "SkipInstall is set; Python dependency installation skipped."
}

Invoke-Python -Python $python -Arguments @("-m", "PyInstaller", "--noconfirm", "aiteachme-backend.spec") -WorkingDirectory $backendDir

$sourceDir = Join-Path $backendDir "dist\aiteachme-backend"
$sourceExe = Join-Path $sourceDir "aiteachme-backend.exe"
if (-not (Test-Path $sourceExe)) {
    throw "Backend sidecar executable was not produced: $sourceExe"
}

New-Item -ItemType Directory -Path $tauriBinariesDir -Force | Out-Null
Get-ChildItem -LiteralPath $tauriBinariesDir -File -Filter "aiteachme-backend-*" -ErrorAction SilentlyContinue |
    Remove-Item -Force

New-Item -ItemType Directory -Path $tauriBackendResourcesDir -Force | Out-Null
Get-ChildItem -LiteralPath $tauriBackendResourcesDir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne ".gitkeep" } |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $sourceDir -Force |
    Copy-Item -Destination $tauriBackendResourcesDir -Recurse -Force

Write-Host ""
Write-Host "Prepared Tauri backend resources: $tauriBackendResourcesDir" -ForegroundColor Green
