#requires -Version 7.2
[CmdletBinding()]
param(
    [switch]$Quick,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
if (-not $ReportPath) {
    $ReportPath = Join-Path $projectRoot ("diagnostics/release-check-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$checks = [System.Collections.Generic.List[object]]::new()

function Add-ReleaseCheck([string]$Name, [scriptblock]$Action) {
    try {
        $detail = & $Action
        $checks.Add([pscustomobject]@{ name = $Name; status = 'passed'; detail = Protect-OperationalText ([string]$detail) })
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } catch {
        $checks.Add([pscustomobject]@{ name = $Name; status = 'failed'; detail = Protect-OperationalText $_.Exception.Message })
        Write-Host "[FAIL] $Name - $(Protect-OperationalText $_.Exception.Message)" -ForegroundColor Red
    }
}

Push-Location $projectRoot
try {
    Add-ReleaseCheck 'version-manifest' {
        $version = (Get-Content -Raw -LiteralPath 'VERSION').Trim()
        $manifest = Get-Content -Raw -LiteralPath 'release-manifest.json' | ConvertFrom-Json
        if ($version -ne $manifest.version) { throw "VERSION=$version but manifest=$($manifest.version)" }
        $environment = Read-DotEnv '.env.example'
        if ($version -ne [string]$environment.APP_VERSION) { throw "VERSION=$version but APP_VERSION=$($environment.APP_VERSION)" }
        if ((Get-Content -Raw 'bridge-service/src/main.py') -notmatch "version=`"$([regex]::Escape($version))`"") {
            throw 'FastAPI version does not match VERSION'
        }
        $cryptographyVersion = [string]$manifest.python_dependencies.cryptography
        if ((Get-Content -Raw 'bridge-service/requirements-runtime.txt') -notmatch "(?m)^cryptography==$([regex]::Escape($cryptographyVersion))$") {
            throw 'cryptography version does not match release manifest'
        }
        "version=$version"
    }

    Add-ReleaseCheck 'release-files' {
        $required = @(
            'docker-compose.yml', 'docker-compose.dify.yml', 'docker-compose.acceptance.yml', '.env.example',
            'docker-compose.production.yml', 'deploy/caddy/Caddyfile',
            'webhook-adapter/Dockerfile', 'webhook-adapter/Dockerfile.test',
            'webhook-adapter/Dockerfile.loadtest', 'webhook-adapter/loadtest/compose.yml',
            'webhook-adapter/loadtest/mock_bridge.py', 'webhook-adapter/loadtest/loadgen.py',
            'scripts/webhook-load-test.ps1',
            'scripts/webhook-real-ai-smoke.ps1',
            'scripts/acceptance-local.ps1',
            'scripts/acceptance-ingress-local.ps1',
            'prometheus/alerts.yml', 'grafana/dashboards/ai-customer-service.json',
            'docs/release/v1.0.0.md', 'docs/release/acceptance-checklist.md',
            'README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md',
            'docs/installation.md', 'docs/configuration.md', 'docs/widget-integration.md',
            'docs/operations.md', 'docs/security-hardening.md', 'docs/troubleshooting.md', 'docs/api.md'
        )
        $missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
        if ($missing) { throw "Missing: $($missing -join ', ')" }
        "required=$($required.Count)"
    }

    Add-ReleaseCheck 'grafana-dashboard-json' {
        $dashboardSource = Get-Content -Raw 'grafana/dashboards/ai-customer-service.json'
        $dashboard = $dashboardSource | ConvertFrom-Json
        if (-not $dashboard.uid -or @($dashboard.panels).Count -lt 6) { throw 'Dashboard is incomplete' }
        foreach ($metric in @(
            'webhook_adapter_inflight', 'webhook_adapter_active_conversations',
            'webhook_adapter_buffered_events', 'webhook_adapter_oldest_event_age_seconds',
            'webhook_adapter_queue_wait_seconds_bucket', 'webhook_adapter_delivery_duration_seconds_bucket'
        )) {
            if (-not $dashboardSource.Contains($metric)) { throw "Dashboard is missing $metric" }
        }
        "uid=$($dashboard.uid); panels=$(@($dashboard.panels).Count)"
    }

    Add-ReleaseCheck 'powershell-syntax' {
        $errors = [System.Collections.Generic.List[string]]::new()
        foreach ($file in Get-ChildItem scripts -Recurse -Filter '*.ps1') {
            $tokens = $null
            $parseErrors = $null
            [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
            foreach ($parseError in $parseErrors) { $errors.Add("$($file.Name): $($parseError.Message)") }
        }
        if ($errors.Count) { throw ($errors -join '; ') }
        'all scripts parsed'
    }

    Add-ReleaseCheck 'compose-standard' {
        $result = Invoke-Native docker @('compose', 'config', '--quiet') -AllowFailure
        if ($result.ExitCode -ne 0) { throw $result.Output }
        $images = Invoke-Native docker @('compose', 'config', '--images') -AllowFailure
        if ($images.ExitCode -ne 0) { throw $images.Output }
        if ($images.Output -match '(?m):latest$') { throw "Mutable latest image found: $($images.Output)" }
        $json = Invoke-Native docker @('compose', 'config', '--format', 'json') -AllowFailure
        if ($json.ExitCode -ne 0) { throw $json.Output }
        $resolved = $json.Output | ConvertFrom-Json
        foreach ($name in @('webhook-gateway', 'webhook-worker')) {
            $service = $resolved.services.$name
            if ($service.PSObject.Properties.Name -contains 'ports' -and @($service.ports).Count -gt 0) {
                throw "$name must not publish host ports"
            }
        }
        $workerEnvironment = $resolved.services.'webhook-worker'.environment
        $expectedWorkerConfig = @{
            WEBHOOK_ADAPTER_CONCURRENCY = 8
            WEBHOOK_ADAPTER_PREFETCH = 64
            WEBHOOK_ADAPTER_BUFFER_LIMIT = 256
            WEBHOOK_ADAPTER_SHUTDOWN_GRACE_SECONDS = 30
            WEBHOOK_ADAPTER_LEASE_TTL_SECONDS = 15
            WEBHOOK_ADAPTER_LEASE_RENEW_SECONDS = 5
        }
        foreach ($entry in $expectedWorkerConfig.GetEnumerator()) {
            if ([double]$workerEnvironment.($entry.Key) -ne [double]$entry.Value) {
                throw "Unexpected $($entry.Key): $($workerEnvironment.($entry.Key))"
            }
        }
        $redisCommand = @($resolved.services.redis.command) -join ' '
        if ($redisCommand -notmatch '--appendonly yes' -or $redisCommand -notmatch '--appendfsync always') {
            throw 'Redis AOF durability is not configured'
        }
        if ([string]$resolved.services.bridge.environment.WEBHOOK_ALLOW_LEGACY_V1 -ne 'false') {
            throw 'Bridge legacy webhook signature compatibility must be disabled'
        }
        'docker compose config valid; adapter is private; Redis AOF and Bridge v2 are enforced'
    }

    Add-ReleaseCheck 'compose-production-ingress' {
        $names = @('ADMIN_HOST', 'AGENT_HOST', 'WIDGET_HOST', 'CHATWOOT_HOST', 'ACME_EMAIL', 'ADMIN_ALLOWED_CIDRS', 'CADDY_IMAGE')
        $old = @{}
        try {
            foreach ($name in $names) { $old[$name] = [Environment]::GetEnvironmentVariable($name) }
            $env:ADMIN_HOST = 'admin.acme.test'
            $env:AGENT_HOST = 'agent.acme.test'
            $env:WIDGET_HOST = 'widget.acme.test'
            $env:CHATWOOT_HOST = 'chat.acme.test'
            $env:ACME_EMAIL = 'ops@acme.test'
            $env:ADMIN_ALLOWED_CIDRS = '127.0.0.1/32'
            $env:CADDY_IMAGE = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'
            $json = Invoke-Native docker @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.production.yml', 'config', '--format', 'json') -AllowFailure
            if ($json.ExitCode -ne 0) { throw $json.Output }
            $resolved = $json.Output | ConvertFrom-Json
            $caddyPorts = @($resolved.services.caddy.ports)
            if (@($caddyPorts | Where-Object { $_.host_ip -eq '0.0.0.0' -and $_.published -in @(80, 443) }).Count -lt 2) { throw 'Caddy does not publish public 80/443' }
            foreach ($service in $resolved.services.PSObject.Properties) {
                if ($service.Name -eq 'caddy') { continue }
                if ($service.Value.PSObject.Properties.Name -contains 'ports') {
                    foreach ($port in @($service.Value.ports)) {
                        if ($port.host_ip -ne '127.0.0.1') { throw "$($service.Name) publishes non-loopback host port $($port.published)" }
                    }
                }
            }
            if (@($resolved.services.caddy.networks.PSObject.Properties.Name) -contains 'internal') { throw 'Caddy must not join internal network' }
            if ([string]$resolved.services.caddy.image -notmatch '@sha256:[a-f0-9]{64}$') { throw 'Caddy image is not digest pinned' }
            'production overlay keeps internal ports loopback-only and Caddy is the public ingress'
        } finally {
            foreach ($name in $names) {
                if ($null -eq $old[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $old[$name] }
            }
        }
    }

    Add-ReleaseCheck 'webhook-loadtest-isolation' {
        $json = Invoke-Native docker @(
            'compose', '-f', 'webhook-adapter/loadtest/compose.yml', 'config', '--format', 'json'
        ) -AllowFailure
        if ($json.ExitCode -ne 0) { throw $json.Output }
        $resolved = $json.Output | ConvertFrom-Json
        foreach ($service in $resolved.services.PSObject.Properties) {
            if ($service.Value.PSObject.Properties.Name -contains 'ports' -and @($service.Value.ports).Count -gt 0) {
                throw "Load-test service $($service.Name) publishes host ports"
            }
        }
        $network = $resolved.networks.loadtest
        if (-not [bool]$network.internal) { throw 'Load-test network must be internal' }
        $wrapper = Get-Content -Raw -LiteralPath 'scripts/webhook-load-test.ps1'
        if ($wrapper -notmatch 'down.+--volumes.+--remove-orphans') {
            throw 'Load-test cleanup is not guarded by the fixed Compose project'
        }
        'load test has no host ports, uses an internal network, and removes its temporary volume'
    }

    Add-ReleaseCheck 'bridge-webhook-capacity-limit' {
        $source = Get-Content -Raw -LiteralPath 'bridge-service/src/main.py'
        if ($source -notmatch '@limiter\.limit\("180/minute"\)\s*#[^\r\n]*\r?\nasync def chatwoot_webhook') {
            throw 'Bridge Chatwoot webhook limit is not 180/minute'
        }
        'Chatwoot webhook limit=180/minute'
    }

    Add-ReleaseCheck 'compose-dify-profile' {
        $oldUrl = $env:DIFY_API_URL
        $oldKey = $env:DIFY_API_KEY
        try {
            $env:DIFY_API_URL = 'http://host.docker.internal:5001/v1'
            $env:DIFY_API_KEY = 'release-check-placeholder'
            $result = Invoke-Native docker @(
                'compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.dify.yml',
                '--profile', 'dify', 'config', '--quiet'
            ) -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
        } finally {
            if ($null -eq $oldUrl) { Remove-Item Env:DIFY_API_URL -ErrorAction SilentlyContinue } else { $env:DIFY_API_URL = $oldUrl }
            if ($null -eq $oldKey) { Remove-Item Env:DIFY_API_KEY -ErrorAction SilentlyContinue } else { $env:DIFY_API_KEY = $oldKey }
        }
        'Dify overlay and profile valid'
    }

    Add-ReleaseCheck 'compose-a0-isolation' {
        $oldVersion = $env:APP_VERSION
        try {
            $env:APP_VERSION = 'a1-release-check'
            $config = Invoke-Native docker @(
                'compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.acceptance.yml',
                '-p', 'ai-customer-service-a0', 'config'
            ) -AllowFailure
            if ($config.ExitCode -ne 0) { throw $config.Output }
            foreach ($required in @(
                'container_name: ai-customer-service-a0-bridge',
                'name: ai_a0_postgres_data',
                'name: ai-customer-service-a0-network'
            )) {
                if (-not $config.Output.Contains($required)) { throw "Missing A0 isolation marker: $required" }
            }
            foreach ($forbidden in @(
                'container_name: ai-customer-service-bridge',
                'name: ai_postgres_data',
                'name: ai-customer-service-network'
            )) {
                if ($config.Output.Contains($forbidden)) { throw "Old-stack target remains in A0 Compose: $forbidden" }
            }
            $images = Invoke-Native docker @(
                'compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.acceptance.yml',
                '-p', 'ai-customer-service-a0', 'config', '--images'
            ) -AllowFailure
            if ($images.ExitCode -ne 0) { throw $images.Output }
            if ($images.Output -match '(?m):latest$') { throw "Mutable latest image found: $($images.Output)" }
            $imageLines = @($images.Output -split "`r?`n" | Where-Object { $_ })
            foreach ($name in @('bridge', 'admin', 'agent')) {
                if ("ai-customer-service-${name}:a1-release-check" -notin $imageLines) {
                    throw "A0 does not select the candidate $name image"
                }
            }
            if ('ai-customer-service-webhook-adapter:a1-release-check' -notin $imageLines) {
                throw 'A0 does not select the candidate webhook adapter image'
            }
        } finally {
            if ($null -eq $oldVersion) { Remove-Item Env:APP_VERSION -ErrorAction SilentlyContinue } else { $env:APP_VERSION = $oldVersion }
        }
        'A0 containers, network, volumes, ports and images are isolated'
    }

    Add-ReleaseCheck 'prometheus-rules' {
        $values = Read-DotEnv '.env.example'
        $image = [string]$values.PROMETHEUS_IMAGE
        $root = [IO.Path]::GetFullPath($projectRoot)
        $result = Invoke-Native docker @(
            'run', '--rm', '--entrypoint', 'promtool',
            '-v', "${root}/prometheus/alerts.yml:/tmp/alerts.yml:ro",
            $image, 'check', 'rules', '/tmp/alerts.yml'
        ) -AllowFailure
        if ($result.ExitCode -ne 0) { throw $result.Output }
        $rules = Get-Content -Raw -LiteralPath 'prometheus/alerts.yml'
        foreach ($alert in @(
            'WebhookAdapterOldestEventStale', 'WebhookAdapterBufferNearCapacity',
            'WebhookAdapterLeaseLost', 'WebhookAdapterQueueWaitSlow'
        )) {
            if ($rules -notmatch "(?m)^\s*- alert: $alert$") { throw "Missing alert: $alert" }
        }
        'Prometheus alert rules valid'
    }

    Add-ReleaseCheck 'immutable-runtime-images' {
        $values = Read-DotEnv '.env.example'
        $required = @(
            'POSTGRES_IMAGE', 'REDIS_IMAGE', 'CHATWOOT_IMAGE', 'QDRANT_IMAGE',
            'PROMETHEUS_IMAGE', 'GRAFANA_IMAGE', 'NODE_IMAGE', 'NGINX_IMAGE', 'CADDY_IMAGE'
        )
        foreach ($name in $required) {
            $value = [string]$values[$name]
            if ($value -notmatch '@sha256:[a-f0-9]{64}$') { throw "$name is not digest pinned" }
        }
        'runtime images use sha256 digests'
    }

    if (-not $Quick) {
        Add-ReleaseCheck 'backend-tests' {
            $python = if (Test-Path 'bridge-service/venv/Scripts/python.exe') { 'bridge-service/venv/Scripts/python.exe' } else { 'python' }
            $result = Invoke-Native $python @('-m', 'pytest', 'bridge-service/tests', '-q') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            ($result.Output -split "`r?`n" | Select-Object -Last 1)
        }
        Add-ReleaseCheck 'webhook-adapter-tests' {
            $tag = 'ai-customer-service-webhook-adapter:release-test'
            $build = Invoke-Native docker @('build', '-f', 'webhook-adapter/Dockerfile.test', '-t', $tag, 'webhook-adapter') -AllowFailure
            if ($build.ExitCode -ne 0) { throw $build.Output }
            $result = Invoke-Native docker @('run', '--rm', $tag) -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            ($result.Output -split "`r?`n" | Select-Object -Last 1)
        }
        Add-ReleaseCheck 'webhook-concurrency-loadtest' {
            $result = Invoke-Native pwsh @('-NoProfile', '-File', './scripts/webhook-load-test.ps1') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            if ($result.Output -notmatch '"status":"passed"') { throw 'Load test did not emit a passing result' }
            'deterministic webhook concurrency gate passed'
        }
        Add-ReleaseCheck 'frontend-tests' {
            $result = Invoke-Native pnpm @('--dir', 'frontend', 'test', '--', '--run') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            'frontend tests passed'
        }
        Add-ReleaseCheck 'frontend-typecheck' {
            $result = Invoke-Native pnpm @('--dir', 'frontend', 'typecheck') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            'frontend typecheck passed'
        }
        Add-ReleaseCheck 'widget-bundle-browser-safe' {
            $result = Invoke-Native pnpm @('--dir', 'frontend', '--filter', '@ai-cs/widget', 'build') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            $bundlePath = 'frontend/apps/widget/dist/widget.js'
            if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) { throw 'Widget bundle was not created' }
            $bundle = Get-Content -Raw -LiteralPath $bundlePath
            if ($bundle -match '\bprocess\.env\b') { throw 'Widget bundle still references Node process.env' }
            if ($bundle -notmatch '(?m)^var\s+AICustomerService=') { throw 'Widget IIFE global is missing' }
            if ($bundle -notmatch '\.init=') { throw 'Widget public init alias is missing' }
            $nginxConfig = Get-Content -Raw -LiteralPath 'frontend/nginx-spa.conf'
            if ($nginxConfig -notmatch '(?m)^\s*proxy_read_timeout\s+300s;') {
                throw 'Frontend API proxy timeout is shorter than the model retry budget'
            }
            'widget bundle contains no Node-only process.env reference'
        }
        Add-ReleaseCheck 'operations-tests' {
            $command = "`$result = Invoke-Pester -Script @('./scripts/tests/Operations.Tests.ps1', './scripts/tests/AcceptanceLocal.Tests.ps1') -PassThru; if (`$result.FailedCount -gt 0) { exit 1 }"
            $result = Invoke-Native pwsh @('-NoProfile', '-Command', $command) -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
            'Pester operations tests passed'
        }
    }
} finally {
    Pop-Location
}

$report = [pscustomobject]@{
    schema_version = 1
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    version = (Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'VERSION')).Trim()
    quick = [bool]$Quick
    success = -not [bool]($checks | Where-Object status -eq 'failed')
    checks = $checks
}
$directory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Path $directory -Force | Out-Null
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Host "Report: $ReportPath" -ForegroundColor Cyan
if (-not $report.success) { exit 1 }
