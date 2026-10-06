#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateRange(1, 64)][int]$MinimumCpu = 4,
    [ValidateRange(1, 256)][int]$MinimumMemoryGB = 8,
    [ValidateRange(1, 2048)][int]$MinimumDiskGB = 20,
    [ValidateRange(30, 1800)][int]$HealthTimeoutSeconds = 420,
    [Security.SecureString]$AgentPassword,
    [switch]$SkipStart,
    [switch]$Production,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$rootEnv = Join-Path $projectRoot '.env'
$bridgeEnv = Join-Path $projectRoot 'bridge-service/.env'
$reportDirectory = Join-Path $projectRoot 'diagnostics'
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Preflight([string]$Name, [bool]$Ok, [string]$Detail) {
    $checks.Add([pscustomobject]@{ name = $Name; ok = $Ok; detail = $Detail })
    Write-Host ("[{0}] {1}: {2}" -f $(if ($Ok) { 'OK' } else { 'FAIL' }), $Name, $Detail) -ForegroundColor $(if ($Ok) { 'Green' } else { 'Red' })
}

$docker = Invoke-Native docker @('version', '--format', '{{.Server.Version}}') -AllowFailure
Add-Preflight 'docker' ($docker.ExitCode -eq 0) (Protect-OperationalText $docker.Output)
$compose = Invoke-Native docker @('compose', 'version', '--short') -AllowFailure
Add-Preflight 'docker-compose' ($compose.ExitCode -eq 0) $compose.Output

$capacity = Get-SystemCapacity -Path $projectRoot
Add-Preflight 'cpu' ($capacity.Cpu -ge $MinimumCpu) "$($capacity.Cpu) cores (minimum $MinimumCpu)"
Add-Preflight 'memory' ($capacity.MemoryGB -ge $MinimumMemoryGB) "$($capacity.MemoryGB) GB (minimum $MinimumMemoryGB GB)"
Add-Preflight 'disk' ($capacity.FreeDiskGB -ge $MinimumDiskGB) "$($capacity.FreeDiskGB) GB free (minimum $MinimumDiskGB GB)"

$templateValues = Read-DotEnv (Join-Path $projectRoot '.env.example')
$ports = @('ADMIN_PORT', 'AGENT_PORT', 'BRIDGE_PORT', 'CHATWOOT_PORT', 'QDRANT_PORT', 'POSTGRES_PORT', 'REDIS_PORT_EXTERNAL', 'PROMETHEUS_PORT', 'GRAFANA_PORT')
foreach ($name in $ports) {
    $port = [int]$templateValues[$name]
    Add-Preflight "port-$port" (Test-PortFree $port) "configured by $name"
}

if ($checks | Where-Object { -not $_.ok }) {
    throw 'Installation preflight failed. Resolve failed checks before continuing.'
}

if ($PSCmdlet.ShouldProcess($projectRoot, 'create production configuration')) {
    if (-not (Test-Path -LiteralPath $rootEnv)) { Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $rootEnv }
    if (-not (Test-Path -LiteralPath $bridgeEnv)) { Copy-Item -LiteralPath (Join-Path $projectRoot 'bridge-service/.env.example') -Destination $bridgeEnv }

    $rootValues = Read-DotEnv $rootEnv
    foreach ($entry in @{
        POSTGRES_PASSWORD = 32
        REDIS_PASSWORD = 32
        SECRET_KEY_BASE = 64
        SETUP_TOKEN = 32
        CONFIG_ENCRYPTION_KEY = 32
        CHATWOOT_ADAPTER_INGRESS_TOKEN = 32
        CHATWOOT_WEBHOOK_SECRET = 32
        GRAFANA_PASSWORD = 24
    }.GetEnumerator()) {
        $current = [string]$rootValues[$entry.Key]
        if ($Force -or [string]::IsNullOrWhiteSpace($current) -or $current -match '(?i)changeme|replace_with|your_secure|required_change_me|^admin$') {
            Set-DotEnvValue -Path $rootEnv -Name $entry.Key -Value (New-SecureHex -Bytes $entry.Value)
        }
    }

    $rootValues = Read-DotEnv $rootEnv
    Set-DotEnvValue -Path $bridgeEnv -Name 'ENVIRONMENT' -Value 'production'
    Set-DotEnvValue -Path $bridgeEnv -Name 'JWT_SECRET' -Value (New-SecureHex -Bytes 48)
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_HOST' -Value 'redis'
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_PORT' -Value '6379'
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_PASSWORD' -Value ([string]$rootValues.REDIS_PASSWORD)
    Set-DotEnvValue -Path $bridgeEnv -Name 'SETUP_TOKEN' -Value ([string]$rootValues.SETUP_TOKEN)
    Set-DotEnvValue -Path $bridgeEnv -Name 'CONFIG_ENCRYPTION_KEY' -Value ([string]$rootValues.CONFIG_ENCRYPTION_KEY)
    Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_WEBHOOK_SECRET' -Value ([string]$rootValues.CHATWOOT_WEBHOOK_SECRET)
    Set-DotEnvValue -Path $bridgeEnv -Name 'WEBHOOK_ALLOW_LEGACY_V1' -Value 'false'

    if ($Production) {
        $productionIssues = @(Test-ProductionIngressEnvironment $rootValues)
        if ($productionIssues.Count -gt 0) { throw ($productionIssues -join [Environment]::NewLine) }
        Set-DotEnvValue -Path $bridgeEnv -Name 'WIDGET_PUBLIC_BASE_URL' -Value ([string]$rootValues.WIDGET_PUBLIC_BASE_URL)
        Set-DotEnvValue -Path $bridgeEnv -Name 'WIDGET_HOST' -Value ([string]$rootValues.WIDGET_HOST)
        Set-DotEnvValue -Path $bridgeEnv -Name 'AUTH_COOKIE_SECURE' -Value 'true'
        Set-DotEnvValue -Path $bridgeEnv -Name 'AUTH_ALLOWED_ORIGINS' -Value "https://$($rootValues.ADMIN_HOST),https://$($rootValues.AGENT_HOST)"
        Set-DotEnvValue -Path $rootEnv -Name 'CHATWOOT_FRONTEND_URL' -Value "https://$($rootValues.CHATWOOT_HOST)"
    }

    $issues = Test-RequiredEnvironment (Read-DotEnv $rootEnv)
    if ($issues.Count -gt 0) { throw ($issues -join [Environment]::NewLine) }
    Ensure-ExternalVolumes -Production:$Production
}

