#requires -Version 7.2
[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$KeepStack,
    [ValidateRange(30, 900)][int]$TimeoutSeconds = 180,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
if (-not $ReportPath) { $ReportPath = Join-Path $projectRoot ("diagnostics/ingress-local-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$checks = [System.Collections.Generic.List[object]]::new()
$environmentNames = @('ADMIN_HOST', 'AGENT_HOST', 'WIDGET_HOST', 'CHATWOOT_HOST', 'ACME_EMAIL', 'ADMIN_ALLOWED_CIDRS', 'HOST_BIND_ADDRESS', 'WIDGET_PUBLIC_BASE_URL', 'CADDY_IMAGE')
$oldEnvironment = @{}

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $checks.Add([pscustomobject]@{ name = $Name; ok = $Ok; detail = Protect-OperationalText $Detail })
    Write-Host "[$(if ($Ok) { 'PASS' } else { 'FAIL' })] $Name - $(Protect-OperationalText $Detail)" -ForegroundColor $(if ($Ok) { 'Green' } else { 'Red' })
}

foreach ($name in $environmentNames) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
    $env:ADMIN_HOST = 'admin.localhost'
    $env:AGENT_HOST = 'agent.localhost'
    $env:WIDGET_HOST = 'widget.localhost'
    $env:CHATWOOT_HOST = 'chat.localhost'
    $env:ACME_EMAIL = 'ops@localhost.test'
    $env:ADMIN_ALLOWED_CIDRS = '127.0.0.1/32'
    $env:HOST_BIND_ADDRESS = '127.0.0.1'
    $env:WIDGET_PUBLIC_BASE_URL = 'https://widget.localhost'
    $env:CADDY_IMAGE = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'

    $docker = Invoke-Native docker @('version', '--format', '{{.Server.Version}}') -AllowFailure
    Add-Check 'docker' ($docker.ExitCode -eq 0) $docker.Output

    $values = Read-DotEnv (Join-Path $projectRoot '.env')
    foreach ($entry in ([ordered]@{
        POSTGRES_PASSWORD = 32; REDIS_PASSWORD = 32; SECRET_KEY_BASE = 64; SETUP_TOKEN = 32;
        CONFIG_ENCRYPTION_KEY = 64; CHATWOOT_ADAPTER_INGRESS_TOKEN = 32; CHATWOOT_WEBHOOK_SECRET = 32
    }).GetEnumerator()) {
        $current = [string]$values[$entry.Key]
        if ([string]::IsNullOrWhiteSpace($current) -or $current.Length -lt $entry.Value -or $current -match '(?i)changeme|replace_with|required_change_me|your_') {
            $values[$entry.Key] = New-SecureHex $entry.Value
        }
    }
    foreach ($name in $environmentNames) { $values[$name] = [Environment]::GetEnvironmentVariable($name) }
    $issues = @(Test-ProductionIngressEnvironment $values -AllowLocalhost)
    Add-Check 'production-environment' ($issues.Count -eq 0) $(if ($issues.Count -eq 0) { 'local four-host HTTPS contract is valid' } else { $issues -join '; ' })

    Push-Location $projectRoot
    try {
        $composeArgs = Get-ComposeFileArguments -Production
        $config = Invoke-Native docker (@('compose') + $composeArgs + @('config', '--quiet')) -AllowFailure
        Add-Check 'compose-config' ($config.ExitCode -eq 0) $(if ($config.ExitCode -eq 0) { 'production overlay is valid' } else { $config.Output })

        $templatePath = [IO.Path]::GetFullPath((Join-Path $projectRoot 'deploy/caddy/Caddyfile'))
        $renderCommand = 'ranges="$(printf "%s" "$ADMIN_ALLOWED_CIDRS" | tr "," " ")"; sed "s#__ADMIN_ALLOWED_CIDRS__#$ranges#g" /etc/caddy/Caddyfile.template > /tmp/Caddyfile; caddy validate --config /tmp/Caddyfile --adapter caddyfile'
        $validate = Invoke-Native docker @('run', '--rm', '-e', "ACME_EMAIL=$env:ACME_EMAIL", '-e', "ADMIN_HOST=$env:ADMIN_HOST", '-e', "AGENT_HOST=$env:AGENT_HOST", '-e', "WIDGET_HOST=$env:WIDGET_HOST", '-e', "CHATWOOT_HOST=$env:CHATWOOT_HOST", '-e', "ADMIN_ALLOWED_CIDRS=$env:ADMIN_ALLOWED_CIDRS", '-v', "${templatePath}:/etc/caddy/Caddyfile.template:ro", $env:CADDY_IMAGE, 'sh', '-ec', $renderCommand) -AllowFailure
        Add-Check 'caddy-validate' ($validate.ExitCode -eq 0) $validate.Output

        if ($Start -and $config.ExitCode -eq 0 -and $validate.ExitCode -eq 0) {
            Ensure-ExternalVolumes -Production
            $up = Invoke-Native docker (@('compose') + $composeArgs + @('up', '-d')) -AllowFailure
            Add-Check 'compose-up' ($up.ExitCode -eq 0) $(if ($up.ExitCode -eq 0) { 'production overlay started' } else { $up.Output })
            if ($up.ExitCode -eq 0) {
                try {
                    Wait-ComposeHealthy -ProjectRoot $projectRoot -Services @('postgres', 'redis', 'qdrant', 'chatwoot-web', 'bridge', 'admin', 'agent', 'caddy') -TimeoutSeconds $TimeoutSeconds
                    Add-Check 'compose-health' $true 'all ingress services healthy'
                } catch { Add-Check 'compose-health' $false $_.Exception.Message }

                $caPath = Join-Path $env:TEMP 'ai-cs-caddy-local-root.crt'
                $ca = Invoke-Native docker @('run', '--rm', '-v', 'ai_caddy_data:/data:ro', '--entrypoint', 'sh', $env:CADDY_IMAGE, '-ec', 'cat /data/caddy/pki/authorities/local/root.crt') -AllowFailure
                if ($ca.ExitCode -eq 0 -and $ca.Output -match 'BEGIN CERTIFICATE') {
                    Set-Content -LiteralPath $caPath -Value $ca.Output -NoNewline
                    foreach ($hostName in @('admin.localhost', 'agent.localhost', 'widget.localhost', 'chat.localhost')) {
                        $probe = Invoke-Native curl.exe @('--silent', '--show-error', '--fail', '--cacert', $caPath, '--resolve', "${hostName}:443:127.0.0.1", "https://${hostName}/") -AllowFailure
                        Add-Check "https-$hostName" ($probe.ExitCode -eq 0) $probe.Output
                    }
                    $widgetDenied = Invoke-Native curl.exe @('--silent', '--output', 'NUL', '--write-out', '%{http_code}', '--cacert', $caPath, '--resolve', 'widget.localhost:443:127.0.0.1', 'https://widget.localhost/api/admin/config') -AllowFailure
                    Add-Check 'widget-route-deny' ($widgetDenied.ExitCode -eq 0 -and $widgetDenied.Output.Trim() -eq '404') "status=$($widgetDenied.Output.Trim())"
                } else { Add-Check 'local-ca' $false 'Caddy local CA was not generated' }
            }
        } elseif (-not $Start) {
            Write-Host 'Start was not requested; runtime HTTPS probes were not executed.' -ForegroundColor Yellow
        }
    } finally { Pop-Location }
} finally {
    if ($Start -and -not $KeepStack) {
        Push-Location $projectRoot
        try { Invoke-Native docker (@('compose') + (Get-ComposeFileArguments -Production) + @('down', '--remove-orphans')) -AllowFailure | Out-Null } finally { Pop-Location }
    }
    foreach ($name in $environmentNames) {
        if ($null -eq $oldEnvironment[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $oldEnvironment[$name] }
    }
}

$report = [pscustomobject]@{
    schema_version = 1
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    started = [bool]$Start
    success = -not [bool]($checks | Where-Object { -not $_.ok })
    checks = $checks
}
New-Item -ItemType Directory -Path (Split-Path -Parent $ReportPath) -Force | Out-Null
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Host "Report: $ReportPath" -ForegroundColor Cyan
if (-not $report.success) { exit 1 }
