#requires -Version 7.2

$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'lib/Operations.psm1'
Import-Module $modulePath -Force

Describe 'Operations module' {
    It 'generates unique secure hexadecimal values' {
        $first = New-SecureHex -Bytes 32
        $second = New-SecureHex -Bytes 32
        $first.Length | Should Be 64
        $first | Should Match '^[a-f0-9]{64}$'
        $first | Should Not Be $second
    }

    It 'updates dotenv values without duplicating keys' {
        $path = Join-Path $TestDrive '.env'
        Set-Content -LiteralPath $path -Value @('A=one', '# note', 'B=two')
        Set-DotEnvValue -Path $path -Name 'A' -Value 'updated'
        Set-DotEnvValue -Path $path -Name 'C' -Value 'three'
        $values = Read-DotEnv $path
        $values.A | Should Be 'updated'
        $values.B | Should Be 'two'
        $values.C | Should Be 'three'
        @((Get-Content $path) | Where-Object { $_ -match '^A=' }).Count | Should Be 1
    }

    It 'allows clearing a dotenv value without removing its key' {
        $path = Join-Path $TestDrive 'clear.env'
        Set-Content -LiteralPath $path -Value 'TOKEN=secret'
        Set-DotEnvValue -Path $path -Name 'TOKEN' -Value ''
        (Get-Content -Raw -LiteralPath $path).Trim() | Should Be 'TOKEN='
        (Read-DotEnv $path).TOKEN | Should Be ''
    }

    It 'escapes dollar signs for Docker Compose dotenv interpolation' {
        $hash = '$argon2id$v=19$m=65536,t=3,p=4$abc$def'
        ConvertTo-ComposeEnvValue $hash | Should Be '$$argon2id$$v=19$$m=65536,t=3,p=4$$abc$$def'
    }

    It 'keeps handoff keywords JSON-decodable in the production template' {
        $template = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'bridge-service/.env.example'
        $keywords = (Read-DotEnv $template).HANDOFF_KEYWORDS | ConvertFrom-Json
        @($keywords).Count | Should BeGreaterThan 3
        (@($keywords) -contains '人工') | Should Be $true
    }

    It 'rejects placeholder production secrets' {
        $issues = Test-RequiredEnvironment ([ordered]@{
            POSTGRES_PASSWORD = 'changeme'
            REDIS_PASSWORD = 'a'
            SECRET_KEY_BASE = 'replace_with_secret'
            SETUP_TOKEN = 'short'
            CONFIG_ENCRYPTION_KEY = 'short'
            CHATWOOT_ADAPTER_INGRESS_TOKEN = 'short'
            CHATWOOT_WEBHOOK_SECRET = 'short'
        })
        $issues.Count | Should Be 7
    }

    It 'accepts generated production secrets' {
        $issues = Test-RequiredEnvironment ([ordered]@{
            POSTGRES_PASSWORD = (New-SecureHex 24)
            REDIS_PASSWORD = (New-SecureHex 24)
            SECRET_KEY_BASE = (New-SecureHex 64)
            SETUP_TOKEN = (New-SecureHex 32)
            CONFIG_ENCRYPTION_KEY = (New-SecureHex 32)
            CHATWOOT_ADAPTER_INGRESS_TOKEN = (New-SecureHex 32)
            CHATWOOT_WEBHOOK_SECRET = (New-SecureHex 32)
        })
        $issues.Count | Should Be 0
    }

    It 'rejects paths outside the allowed parent' {
        $parent = Join-Path $TestDrive 'allowed'
        New-Item -ItemType Directory -Path $parent | Out-Null
        $threw = $false
        try { Get-SafeChildPath -Parent $parent -Child (Join-Path $TestDrive 'outside') | Out-Null } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'detects checksum tampering' {
        $root = Join-Path $TestDrive 'backup'
        New-Item -ItemType Directory -Path $root | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'payload.txt') -Value 'original'
        New-ChecksumManifest -Root $root
        Test-ChecksumManifest -Root $root | Should Be $true
        Set-Content -LiteralPath (Join-Path $root 'payload.txt') -Value 'tampered'
        $threw = $false
        try { Test-ChecksumManifest -Root $root | Out-Null } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'redacts credentials and connection strings' {
        $safe = Protect-OperationalText 'Authorization=Bearer top-secret token=another password=hunter2 redis://user:pass@redis'
        $safe | Should Not Match 'top-secret|another|hunter2|user:pass'
        $safe | Should Match '\*\*\*'
    }

    It 'copies Bridge business data without traversing the model cache' {
        $source = Join-Path $TestDrive 'bridge-data'
        $destination = Join-Path $TestDrive 'backup-data'
        New-Item -ItemType Directory -Path (Join-Path $source 'knowledge') -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $source 'runtime') -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $source 'model_cache') -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $source 'model_cache_notes') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $source 'knowledge/source.txt') -Value 'knowledge'
        Set-Content -LiteralPath (Join-Path $source 'runtime/config.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $source 'model_cache/unreadable-link') -Value 'cache'
        Set-Content -LiteralPath (Join-Path $source 'model_cache_notes/readme.txt') -Value 'keep'
        Set-Content -LiteralPath (Join-Path $source 'state.json') -Value '{}'

        $result = Copy-BridgeBackupData -Source $source -Destination $destination

        $result.SourceExists | Should Be $true
        @($result.ExcludedPaths).Count | Should Be 1
        $result.ExcludedPaths[0] | Should Be 'bridge-data/model_cache'
        (Test-Path -LiteralPath (Join-Path $destination 'knowledge/source.txt')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $destination 'runtime/config.json')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $destination 'model_cache')) | Should Be $false
        (Test-Path -LiteralPath (Join-Path $destination 'model_cache_notes/readme.txt')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $destination 'state.json')) | Should Be $true
    }

    It 'does not create Bridge backup data when the source is absent' {
        $source = Join-Path $TestDrive 'missing-bridge-data'
        $destination = Join-Path $TestDrive 'missing-backup-data'

        $result = Copy-BridgeBackupData -Source $source -Destination $destination

        $result.SourceExists | Should Be $false
        @($result.ExcludedPaths).Count | Should Be 0
        (Test-Path -LiteralPath $destination) | Should Be $false
    }

    It 'restarts Bridge proxies as part of a consistent backup' {
        $services = @(Get-BackupConsistencyServices)

        @($services | Sort-Object -Unique).Count | Should Be $services.Count
        foreach ($expected in @('bridge', 'admin', 'agent', 'webhook-gateway', 'webhook-worker', 'chatwoot-web', 'chatwoot-worker', 'redis', 'qdrant')) {
            ($expected -in $services) | Should Be $true
        }
        ('postgres' -in $services) | Should Be $false
        ('prometheus' -in $services) | Should Be $false
        ('grafana' -in $services) | Should Be $false
    }
}

