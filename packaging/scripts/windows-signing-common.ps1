$script:AITeachMeDefaultTimestampUrl = "http://timestamp.digicert.com"

function Get-AITeachMeEnvValue {
    param([string[]]$Names)

    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }

    return ""
}

function Test-AITeachMeTruthy {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    return $Value -match "^(1|true|yes|on)$"
}

function Get-AITeachMeWindowsSigningState {
    $signCommand = Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_SIGN_COMMAND")
    $certificateThumbprint = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_CERTIFICATE_THUMBPRINT",
        "AITEACHME_WINDOWS_CERTIFICATE_SHA1",
        "WIN_CSC_SHA1_HASH",
        "CSC_SHA1_HASH"
    )
    $certificateFile = Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_CERTIFICATE_FILE")
    $electronCertificateLink = Get-AITeachMeEnvValue @("WIN_CSC_LINK", "CSC_LINK")
    $certificatePassword = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_CERTIFICATE_PASSWORD",
        "WIN_CSC_KEY_PASSWORD",
        "CSC_KEY_PASSWORD"
    )
    $certificateSubjectName = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_CERTIFICATE_SUBJECT_NAME",
        "WIN_CSC_NAME",
        "CSC_NAME"
    )
    $publisherName = Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_PUBLISHER_NAME")
    $timestampUrl = Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_TIMESTAMP_URL")
    if ([string]::IsNullOrWhiteSpace($timestampUrl)) {
        $timestampUrl = $script:AITeachMeDefaultTimestampUrl
    }

    $azureEndpoint = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_AZURE_ENDPOINT",
        "AITEACHME_WINDOWS_AZURE_SIGN_ENDPOINT"
    )
    $azureAccount = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_AZURE_ACCOUNT_NAME",
        "AITEACHME_WINDOWS_AZURE_SIGN_ACCOUNT",
        "AITEACHME_WINDOWS_AZURE_CODE_SIGNING_ACCOUNT_NAME"
    )
    $azureProfile = Get-AITeachMeEnvValue @(
        "AITEACHME_WINDOWS_AZURE_CERTIFICATE_PROFILE_NAME",
        "AITEACHME_WINDOWS_AZURE_SIGN_PROFILE"
    )

    $required = Test-AITeachMeTruthy (Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_SIGNING_REQUIRED"))
    $explicitEnabled = Test-AITeachMeTruthy (Get-AITeachMeEnvValue @("AITEACHME_WINDOWS_SIGNING_ENABLED"))
    $hasAzure = -not [string]::IsNullOrWhiteSpace($azureEndpoint) -or
        -not [string]::IsNullOrWhiteSpace($azureAccount) -or
        -not [string]::IsNullOrWhiteSpace($azureProfile)
    $hasCompleteAzure = -not [string]::IsNullOrWhiteSpace($azureEndpoint) -and
        -not [string]::IsNullOrWhiteSpace($azureAccount) -and
        -not [string]::IsNullOrWhiteSpace($azureProfile) -and
        -not [string]::IsNullOrWhiteSpace($publisherName)
    $hasClassicCertificate = -not [string]::IsNullOrWhiteSpace($certificateFile) -or
        -not [string]::IsNullOrWhiteSpace($electronCertificateLink) -or
        -not [string]::IsNullOrWhiteSpace($certificateThumbprint) -or
        -not [string]::IsNullOrWhiteSpace($certificateSubjectName)
    $hasManualSigner = -not [string]::IsNullOrWhiteSpace($signCommand) -or
        -not [string]::IsNullOrWhiteSpace($certificateFile) -or
        -not [string]::IsNullOrWhiteSpace($certificateThumbprint) -or
        -not [string]::IsNullOrWhiteSpace($certificateSubjectName)
    $enabled = $explicitEnabled -or $hasCompleteAzure -or $hasClassicCertificate -or
        -not [string]::IsNullOrWhiteSpace($signCommand)

    return @{
        Enabled = $enabled
        Required = $required
        HasAzure = $hasAzure
        HasCompleteAzure = $hasCompleteAzure
        HasClassicCertificate = $hasClassicCertificate
        HasManualSigner = $hasManualSigner
        SignCommand = $signCommand
        CertificateThumbprint = $certificateThumbprint
        CertificateFile = $certificateFile
        ElectronCertificateLink = $electronCertificateLink
        CertificatePassword = $certificatePassword
        CertificateSubjectName = $certificateSubjectName
        PublisherName = $publisherName
        TimestampUrl = $timestampUrl
        DigestAlgorithm = "sha256"
        AzureEndpoint = $azureEndpoint
        AzureAccountName = $azureAccount
        AzureCertificateProfileName = $azureProfile
    }
}

