param(
    [string]$RepoRoot,
    [string]$ProductName = "AiTeachMe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
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

function Convert-ToPortableCacheName {
    param([string]$Name)

    $safeName = $Name -replace '[^A-Za-z0-9._-]', ''
    if ([string]::IsNullOrWhiteSpace($safeName)) {
        return "AiTeachMe"
    }
    return $safeName
}

$frontendDir = Join-Path $RepoRoot "frontend"
$releaseDir = Join-Path $frontendDir "release"
$unpackedDir = Join-Path $releaseDir "win-unpacked"
$appExeName = "$ProductName.exe"
$appExe = Join-Path $unpackedDir $appExeName
$outputExe = Join-Path $releaseDir $appExeName
$iconPath = Join-Path $RepoRoot "docs\brand\app-icon.ico"
$scriptPath = Join-Path $releaseDir "aiteachme-portable.nsi"

if (-not (Test-Path $appExe)) {
    throw "Missing unpacked Electron app. Run the installer build first: $unpackedDir"
}

$projectVersion = Get-ProjectVersion -RepoRoot $RepoRoot
$portableBuildId = (Get-Item -LiteralPath $appExe).LastWriteTimeUtc.ToString("yyyyMMddHHmmss")
$portableCacheName = Convert-ToPortableCacheName "$ProductName-v$projectVersion-$portableBuildId"

if (-not (Test-Path $iconPath)) {
    throw "Missing desktop icon: $iconPath"
}

$makensis = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache\nsis" -Recurse -File -Filter "makensis.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\Bin\\makensis.exe$" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $makensis) {
    $makensis = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache\nsis" -Recurse -File -Filter "makensis.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if ($null -eq $makensis) {
    throw "Cannot find makensis.exe in electron-builder cache. Run npm run desktop:installer once first."
}

function Convert-ToNsisPath {
    param([string]$Path)
    return $Path.Replace("\", "\\")
}

$outputNsisPath = Convert-ToNsisPath $outputExe
$iconNsisPath = Convert-ToNsisPath $iconPath
$sourceNsisPath = Convert-ToNsisPath (Join-Path $unpackedDir "*")
$cacheNsisPath = "AiTeachMe\PortableCache\$portableCacheName"

$nsisScript = @"
Unicode true
Name "$ProductName"
OutFile "$outputNsisPath"
Icon "$iconNsisPath"
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
ShowInstDetails nevershow
SetCompressor /SOLID lzma
InstallDir "`$LOCALAPPDATA\$cacheNsisPath"

Section
  IfFileExists "`$INSTDIR\$appExeName" launch extract

extract:
  RMDir /r "`$INSTDIR"
  SetOutPath "`$INSTDIR"
  File /r "$sourceNsisPath"

launch:
  ExecWait '"`$INSTDIR\$appExeName"'
SectionEnd
"@

Set-Content -LiteralPath $scriptPath -Value $nsisScript -Encoding UTF8
Remove-Item -LiteralPath $outputExe -Force -ErrorAction SilentlyContinue

& $makensis.FullName $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "makensis failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $outputExe)) {
    throw "Portable exe was not produced: $outputExe"
}

Write-Host "Portable exe: $outputExe"
Write-Host "Portable cache: `$LOCALAPPDATA\$cacheNsisPath"
