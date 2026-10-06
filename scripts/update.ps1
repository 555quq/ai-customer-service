#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TargetRef = "",
    [switch]$SkipGit,
    [switch]$NoAutomaticRollback,
    [ValidateRange(30, 1800)][int]$HealthTimeoutSeconds = 420
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$rootEnv = Join-Path $projectRoot '.env'
$bridgeEnv = Join-Path $projectRoot 'bridge-service/.env'
Push-Location $projectRoot
try {
    Invoke-Native docker @('compose', 'config', '--quiet') | Out-Null
    $previousRef = (Invoke-Native git @('rev-parse', 'HEAD')).Output.Trim()
    if (-not $SkipGit) {
        if (-not $TargetRef) { throw 'TargetRef is required unless -SkipGit is used for a pre-unpacked release.' }
        $dirty = (Invoke-Native git @('status', '--porcelain')).Output
        if ($dirty) { throw 'The Git worktree must be clean before a versioned update.' }
    }

    if (-not $PSCmdlet.ShouldProcess($projectRoot, "update deployment to $(if ($TargetRef) { $TargetRef } else { 'current release files' })")) { return }

    Write-Host 'Creating mandatory pre-update backup...' -ForegroundColor Cyan
    $backupOutput = @(& (Join-Path $PSScriptRoot 'backup.ps1'))
    $backupPath = [string]($backupOutput | Where-Object { $_ -and (Test-Path -LiteralPath ([string]$_)) } | Select-Object -Last 1)
    if (-not $backupPath) { throw 'Pre-update backup did not return a valid archive path.' }

    $stateRoot = Join-Path $projectRoot "backups/update-state-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'docker-compose.yml') -Destination (Join-Path $stateRoot 'docker-compose.yml')
    foreach ($mapping in @(@{ source = '.env'; target = 'root.env' }, @{ source = 'bridge-service/.env'; target = 'bridge.env' })) {
        $source = Join-Path $projectRoot $mapping.source
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $stateRoot $mapping.target) }
    }
    $state = [ordered]@{
        schema_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        previous_ref = $previousRef
        target_ref = $TargetRef
        backup_path = $backupPath
        previous_images = @(Get-ComposeImages -ProjectRoot $projectRoot)
    }
    $statePath = Join-Path $stateRoot 'state.json'
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8

    try {
        if (-not $SkipGit) {
            Invoke-Native git @('fetch', '--tags', '--prune') | Out-Null
            Invoke-Native git @('rev-parse', '--verify', "${TargetRef}^{commit}") | Out-Null
            Invoke-Native git @('checkout', '--detach', $TargetRef) | Out-Null
        }
        if (-not (Test-Path -LiteralPath $rootEnv) -or -not (Test-Path -LiteralPath $bridgeEnv)) {
            throw 'Both .env and bridge-service/.env are required before update.'
        }
        $rootValues = Read-DotEnv $rootEnv
        $configEncryptionKey = [string]$rootValues.CONFIG_ENCRYPTION_KEY
        if ([string]::IsNullOrWhiteSpace($configEncryptionKey) -or $configEncryptionKey -match '(?i)replace_with|required_change_me|changeme|your_') {
            $configEncryptionKey = New-SecureHex -Bytes 32
            Set-DotEnvValue -Path $rootEnv -Name 'CONFIG_ENCRYPTION_KEY' -Value $configEncryptionKey
        }
        Set-DotEnvValue -Path $bridgeEnv -Name 'CONFIG_ENCRYPTION_KEY' -Value $configEncryptionKey
        Invoke-Native docker @('compose', 'config', '--quiet') | Out-Null
        Ensure-ExternalVolumes
        Invoke-Native docker @('compose', 'pull', '--ignore-buildable') | Out-Null
        Invoke-Native docker @('compose', 'build', '--pull', 'bridge', 'webhook-gateway', 'webhook-worker', 'admin', 'agent') | Out-Null
        Invoke-Native docker @('compose', 'up', '-d') | Out-Null
        Wait-ComposeHealthy -ProjectRoot $projectRoot -TimeoutSeconds $HealthTimeoutSeconds
        Write-Host "Update completed. State: $statePath" -ForegroundColor Green
    } catch {
        Write-Warning (Protect-OperationalText $_.Exception.Message)
        if (-not $NoAutomaticRollback) {
            Write-Host 'Update failed; starting automatic rollback...' -ForegroundColor Yellow
            & (Join-Path $PSScriptRoot 'rollback.ps1') -StatePath $statePath -Force -RestoreData -HealthTimeoutSeconds $HealthTimeoutSeconds
        }
        throw
    }
} finally { Pop-Location }
