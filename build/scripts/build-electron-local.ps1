param(
    [switch]$SkipInstall,
    [string]$BackendPort = "9020"
)

$params = @{
    Flavor = "local"
    BackendPort = $BackendPort
}
if ($SkipInstall) {
    $params.SkipInstall = $true
}

& (Join-Path $PSScriptRoot "build-electron.ps1") @params
