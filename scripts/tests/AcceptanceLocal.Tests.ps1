#requires -Version 7.2

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$composePath = Join-Path $projectRoot 'docker-compose.acceptance.yml'
$scriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'acceptance-local.ps1'

Describe 'A0 acceptance isolation' {
    It 'uses only A0 container, network and volume names' {
        $content = Get-Content -Raw -LiteralPath $composePath
        foreach ($service in @(
            'postgres', 'redis', 'chatwoot-web', 'chatwoot-prepare', 'chatwoot-worker',
            'qdrant', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent', 'prometheus', 'grafana'
        )) {
            $content | Should Match "container_name: ai-customer-service-a0-$([regex]::Escape($service))"
        }
        $content | Should Match 'name: ai-customer-service-a0-network'
        @([regex]::Matches($content, '(?m)^\s+name: ai_a0_[a-z0-9_]+$')).Count | Should Be 6
    }

    It 'publishes only the dedicated A0 host ports' {
        $content = Get-Content -Raw -LiteralPath $composePath
        foreach ($port in @(15174, 15175, 18000, 13000, 16334, 25432, 26379, 19090, 13001)) {
            $content | Should Match "\:-$port\}"
        }
    }

    It 'produces an isolated merged Compose model' {
        $oldVersion = $env:APP_VERSION
        try {
            $env:APP_VERSION = 'a1-test'
            $output = & docker compose -f (Join-Path $projectRoot 'docker-compose.yml') -f $composePath -p ai-customer-service-a0 config 2>&1
            $LASTEXITCODE | Should Be 0
            $text = ($output | ForEach-Object { [string]$_ }) -join "`n"
            $text | Should Match 'container_name: ai-customer-service-a0-bridge'
            $text | Should Match 'name: ai_a0_postgres_data'
            $text | Should Match 'name: ai-customer-service-a0-network'
            $text | Should Not Match 'container_name: ai-customer-service-bridge(?:\r?$)'
            $text | Should Not Match 'name: ai_postgres_data(?:\r?$)'
        } finally {
            if ($null -eq $oldVersion) { Remove-Item Env:APP_VERSION -ErrorAction SilentlyContinue }
            else { $env:APP_VERSION = $oldVersion }
        }
    }

    It 'guards destructive cleanup with exact targets and Force' {
        $content = Get-Content -Raw -LiteralPath $scriptPath
        $content | Should Match 'if \(-not \$Force\) \{ throw ''Destroy requires -Force\.'' \}'
        $content | Should Match "'ai_a0_postgres_data'"
        $content | Should Match 'Assert-A0TargetName'
        $content | Should Match '@\(Get-A0ContainerNames\)\.Count'
        $content | Should Not Match 'docker\s+system\s+prune'
        $content | Should Not Match "@\('down',\s*'-v'"
        $content | Should Not Match '--volumes'
    }

    It 'accepts a traceable candidate image version' {
        $content = Get-Content -Raw -LiteralPath $scriptPath
        $content | Should Match '\[AllowEmptyString\(\)\]'
        $content | Should Match '\[string\]\$CandidateVersion'
        $content | Should Match 'Set-DotEnvValue -Path \$rootEnv -Name ''APP_VERSION'' -Value \$candidateVersion'
    }
}

Describe 'P4-B webhook concurrency operations' {
    It 'injects the bounded single-worker concurrency defaults' {
        $compose = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'docker-compose.yml')
        $compose | Should Match 'WEBHOOK_ADAPTER_CONCURRENCY: \$\{WEBHOOK_ADAPTER_CONCURRENCY:-8\}'
        $compose | Should Match 'WEBHOOK_ADAPTER_PREFETCH: \$\{WEBHOOK_ADAPTER_PREFETCH:-64\}'
        $compose | Should Match 'WEBHOOK_ADAPTER_BUFFER_LIMIT: \$\{WEBHOOK_ADAPTER_BUFFER_LIMIT:-256\}'
        @([regex]::Matches($compose, '(?m)^  webhook-worker:$')).Count | Should Be 1
    }

    It 'keeps the load test isolated and cleanup recoverable' {
        $loadCompose = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'webhook-adapter/loadtest/compose.yml')
        $loadCompose | Should Match '(?m)^\s+internal: true$'
        $loadCompose | Should Not Match '(?m)^\s+ports:$'
        $wrapper = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'scripts/webhook-load-test.ps1')
        $wrapper | Should Match '\$projectName = ''ai-customer-service-p4b-loadtest'''
        $wrapper | Should Match 'finally'
        $wrapper | Should Match 'down --volumes --remove-orphans'
    }

    It 'requires explicit confirmation before a real AI write' {
        $script = Join-Path $projectRoot 'scripts/webhook-real-ai-smoke.ps1'
        $report = Join-Path $TestDrive 'not-confirmed.json'
        $output = & $script -ConcurrentConversationIds '1,2,3,4,5' -OrderedConversationId 6 -ReportPath $report
        ($output -join "`n") | Should Match '未发送任何请求'
        Test-Path -LiteralPath $report | Should Be $false
    }

    It 'calculates a redacted mock real-AI acceptance report' {
        $script = Join-Path $projectRoot 'scripts/webhook-real-ai-smoke.ps1'
        $report = Join-Path $TestDrive 'mock-real-ai.json'
        & $script -ConcurrentConversationIds '101,102,103,104,105' -OrderedConversationId 106 -ConfirmRealAiCost -Mock -ReportPath $report | Out-Null
        $result = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
        $result.status | Should Be 'passed'
        $result.mock_used | Should Be $true
        $result.latency_p50_seconds | Should Be 0.84
        $result.latency_p95_seconds | Should Be 1.35
        $result.completion_modes.public | Should Be 8
        $result.completion_modes.private_ai_reference | Should Be 0
        ($result.completion_modes.public + $result.completion_modes.private_ai_reference) | Should Be $result.replies
        $result.concurrent_conversations[0] | Should Not Be '101'
    }
}