Describe 'Restore command safety gate' {
    It 'verifies a compatible backup before honoring WhatIf' {
        $backup = Join-Path $TestDrive 'synthetic-backup'
        New-Item -ItemType Directory -Path $backup | Out-Null
        [pscustomobject]@{
            schema_version = 1
            product = 'ai-customer-service'
            created_at = (Get-Date).ToUniversalTime().ToString('o')
            git_commit = 'test'
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'manifest.json')
        New-ChecksumManifest -Root $backup

        $restore = Join-Path (Split-Path -Parent $PSScriptRoot) 'restore.ps1'
        $threw = $false
        try { & $restore -BackupPath $backup -Force -WhatIf } catch { $threw = $true }
        $threw | Should Be $false
    }
}

Describe 'Production ingress Compose contract' {
    BeforeAll {
        $projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $compose = Get-Content -LiteralPath (Join-Path $projectRoot 'docker-compose.yml') -Raw
        $production = Get-Content -LiteralPath (Join-Path $projectRoot 'docker-compose.production.yml') -Raw
        $caddyfile = Get-Content -LiteralPath (Join-Path $projectRoot 'deploy/caddy/Caddyfile') -Raw
    }

    It 'defaults every published base service port to loopback binding' {
        foreach ($pattern in @(
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{POSTGRES_PORT:-15432\}:5432',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{REDIS_PORT_EXTERNAL:-16379\}:6379',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{CHATWOOT_PORT:-3000\}:3000',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{QDRANT_PORT:-6333\}:6333',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{BRIDGE_PORT:-8000\}:8000',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{ADMIN_PORT:-5175\}:8080',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{AGENT_PORT:-5174\}:8080',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{PROMETHEUS_PORT:-9090\}:9090',
            '\$\{HOST_BIND_ADDRESS:-127\.0\.0\.1\}:\$\{GRAFANA_PORT:-3001\}:3000'
        )) {
            $compose | Should Match $pattern
        }
        $compose | Should Not Match '(?m)^\s*- "\$\{(?:POSTGRES|REDIS|CHATWOOT|QDRANT|BRIDGE|ADMIN|AGENT|PROMETHEUS|GRAFANA)_PORT'
    }

    It 'publishes only Caddy on public 80 and 443 in the production overlay' {
        $production | Should Match '0\.0\.0\.0:80:80'
        $production | Should Match '0\.0\.0\.0:443:443'
        $production | Should Match 'CADDY_IMAGE:\?CADDY_IMAGE must be a pinned Caddy image'
        $production | Should Match 'caddy_data'
        $production | Should Match 'caddy_config'
    }

    It 'keeps Caddy off the internal network and attaches only edge services' {
        $production | Should Match '(?s)caddy:.*?networks:\s*- edge'
        $production | Should Match '(?s)admin:\s*networks:\s*- internal\s*- edge'
        $production | Should Match '(?s)agent:\s*networks:\s*- internal\s*- edge'
        $production | Should Match '(?s)chatwoot-web:\s*.*?networks:\s*- internal\s*- edge'
    }

    It 'exposes the Widget route allowlist and a 404 default' {
        foreach ($route in @(
            'method GET\s+path /assets/widget\.js',
            'method GET\s+path /api/widget/config',
            'method POST\s+path /api/widget/session',
            'method POST\s+path /api/chat',
            'method GET\s+path /api/chat/handoff',
            'method GET\s+path /ws/widget'
        )) {
            $caddyfile | Should Match $route
        }
        $caddyfile | Should Match 'respond "not found" 404'
        $caddyfile | Should Not Match '/api/widget/snippet'
        $caddyfile | Should Not Match '/ws/agent'
    }

    It 'uses the same CIDR gate for Admin and Chatwoot' {
        ([regex]::Matches($caddyfile, 'remote_ip __ADMIN_ALLOWED_CIDRS__')).Count | Should Be 2
        $caddyfile | Should Match 'respond @admin_host "forbidden" 403'
        $caddyfile | Should Match 'respond @chatwoot_host "forbidden" 403'
    }
}