function Assert-AITeachMeWindowsSigningReady {
    param([hashtable]$Signing)

    if ($Signing.HasAzure -and -not $Signing.HasCompleteAzure) {
        throw "Azure Windows signing is partially configured. Required variables: AITEACHME_WINDOWS_PUBLISHER_NAME, AITEACHME_WINDOWS_AZURE_ENDPOINT, AITEACHME_WINDOWS_AZURE_ACCOUNT_NAME, AITEACHME_WINDOWS_AZURE_CERTIFICATE_PROFILE_NAME."
    }

    if ($Signing.Required -and -not $Signing.Enabled) {
        throw "AITEACHME_WINDOWS_SIGNING_REQUIRED is set, but no Windows signing configuration was found."
    }
}

function Get-AITeachMeTauriWindowsSigningConfig {
    param([hashtable]$Signing)

    if (-not $Signing.Enabled) {
        return $null
    }

    if (-not [string]::IsNullOrWhiteSpace($Signing.SignCommand)) {
        return [ordered]@{
            signCommand = $Signing.SignCommand
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($Signing.CertificateThumbprint)) {
        return [ordered]@{
            certificateThumbprint = $Signing.CertificateThumbprint
            digestAlgorithm = $Signing.DigestAlgorithm
            timestampUrl = $Signing.TimestampUrl
        }
    }

    return $null
}

function Write-AITeachMeWindowsSigningSummary {
    param([hashtable]$Signing)

    if (-not $Signing.Enabled) {
        Write-Host "Windows code signing: disabled. Unsigned installers may trigger Defender SmartScreen reputation prompts." -ForegroundColor Yellow
        return
    }

    if (-not [string]::IsNullOrWhiteSpace($Signing.SignCommand)) {
        Write-Host "Windows code signing: custom sign command enabled."
    }
    elseif ($Signing.HasCompleteAzure) {
        Write-Host "Windows code signing: Azure Trusted Signing enabled."
    }
    elseif (-not [string]::IsNullOrWhiteSpace($Signing.CertificateFile)) {
        Write-Host "Windows code signing: certificate file/env link enabled."
    }
    elseif (-not [string]::IsNullOrWhiteSpace($Signing.CertificateThumbprint)) {
        Write-Host "Windows code signing: certificate thumbprint enabled."
    }
    else {
        Write-Host "Windows code signing: enabled by environment."
    }
}

function Resolve-AITeachMeSignTool {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }

    $kitsRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidate = Get-ChildItem -LiteralPath $kitsRoot -Recurse -File -Filter "signtool.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($null -ne $candidate) {
            return $candidate.FullName
        }
    }

    return ""
}

function Quote-AITeachMeCommandArgument {
    param([string]$Value)

    return '"' + ($Value -replace '"', '\"') + '"'
}

function Test-AITeachMeSignatureValid {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $false
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction SilentlyContinue
    return $null -ne $signature -and $signature.Status -eq "Valid"
}

