param(
    [Parameter(Mandatory = $true)]
    [string]$Image,

    [ValidateSet("slim", "office")]
    [string]$Variant = "office",

    [string]$Tag = "",

    [string]$Platform = "",

    [switch]$Push
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dockerfile = if ($Variant -eq "office") {
    "infra/deployment/docker/backend-office.Dockerfile"
} else {
    "infra/deployment/docker/backend.Dockerfile"
}

if (-not $Tag.Trim()) {
    $date = Get-Date -Format "yyyyMMdd"
    $shortSha = ""
    try {
        $shortSha = (git -C $repoRoot rev-parse --short HEAD 2>$null).Trim()
    } catch {
        $shortSha = "local"
    }
    if (-not $shortSha) {
        $shortSha = "local"
    }
    $Tag = "$Variant-$date-$shortSha"
}

$fullImage = "${Image}:${Tag}"

if ($Platform.Trim()) {
    $args = @(
        "buildx", "build",
        "--platform", $Platform,
        "-f", $dockerfile,
        "-t", $fullImage
    )
    if ($Push) {
        $args += "--push"
    } else {
        $args += "--load"
    }
    $args += $repoRoot
} else {
    $args = @(
        "build",
        "-f", $dockerfile,
        "-t", $fullImage,
        $repoRoot
    )
}

Write-Host "Building backend image: $fullImage"
Write-Host "Dockerfile: $dockerfile"

& docker @args
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed with exit code $LASTEXITCODE"
}

if ($Push -and -not $Platform.Trim()) {
    & docker push $fullImage
    if ($LASTEXITCODE -ne 0) {
        throw "docker push failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Done: $fullImage"
