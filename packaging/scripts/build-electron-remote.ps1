param(
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled",
    [switch]$HideElectronSuffix
)

$params = @{
    Flavor = "remote"
    ApiUrl = $ApiUrl
    BundledEnvConfigPath = $BundledEnvConfigPath
    BundledEnvArtifactSuffix = $BundledEnvArtifactSuffix
}
if ($SkipInstall) {
    $params.SkipInstall = $true
}
if ($ImportBundledEnv) {
    $params.ImportBundledEnv = $true
}
if ($HideElectronSuffix) {
    $params.HideElectronSuffix = $true
}

& (Join-Path $PSScriptRoot "build-electron.ps1") @params
