param(
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json",
    [string]$BundledEnvArtifactSuffix = "bundled",
    [switch]$HideElectronSuffix
)

$params = @{
    Flavor = "local"
    BackendPort = $BackendPort
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
