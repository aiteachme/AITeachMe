param(
    [string]$RepoRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$frontendDir = Join-Path $RepoRoot "frontend"
$releaseDir = Join-Path $frontendDir "release"
$unpackedDir = Join-Path $releaseDir "win-unpacked"
$outputExe = Join-Path $releaseDir "AiTeachMe.exe"
$iconPath = Join-Path $RepoRoot "docs\brand\atm-logo-3_ico_96x96.ico"
$scriptPath = Join-Path $releaseDir "aiteachme-portable.nsi"

if (-not (Test-Path (Join-Path $unpackedDir "AiTeachMe.exe"))) {
    throw "Missing unpacked Electron app. Run the installer build first: $unpackedDir"
}

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

$nsisScript = @"
Unicode true
Name "AiTeachMe"
OutFile "$outputNsisPath"
Icon "$iconNsisPath"
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
ShowInstDetails nevershow
SetCompressor /SOLID lzma
InstallDir "`$TEMP\AiTeachMePortable"

Section
  IfFileExists "`$INSTDIR\AiTeachMe.exe" 0 +2
  RMDir /r "`$INSTDIR"
  SetOutPath "`$INSTDIR"
  File /r "$sourceNsisPath"
  ExecWait '"`$INSTDIR\AiTeachMe.exe"'
  RMDir /r "`$INSTDIR"
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
