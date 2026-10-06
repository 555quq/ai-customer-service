#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$StatePath,
    [switch]$Force,
    [switch]$RestoreData,
    [ValidateRange(30, 1800)][int]$HealthTimeoutSeconds = 420
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$resolvedState = [IO.Path]::GetFullPath($StatePath)
if (-not (Test-Path -LiteralPath $resolvedState -PathType Leaf)) { throw "Rollback state does not exist: $resolvedState" }
if (-not $Force -and -not $WhatIfPreference) { throw 'Rollback changes code and running data. Re-run with -Force.' }
$state = Get-Content -LiteralPath $resolvedState -Raw | ConvertFrom-Json
if ($state.schema_version -ne 1 -or -not $state.previous_ref) { throw 'Rollback state is invalid or incompatible' }
$stateRoot = Split-Path -Parent $resolvedState

if (-not $PSCmdlet.ShouldProcess($projectRoot, "rollback to $($state.previous_ref)")) { return }

Push-Location $projectRoot
try {
    Invoke-Native git @('rev-parse', '--verify', "$($state.previous_ref)^{commit}") | Out-Null
    Invoke-Native git @('checkout', '--detach', [string]$state.previous_ref) | Out-Null
    Copy-Item -LiteralPath (Join-Path $stateRoot 'docker-compose.yml') -Destination (Join-Path $projectRoot 'docker-compose.yml') -Force
    if (Test-Path -LiteralPath (Join-Path $stateRoot 'root.env')) { Copy-Item -LiteralPath (Join-Path $stateRoot 'root.env') -Destination (Join-Path $projectRoot '.env') -Force }
    if (Test-Path -LiteralPath (Join-Path $stateRoot 'bridge.env')) { Copy-Item -LiteralPath (Join-Path $stateRoot 'bridge.env') -Destination (Join-Path $projectRoot 'bridge-service/.env') -Force }

    if ($RestoreData) {
        & (Join-Path $PSScriptRoot 'restore.ps1') -BackupPath ([string]$state.backup_path) -Force -SkipSafetyBackup -HealthTimeoutSeconds $HealthTimeoutSeconds
    } else {
        Ensure-ExternalVolumes
        Invoke-Native docker @('compose', 'pull', '--ignore-buildable') | Out-Null
        Invoke-Native docker @('compose', 'build', 'bridge', 'webhook-gateway', 'webhook-worker', 'admin', 'agent') | Out-Null
        Invoke-Native docker @('compose', 'up', '-d') | Out-Null
        Wait-ComposeHealthy -ProjectRoot $projectRoot -TimeoutSeconds $HealthTimeoutSeconds
    }
    Write-Host "Rollback completed: $($state.previous_ref)" -ForegroundColor Green
} finally { Pop-Location }
