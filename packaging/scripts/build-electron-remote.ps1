param(
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall,
    [switch]$ImportBundledEnv,
    [string]$BundledEnvConfigPath = "packaging\private\bundled-env.json"
)

$params = @{
    Flavor = "remote"
    ApiUrl = $ApiUrl
    BundledEnvConfigPath = $BundledEnvConfigPath
}
if ($SkipInstall) {
    $params.SkipInstall = $true
}
if ($ImportBundledEnv) {
    $params.ImportBundledEnv = $true
}

& (Join-Path $PSScriptRoot "build-electron.ps1") @params
