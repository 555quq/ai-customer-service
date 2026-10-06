#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('Prepare', 'Start', 'Status', 'Stop', 'Destroy')]
    [string]$Action,
    [AllowEmptyString()]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$|^$')]
    [string]$CandidateVersion,
    [ValidateRange(60, 1800)][int]$HealthTimeoutSeconds = 600,
    [Security.SecureString]$ModelApiKey,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$a0Root = Join-Path $projectRoot 'diagnostics/a0'
$rootEnv = Join-Path $a0Root 'root.env'
$bridgeEnv = Join-Path $a0Root 'bridge.env'
$bridgeData = Join-Path $a0Root 'bridge-data'
$baselinePath = Join-Path $a0Root 'old-stack-baseline.json'
$accessPath = Join-Path $a0Root 'access.txt'
$baseCompose = Join-Path $projectRoot 'docker-compose.yml'
$acceptanceCompose = Join-Path $projectRoot 'docker-compose.acceptance.yml'
$projectName = 'ai-customer-service-a0'

$candidateVersion = $CandidateVersion
if ([string]::IsNullOrWhiteSpace($candidateVersion) -and (Test-Path -LiteralPath $rootEnv -PathType Leaf)) {
    $candidateVersion = [string](Read-DotEnv $rootEnv)['APP_VERSION']
}
if ([string]::IsNullOrWhiteSpace($candidateVersion)) {
    $candidateVersion = 'a1-9cfbc5c'
}

