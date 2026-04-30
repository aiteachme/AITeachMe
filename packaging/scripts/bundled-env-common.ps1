$DefaultBundledEnvConfigPath = "packaging\private\bundled-env.json"
$DefaultBundledEnvArtifactSuffix = "bundled"
$BundledEnvFileName = "aiteachme_bundled_env.enc.json"

function Resolve-BundledEnvRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Resolve-BundledEnvRepoRelativePath {
    param(
        [string]$RepoRoot,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return Join-Path $RepoRoot $Path
}

function ConvertTo-BundledEnvHashtable {
    param([object]$Config)

    $source = $Config
    if ($null -ne $Config -and ($Config.PSObject.Properties.Name -contains "env")) {
        $source = $Config.env
    }

    $values = @{}
    if ($null -eq $source) {
        return $values
    }

    foreach ($property in @($source.PSObject.Properties)) {
        $key = [string]$property.Name
        if ([string]::IsNullOrWhiteSpace($key)) {
            continue
        }
        $value = [string]$property.Value
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        $values[$key.Trim()] = $value
    }

    return $values
}

function Read-BundledEnvJsonFile {
    param(
        [string]$RepoRoot,
        [string]$Path
    )

    $resolvedPath = Resolve-BundledEnvRepoRelativePath -RepoRoot $RepoRoot -Path $Path
    if (-not (Test-Path $resolvedPath)) {
        throw "Bundled env config file was not found: $resolvedPath"
    }

    $config = Get-Content -Raw -LiteralPath $resolvedPath | ConvertFrom-Json
    $values = ConvertTo-BundledEnvHashtable -Config $config
    Write-Host "Imported bundled env config: $resolvedPath"
    return $values
}

function Get-BundledEnvOutputPath {
    param([string]$RepoRoot)

    return Join-Path $RepoRoot "packaging\artifacts\generated-configs\$BundledEnvFileName"
}

function Remove-BundledEnvOutput {
    param([string]$RepoRoot)

    $outputPath = Get-BundledEnvOutputPath -RepoRoot $RepoRoot
    if (Test-Path $outputPath) {
        Remove-Item -LiteralPath $outputPath -Force
    }
}

function ConvertTo-BundledEnvArtifactSuffix {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultBundledEnvArtifactSuffix
    }
    $slug = ($Value.Trim() -replace '[^A-Za-z0-9._-]+', '-').Trim("-._")
    if ($slug) {
        return $slug
    }
    return $DefaultBundledEnvArtifactSuffix
}

function Get-BundledEnvReleaseSuffix {
    param(
        [switch]$ImportBundledEnv,
        [string]$BundledEnvArtifactSuffix = $DefaultBundledEnvArtifactSuffix
    )

    return Get-AITeachMeInstallerReleaseSuffix `
        -Bundled:$ImportBundledEnv `
        -BundledEnvArtifactSuffix $BundledEnvArtifactSuffix
}

function Get-AITeachMeInstallerReleaseSuffix {
    param(
        [switch]$Bundled,
        [switch]$Remote,
        [switch]$Electron,
        [switch]$Tauri,
        [string]$BundledEnvArtifactSuffix = $DefaultBundledEnvArtifactSuffix
    )

    $parts = @()
    if ($Electron) {
        $parts += "electron"
    }
    if ($Tauri) {
        $parts += "tauri"
    }
    if ($Bundled) {
        $parts += (ConvertTo-BundledEnvArtifactSuffix -Value $BundledEnvArtifactSuffix)
    }
    if ($Remote) {
        $parts += "remote"
    }
    if ($parts.Count -eq 0) {
        return ""
    }
    return "-" + ($parts -join "-")
}

function Get-BundledEnvCryptoBytes {
    param([string]$Purpose)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Purpose))
    }
    finally {
        $sha.Dispose()
    }
}

function Convert-ToBase64 {
    param([byte[]]$Bytes)

    return [Convert]::ToBase64String($Bytes)
}

function New-EncryptedBundledEnvFile {
    param(
        [string]$OutputPath,
        [hashtable]$Values
    )

    $payload = [ordered]@{
        env = [ordered]@{}
    }
    foreach ($key in ($Values.Keys | Sort-Object)) {
        $payload.env[$key] = [string]$Values[$key]
    }

    $plaintext = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Depth 10 -Compress))
    $encryptionKey = Get-BundledEnvCryptoBytes -Purpose "AiTeachMe bundled env encryption v1"
    $macKey = Get-BundledEnvCryptoBytes -Purpose "AiTeachMe bundled env authentication v1"
    $iv = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($iv)

    $aes = [System.Security.Cryptography.Aes]::Create()
    try {
        $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
        $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
        $aes.Key = $encryptionKey
        $aes.IV = $iv
        $encryptor = $aes.CreateEncryptor()
        try {
            $ciphertext = $encryptor.TransformFinalBlock($plaintext, 0, $plaintext.Length)
        }
        finally {
            $encryptor.Dispose()
        }
    }
    finally {
        $aes.Dispose()
    }

    $tagInput = New-Object byte[] ($iv.Length + $ciphertext.Length)
    [Array]::Copy($iv, 0, $tagInput, 0, $iv.Length)
    [Array]::Copy($ciphertext, 0, $tagInput, $iv.Length, $ciphertext.Length)
    $hmac = [System.Security.Cryptography.HMACSHA256]::new($macKey)
    try {
        $tag = $hmac.ComputeHash($tagInput)
    }
    finally {
        $hmac.Dispose()
    }

    $document = [ordered]@{
        version = 1
        algorithm = "AES-256-CBC-HMAC-SHA256"
        key_id = "aiteachme-bundled-env-v1"
        iv = Convert-ToBase64 -Bytes $iv
        ciphertext = Convert-ToBase64 -Bytes $ciphertext
        tag = Convert-ToBase64 -Bytes $tag
        keys = @($Values.Keys | Sort-Object)
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
    [System.IO.File]::WriteAllText(
        $OutputPath,
        ($document | ConvertTo-Json -Depth 10) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Initialize-BundledEnvConfig {
    param(
        [string]$RepoRoot,
        [switch]$ImportBundledEnv,
        [string]$BundledEnvConfigPath = $DefaultBundledEnvConfigPath
    )

    Remove-BundledEnvOutput -RepoRoot $RepoRoot

    if (-not $ImportBundledEnv) {
        return $null
    }

    $selected = Read-BundledEnvJsonFile -RepoRoot $RepoRoot -Path $BundledEnvConfigPath

    $missing = @()
    foreach ($required in @("LLM_API_KEY", "LLM_BASE_URL")) {
        if (-not $selected.ContainsKey($required)) {
            $missing += $required
        }
    }
    if ($missing.Count -gt 0) {
        throw "Bundled env configuration is incomplete. Missing: $($missing -join ', ')"
    }

    $outputPath = Get-BundledEnvOutputPath -RepoRoot $RepoRoot
    New-EncryptedBundledEnvFile -OutputPath $outputPath -Values $selected
    Write-Host "Bundled encrypted env keys: $((@($selected.Keys) | Sort-Object) -join ', ')"
    Write-Host "Bundled encrypted env file: $outputPath"
    return $outputPath
}
