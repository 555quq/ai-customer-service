#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$OutputDirectory = "",
    [switch]$KeepStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'backups' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stagingParent = Join-Path ([IO.Path]::GetTempPath()) 'ai-customer-service-backup'
$staging = Get-SafeChildPath -Parent $stagingParent -Child (Join-Path $stagingParent $timestamp)
$payload = Join-Path $staging 'payload'
$archivePath = Join-Path $outputRoot "ai-customer-service-backup-$timestamp.zip"

if (-not $PSCmdlet.ShouldProcess($archivePath, 'create full system backup')) { return }

New-Item -ItemType Directory -Path $payload -Force | Out-Null
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$rootEnv = Read-DotEnv (Join-Path $projectRoot '.env')
$helperImage = if ($rootEnv.Contains('POSTGRES_IMAGE')) { [string]$rootEnv['POSTGRES_IMAGE'] } else { '' }
if ([string]::IsNullOrWhiteSpace($helperImage)) {
    $helperImage = 'postgres:14.23-alpine@sha256:f1341c01408dc7278e9d365ed4f860cd3f87dd16b4464ac326fc0f422083a579'
}

Push-Location $projectRoot
try {
    Invoke-Native docker @('compose', 'config', '--quiet') | Out-Null
    $postgresId = (Invoke-Native docker @('compose', 'ps', '-q', 'postgres')).Output.Trim()
    if (-not $postgresId) { throw 'PostgreSQL service is not running' }

    $databaseDirectory = Join-Path $payload 'database'
    New-Item -ItemType Directory -Path $databaseDirectory -Force | Out-Null
    $containerDump = "/tmp/chatwoot-$timestamp.dump"
    Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'pg_dump', '-U', 'postgres', '-d', 'chatwoot', '-Fc', '-f', $containerDump) | Out-Null
    Invoke-Native docker @('cp', "${postgresId}:$containerDump", (Join-Path $databaseDirectory 'chatwoot.dump')) | Out-Null
    Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'rm', '-f', $containerDump) | Out-Null

    $runningResult = Invoke-Native docker @('compose', 'ps', '--status', 'running', '--services')
    $runningServices = @($runningResult.Output -split "`r?`n" | Where-Object { $_ })
    $consistentServices = @(Get-BackupConsistencyServices | Where-Object { $_ -in $runningServices })
    if ($consistentServices.Count -gt 0) { Invoke-Native docker (@('compose', 'stop') + $consistentServices) | Out-Null }
    try {
        $volumeDirectory = Join-Path $payload 'volumes'
        foreach ($volume in @('ai_redis_data', 'ai_chatwoot_storage', 'ai_qdrant_data')) {
            Export-DockerVolume -Volume $volume -DestinationDirectory $volumeDirectory -HelperImage $helperImage
        }
    } finally {
        if ($consistentServices.Count -gt 0) { Invoke-Native docker (@('compose', 'up', '-d') + $consistentServices) | Out-Null }
    }

    $configDirectory = Join-Path $payload 'config'
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    foreach ($mapping in @(
        @{ source = '.env'; target = 'root.env' },
        @{ source = 'bridge-service/.env'; target = 'bridge.env' },
        @{ source = 'docker-compose.yml'; target = 'docker-compose.yml' },
        @{ source = '.env.example'; target = 'env.example' }
    )) {
        $source = Join-Path $projectRoot $mapping.source
        if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination (Join-Path $configDirectory $mapping.target) }
    }
    $bridgeData = Join-Path $projectRoot 'bridge-service/data'
    $bridgeCopy = Copy-BridgeBackupData -Source $bridgeData -Destination (Join-Path $payload 'bridge-data')

    $git = Invoke-Native git @('rev-parse', 'HEAD') -AllowFailure
    $manifest = [ordered]@{
        schema_version = 1
        product = 'ai-customer-service'
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        git_commit = $(if ($git.ExitCode -eq 0) { $git.Output.Trim() } else { $null })
        compose_project = 'ai-customer-service'
        images = @(Get-ComposeImages -ProjectRoot $projectRoot)
        volumes = @('ai_redis_data', 'ai_chatwoot_storage', 'ai_qdrant_data')
        database = 'database/chatwoot.dump'
        excluded_cache_paths = @($bridgeCopy.ExcludedPaths)
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $staging 'manifest.json') -Encoding UTF8
    New-ChecksumManifest -Root $staging
    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $archivePath -CompressionLevel Optimal -Force
    if ((Get-Item -LiteralPath $archivePath).Length -le 0) { throw 'Backup archive is empty' }
    Write-Host "Backup complete: $archivePath" -ForegroundColor Green
    Write-Output $archivePath
} finally {
    Pop-Location
    if (-not $KeepStaging -and (Test-Path -LiteralPath $staging)) {
        $validated = Get-SafeChildPath -Parent $stagingParent -Child $staging
        Remove-Item -LiteralPath $validated -Recurse -Force
    }
}
