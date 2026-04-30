param(
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

. (Join-Path $PSScriptRoot "tauri-build-common.ps1")

$repoRoot = Resolve-RepoRoot
$backendDir = Join-Path $repoRoot "backend"
$tauriBinariesDir = Join-Path $repoRoot "frontend\src-tauri\binaries"
$python = Resolve-PythonCommand $repoRoot
$targetTriple = Get-RustHostTriple

Write-Host "Repo: $repoRoot"
Write-Host "Python: $($python.File) $($python.PrefixArgs -join ' ')"
Write-Host "Tauri sidecar target: $targetTriple"
Write-Host "Backend port: $BackendPort"

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

Invoke-Python -Python $python -Arguments @("-m", "PyInstaller", "--noconfirm", "aiteachme-backend-onefile.spec") -WorkingDirectory $backendDir

$sourceExe = Join-Path $backendDir "dist\aiteachme-backend.exe"
if (-not (Test-Path $sourceExe)) {
    throw "Backend sidecar executable was not produced: $sourceExe"
}

New-Item -ItemType Directory -Path $tauriBinariesDir -Force | Out-Null
Get-ChildItem -LiteralPath $tauriBinariesDir -File -Filter "aiteachme-backend-*" -ErrorAction SilentlyContinue |
    Remove-Item -Force

$suffix = if ($targetTriple -match "windows") { ".exe" } else { "" }
$targetExe = Join-Path $tauriBinariesDir "aiteachme-backend-$targetTriple$suffix"
Copy-Item -LiteralPath $sourceExe -Destination $targetExe -Force

Write-Host ""
Write-Host "Prepared Tauri backend sidecar: $targetExe" -ForegroundColor Green
