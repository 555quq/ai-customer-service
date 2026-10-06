#requires -Version 7.2
[CmdletBinding()]
param(
    [string]$BaseUrl = "",
    [string]$AdminUrl = "",
    [string]$AgentUrl = "",
    [string]$ReportPath = "",
    [string]$AdminAccessToken = "",
    [ValidateRange(1, 60)][int]$TimeoutSeconds = 8,
    [switch]$Production,
    [switch]$Json,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
$environment = Read-DotEnv (Join-Path $projectRoot '.env')
function Get-EnvironmentValue([string]$Name, [string]$Default) {
    if ($environment.Contains($Name) -and -not [string]::IsNullOrWhiteSpace([string]$environment[$Name])) { return [string]$environment[$Name] }
    return $Default
}
if (-not $BaseUrl) { $BaseUrl = "http://localhost:$(Get-EnvironmentValue 'BRIDGE_PORT' '8000')" }
if (-not $AdminUrl) { $AdminUrl = "http://localhost:$(Get-EnvironmentValue 'ADMIN_PORT' '5175')" }
if (-not $AgentUrl) { $AgentUrl = "http://localhost:$(Get-EnvironmentValue 'AGENT_PORT' '5174')" }
if ($Production) {
    if (-not $AdminUrl -or $AdminUrl -like 'http://localhost:*') { $AdminUrl = "https://$(Get-EnvironmentValue 'ADMIN_HOST' 'admin.example.invalid')" }
    if (-not $AgentUrl -or $AgentUrl -like 'http://localhost:*') { $AgentUrl = "https://$(Get-EnvironmentValue 'AGENT_HOST' 'agent.example.invalid')" }
    $widgetUrl = "https://$(Get-EnvironmentValue 'WIDGET_HOST' 'widget.example.invalid')"
    $chatwootUrl = "https://$(Get-EnvironmentValue 'CHATWOOT_HOST' 'chat.example.invalid')"
    $BaseUrl = "http://127.0.0.1:$(Get-EnvironmentValue 'BRIDGE_PORT' '8000')"
}
if (-not $AdminAccessToken) { $AdminAccessToken = [Environment]::GetEnvironmentVariable('AI_CS_DOCTOR_TOKEN') }
if (-not $ReportPath) { $ReportPath = Join-Path $projectRoot ("diagnostics/doctor-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) }

$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [string]$Status, [string]$Detail, [string]$Category = 'runtime') {
    $safeDetail = Protect-OperationalText $Detail
    $checks.Add([pscustomobject]@{ name = $Name; status = $Status; ok = $Status -ne 'failed'; category = $Category; detail = $safeDetail })
    if (-not $Quiet) {
        $color = @{ passed = 'Green'; warning = 'Yellow'; failed = 'Red' }[$Status]
        Write-Host ("[{0}] {1}: {2}" -f $Status.ToUpperInvariant(), $Name, $safeDetail) -ForegroundColor $color
    }
}

function Test-HttpEndpoint([string]$Name, [string]$Uri, [string]$Category = 'http') {
    try {
        $response = Invoke-WebRequest -Uri $Uri -TimeoutSec $TimeoutSeconds -UseBasicParsing
        Add-Check $Name $(if ($response.StatusCode -eq 200) { 'passed' } else { 'failed' }) "HTTP $($response.StatusCode)" $Category
    } catch { Add-Check $Name 'failed' $_.Exception.Message $Category }
}

$docker = Invoke-Native docker @('version', '--format', '{{.Server.Version}}') -AllowFailure
Add-Check 'docker' $(if ($docker.ExitCode -eq 0) { 'passed' } else { 'failed' }) $docker.Output 'host'

if ($Production) {
    $productionIssues = @(Test-ProductionIngressEnvironment $environment)
    Add-Check 'production-ingress-environment' $(if ($productionIssues.Count -eq 0) { 'passed' } else { 'failed' }) $(if ($productionIssues.Count -eq 0) { 'four hosts, CIDR allowlist, HTTPS origin and pinned Caddy image are valid' } else { $productionIssues -join '; ' }) 'security'
}

Push-Location $projectRoot
try {
    $composeArgs = Get-ComposeFileArguments -Production:$Production
    $compose = Invoke-Native docker (@('compose') + $composeArgs + @('config', '--quiet')) -AllowFailure
    Add-Check 'compose-config' $(if ($compose.ExitCode -eq 0) { 'passed' } else { 'failed' }) $(if ($compose.ExitCode -eq 0) { 'configuration valid' } else { $compose.Output }) 'host'

    $services = @('postgres', 'redis', 'qdrant', 'chatwoot-web', 'chatwoot-worker', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent', 'prometheus', 'grafana')
    if ($Production) { $services += 'caddy' }
    foreach ($service in $services) {
        $id = Invoke-Native docker @('compose', 'ps', '-q', $service) -AllowFailure
        if ($id.ExitCode -ne 0 -or -not $id.Output.Trim()) {
            Add-Check "container-$service" 'failed' 'container is missing' 'container'
            continue
        }
        $state = Invoke-Native docker @('inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}', $id.Output.Trim()) -AllowFailure
        $parts = $state.Output.Trim() -split '\|', 2
        $healthy = $state.ExitCode -eq 0 -and $parts[0] -in @('healthy', 'running')
        Add-Check "container-$service" $(if ($healthy) { 'passed' } else { 'failed' }) "state=$($parts[0]); restarts=$(if ($parts.Count -gt 1) { $parts[1] } else { '?' })" 'container'
    }

    $postgres = Invoke-Native docker @('compose', 'exec', '-T', 'postgres', 'pg_isready', '-U', 'postgres') -AllowFailure
    Add-Check 'postgres' $(if ($postgres.ExitCode -eq 0) { 'passed' } else { 'failed' }) $postgres.Output 'data'
    $redisPassword = Get-EnvironmentValue 'REDIS_PASSWORD' ''
    $redis = Invoke-Native docker @('compose', 'exec', '-T', 'redis', 'redis-cli', '--no-auth-warning', '-a', $redisPassword, 'ping') -AllowFailure
    Add-Check 'redis' $(if ($redis.ExitCode -eq 0 -and $redis.Output -match 'PONG') { 'passed' } else { 'failed' }) $redis.Output 'data'
    $redisAof = Invoke-Native docker @('compose', 'exec', '-T', 'redis', 'redis-cli', '--no-auth-warning', '-a', $redisPassword, 'CONFIG', 'GET', 'appendonly', 'appendfsync') -AllowFailure
    $aofLines = @($redisAof.Output -split "`r?`n")
    $aofReady = $redisAof.ExitCode -eq 0 -and 'yes' -in $aofLines -and 'always' -in $aofLines
    Add-Check 'redis-aof' $(if ($aofReady) { 'passed' } else { 'failed' }) $(if ($aofReady) { 'appendonly=yes; appendfsync=always' } else { $redisAof.Output }) 'data'
    $workerHeartbeat = Invoke-Native docker @('compose', 'exec', '-T', 'redis', 'redis-cli', '--no-auth-warning', '-a', $redisPassword, 'GET', 'ai:webhook-adapter:worker-heartbeat') -AllowFailure
    $heartbeatReady = $workerHeartbeat.ExitCode -eq 0 -and $workerHeartbeat.Output.Trim() -match '^\d{10,}$'
    $heartbeatAge = if ($heartbeatReady) { [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$workerHeartbeat.Output.Trim() } else { -1 }
    $heartbeatFresh = $heartbeatReady -and $heartbeatAge -ge 0 -and $heartbeatAge -le 15
    Add-Check 'webhook-worker-heartbeat' $(if ($heartbeatFresh) { 'passed' } else { 'failed' }) $(if ($heartbeatReady) { "age=${heartbeatAge}s" } else { 'heartbeat missing' }) 'integration'
    $workerLease = Invoke-Native docker @('compose', 'exec', '-T', 'redis', 'redis-cli', '--no-auth-warning', '-a', $redisPassword, 'PTTL', 'ai:webhook-adapter:worker-lease') -AllowFailure
    $leaseTtl = if ($workerLease.ExitCode -eq 0 -and $workerLease.Output.Trim() -match '^-?\d+$') { [int64]$workerLease.Output.Trim() } else { -2 }
    Add-Check 'webhook-worker-lease' $(if ($leaseTtl -gt 0) { 'passed' } else { 'failed' }) "ttl_ms=$leaseTtl" 'integration'
    $workerMetrics = Invoke-Native docker @(
        'compose', 'exec', '-T', 'webhook-worker', 'python', '-c',
        'import urllib.request; print(urllib.request.urlopen(''http://127.0.0.1:9101'', timeout=3).read().decode())'
    ) -AllowFailure
    $bufferMatch = [regex]::Match($workerMetrics.Output, '(?m)^webhook_adapter_buffered_events\s+([0-9.eE+-]+)\r?$')
    $oldestMatch = [regex]::Match($workerMetrics.Output, '(?m)^webhook_adapter_oldest_event_age_seconds\s+([0-9.eE+-]+)\r?$')
    if ($workerMetrics.ExitCode -eq 0 -and $bufferMatch.Success -and $oldestMatch.Success) {
        $buffered = [double]$bufferMatch.Groups[1].Value
        $bufferLimit = [double](Get-EnvironmentValue 'WEBHOOK_ADAPTER_BUFFER_LIMIT' '256')
        $oldest = [double]$oldestMatch.Groups[1].Value
        $bufferStatus = if ($buffered -ge $bufferLimit) { 'failed' } elseif ($buffered -ge ($bufferLimit * 0.8)) { 'warning' } else { 'passed' }
        Add-Check 'webhook-worker-buffer' $bufferStatus "buffered=$buffered; limit=$bufferLimit" 'integration'
        Add-Check 'webhook-worker-oldest-event' $(if ($oldest -gt 900) { 'failed' } elseif ($oldest -gt 300) { 'warning' } else { 'passed' }) "age_seconds=$oldest" 'integration'
    } else {
        Add-Check 'webhook-worker-metrics' 'failed' 'concurrency metrics unavailable' 'integration'
    }
    $bridgeWebhook = Invoke-Native docker @('compose', 'exec', '-T', 'bridge', 'python', '-c', 'import os; print(f"legacy={os.getenv(''WEBHOOK_ALLOW_LEGACY_V1'','''').lower()};secret={bool(os.getenv(''CHATWOOT_WEBHOOK_SECRET''))}")') -AllowFailure
    $bridgeWebhookReady = $bridgeWebhook.ExitCode -eq 0 -and $bridgeWebhook.Output -match 'legacy=false;secret=True'
    Add-Check 'bridge-webhook-v2' $(if ($bridgeWebhookReady) { 'passed' } else { 'failed' }) $(if ($bridgeWebhookReady) { 'legacy=false; secret configured' } else { 'v2 production configuration missing' }) 'security'
} catch {
    Add-Check 'compose-runtime' 'failed' $_.Exception.Message 'container'
} finally { Pop-Location }

Test-HttpEndpoint 'bridge-health' ($BaseUrl.TrimEnd('/') + '/health')
Test-HttpEndpoint 'bridge-metrics' ($BaseUrl.TrimEnd('/') + '/metrics/')
Test-HttpEndpoint 'qdrant' "http://localhost:$(Get-EnvironmentValue 'QDRANT_PORT' '6333')/healthz" 'data'
Test-HttpEndpoint 'chatwoot' $(if ($Production) { $chatwootUrl } else { "http://localhost:$(Get-EnvironmentValue 'CHATWOOT_PORT' '3000')" }) 'integration'
Test-HttpEndpoint 'admin' $AdminUrl 'frontend'
Test-HttpEndpoint 'agent' $AgentUrl 'frontend'
Test-HttpEndpoint 'widget-asset' $(if ($Production) { $widgetUrl.TrimEnd('/') + '/assets/widget.js' } else { $AdminUrl.TrimEnd('/') + '/assets/widget.js' }) 'widget'
Test-HttpEndpoint 'prometheus' "http://localhost:$(Get-EnvironmentValue 'PROMETHEUS_PORT' '9090')/-/healthy" 'monitoring'
Test-HttpEndpoint 'grafana' "http://localhost:$(Get-EnvironmentValue 'GRAFANA_PORT' '3001')/api/health" 'monitoring'

try {
    $origin = $AdminUrl.TrimEnd('/')
    $response = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/api/widget/session') -Method Options -Headers @{
        Origin = $origin
        'Access-Control-Request-Method' = 'POST'
        'Access-Control-Request-Headers' = 'content-type,x-site-token'
    } -TimeoutSec $TimeoutSeconds -UseBasicParsing
    $allowed = [string]$response.Headers['Access-Control-Allow-Origin']
    Add-Check 'cors' $(if ($response.StatusCode -in 200, 204 -and $allowed -eq $origin) { 'passed' } else { 'failed' }) "status=$($response.StatusCode); origin=$origin; allow-origin=$allowed" 'security'
} catch { Add-Check 'cors' 'failed' $_.Exception.Message 'security' }

$aiProvider = Get-EnvironmentValue 'AI_PROVIDER' 'local'
if ($aiProvider -eq 'local' -and $AdminAccessToken) {
    try {
        $response = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + '/api/ai/health') -Headers @{ Authorization = "Bearer $AdminAccessToken" } -TimeoutSec $TimeoutSeconds
        Add-Check 'ai-engine' $(if ($response.status -eq 'healthy') { 'passed' } else { 'failed' }) "status=$($response.status); vectorDB=$($response.vectorDB); llm=$($response.llm)" 'integration'
    } catch { Add-Check 'ai-engine' 'failed' $_.Exception.Message 'integration' }
} elseif ($aiProvider -eq 'local') {
    Add-Check 'ai-engine' 'warning' 'set AI_CS_DOCTOR_TOKEN to run the authenticated AI/Qdrant configuration check' 'integration'
} else {
    Add-Check 'ai-engine' 'passed' "provider=$aiProvider; availability is included in bridge-health dependencies" 'integration'
}

$capacity = Get-SystemCapacity -Path $projectRoot
Add-Check 'disk-space' $(if ($capacity.FreeDiskGB -ge 10) { 'passed' } elseif ($capacity.FreeDiskGB -ge 5) { 'warning' } else { 'failed' }) "$($capacity.FreeDiskGB) GB free" 'host'
$latestBackup = Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backups') -File -Filter '*.zip' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestBackup) {
    $ageHours = [math]::Round(((Get-Date) - $latestBackup.LastWriteTime).TotalHours, 1)
    Add-Check 'recent-backup' $(if ($ageHours -le 48) { 'passed' } else { 'warning' }) "$($latestBackup.Name); age=$ageHours hours" 'backup'
} else { Add-Check 'recent-backup' 'warning' 'no backup archive found' 'backup' }

$report = [pscustomobject]@{
    schema_version = 1
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    project_root = $projectRoot
    success = -not [bool]($checks | Where-Object { $_.status -eq 'failed' })
    warning_count = @($checks | Where-Object { $_.status -eq 'warning' }).Count
    failure_count = @($checks | Where-Object { $_.status -eq 'failed' }).Count
    checks = $checks
}
$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$reportJson = $report | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), $reportJson, [Text.UTF8Encoding]::new($false))
if ($Json) { Write-Output $reportJson }
elseif (-not $Quiet) { Write-Host "Report: $ReportPath" -ForegroundColor Cyan }
if (-not $report.success) { exit 1 }