Push-Location $projectRoot
try {
    $composeArgs = Get-ComposeFileArguments -Production:$Production
    Invoke-Native docker (@('compose') + $composeArgs + @('config', '--quiet')) | Out-Null
    if (-not $SkipStart -and $PSCmdlet.ShouldProcess('Docker Compose services', 'pull, build and start')) {
        Invoke-Native docker (@('compose') + $composeArgs + @('pull', '--ignore-buildable')) | Out-Null
        Invoke-Native docker (@('compose') + $composeArgs + @('build', '--pull', 'bridge', 'webhook-gateway', 'webhook-worker', 'admin', 'agent')) | Out-Null
        if ($null -eq $AgentPassword) {
            $AgentPassword = Read-Host 'Set the initial Bridge agent password' -AsSecureString
        }
        $credential = [Net.NetworkCredential]::new('', $AgentPassword)
        $plainAgentPassword = $credential.Password
        if ($plainAgentPassword.Length -lt 12) { throw 'Initial agent password must contain at least 12 characters.' }
        try {
            $env:AI_CS_INITIAL_AGENT_PASSWORD = $plainAgentPassword
            $hashResult = Invoke-Native docker @(
                'compose', 'run', '--rm', '--no-deps', '-e', 'AI_CS_INITIAL_AGENT_PASSWORD',
                'bridge', 'python', '-c',
                'import os; from argon2 import PasswordHasher; print(PasswordHasher().hash(os.environ["AI_CS_INITIAL_AGENT_PASSWORD"]))'
            )
            $agentHash = ($hashResult.Output -split "`r?`n" | Where-Object { $_ -match '^\$argon2' } | Select-Object -Last 1)
            if (-not $agentHash) { throw 'Unable to generate the initial agent password hash.' }
            Set-DotEnvValue -Path $bridgeEnv -Name 'AGENT_PASSWORD_HASH' -Value (ConvertTo-ComposeEnvValue $agentHash)
            Set-DotEnvValue -Path $bridgeEnv -Name 'AGENT_PASSWORD' -Value ''
        } finally {
            Remove-Item Env:AI_CS_INITIAL_AGENT_PASSWORD -ErrorAction SilentlyContinue
            $plainAgentPassword = $null
        }
        Invoke-Native docker (@('compose') + $composeArgs + @('up', '-d')) | Out-Null
        $healthyServices = @('postgres', 'redis', 'qdrant', 'chatwoot-web', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent')
        if ($Production) { $healthyServices += 'caddy' }
        Wait-ComposeHealthy -ProjectRoot $projectRoot -Services $healthyServices -TimeoutSeconds $HealthTimeoutSeconds
    }
} finally { Pop-Location }

if ($PSCmdlet.ShouldProcess($reportDirectory, 'write installation report')) {
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $reportPath = Join-Path $reportDirectory ("install-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $setupUrl = if ($Production) { "https://$($rootValues.ADMIN_HOST)/setup" } else { "http://localhost:$($templateValues.ADMIN_PORT)/setup" }
    [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        success = $true
        project_root = $projectRoot
        setup_url = $setupUrl
        checks = $checks
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Installation complete. Open $setupUrl" -ForegroundColor Green
    Write-Host "Report: $reportPath" -ForegroundColor Cyan
}
