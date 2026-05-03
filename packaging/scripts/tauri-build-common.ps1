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

    $configuredPython = [Environment]::GetEnvironmentVariable("AITEACHME_PYTHON", "Process")
    if (-not [string]::IsNullOrWhiteSpace($configuredPython)) {
        if (-not (Test-Path $configuredPython)) {
            throw "AITEACHME_PYTHON points to a missing file: $configuredPython"
        }
        return @{
            File = (Resolve-Path $configuredPython).Path
            PrefixArgs = @()
        }
    }

    $activeCondaPrefix = [Environment]::GetEnvironmentVariable("CONDA_PREFIX", "Process")
    if (-not [string]::IsNullOrWhiteSpace($activeCondaPrefix)) {
        $activeCondaPython = Join-Path $activeCondaPrefix "python.exe"
        if (Test-Path $activeCondaPython) {
            return @{
                File = $activeCondaPython
                PrefixArgs = @()
            }
        }
    }

    $repoVenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $repoVenvPython) {
        return @{
            File = $repoVenvPython
            PrefixArgs = @()
        }
    }

    $conda = Get-Command "conda.exe", "conda.cmd", "conda" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $conda) {
        $condaEnvName = [Environment]::GetEnvironmentVariable("AITEACHME_CONDA_ENV", "Process")
        if ([string]::IsNullOrWhiteSpace($condaEnvName)) {
            $condaEnvName = "aiteachme"
        }
        return @{
            File = $conda.Source
            PrefixArgs = @("run", "--no-capture-output", "-n", $condaEnvName, "python")
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

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )

    [System.IO.File]::WriteAllText(
        $Path,
        $Content,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Copy-TauriArtifacts {
    param(
        [string]$RepoRoot,
        [string]$Flavor,
        [string]$ReleaseSuffix = "",
        [switch]$IncludeUpdater
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
    Get-ChildItem -LiteralPath $releaseDir -File -Filter "AiTeachMe-v*-installer$ReleaseSuffix.*" -ErrorAction SilentlyContinue |
        Remove-Item -Force
    Get-ChildItem -LiteralPath $releaseDir -File -Filter "AiTeachMe-v*-updater$ReleaseSuffix.*" -ErrorAction SilentlyContinue |
        Remove-Item -Force
    Get-ChildItem -LiteralPath $releaseDir -File -Filter "AiTeachMe-v*-$Flavor-*.*" -ErrorAction SilentlyContinue |
        Remove-Item -Force
    if ($Flavor -eq "tauri-local") {
        $latestJsonPath = Join-Path $releaseDir "latest-tauri-local.json"
        if (Test-Path $latestJsonPath) {
            Remove-Item -LiteralPath $latestJsonPath -Force
        }
    }

    $bundleArtifactDir = Join-Path $artifactDir $Flavor
    if (Test-Path $bundleArtifactDir) {
        Remove-Item -LiteralPath $bundleArtifactDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $bundleArtifactDir -Force | Out-Null

    $directDir = Join-Path (Join-Path $artifactDir "direct") $Flavor
    if (Test-Path $directDir) {
        Remove-Item -LiteralPath $directDir -Recurse -Force
    }

    $artifacts = @(Get-ChildItem $bundleDir -Recurse -File |
        Where-Object {
            $isNsisInstaller = $_.Extension -eq ".exe" -and $_.Directory.Name -eq "nsis"
            $isMsiInstaller = $_.Extension -in @(".msi", ".msix")
            $isNsisInstaller -or $isMsiInstaller
        } |
        Sort-Object LastWriteTime -Descending)

    if ($artifacts.Count -eq 0) {
        throw "Could not find Tauri installer artifacts under $bundleDir"
    }

    $releaseOutputs = @()
    foreach ($artifact in $artifacts) {
        $artifactName = "AiTeachMe-v$projectVersion-installer$ReleaseSuffix$($artifact.Extension)"
        $releaseOutput = Join-Path $releaseDir $artifactName
        Copy-Item -LiteralPath $artifact.FullName -Destination (Join-Path $bundleArtifactDir $artifact.Name) -Force
        Copy-Item -LiteralPath $artifact.FullName -Destination $releaseOutput -Force
        $releaseOutputs += $releaseOutput
    }

    $updaterOutputs = @()
    if ($IncludeUpdater) {
        $legacyUpdaterPackages = @(Get-ChildItem $bundleDir -Recurse -File |
            Where-Object {
                ($_.Directory.Name -eq "nsis" -and $_.Name -like "*.nsis.zip") -or
                ($_.Directory.Name -eq "msi" -and $_.Name -like "*.msi.zip")
            } |
            Sort-Object LastWriteTime -Descending)

        $signedInstallerUpdaterPackages = @(Get-ChildItem $bundleDir -Recurse -File |
            Where-Object {
                $isSignedNsisInstaller = $_.Directory.Name -eq "nsis" -and $_.Extension -eq ".exe" -and (Test-Path "$($_.FullName).sig")
                $isSignedMsiInstaller = $_.Directory.Name -eq "msi" -and $_.Extension -eq ".msi" -and (Test-Path "$($_.FullName).sig")
                $isSignedNsisInstaller -or $isSignedMsiInstaller
            } |
            Sort-Object LastWriteTime -Descending)

        $updaterPackages = @()
        if ($legacyUpdaterPackages.Count -gt 0) {
            $updaterPackages = @($legacyUpdaterPackages)
        }
        else {
            $updaterPackages = @($signedInstallerUpdaterPackages)
        }

        if ($Flavor -eq "tauri-local" -and $updaterPackages.Count -eq 0) {
            throw "Could not find a signed Tauri updater package under $bundleDir. Ensure createUpdaterArtifacts is enabled for tauri-local builds."
        }

        foreach ($updaterPackage in $updaterPackages) {
            $sigPath = "$($updaterPackage.FullName).sig"
            if (-not (Test-Path $sigPath)) {
                throw "Tauri updater signature was not produced: $sigPath"
            }

            $updaterExtension = if ($updaterPackage.Name -like "*.nsis.zip") {
                ".nsis.zip"
            }
            elseif ($updaterPackage.Name -like "*.msi.zip") {
                ".msi.zip"
            }
            else {
                $updaterPackage.Extension
            }
            $updaterName = "AiTeachMe-v$projectVersion-updater$ReleaseSuffix$updaterExtension"
            $updaterReleaseOutput = Join-Path $releaseDir $updaterName
            $updaterSigReleaseOutput = "$updaterReleaseOutput.sig"

            Copy-Item -LiteralPath $updaterPackage.FullName -Destination (Join-Path $bundleArtifactDir $updaterPackage.Name) -Force
            Copy-Item -LiteralPath $sigPath -Destination (Join-Path $bundleArtifactDir (Split-Path $sigPath -Leaf)) -Force
            Copy-Item -LiteralPath $updaterPackage.FullName -Destination $updaterReleaseOutput -Force
            Copy-Item -LiteralPath $sigPath -Destination $updaterSigReleaseOutput -Force
            $updaterOutputs += $updaterReleaseOutput
            $updaterOutputs += $updaterSigReleaseOutput
        }
    }

    if ($IncludeUpdater -and $Flavor -eq "tauri-local") {
        if ($updaterOutputs.Count -eq 0) {
            throw "Tauri local updater package was not copied."
        }

        $updaterPackageOutput = $updaterOutputs | Where-Object { $_ -notlike "*.sig" } | Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace($updaterPackageOutput)) {
            throw "Tauri local updater package was not copied."
        }

        $updaterSig = "$updaterPackageOutput.sig"
        if (-not (Test-Path $updaterSig)) {
            throw "Tauri local updater signature is missing: $updaterSig"
        }

        $releaseTag = [Environment]::GetEnvironmentVariable("AITEACHME_RELEASE_TAG", "Process")
        if ([string]::IsNullOrWhiteSpace($releaseTag)) {
            $releaseTag = "v$projectVersion"
        }

        $repository = [Environment]::GetEnvironmentVariable("GITHUB_REPOSITORY", "Process")
        if ([string]::IsNullOrWhiteSpace($repository)) {
            $repository = "aiteachme/AITeachMe"
        }

        $updaterFileName = Split-Path $updaterPackageOutput -Leaf
        $assetBaseUrl = [Environment]::GetEnvironmentVariable("AITEACHME_TAURI_LOCAL_UPDATER_ASSET_BASE_URL", "Process")
        if ([string]::IsNullOrWhiteSpace($assetBaseUrl)) {
            $assetBaseUrl = "https://github.com/$repository/releases/download/$releaseTag"
        }
        else {
            $assetBaseUrl = $assetBaseUrl.TrimEnd("/")
        }

        $signature = (Get-Content -LiteralPath $updaterSig -Raw).Trim()
        $latestJson = [ordered]@{
            version = $projectVersion
            notes = "AiTeachMe $projectVersion"
            pub_date = [DateTimeOffset]::UtcNow.ToString("o")
            platforms = [ordered]@{
                "windows-x86_64" = [ordered]@{
                    signature = $signature
                    url = "$assetBaseUrl/$updaterFileName"
                }
            }
        } | ConvertTo-Json -Depth 8

        $latestJsonPath = Join-Path $releaseDir "latest-tauri-local.json"
        Write-Utf8NoBomFile -Path $latestJsonPath -Content ($latestJson + [Environment]::NewLine)
        $releaseOutputs += $latestJsonPath
    }

    Write-Host ""
    Write-Host "Tauri $Flavor release packages:" -ForegroundColor Green
    $releaseOutputs | ForEach-Object {
        Write-Host "  $_"
    }
    if ($updaterOutputs.Count -gt 0) {
        Write-Host "Tauri $Flavor updater packages:" -ForegroundColor Green
        $updaterOutputs | ForEach-Object {
            Write-Host "  $_"
        }
    }
    Write-Host "Intermediate artifacts:" -ForegroundColor DarkGray
    Write-Host "  $bundleArtifactDir"
}
