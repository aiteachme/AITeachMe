param(
    [ValidateSet("apk", "aab", "all")]
    [string]$PackageType = "apk",
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [string]$DefaultApiUrl = "https://umlxyfrxsjyp.sealosbja.site",
    [string]$OutputDir = "packaging\android\release",
    [switch]$SkipClean,
    [switch]$Unsigned
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}

function Resolve-GradleCommand {
    param([string]$AndroidDir)

    $gradlew = Join-Path $AndroidDir "gradlew.bat"
    if (Test-Path $gradlew) {
        return $gradlew
    }

    $gradle = Get-Command "gradle.bat", "gradle" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $gradle) {
        return $gradle.Source
    }

    throw "Cannot find Gradle. Expected android\gradlew.bat or gradle on PATH."
}

function Initialize-JavaEnvironment {
    $java = Get-Command "java.exe", "java" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $java) {
        return
    }

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
        $candidates += $env:JAVA_HOME
    }
    $candidates += @(
        "C:\Program Files\Android\Android Studio\jbr",
        "C:\Program Files\Android\Android Studio\jre"
    )
    $candidates += @(Get-ChildItem -LiteralPath "C:\Program Files\Java" -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    $candidates += @(Get-ChildItem -LiteralPath "C:\Program Files\Eclipse Adoptium" -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    $candidates += @(Get-ChildItem -LiteralPath "C:\Program Files\Microsoft" -Directory -Filter "jdk-*" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }

        $javaPath = Join-Path $candidate "bin\java.exe"
        if (Test-Path $javaPath) {
            $env:JAVA_HOME = $candidate
            $javaBin = Join-Path $candidate "bin"
            if (($env:Path -split ";") -notcontains $javaBin) {
                $env:Path = "$javaBin;$env:Path"
            }
            return
        }
    }
}

function Resolve-KeytoolCommand {
    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
        $keytool = Join-Path $env:JAVA_HOME "bin\keytool.exe"
        if (Test-Path $keytool) {
            return $keytool
        }
    }

    $command = Get-Command "keytool.exe", "keytool" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }

    throw "Cannot find keytool. Install JDK 17+ or Android Studio, then rerun this script."
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

function Resolve-ReleaseApiUrl {
    param(
        [string]$ConfiguredApiUrl,
        [string]$FallbackApiUrl
    )

    $candidates = @(
        $ConfiguredApiUrl,
        [Environment]::GetEnvironmentVariable("AITEACHME_REMOTE_API_URL", "Process"),
        [Environment]::GetEnvironmentVariable("AITEACHME_ANDROID_API_URL", "Process"),
        $FallbackApiUrl
    )

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $resolved = $candidate.Trim().TrimEnd("/")
            if ($resolved -notmatch "^https?://") {
                throw "Android release API URL must start with http:// or https://: $resolved"
            }
            return $resolved
        }
    }

    throw "Android release API URL is required. Pass -ApiUrl https://your-public-origin or set AITEACHME_REMOTE_API_URL."
}

