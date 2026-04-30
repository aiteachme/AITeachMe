param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("local", "remote")]
    [string]$Flavor,
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
        return @{
            File = $conda.Source
            PrefixArgs = @("run", "--no-capture-output", "-n", "atm", "python")
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

function Write-ElectronBuildConfig {
    param(
        [string]$FrontendDir,
        [string]$BackendMode,
        [string]$ApiBaseUrl,
        [string]$BackendPort,
        [string]$AppId,
        [string]$ProductName
    )

    $configPath = Join-Path $FrontendDir "electron\build-config.cjs"
    $config = [ordered]@{
        backendMode = $BackendMode
        apiBaseUrl = $ApiBaseUrl
        backendPort = $BackendPort
        appId = $AppId
        appName = $ProductName
        productName = $ProductName
    }
    $json = $config | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath $configPath -Value "module.exports = $json;`n" -Encoding UTF8
}

function Set-ProcessEnv {
    param(
        [string]$Name,
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Restore-ProcessEnv {
    param([hashtable]$PreviousValues)

    foreach ($name in $PreviousValues.Keys) {
        [Environment]::SetEnvironmentVariable($name, $PreviousValues[$name], "Process")
    }
}

$repoRoot = Resolve-RepoRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendReleaseDir = Join-Path $frontendDir "release"
$packagingArtifactsDir = Join-Path $repoRoot "packaging\artifacts"
$finalReleaseDir = Join-Path $repoRoot "packaging\release"
$backendDistDir = Join-Path $backendDir "dist\aiteachme-backend"
$projectVersion = Get-ProjectVersion -RepoRoot $repoRoot
$productName = if ($Flavor -eq "local") { "AiTeachMe Electron Local" } else { "AiTeachMe Electron Remote" }
$appId = if ($Flavor -eq "local") { "com.aiteachme.desktop.electron.local" } else { "com.aiteachme.desktop.electron.remote" }

if ($Flavor -eq "remote") {
    if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
        throw "Remote API URL is required. Pass -ApiUrl https://your-api.example.com or set AITEACHME_REMOTE_API_URL."
    }
    if ($ApiUrl -notmatch "^https?://") {
        throw "Remote API URL must start with http:// or https://: $ApiUrl"
    }
}

$apiBaseUrl = if ($Flavor -eq "local") { "http://127.0.0.1:$BackendPort" } else { $ApiUrl.TrimEnd("/") }

$python = Resolve-PythonCommand $repoRoot
$npm = Resolve-CommandPath @("npm.cmd", "npm")
Stop-LocalBuildToolProcesses -RepoRoot $repoRoot

. (Join-Path $PSScriptRoot "bundled-env-common.ps1")
$bundledEnvConfigPath = Initialize-BundledEnvConfig `
    -RepoRoot $repoRoot `
    -ImportBundledEnv:($ImportBundledEnv -and $Flavor -eq "local") `
    -BundledEnvConfigPath $BundledEnvConfigPath
if ($ImportBundledEnv -and $Flavor -ne "local") {
    Write-Host "ImportBundledEnv is only used by local packages with an embedded backend; skipping for electron-$Flavor." -ForegroundColor Yellow
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("ELECTRON_MIRROR", "Process"))) {
    Set-ProcessEnv -Name "ELECTRON_MIRROR" -Value "https://npmmirror.com/mirrors/electron/"
}
if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("ELECTRON_BUILDER_BINARIES_MIRROR", "Process"))) {
    Set-ProcessEnv -Name "ELECTRON_BUILDER_BINARIES_MIRROR" -Value "https://npmmirror.com/mirrors/electron-builder-binaries/"
}

Write-Host "Repo: $repoRoot"
Write-Host "Flavor: electron-$Flavor"
Write-Host "Version: $projectVersion"
Write-Host "Product: $productName"
Write-Host "Python: $($python.File) $($python.PrefixArgs -join ' ')"
Write-Host "npm: $npm"
Write-Host "API base URL: $apiBaseUrl"
if ($Flavor -eq "local") {
    Write-Host "Backend port: $BackendPort"
    if ($bundledEnvConfigPath) {
        Write-Host "Bundled env: $bundledEnvConfigPath"
    }
}

Write-Step "Install build dependencies"
if ($SkipInstall) {
    Write-Host "SkipInstall is set; dependency installation skipped."
}
else {
    if ($Flavor -eq "local") {
        Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "-e", ".") -WorkingDirectory $backendDir
        Invoke-Python -Python $python -Arguments @("-m", "pip", "install", "pyinstaller") -WorkingDirectory $backendDir
    }
    Invoke-External -File $npm -Arguments @("install") -WorkingDirectory $frontendDir
}

if ($Flavor -eq "local") {
    Write-Step "Build backend executable"
    Remove-DirectoryIfExists -Path (Join-Path $backendDir "build") -RepoRoot $repoRoot
    Remove-DirectoryIfExists -Path $backendDistDir -RepoRoot $repoRoot
    Invoke-Python -Python $python -Arguments @("-m", "PyInstaller", "--noconfirm", "aiteachme-backend.spec") -WorkingDirectory $backendDir

    if (-not (Test-Path (Join-Path $backendDistDir "aiteachme-backend.exe"))) {
        throw "Backend executable was not produced: $backendDistDir"
    }
}

Write-Step "Write Electron runtime build config"
Write-ElectronBuildConfig `
    -FrontendDir $frontendDir `
    -BackendMode $Flavor `
    -ApiBaseUrl $apiBaseUrl `
    -BackendPort $BackendPort `
    -AppId $appId `
    -ProductName $productName

$envNames = @(
    "VITE_API_URL",
    "AITEACHME_ELECTRON_FLAVOR",
    "AITEACHME_ELECTRON_PRODUCT_NAME",
    "AITEACHME_ELECTRON_APP_ID"
)
$previousEnv = @{}
foreach ($name in $envNames) {
    $previousEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    Set-ProcessEnv -Name "VITE_API_URL" -Value $apiBaseUrl
    Set-ProcessEnv -Name "AITEACHME_ELECTRON_FLAVOR" -Value $Flavor
    Set-ProcessEnv -Name "AITEACHME_ELECTRON_PRODUCT_NAME" -Value $productName
    Set-ProcessEnv -Name "AITEACHME_ELECTRON_APP_ID" -Value $appId

    Write-Step "Generate frontend API client"
    Invoke-External -File $npm -Arguments @("exec", "--", "orval", "--config", "orval.config.js") -WorkingDirectory $frontendDir

    Write-Step "Build frontend"
    Invoke-External -File $npm -Arguments @("run", "build") -WorkingDirectory $frontendDir

    Write-Step "Build Electron installer and portable exe"
    Stop-LocalBuildToolProcesses -RepoRoot $repoRoot
    Stop-ProcessesUnderPath -Path $frontendReleaseDir
    Remove-DirectoryIfExists -Path $frontendReleaseDir -RepoRoot $repoRoot
    Invoke-External -File $npm -Arguments @("run", "electron:installer") -WorkingDirectory $frontendDir
    Stop-LocalBuildToolProcesses -RepoRoot $repoRoot
    Invoke-External -File "powershell" -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $repoRoot "packaging\scripts\build-electron-portable-nsis.ps1"),
        "-RepoRoot",
        $repoRoot,
        "-ProductName",
        $productName
    ) -WorkingDirectory $repoRoot
}
finally {
    Restore-ProcessEnv -PreviousValues $previousEnv
}

Write-Step "Collect release packages"
New-Item -ItemType Directory -Path $packagingArtifactsDir -Force | Out-Null
$electronArtifactDir = Join-Path $packagingArtifactsDir "electron-$Flavor"
Remove-DirectoryIfExists -Path $electronArtifactDir -RepoRoot $repoRoot
New-Item -ItemType Directory -Path $electronArtifactDir -Force | Out-Null
New-Item -ItemType Directory -Path $finalReleaseDir -Force | Out-Null
Get-ChildItem -LiteralPath $finalReleaseDir -File -Filter "AiTeachMe-v*-electron-$Flavor-*.*" -ErrorAction SilentlyContinue |
    Remove-Item -Force

$installer = Get-ChildItem $frontendReleaseDir -Recurse -File -Filter "*.exe" |
    Where-Object { $_.Name -match "Setup" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$portable = Get-ChildItem $frontendReleaseDir -Recurse -File -Filter "*.exe" |
    Where-Object { $_.Name -eq "$productName.exe" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $installer) {
    throw "Could not find installer exe under $frontendReleaseDir"
}

if ($null -eq $portable) {
    throw "Could not find portable exe under $frontendReleaseDir"
}

$installerOutput = Join-Path $finalReleaseDir "AiTeachMe-v$projectVersion-electron-$Flavor-installer$($installer.Extension)"
$portableOutput = Join-Path $finalReleaseDir "AiTeachMe-v$projectVersion-electron-$Flavor-portable$($portable.Extension)"
$installerArtifact = Join-Path $electronArtifactDir $installer.Name
$portableArtifact = Join-Path $electronArtifactDir $portable.Name

Copy-Item -LiteralPath $installer.FullName -Destination $installerArtifact -Force
Copy-Item -LiteralPath $portable.FullName -Destination $portableArtifact -Force
Copy-Item -LiteralPath $installerArtifact -Destination $installerOutput -Force
Copy-Item -LiteralPath $portableArtifact -Destination $portableOutput -Force

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Installer: $installerOutput"
Write-Host "Portable : $portableOutput"
