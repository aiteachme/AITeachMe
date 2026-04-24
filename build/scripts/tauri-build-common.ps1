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

    $outputDir = Join-Path $RepoRoot "build\$Flavor"
    if (Test-Path $outputDir) {
        Remove-Item -LiteralPath $outputDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $outputDir | Out-Null

    $artifacts = @(Get-ChildItem $bundleDir -Recurse -File |
        Where-Object { $_.Extension -in @(".exe", ".msi", ".msix", ".zip") } |
        Sort-Object LastWriteTime -Descending)

    if ($artifacts.Count -eq 0) {
        throw "Could not find Tauri installer artifacts under $bundleDir"
    }

    foreach ($artifact in $artifacts) {
        Copy-Item -LiteralPath $artifact.FullName -Destination (Join-Path $outputDir $artifact.Name) -Force
    }

    Write-Host ""
    Write-Host "Tauri $Flavor artifacts:" -ForegroundColor Green
    Get-ChildItem $outputDir -File | ForEach-Object {
        Write-Host "  $($_.FullName)"
    }
}
