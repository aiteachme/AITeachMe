param(
    [switch]$SkipInstall,
    [string]$BackendPort = "9020",
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

$params = @{
    Flavor = "local"
    BackendPort = $BackendPort
    BundledEnvConfigPath = $BundledEnvConfigPath
}
if ($SkipInstall) {
    $params.SkipInstall = $true
}
if ($ImportBundledEnv) {
    $params.ImportBundledEnv = $true
}

& (Join-Path $PSScriptRoot "build-electron.ps1") @params
