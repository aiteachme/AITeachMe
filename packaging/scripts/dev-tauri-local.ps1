param(
    [switch]$SkipInstall
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

function Invoke-Checked {
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

$repoRoot = Resolve-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$npm = Resolve-CommandPath @("npm.cmd", "npm")
$powershell = Resolve-CommandPath @("powershell.exe", "powershell")

# Keep Tauri local dev away from the normal browser/Vite dev default port 5180.
$env:AITEACHME_FRONTEND_PORT = "5181"

$prepareArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    (Join-Path $repoRoot "packaging\scripts\prepare-tauri-sidecar.ps1")
)
if ($SkipInstall) {
    $prepareArgs += "-SkipInstall"
}

Write-Host "Repo: $repoRoot"
Write-Host "Tauri local frontend port: $env:AITEACHME_FRONTEND_PORT"
Write-Host "Tauri local backend port: dynamic local loopback port (resolved at app startup)"

Invoke-Checked -File $powershell -Arguments $prepareArgs -WorkingDirectory $repoRoot

Push-Location $frontendDir
try {
    Write-Host ""
    Write-Host "> $npm run tauri:dev:local:raw" -ForegroundColor DarkGray
    & $npm run tauri:dev:local:raw
    exit $(if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE })
}
finally {
    Pop-Location
}
