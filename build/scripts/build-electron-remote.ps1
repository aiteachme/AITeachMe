param(
    [string]$ApiUrl = $env:AITEACHME_REMOTE_API_URL,
    [switch]$SkipInstall
)

$params = @{
    Flavor = "remote"
    ApiUrl = $ApiUrl
}
if ($SkipInstall) {
    $params.SkipInstall = $true
}

& (Join-Path $PSScriptRoot "build-electron.ps1") @params