function Write-AITeachMeSignatureStatus {
    param(
        [string]$Path,
        [string]$Description = "file"
    )

    if (-not (Test-Path $Path)) {
        Write-Host "Windows signature: $Description missing: $Path" -ForegroundColor Yellow
        return
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $signature) {
        Write-Host "Windows signature: $Description status unavailable." -ForegroundColor Yellow
        return
    }

    if ($signature.Status -eq "Valid") {
        Write-Host "Windows signature: $Description is signed and valid."
    }
    else {
        Write-Host "Windows signature: $Description is $($signature.Status)." -ForegroundColor Yellow
    }
}

function Invoke-AITeachMeWindowsSignFile {
    param(
        [hashtable]$Signing,
        [string]$Path,
        [string]$Description = "file",
        [switch]$SkipIfSigned
    )

    if (-not (Test-Path $Path)) {
        throw "Cannot sign missing $Description`: $Path"
    }

    if ($SkipIfSigned -and (Test-AITeachMeSignatureValid -Path $Path)) {
        Write-Host "Windows code signing skipped; $Description is already signed."
        return
    }

    if (-not $Signing.HasManualSigner) {
        Write-AITeachMeSignatureStatus -Path $Path -Description $Description
        if ($Signing.Required -and -not (Test-AITeachMeSignatureValid -Path $Path)) {
            throw "Windows signing is required, but no manual signer is available for $Description`: $Path"
        }
        return
    }

    $resolvedPath = (Resolve-Path $Path).Path
    if (-not [string]::IsNullOrWhiteSpace($Signing.SignCommand)) {
        $quotedPath = Quote-AITeachMeCommandArgument $resolvedPath
        $command = if ($Signing.SignCommand.Contains("%1")) {
            $Signing.SignCommand.Replace("%1", $quotedPath)
        }
        else {
            "$($Signing.SignCommand) $quotedPath"
        }

        Write-Host "Windows code signing $Description with custom command."
        $global:LASTEXITCODE = 0
        & cmd.exe /d /s /c $command
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        if ($exitCode -ne 0) {
            throw "Custom Windows signing failed for $Description with exit code $exitCode"
        }
    }
    else {
        $signtool = Resolve-AITeachMeSignTool
        if ([string]::IsNullOrWhiteSpace($signtool)) {
            throw "signtool.exe was not found. Install Windows SDK or use AITEACHME_WINDOWS_SIGN_COMMAND."
        }

        $args = @("sign", "/fd", $Signing.DigestAlgorithm, "/tr", $Signing.TimestampUrl, "/td", $Signing.DigestAlgorithm)
        if (-not [string]::IsNullOrWhiteSpace($Signing.CertificateThumbprint)) {
            $args += @("/sha1", $Signing.CertificateThumbprint)
        }
        elseif (-not [string]::IsNullOrWhiteSpace($Signing.CertificateSubjectName)) {
            $args += @("/n", $Signing.CertificateSubjectName)
        }
        elseif (-not [string]::IsNullOrWhiteSpace($Signing.CertificateFile)) {
            $args += @("/f", $Signing.CertificateFile)
            if (-not [string]::IsNullOrWhiteSpace($Signing.CertificatePassword)) {
                $args += @("/p", $Signing.CertificatePassword)
            }
        }
        else {
            throw "No usable manual Windows signing certificate is configured."
        }
        if (-not [string]::IsNullOrWhiteSpace($Signing.PublisherName)) {
            $args += @("/d", $Signing.PublisherName)
        }
        $args += $resolvedPath

        Write-Host "Windows code signing $Description with signtool."
        $global:LASTEXITCODE = 0
        & $signtool @args
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        if ($exitCode -ne 0) {
            throw "signtool failed for $Description with exit code $exitCode"
        }
    }

    Write-AITeachMeSignatureStatus -Path $resolvedPath -Description $Description
    if ($Signing.Required -and -not (Test-AITeachMeSignatureValid -Path $resolvedPath)) {
        throw "Windows signing is required, but $Description does not have a valid Authenticode signature: $resolvedPath"
    }
}
