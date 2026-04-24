param(
    [switch]$SkipInstall,
    [string]$BackendPort = "8010"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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

function Get-ProcessPathOrNull {
    param([System.Diagnostics.Process]$Process)

    try {
        return $Process.Path
    }
    catch {
        return $null
    }
}

function Stop-ProcessesUnderPath {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    $resolvedPath = (Resolve-Path $Path).Path
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            $processPath = Get-ProcessPathOrNull -Process $_
            $processPath -and $processPath.StartsWith($resolvedPath, [System.StringComparison]::OrdinalIgnoreCase)
        } |
        ForEach-Object {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
}

function Convert-ToExtendedPath {
    param([string]$Path)

    if ($Path.StartsWith("\\?\")) {
        return $Path
    }
    if ($Path.StartsWith("\\")) {
        return "\\?\UNC\" + $Path.Substring(2)
    }
    return "\\?\" + $Path
}

function Remove-DirectoryIfExists {
    param(
        [string]$Path,
        [string]$RepoRoot
    )

    if (-not (Test-Path $Path)) {
        return
    }

    $resolvedPath = (Resolve-Path $Path).Path
    $resolvedRoot = (Resolve-Path $RepoRoot).Path
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repo: $resolvedPath"
    }

    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            Remove-Item -LiteralPath (Convert-ToExtendedPath $resolvedPath) -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq 6) {
                throw
            }

            Stop-ProcessesUnderPath -Path $resolvedPath
            Start-Sleep -Seconds 2
        }
    }
}

function Stop-LocalBuildToolProcesses {
    param([string]$RepoRoot)

    $sevenZipRoot = (Join-Path $RepoRoot "frontend\node_modules\7zip-bin")
    Get-Process -Name "7za" -ErrorAction SilentlyContinue |
        Where-Object {
            $processPath = Get-ProcessPathOrNull -Process $_
            $processPath -and $processPath.StartsWith($sevenZipRoot, [System.StringComparison]::OrdinalIgnoreCase)
        } |
        Stop-Process -Force

    Get-CimInstance Win32_Process -Filter "Name='makensis.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains($RepoRoot)
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

$repoRoot = Resolve-RepoRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendReleaseDir = Join-Path $frontendDir "release"
$finalReleaseDir = Join-Path $repoRoot "desktop-release"
$backendDistDir = Join-Path $backendDir "dist\aiteachme-backend"

$python = Resolve-PythonCommand $repoRoot
$npm = Resolve-CommandPath @("npm.cmd", "npm")
Stop-LocalBuildToolProcesses -RepoRoot $repoRoot

Write-Host "Repo: $repoRoot"
Write-Host "Python: $($python.File) $($python.PrefixArgs -join ' ')"
Write-Host "npm: $npm"
Write-Host "Backend port: $BackendPort"

Write-Step "Install build dependencies"
if ($SkipInstall) {
    Write-Host "SkipInstall is set; dependency installation skipped."
}
else {
    Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "-e", ".") -WorkingDirectory $backendDir
    Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "pyinstaller") -WorkingDirectory $backendDir
    Invoke-External -File $npm -Arguments @("install") -WorkingDirectory $frontendDir
}

Write-Step "Build backend executable"
Remove-DirectoryIfExists -Path (Join-Path $backendDir "build") -RepoRoot $repoRoot
Remove-DirectoryIfExists -Path $backendDistDir -RepoRoot $repoRoot
Invoke-Python -Python $python -Arguments @("-m", "PyInstaller", "--noconfirm", "aiteachme-backend.spec") -WorkingDirectory $backendDir

if (-not (Test-Path (Join-Path $backendDistDir "aiteachme-backend.exe"))) {
    throw "Backend executable was not produced: $backendDistDir"
}

Write-Step "Build frontend"
$previousViteApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL", "Process")
[Environment]::SetEnvironmentVariable("VITE_API_URL", "http://127.0.0.1:$BackendPort", "Process")
try {
    Invoke-External -File $npm -Arguments @("run", "build") -WorkingDirectory $frontendDir
}
finally {
    [Environment]::SetEnvironmentVariable("VITE_API_URL", $previousViteApiUrl, "Process")
}

Write-Step "Build Electron installer and portable exe"
Stop-LocalBuildToolProcesses -RepoRoot $repoRoot
Stop-ProcessesUnderPath -Path $frontendReleaseDir
Remove-DirectoryIfExists -Path $frontendReleaseDir -RepoRoot $repoRoot
Invoke-External -File $npm -Arguments @("run", "desktop:installer") -WorkingDirectory $frontendDir
Stop-LocalBuildToolProcesses -RepoRoot $repoRoot
Invoke-External -File "powershell" -Arguments @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    (Join-Path $repoRoot "scripts\build-portable-nsis.ps1"),
    "-RepoRoot",
    $repoRoot
) -WorkingDirectory $repoRoot

Write-Step "Collect artifacts"
Remove-DirectoryIfExists -Path $finalReleaseDir -RepoRoot $repoRoot
New-Item -ItemType Directory -Path $finalReleaseDir | Out-Null

$installer = Get-ChildItem $frontendReleaseDir -Recurse -File -Filter "*.exe" |
    Where-Object { $_.Name -match "Setup" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$portable = Get-ChildItem $frontendReleaseDir -Recurse -File -Filter "*.exe" |
    Where-Object { $_.Name -notmatch "Setup" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $installer) {
    throw "Could not find installer exe under $frontendReleaseDir"
}

if ($null -eq $portable) {
    throw "Could not find portable exe under $frontendReleaseDir"
}

$installerOutput = Join-Path $finalReleaseDir "AiTeachMe Setup.exe"
$portableOutput = Join-Path $finalReleaseDir "AiTeachMe.exe"

Copy-Item -LiteralPath $installer.FullName -Destination $installerOutput -Force
Copy-Item -LiteralPath $portable.FullName -Destination $portableOutput -Force

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Installer: $installerOutput"
Write-Host "Portable : $portableOutput"
