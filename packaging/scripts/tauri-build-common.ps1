$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ((Test-Path $cargoBin) -and (($env:Path -split ";") -notcontains $cargoBin)) {
    $env:Path = "$cargoBin;$env:Path"
}

$localNsisBin = Join-Path $env:LOCALAPPDATA "Programs\nsis-3.11\nsis-3.11\Bin"
if ((Test-Path $localNsisBin) -and (($env:Path -split ";") -notcontains $localNsisBin)) {
    $env:Path = "$localNsisBin;$env:Path"
}

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Resolve-CommandPath {
    param([string[]]$Names)

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw "Cannot find command: $($Names -join ', ')"
}

function Get-ProjectVersion {
    param([string]$RepoRoot)

    $packageJsonPath = Join-Path $RepoRoot "frontend\package.json"
    if (-not (Test-Path $packageJsonPath)) {
        throw "Cannot find frontend package.json: $packageJsonPath"
    }

    $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($packageJson.version)) {
        throw "frontend package.json does not contain a version."
    }

    return $packageJson.version
}

function Assert-RustToolchain {
    try {
        [void](Resolve-CommandPath @("rustc.exe", "rustc"))
        [void](Resolve-CommandPath @("cargo.exe", "cargo"))
    }
    catch {
        throw "Rust toolchain is required for Tauri builds. Install Rust from https://rustup.rs/ and Visual Studio Build Tools with MSVC + Windows SDK, then rerun this script."
    }
}

function Resolve-PythonCommand {
    param([string]$RepoRoot)

    $repoVenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $repoVenvPython) {
        return @{
            File = $repoVenvPython
            PrefixArgs = @()
        }
    }

    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pyLauncher) {
        return @{
            File = $pyLauncher.Source
            PrefixArgs = @("-3.11")
        }
    }

    return @{
        File = Resolve-CommandPath @("python.exe", "python")
        PrefixArgs = @()
    }
}

function Invoke-External {
    param(
        [string]$File,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        Write-Host ""
        Write-Host "> $File $($Arguments -join ' ')" -ForegroundColor DarkGray
        $global:LASTEXITCODE = 0
        & $File @Arguments
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        if ($exitCode -ne 0) {
            throw "Command failed with exit code $exitCode"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Invoke-External `
        -File $Python.File `
        -Arguments @($Python.PrefixArgs + $Arguments) `
        -WorkingDirectory $WorkingDirectory
}

function Get-RustHostTriple {
    $rustc = Get-Command "rustc.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $rustc) {
        $rustc = Get-Command "rustc" -ErrorAction SilentlyContinue | Select-Object -First 1
    }

    if ($null -ne $rustc) {
        $hostTuple = (& $rustc.Source --print host-tuple 2>$null)
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($hostTuple)) {
            return $hostTuple.Trim()
        }

        $versionInfo = (& $rustc.Source -vV 2>$null)
        foreach ($line in $versionInfo) {
            if ($line -match "^host:\s*(.+)$") {
                return $Matches[1].Trim()
            }
        }
    }

    return "x86_64-pc-windows-msvc"
}

function Remove-TauriBundleOutput {
    param([string]$RepoRoot)

    $bundleDir = Join-Path $RepoRoot "frontend\src-tauri\target\release\bundle"
    if (Test-Path $bundleDir) {
        Remove-Item -LiteralPath $bundleDir -Recurse -Force
    }
}

function Copy-TauriArtifacts {
    param(
        [string]$RepoRoot,
        [string]$Flavor
    )

    $bundleDir = Join-Path $RepoRoot "frontend\src-tauri\target\release\bundle"
    if (-not (Test-Path $bundleDir)) {
        throw "Tauri bundle output was not produced: $bundleDir"
    }

    $projectVersion = Get-ProjectVersion -RepoRoot $RepoRoot
    $artifactDir = Join-Path $RepoRoot "packaging\artifacts"
    $releaseDir = Join-Path $RepoRoot "packaging\release"
    New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    Get-ChildItem -LiteralPath $releaseDir -File -Filter "AiTeachMe-v*-$Flavor-*.*" -ErrorAction SilentlyContinue |
        Remove-Item -Force

    $bundleArtifactDir = Join-Path $artifactDir $Flavor
    if (Test-Path $bundleArtifactDir) {
        Remove-Item -LiteralPath $bundleArtifactDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $bundleArtifactDir -Force | Out-Null

    $directRoot = Join-Path $artifactDir "direct"
    $directDir = Join-Path $directRoot $Flavor
    if (Test-Path $directDir) {
        Remove-Item -LiteralPath $directDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $directDir -Force | Out-Null

    $artifacts = @(Get-ChildItem $bundleDir -Recurse -File |
        Where-Object { $_.Extension -in @(".exe", ".msi", ".msix", ".zip") } |
        Sort-Object LastWriteTime -Descending)

    if ($artifacts.Count -eq 0) {
        throw "Could not find Tauri installer artifacts under $bundleDir"
    }

    foreach ($artifact in $artifacts) {
        $artifactKind = if ($artifact.Extension -eq ".zip") { "bundle" } else { "installer" }
        $artifactName = "AiTeachMe-v$projectVersion-$Flavor-$artifactKind$($artifact.Extension)"
        Copy-Item -LiteralPath $artifact.FullName -Destination (Join-Path $bundleArtifactDir $artifact.Name) -Force
        if ($artifact.Extension -ne ".zip") {
            Copy-Item -LiteralPath $artifact.FullName -Destination (Join-Path $releaseDir $artifactName) -Force
        }
    }

    $releaseDir = Join-Path $RepoRoot "frontend\src-tauri\target\release"
    $mainBinaryName = if ($Flavor -eq "tauri-local") { "aiteachme-local.exe" } else { "aiteachme-remote.exe" }
    $productExeName = if ($Flavor -eq "tauri-local") { "AiTeachMe Local.exe" } else { "AiTeachMe Remote.exe" }
    $mainBinary = Join-Path $releaseDir $mainBinaryName

    if (-not (Test-Path $mainBinary)) {
        throw "Tauri direct executable was not produced: $mainBinary"
    }

    Copy-Item -LiteralPath $mainBinary -Destination (Join-Path $directDir $productExeName) -Force

    if ($Flavor -eq "tauri-local") {
        $sidecar = Join-Path $releaseDir "aiteachme-backend.exe"
        if (-not (Test-Path $sidecar)) {
            throw "Tauri local backend sidecar was not produced: $sidecar"
        }
        Copy-Item -LiteralPath $sidecar -Destination (Join-Path $directDir "aiteachme-backend.exe") -Force
    }

    $directZip = Join-Path $releaseDir "AiTeachMe-v$projectVersion-$Flavor-direct.zip"
    if (Test-Path $directZip) {
        Remove-Item -LiteralPath $directZip -Force
    }
    Compress-Archive -Path (Join-Path $directDir "*") -DestinationPath $directZip -Force

    Write-Host ""
    Write-Host "Tauri $Flavor release packages:" -ForegroundColor Green
    Get-ChildItem $releaseDir -File -Filter "AiTeachMe-v*-$Flavor-*.*" | ForEach-Object {
        Write-Host "  $($_.FullName)"
    }
    Write-Host "Intermediate artifacts:" -ForegroundColor DarkGray
    Write-Host "  $bundleArtifactDir"
    Write-Host "  $directDir"
}
