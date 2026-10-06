[CmdletBinding()]
param(
    [switch]$KeepArtifacts
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $projectRoot 'webhook-adapter/loadtest/compose.yml'
$projectName = 'ai-customer-service-p4b-loadtest'
$exitCode = 1

Push-Location $projectRoot
try {
    & docker compose --project-name $projectName --file $composePath up --build --abort-on-container-exit --exit-code-from loadgen
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        & docker compose --project-name $projectName --file $composePath logs --no-color
    }
} finally {
    if (-not $KeepArtifacts) {
        & docker compose --project-name $projectName --file $composePath down --volumes --remove-orphans
    }
    Pop-Location
}

exit $exitCode