function Resolve-OutputPath {
    param(
        [string]$RepoRoot,
        [string]$Path
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return (Join-Path $RepoRoot $Path)
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

function Set-ProcessEnv {
    param(
        [string]$Name,
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Initialize-AndroidSigningEnvironment {
    param(
        [string]$RepoRoot,
        [switch]$AllowUnsigned
    )

    $requiredNames = @(
        "AITEACHME_ANDROID_KEYSTORE_FILE",
        "AITEACHME_ANDROID_KEYSTORE_PASSWORD",
        "AITEACHME_ANDROID_KEY_ALIAS",
        "AITEACHME_ANDROID_KEY_PASSWORD"
    )
    $configuredNames = @($requiredNames | Where-Object {
            -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, "Process"))
        })

    if ($configuredNames.Count -eq 0) {
        if ($AllowUnsigned) {
            return @{
                Enabled = $false
                Source = "unsigned"
                Suffix = "-unsigned"
            }
        }

        $privateDir = Join-Path $RepoRoot "packaging\android\private"
        New-Item -ItemType Directory -Path $privateDir -Force | Out-Null

        $keystorePath = Join-Path $privateDir "aiteachme-android-local-test.jks"
        $storePassword = "aiteachme-local-test"
        $keyAlias = "aiteachme-local-test"
        $keyPassword = $storePassword

        if (-not (Test-Path $keystorePath)) {
            $keytool = Resolve-KeytoolCommand
            Invoke-External `
                -File $keytool `
                -Arguments @(
                    "-genkeypair",
                    "-v",
                    "-keystore",
                    $keystorePath,
                    "-storepass",
                    $storePassword,
                    "-keypass",
                    $keyPassword,
                    "-alias",
                    $keyAlias,
                    "-keyalg",
                    "RSA",
                    "-keysize",
                    "2048",
                    "-validity",
                    "10000",
                    "-dname",
                    "CN=AiTeachMe Android Local Test,O=AiTeachMe,C=CN"
                ) `
                -WorkingDirectory $RepoRoot
        }

        Set-ProcessEnv -Name "AITEACHME_ANDROID_KEYSTORE_FILE" -Value $keystorePath
        Set-ProcessEnv -Name "AITEACHME_ANDROID_KEYSTORE_PASSWORD" -Value $storePassword
        Set-ProcessEnv -Name "AITEACHME_ANDROID_KEY_ALIAS" -Value $keyAlias
        Set-ProcessEnv -Name "AITEACHME_ANDROID_KEY_PASSWORD" -Value $keyPassword

        return @{
            Enabled = $true
            Source = "local test keystore"
            Suffix = "-signed"
            KeystorePath = $keystorePath
        }
    }

    if ($configuredNames.Count -ne $requiredNames.Count) {
        $missingNames = @($requiredNames | Where-Object { $configuredNames -notcontains $_ })
        throw "Android signing configuration is incomplete. Missing environment variable(s): $($missingNames -join ', ')"
    }

    $keystoreFile = [Environment]::GetEnvironmentVariable("AITEACHME_ANDROID_KEYSTORE_FILE", "Process")
    $keystorePath = if ([System.IO.Path]::IsPathRooted($keystoreFile)) {
        $keystoreFile
    }
    else {
        Join-Path $RepoRoot $keystoreFile
    }

    if (-not (Test-Path $keystorePath)) {
        throw "AITEACHME_ANDROID_KEYSTORE_FILE points to a missing file: $keystorePath"
    }

    return @{
        Enabled = $true
        Source = "configured keystore"
        Suffix = "-signed"
        KeystorePath = $keystorePath
    }
}

function Copy-LatestArtifact {
    param(
        [string]$SourceDir,
        [string]$Filter,
        [string]$Destination
    )

    if (-not (Test-Path $SourceDir)) {
        throw "Android build output directory was not produced: $SourceDir"
    }

    $artifact = Get-ChildItem -LiteralPath $SourceDir -File -Filter $Filter |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $artifact) {
        throw "Could not find Android artifact matching $Filter under $SourceDir"
    }

    Copy-Item -LiteralPath $artifact.FullName -Destination $Destination -Force
    return $Destination
}

$repoRoot = Resolve-RepoRoot
$androidDir = Join-Path $repoRoot "android"
Initialize-JavaEnvironment
$gradle = Resolve-GradleCommand -AndroidDir $androidDir
$projectVersion = Get-ProjectVersion -RepoRoot $repoRoot
$apiBaseUrl = Resolve-ReleaseApiUrl -ConfiguredApiUrl $ApiUrl -FallbackApiUrl $DefaultApiUrl
$releaseDir = Resolve-OutputPath -RepoRoot $repoRoot -Path $OutputDir
$androidSigning = Initialize-AndroidSigningEnvironment -RepoRoot $repoRoot -AllowUnsigned:$Unsigned

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Get-ChildItem -LiteralPath $releaseDir -File -Filter "AiTeachMe-v*-android-release*.*" -ErrorAction SilentlyContinue |
    Remove-Item -Force

$gradleTasks = @()
if (-not $SkipClean) {
    $gradleTasks += "clean"
}
if ($PackageType -in @("apk", "all")) {
    $gradleTasks += ":app:assembleRelease"
}
if ($PackageType -in @("aab", "all")) {
    $gradleTasks += ":app:bundleRelease"
}

$gradleArgs = @(
    "--no-daemon",
    "-PaiteachmeAndroidApiUrl=$apiBaseUrl"
) + $gradleTasks

$previousAndroidApiUrl = [Environment]::GetEnvironmentVariable("AITEACHME_ANDROID_API_URL", "Process")

Write-Host "Repo: $repoRoot"
Write-Host "Package type: $PackageType"
Write-Host "Version: $projectVersion"
Write-Host "API base URL: $apiBaseUrl"
Write-Host "Output: $releaseDir"
if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
    Write-Host "JAVA_HOME: $env:JAVA_HOME"
}
if (-not $androidSigning.Enabled) {
    Write-Host "Android signing: disabled by -Unsigned; Gradle will produce unsigned release artifacts." -ForegroundColor Yellow
}
else {
    Write-Host "Android signing: $($androidSigning.Source)"
    if ($androidSigning.KeystorePath) {
        Write-Host "Keystore: $($androidSigning.KeystorePath)"
    }
}

try {
    [Environment]::SetEnvironmentVariable("AITEACHME_ANDROID_API_URL", $apiBaseUrl, "Process")
    Invoke-External -File $gradle -Arguments $gradleArgs -WorkingDirectory $androidDir
}
finally {
    [Environment]::SetEnvironmentVariable("AITEACHME_ANDROID_API_URL", $previousAndroidApiUrl, "Process")
}

$releaseOutputs = @()
if ($PackageType -in @("apk", "all")) {
    $apkOutput = Join-Path $releaseDir "AiTeachMe-v$projectVersion-android-release$($androidSigning.Suffix).apk"
    $releaseOutputs += Copy-LatestArtifact `
        -SourceDir (Join-Path $androidDir "app\build\outputs\apk\release") `
        -Filter "*.apk" `
        -Destination $apkOutput
}
if ($PackageType -in @("aab", "all")) {
    $aabOutput = Join-Path $releaseDir "AiTeachMe-v$projectVersion-android-release$($androidSigning.Suffix).aab"
    $releaseOutputs += Copy-LatestArtifact `
        -SourceDir (Join-Path $androidDir "app\build\outputs\bundle\release") `
        -Filter "*.aab" `
        -Destination $aabOutput
}

Write-Host ""
Write-Host "Android release packages:" -ForegroundColor Green
$releaseOutputs | ForEach-Object {
    Write-Host "  $_"
}
