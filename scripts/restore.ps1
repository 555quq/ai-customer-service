#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$BackupPath,
    [switch]$Force,
    [switch]$SkipSafetyBackup,
    [switch]$SkipHealthCheck,
    [ValidateRange(30, 1800)][int]$HealthTimeoutSeconds = 420
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$requestedWhatIf = $WhatIfPreference
$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)
if (-not (Test-Path -LiteralPath $resolvedBackup)) { throw "Backup does not exist: $resolvedBackup" }
if (-not $Force -and -not $requestedWhatIf) { throw 'Restore overwrites live data. Re-run with -Force after verifying the backup path.' }

$restoreParent = Join-Path ([IO.Path]::GetTempPath()) 'ai-customer-service-restore'
$restoreRoot = Get-SafeChildPath -Parent $restoreParent -Child (Join-Path $restoreParent ([guid]::NewGuid().ToString('N')))
$WhatIfPreference = $false
New-Item -ItemType Directory -Path $restoreRoot -Force | Out-Null

try {
    if ((Get-Item -LiteralPath $resolvedBackup).PSIsContainer) {
        Copy-Item -Path (Join-Path $resolvedBackup '*') -Destination $restoreRoot -Recurse
    } else {
        if ([IO.Path]::GetExtension($resolvedBackup) -ne '.zip') { throw 'Backup must be a directory or .zip archive' }
        Expand-Archive -LiteralPath $resolvedBackup -DestinationPath $restoreRoot -Force
    }

    Test-ChecksumManifest -Root $restoreRoot | Out-Null
    $manifestPath = Join-Path $restoreRoot 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.product -ne 'ai-customer-service') {
        throw 'Backup manifest is incompatible with this product version'
    }
    $capacity = Get-SystemCapacity -Path $projectRoot
    $backupSize = (Get-ChildItem -LiteralPath $restoreRoot -Recurse -File | Measure-Object Length -Sum).Sum
    if ($capacity.FreeDiskGB * 1GB -lt $backupSize * 2) { throw 'Insufficient free disk space for restore staging' }

    Write-Host "Backup verified: $($manifest.created_at), commit $($manifest.git_commit)" -ForegroundColor Green
    $WhatIfPreference = $requestedWhatIf
    if (-not $PSCmdlet.ShouldProcess($projectRoot, "restore backup $resolvedBackup")) { return }

    if (-not $SkipSafetyBackup) {
        Write-Host 'Creating safety backup of the current instance...' -ForegroundColor Cyan
        & (Join-Path $PSScriptRoot 'backup.ps1') | Out-Null
    }

    $backedRootEnv = Join-Path $restoreRoot 'payload/config/root.env'
    $backedBridgeEnv = Join-Path $restoreRoot 'payload/config/bridge.env'
    $backedCompose = Join-Path $restoreRoot 'payload/config/docker-compose.yml'
    foreach ($required in @($backedRootEnv, $backedBridgeEnv, $backedCompose, (Join-Path $restoreRoot 'payload/database/chatwoot.dump'))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required backup payload is missing: $required" }
    }
    $helperImage = [string](Read-DotEnv $backedRootEnv).POSTGRES_IMAGE
    if ([string]::IsNullOrWhiteSpace($helperImage)) { throw 'POSTGRES_IMAGE is missing from backup configuration' }

    Push-Location $projectRoot
    try {
        Invoke-Native docker @('compose', 'down', '--remove-orphans') | Out-Null
        Ensure-ExternalVolumes
        foreach ($volume in @('ai_redis_data', 'ai_chatwoot_storage', 'ai_qdrant_data')) {
            Import-DockerVolume -Volume $volume -ArchiveDirectory (Join-Path $restoreRoot 'payload/volumes') -HelperImage $helperImage
        }

        Copy-Item -LiteralPath $backedRootEnv -Destination (Join-Path $projectRoot '.env') -Force
        Copy-Item -LiteralPath $backedBridgeEnv -Destination (Join-Path $projectRoot 'bridge-service/.env') -Force
        Copy-Item -LiteralPath $backedCompose -Destination (Join-Path $projectRoot 'docker-compose.yml') -Force

        $restoredBridgeData = Join-Path $restoreRoot 'payload/bridge-data'
        if (Test-Path -LiteralPath $restoredBridgeData -PathType Container) {
            $bridgeParent = Join-Path $projectRoot 'bridge-service'
            $targetData = Get-SafeChildPath -Parent $bridgeParent -Child (Join-Path $bridgeParent 'data')
            if (Test-Path -LiteralPath $targetData) {
                $safetyData = Join-Path $projectRoot "backups/pre-restore-bridge-data-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
                Move-Item -LiteralPath $targetData -Destination $safetyData
            }
            Copy-Item -LiteralPath $restoredBridgeData -Destination $targetData -Recurse
        }

        Invoke-Native docker @('compose', 'up', '-d', 'postgres') | Out-Null
        Wait-ComposeHealthy -ProjectRoot $projectRoot -Services @('postgres') -TimeoutSeconds 120
        $postgresId = (Invoke-Native docker @('compose', 'ps', '-q', 'postgres')).Output.Trim()
        $containerDump = '/tmp/chatwoot-restore.dump'
        Invoke-Native docker @('cp', (Join-Path $restoreRoot 'payload/database/chatwoot.dump'), "${postgresId}:$containerDump") | Out-Null
        Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'psql', '-U', 'postgres', '-d', 'postgres', '-c', "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='chatwoot' AND pid <> pg_backend_pid();") | Out-Null
        Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'dropdb', '-U', 'postgres', '--if-exists', 'chatwoot') | Out-Null
        Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'createdb', '-U', 'postgres', 'chatwoot') | Out-Null
        Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'pg_restore', '-U', 'postgres', '-d', 'chatwoot', '--no-owner', $containerDump) | Out-Null
        Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'rm', '-f', $containerDump) | Out-Null

        Invoke-Native docker @('compose', 'up', '-d', '--build') | Out-Null
        if (-not $SkipHealthCheck) { Wait-ComposeHealthy -ProjectRoot $projectRoot -TimeoutSeconds $HealthTimeoutSeconds }
    } finally { Pop-Location }

    Write-Host 'Restore completed successfully.' -ForegroundColor Green
} finally {
    $WhatIfPreference = $false
    if (Test-Path -LiteralPath $restoreRoot) {
        $validated = Get-SafeChildPath -Parent $restoreParent -Child $restoreRoot
        Remove-Item -LiteralPath $validated -Recurse -Force
    }
    $WhatIfPreference = $requestedWhatIf
}