Describe 'Production ingress environment contract' {
    It 'accepts a complete pinned HTTPS configuration' {
        $values = [ordered]@{
            ADMIN_HOST = 'admin.acme.test'
            AGENT_HOST = 'agent.acme.test'
            WIDGET_HOST = 'widget.acme.test'
            CHATWOOT_HOST = 'chat.acme.test'
            ACME_EMAIL = 'ops@acme.test'
            ADMIN_ALLOWED_CIDRS = '203.0.113.10/32,2001:db8::/64'
            HOST_BIND_ADDRESS = '127.0.0.1'
            WIDGET_PUBLIC_BASE_URL = 'https://widget.acme.test'
            CADDY_IMAGE = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'
            POSTGRES_PASSWORD = New-SecureHex 24
            REDIS_PASSWORD = New-SecureHex 24
            SECRET_KEY_BASE = New-SecureHex 64
            SETUP_TOKEN = New-SecureHex 32
            CONFIG_ENCRYPTION_KEY = New-SecureHex 32
            CHATWOOT_ADAPTER_INGRESS_TOKEN = New-SecureHex 32
            CHATWOOT_WEBHOOK_SECRET = New-SecureHex 32
        }
        @(Test-ProductionIngressEnvironment $values).Count | Should Be 0
    }

    It 'rejects public bind, open CIDR, invalid host and unpinned image' {
        $values = [ordered]@{
            ADMIN_HOST = 'https://admin.example.com/path'
            AGENT_HOST = 'agent.example.com'
            WIDGET_HOST = 'widget.example.com'
            CHATWOOT_HOST = 'chat.example.com'
            ACME_EMAIL = 'not-an-email'
            ADMIN_ALLOWED_CIDRS = '0.0.0.0/0'
            HOST_BIND_ADDRESS = '0.0.0.0'
            WIDGET_PUBLIC_BASE_URL = 'http://widget.example.com/path'
            CADDY_IMAGE = 'caddy:latest'
        }
        $issues = @(Test-ProductionIngressEnvironment $values)
        $issues.Count | Should BeGreaterThan 5
        ($issues -join "`n") | Should Match 'ADMIN_HOST|ACME_EMAIL|ADMIN_ALLOWED_CIDRS|HOST_BIND_ADDRESS|WIDGET_PUBLIC_BASE_URL|CADDY_IMAGE'
    }

    It 'returns the production Compose file arguments only when requested' {
        (Get-ComposeFileArguments -Production:$false) -join ' ' | Should Be '-f docker-compose.yml'
        (Get-ComposeFileArguments -Production) -join ' ' | Should Be '-f docker-compose.yml -f docker-compose.production.yml'
    }
}