$a0Ports = [ordered]@{
    AGENT_PORT = 15174
    ADMIN_PORT = 15175
    BRIDGE_PORT = 18000
    CHATWOOT_PORT = 13000
    QDRANT_PORT = 16334
    POSTGRES_PORT = 25432
    REDIS_PORT_EXTERNAL = 26379
    PROMETHEUS_PORT = 19090
    GRAFANA_PORT = 13001
}
$a0Volumes = @(
    'ai_a0_postgres_data',
    'ai_a0_redis_data',
    'ai_a0_chatwoot_storage',
    'ai_a0_qdrant_data',
    'ai_a0_prometheus_data',
    'ai_a0_grafana_data'
)
$candidateImages = @(
    "ai-customer-service-bridge:$candidateVersion",
    "ai-customer-service-webhook-adapter:$candidateVersion",
    "ai-customer-service-admin:$candidateVersion",
    "ai-customer-service-agent:$candidateVersion"
)
$healthyServices = @('postgres', 'redis', 'qdrant', 'chatwoot-web', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent')

function Get-A0ComposeArguments {
    param([string[]]$Arguments = @())
    return @(
        'compose', '--env-file', $rootEnv,
        '-f', $baseCompose,
        '-f', $acceptanceCompose,
        '-p', $projectName
    ) + $Arguments
}

function Invoke-A0Compose {
    param([string[]]$Arguments = @(), [switch]$AllowFailure)
    return Invoke-Native docker (Get-A0ComposeArguments $Arguments) -AllowFailure:$AllowFailure
}

function Get-A0ContainerNames {
    $result = Invoke-Native docker @('ps', '-a', '--format', '{{.Names}}') -AllowFailure
    if ($result.ExitCode -ne 0) { return @() }
    return @($result.Output -split "`r?`n" | Where-Object { $_ -match '^ai-customer-service-a0-' })
}

function Get-OldStackSnapshot {
    $result = Invoke-Native docker @('ps', '-a', '--format', '{{.Names}}')
    $names = @($result.Output -split "`r?`n" | Where-Object {
        $_ -match '^ai-customer-service-' -and $_ -notmatch '^ai-customer-service-a0-'
    } | Sort-Object)
    $items = foreach ($name in $names) {
        $json = Invoke-Native docker @(
            'inspect', '--format',
            '{"id":{{json .Id}},"image":{{json .Image}},"status":{{json .State.Status}},"restart_count":{{.RestartCount}}}',
            $name
        )
        $details = $json.Output | ConvertFrom-Json
        [pscustomobject]@{
            name = $name
            id = [string]$details.id
            image = [string]$details.image
            status = [string]$details.status
            restart_count = [int]$details.restart_count
        }
    }
    return @($items)
}

function Save-OldStackBaseline {
    $snapshot = Get-OldStackSnapshot
    [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        containers = $snapshot
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $baselinePath -Encoding UTF8
}

function Assert-OldStackBaseline {
    if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) {
        throw 'A0 baseline is missing. Run Prepare first.'
    }
    $baseline = Get-Content -Raw -LiteralPath $baselinePath | ConvertFrom-Json
    foreach ($expected in @($baseline.containers)) {
        if ([string]$expected.name -match '^ai-customer-service-a0-') {
            throw "Invalid old-stack baseline entry: $($expected.name)"
        }
        $inspect = Invoke-Native docker @(
            'inspect', '--format', '{"id":{{json .Id}},"image":{{json .Image}}}', [string]$expected.name
        ) -AllowFailure
        if ($inspect.ExitCode -ne 0) { throw "Old-stack container is missing: $($expected.name)" }
        $actual = $inspect.Output | ConvertFrom-Json
        if ([string]$actual.id -ne [string]$expected.id -or [string]$actual.image -ne [string]$expected.image) {
            throw "Old-stack container changed during A0 work: $($expected.name)"
        }
    }
}

function Assert-A0TargetName {
    param([Parameter(Mandatory)][string]$Name, [ValidateSet('container', 'volume', 'network')][string]$Kind)
    $valid = switch ($Kind) {
        'container' { $Name -match '^ai-customer-service-a0-[a-z0-9-]+$' }
        'volume' { $Name -match '^ai_a0_[a-z0-9_]+$' }
        'network' { $Name -eq 'ai-customer-service-a0-network' }
    }
    if (-not $valid) { throw "Unsafe A0 $Kind target: $Name" }
}

function ConvertFrom-A0SecureString {
    param([Parameter(Mandatory)][Security.SecureString]$Value)
    return [Net.NetworkCredential]::new('', $Value).Password
}

function Set-A0Environment {
    New-Item -ItemType Directory -Path $a0Root -Force | Out-Null
    New-Item -ItemType Directory -Path $bridgeData -Force | Out-Null

    if (-not (Test-Path -LiteralPath $rootEnv -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $rootEnv
    }
    if (-not (Test-Path -LiteralPath $bridgeEnv -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot 'bridge-service/.env.example') -Destination $bridgeEnv
    }

    $rootValues = Read-DotEnv $rootEnv
    foreach ($entry in ([ordered]@{
        POSTGRES_PASSWORD = 32
        REDIS_PASSWORD = 32
        SECRET_KEY_BASE = 64
        SETUP_TOKEN = 32
        CONFIG_ENCRYPTION_KEY = 32
        CHATWOOT_ADAPTER_INGRESS_TOKEN = 32
        CHATWOOT_WEBHOOK_SECRET = 32
        GRAFANA_PASSWORD = 24
    }).GetEnumerator()) {
        $current = [string]$rootValues[$entry.Key]
        if ([string]::IsNullOrWhiteSpace($current) -or $current -match '(?i)changeme|replace_with|your_secure|required_change_me|^admin$') {
            Set-DotEnvValue -Path $rootEnv -Name $entry.Key -Value (New-SecureHex -Bytes $entry.Value)
        }
    }
    Set-DotEnvValue -Path $rootEnv -Name 'APP_VERSION' -Value $candidateVersion
    Set-DotEnvValue -Path $rootEnv -Name 'AI_PROVIDER' -Value 'local'
    Set-DotEnvValue -Path $rootEnv -Name 'CHATWOOT_FRONTEND_URL' -Value "http://localhost:$($a0Ports.CHATWOOT_PORT)"
    foreach ($entry in $a0Ports.GetEnumerator()) {
        Set-DotEnvValue -Path $rootEnv -Name $entry.Key -Value ([string]$entry.Value)
    }

    $rootValues = Read-DotEnv $rootEnv
    Set-DotEnvValue -Path $bridgeEnv -Name 'ENVIRONMENT' -Value 'production'
    Set-DotEnvValue -Path $bridgeEnv -Name 'AI_PROVIDER' -Value 'local'
    Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_BASE_URL' -Value 'http://chatwoot-web:3000'
    $bridgeValues = Read-DotEnv $bridgeEnv
    if ([string]$bridgeValues['CHATWOOT_API_TOKEN'] -match 'your_|example') {
        Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_API_TOKEN' -Value ''
    }
    if ([string]::IsNullOrWhiteSpace([string]$bridgeValues['CHATWOOT_ACCOUNT_ID'])) {
        Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_ACCOUNT_ID' -Value '1'
    }
    if ([string]::IsNullOrWhiteSpace([string]$bridgeValues['CHATWOOT_INBOX_ID'])) {
        Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_INBOX_ID' -Value '0'
    }
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_HOST' -Value 'redis'
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_PORT' -Value '6379'
    Set-DotEnvValue -Path $bridgeEnv -Name 'REDIS_PASSWORD' -Value ([string]$rootValues.REDIS_PASSWORD)
    if ([string]::IsNullOrWhiteSpace([string]$bridgeValues['JWT_SECRET']) -or [string]$bridgeValues['JWT_SECRET'] -match '(?i)replace_with|required_change_me|your_') {
        Set-DotEnvValue -Path $bridgeEnv -Name 'JWT_SECRET' -Value (New-SecureHex -Bytes 48)
    }
    Set-DotEnvValue -Path $bridgeEnv -Name 'SETUP_TOKEN' -Value ([string]$rootValues.SETUP_TOKEN)
    Set-DotEnvValue -Path $bridgeEnv -Name 'CONFIG_ENCRYPTION_KEY' -Value ([string]$rootValues.CONFIG_ENCRYPTION_KEY)
    Set-DotEnvValue -Path $bridgeEnv -Name 'CHATWOOT_WEBHOOK_SECRET' -Value ([string]$rootValues.CHATWOOT_WEBHOOK_SECRET)
    Set-DotEnvValue -Path $bridgeEnv -Name 'WEBHOOK_ALLOW_LEGACY_V1' -Value 'false'
    Set-DotEnvValue -Path $bridgeEnv -Name 'AUTH_COOKIE_SECURE' -Value 'false'
    Set-DotEnvValue -Path $bridgeEnv -Name 'HANDOFF_KEYWORDS' -Value '["人工","转人工","人工客服","联系客服","投诉","退款","售后","经理"]'
    Set-DotEnvValue -Path $bridgeEnv -Name 'AUTH_ALLOWED_ORIGINS' -Value (
        "http://localhost:$($a0Ports.AGENT_PORT),http://127.0.0.1:$($a0Ports.AGENT_PORT)," +
        "http://localhost:$($a0Ports.ADMIN_PORT),http://127.0.0.1:$($a0Ports.ADMIN_PORT)"
    )
    Set-DotEnvValue -Path $bridgeEnv -Name 'ADMIN_PASSWORD' -Value ''
    Set-DotEnvValue -Path $bridgeEnv -Name 'AGENT_PASSWORD' -Value ''

    $existingModel = Read-DotEnv (Join-Path $projectRoot 'bridge-service/.env')
    foreach ($name in @('AI_OPENAI_API_BASE', 'AI_OPENAI_MODEL', 'AI_EMBEDDING_MODEL', 'AI_EMBEDDING_CACHE_DIR', 'AI_EMBEDDING_DIMENSION')) {
        $value = [string]$existingModel[$name]
        if (-not [string]::IsNullOrWhiteSpace($value)) { Set-DotEnvValue -Path $bridgeEnv -Name $name -Value $value }
    }

    $bridgeValues = Read-DotEnv $bridgeEnv
    $currentModelKey = [string]$bridgeValues['AI_OPENAI_API_KEY']
    if ([string]::IsNullOrWhiteSpace($currentModelKey) -or $currentModelKey -match '(?i)your_|required_change_me|example|sk-your') {
        if ($null -eq $ModelApiKey) {
            $script:ModelApiKey = Read-Host 'Enter the A0 model API key' -AsSecureString
        }
        $plainModelKey = ConvertFrom-A0SecureString $script:ModelApiKey
        try {
            if ([string]::IsNullOrWhiteSpace($plainModelKey)) { throw 'A0 model API key cannot be empty.' }
            Set-DotEnvValue -Path $bridgeEnv -Name 'AI_OPENAI_API_KEY' -Value $plainModelKey
        } finally { $plainModelKey = $null }
    }

    $bridgeValues = Read-DotEnv $bridgeEnv
    $storedAgentHash = [string]$bridgeValues['AGENT_PASSWORD_HASH']
    if ($storedAgentHash.StartsWith('$argon2')) {
        Set-DotEnvValue -Path $bridgeEnv -Name 'AGENT_PASSWORD_HASH' -Value (ConvertTo-ComposeEnvValue $storedAgentHash)
        $bridgeValues = Read-DotEnv $bridgeEnv
    }
    if ([string]::IsNullOrWhiteSpace([string]$bridgeValues['AGENT_PASSWORD_HASH']) -or -not (Test-Path -LiteralPath $accessPath -PathType Leaf)) {
        $agentPassword = New-SecureHex -Bytes 16
        try {
            $env:AI_CS_A0_AGENT_PASSWORD = $agentPassword
            $hash = Invoke-Native docker @(
                'run', '--rm', '--network', 'none', '-e', 'AI_CS_A0_AGENT_PASSWORD',
                '--entrypoint', 'python', $candidateImages[0], '-c',
                'import os; from argon2 import PasswordHasher; print(PasswordHasher().hash(os.environ["AI_CS_A0_AGENT_PASSWORD"]))'
            )
            $agentHash = @($hash.Output -split "`r?`n" | Where-Object { $_ -match '^\$argon2' })[-1]
            if (-not $agentHash) { throw 'Unable to generate the A0 agent password hash.' }
            Set-DotEnvValue -Path $bridgeEnv -Name 'AGENT_PASSWORD_HASH' -Value (ConvertTo-ComposeEnvValue $agentHash)
            [IO.File]::WriteAllLines($accessPath, @(
                "SETUP_TOKEN=$($rootValues.SETUP_TOKEN)",
                'AGENT_USERNAME=agent',
                "AGENT_PASSWORD=$agentPassword"
            ), [Text.UTF8Encoding]::new($false))
        } finally {
            Remove-Item Env:AI_CS_A0_AGENT_PASSWORD -ErrorAction SilentlyContinue
            $agentPassword = $null
        }
    }
}

function Assert-A0Prerequisites {
    $docker = Invoke-Native docker @('version', '--format', '{{.Server.Version}}') -AllowFailure
    if ($docker.ExitCode -ne 0) { throw 'Docker Engine is unavailable.' }
    $compose = Invoke-Native docker @('compose', 'version', '--short') -AllowFailure
    if ($compose.ExitCode -ne 0) { throw 'Docker Compose is unavailable.' }
    if (-not (Test-Path -LiteralPath $acceptanceCompose -PathType Leaf)) { throw 'A0 Compose override is missing.' }

    $capacity = Get-SystemCapacity -Path $projectRoot
    if ($capacity.Cpu -lt 4) { throw "A0 requires at least 4 CPU cores; found $($capacity.Cpu)." }
    if ($capacity.MemoryGB -lt 8) { throw "A0 requires at least 8 GB host memory; found $($capacity.MemoryGB)." }
    if ($capacity.FreeDiskGB -lt 20) { throw "A0 requires at least 20 GB free disk; found $($capacity.FreeDiskGB)." }

    foreach ($image in $candidateImages) {
        $inspect = Invoke-Native docker @('image', 'inspect', $image) -AllowFailure
        if ($inspect.ExitCode -ne 0) { throw "A1 candidate image is missing: $image" }
    }
    if (@(Get-A0ContainerNames).Count -gt 0) { throw 'A0 containers already exist. Run Stop or Status before Prepare.' }
    foreach ($entry in $a0Ports.GetEnumerator()) {
        if (-not (Test-PortFree ([int]$entry.Value))) { throw "A0 port is already in use: $($entry.Key)=$($entry.Value)" }
    }
}

function Ensure-A0Volumes {
    foreach ($name in $a0Volumes) {
        Assert-A0TargetName -Name $name -Kind volume
        $inspect = Invoke-Native docker @('volume', 'inspect', $name) -AllowFailure
        if ($inspect.ExitCode -ne 0) { Invoke-Native docker @('volume', 'create', $name) | Out-Null }
    }
}

function Assert-A0ComposeConfig {
    $config = Invoke-A0Compose @('config')
    foreach ($forbidden in @(
        'container_name: ai-customer-service-postgres',
        'container_name: ai-customer-service-bridge',
        'name: ai_postgres_data',
        'name: ai-customer-service-network'
    )) {
        if ($config.Output.Contains($forbidden)) { throw "A0 Compose still contains an old-stack target: $forbidden" }
    }
    foreach ($required in @(
        'container_name: ai-customer-service-a0-postgres',
        'container_name: ai-customer-service-a0-bridge',
        'name: ai_a0_postgres_data',
        'name: ai-customer-service-a0-network'
    )) {
        if (-not $config.Output.Contains($required)) { throw "A0 Compose isolation is missing: $required" }
    }
    $images = Invoke-A0Compose @('config', '--images')
    if ($images.Output -match '(?m):latest$') { throw 'A0 Compose contains a mutable latest image.' }
    $imageLines = @($images.Output -split "`r?`n" | Where-Object { $_ })
    foreach ($image in $candidateImages) {
        if ($image -notin $imageLines) { throw "A0 candidate image is not selected: $image" }
    }
}

function Wait-A0Healthy {
    param([string[]]$Services)
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    do {
        $pending = [System.Collections.Generic.List[string]]::new()
        foreach ($service in $Services) {
            $id = Invoke-A0Compose @('ps', '-q', $service) -AllowFailure
            if ($id.ExitCode -ne 0 -or -not $id.Output.Trim()) { $pending.Add("${service}:missing"); continue }
            $state = Invoke-Native docker @(
                'inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
                $id.Output.Trim()
            ) -AllowFailure
            if ($state.ExitCode -ne 0 -or $state.Output.Trim() -notin @('healthy', 'running')) {
                $pending.Add("${service}:$($state.Output.Trim())")
            }
        }
        if ($pending.Count -eq 0) { return }
        Start-Sleep -Seconds 3
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "A0 services did not become healthy: $($pending -join ', ')"
}

function Write-A0Report {
    param([string]$Name, [bool]$Success, [string]$Detail)
    New-Item -ItemType Directory -Path $a0Root -Force | Out-Null
    $path = Join-Path $a0Root ("{0}-{1}.json" -f $Name, (Get-Date -Format 'yyyyMMdd-HHmmss'))
    [pscustomobject]@{
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        action = $Name
        success = $Success
        candidate_version = $candidateVersion
        project = $projectName
        detail = Protect-OperationalText $Detail
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding UTF8
    Write-Host "Report: $path" -ForegroundColor Cyan
}

Push-Location $projectRoot
try {
    switch ($Action) {
        'Prepare' {
            Assert-A0Prerequisites
            if ($PSCmdlet.ShouldProcess($a0Root, 'prepare isolated A0 configuration and volumes')) {
                New-Item -ItemType Directory -Path $a0Root -Force | Out-Null
                Save-OldStackBaseline
                Set-A0Environment
                Assert-A0ComposeConfig
                Ensure-A0Volumes
                Assert-OldStackBaseline
                Write-A0Report -Name 'prepare' -Success $true -Detail 'A0 configuration, baseline and volumes prepared.'
                Write-Host "A0 prepared. Credentials: $accessPath" -ForegroundColor Green
            }
        }
        'Start' {
            Assert-OldStackBaseline
            Assert-A0ComposeConfig
            if ($PSCmdlet.ShouldProcess($projectName, 'start isolated A0 services')) {
                Invoke-A0Compose @('up', '-d', 'postgres', 'redis', 'qdrant') | Out-Null
                Wait-A0Healthy @('postgres', 'redis', 'qdrant')
                Invoke-A0Compose @('up', '-d', 'chatwoot-web', 'chatwoot-worker') | Out-Null
                Wait-A0Healthy @('chatwoot-web')
                Invoke-A0Compose @('up', '-d', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent', 'prometheus', 'grafana') | Out-Null
                Wait-A0Healthy $healthyServices
                Assert-OldStackBaseline
                Write-A0Report -Name 'start' -Success $true -Detail 'All A0 core services are healthy.'
                Write-Host "A0 started. Admin: http://localhost:$($a0Ports.ADMIN_PORT)" -ForegroundColor Green
            }
        }
        'Status' {
            Assert-OldStackBaseline
            $status = Invoke-A0Compose @('ps', '--all') -AllowFailure
            Write-Host (Protect-OperationalText $status.Output)
            Assert-OldStackBaseline
        }
        'Stop' {
            Assert-OldStackBaseline
            if ($PSCmdlet.ShouldProcess($projectName, 'stop A0 containers and keep A0 volumes')) {
                Invoke-A0Compose @('down', '--remove-orphans') | Out-Null
                Assert-OldStackBaseline
                Write-A0Report -Name 'stop' -Success $true -Detail 'A0 containers stopped; A0 volumes retained.'
            }
        }
        'Destroy' {
            if (-not $Force) { throw 'Destroy requires -Force.' }
            Assert-OldStackBaseline
            if ($PSCmdlet.ShouldProcess($projectName, 'destroy only whitelisted A0 resources')) {
                Invoke-A0Compose @('down', '--remove-orphans') -AllowFailure | Out-Null
                foreach ($name in @(Get-A0ContainerNames)) {
                    Assert-A0TargetName -Name $name -Kind container
                    throw "A0 container remains after down; refusing volume cleanup: $name"
                }
                foreach ($name in $a0Volumes) {
                    Assert-A0TargetName -Name $name -Kind volume
                    $inspect = Invoke-Native docker @('volume', 'inspect', $name) -AllowFailure
                    if ($inspect.ExitCode -eq 0) { Invoke-Native docker @('volume', 'rm', $name) | Out-Null }
                }
                if (Test-Path -LiteralPath $bridgeData) {
                    $safeData = Get-SafeChildPath -Parent $a0Root -Child $bridgeData
                    Remove-Item -LiteralPath $safeData -Recurse -Force
                }
                Assert-OldStackBaseline
                Write-A0Report -Name 'destroy' -Success $true -Detail 'Whitelisted A0 containers, network, volumes and bridge data removed.'
            }
        }
    }
} catch {
    Write-A0Report -Name $Action.ToLowerInvariant() -Success $false -Detail $_.Exception.Message
    throw
} finally {
    Pop-Location
}
