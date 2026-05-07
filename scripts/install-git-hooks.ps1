$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
git -C $repoRoot config core.hooksPath .githooks

Write-Host "Git hooks installed: core.hooksPath=.githooks"
Write-Host "pre-push verifies generated API files are clean."
