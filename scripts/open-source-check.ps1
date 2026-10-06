#requires -Version 7.2
[CmdletBinding()]
param([string]$ProjectRoot = "", [switch]$Quick, [string]$ReportPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Import-Module (Join-Path $ProjectRoot 'scripts/lib/Operations.psm1') -Force
$checks = [Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [scriptblock]$Action) {
    try {
        $detail = & $Action
        $checks.Add([pscustomobject]@{ name = $Name; status = 'passed'; detail = Protect-OperationalText ([string]$detail) })
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } catch {
        $checks.Add([pscustomobject]@{ name = $Name; status = 'failed'; detail = Protect-OperationalText $_.Exception.Message })
        Write-Host "[FAIL] $Name" -ForegroundColor Red
    }
}

Push-Location $ProjectRoot
try {
    Add-Check 'required-public-files' {
        $required = @('README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', '.env.example', '.gitignore', 'VERSION', 'release-manifest.json', 'docker-compose.yml', 'docs/installation.md', 'docs/configuration.md', 'docs/widget-integration.md', 'docs/operations.md', 'docs/security-hardening.md', 'docs/troubleshooting.md', 'docs/api.md')
        $missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
        if ($missing) { throw "Missing public files: $($missing -join ', ')" }
        "required=$($required.Count)"
    }
    Add-Check 'forbidden-paths' {
        # A published repository necessarily contains .git metadata. The exporter
        # itself separately guarantees that metadata is never copied into a new
        # release directory.
        $forbidden = @('.env', 'docs/superpowers', 'diagnostics', 'backups')
        $present = @($forbidden | Where-Object { Test-Path -LiteralPath $_ })
        $generated = @(Get-ChildItem -Force -Recurse -File | Where-Object { $_.Name -match '\.(log(\..*)?|pid|bak|backup|old)$' -or $_.FullName -match '[\\/](node_modules|dist|model_cache|runtime)[\\/]' })
        if ($present -or $generated) {
            $names = @($present) + @($generated | ForEach-Object { [IO.Path]::GetRelativePath($ProjectRoot, $_.FullName) })
            throw "Forbidden public paths: $($names -join ', ')"
        }
        'none'
    }
    Add-Check 'license-and-version' {
        if ((Get-Content -Raw 'LICENSE') -notmatch 'Apache License\s+Version 2\.0, January 2004') { throw 'LICENSE is not Apache-2.0.' }
        $version = (Get-Content -Raw 'VERSION').Trim()
        $manifest = Get-Content -Raw 'release-manifest.json' | ConvertFrom-Json
        if ($version -ne [string]$manifest.version) { throw 'VERSION and release manifest differ.' }
        "version=$version"
    }
    Add-Check 'readme-links' {
        $readme = Get-Content -Raw 'README.md'
        foreach ($match in [regex]::Matches($readme, '\]\(([^)#]+)')) {
            $path = $match.Groups[1].Value
            if ($path -notmatch '^(https?|mailto):' -and -not (Test-Path -LiteralPath $path)) { throw "Broken README link: $path" }
        }
        'all local links exist'
    }
    Add-Check 'sensitive-content' {
        $extensions = @('.py', '.ps1', '.psm1', '.ts', '.tsx', '.js', '.mjs', '.json', '.yml', '.yaml', '.md', '.txt', '.html', '.sh', '.conf', '.example')
        $patterns = [ordered]@{
            'private-key' = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
            'github-token' = 'gh[pousr]_[A-Za-z0-9]{20,}'
            'openai-style-key' = 'sk-[A-Za-z0-9_-]{20,}'
            'windows-user-path' = '[A-Za-z]:\\Users\\[^\\\s]+'
        }
        $findings = [Collections.Generic.List[string]]::new()
        foreach ($file in Get-ChildItem -Force -Recurse -File | Where-Object { $_.Extension -in $extensions -or $_.Name -in @('Dockerfile', 'Caddyfile', 'LICENSE') }) {
            $relative = [IO.Path]::GetRelativePath($ProjectRoot, $file.FullName).Replace('\', '/')
            $content = Get-Content -Raw -LiteralPath $file.FullName
            foreach ($entry in $patterns.GetEnumerator()) { if ($content -match $entry.Value) { $findings.Add("$($entry.Key):$relative") } }
        }
        if ($findings.Count) { throw "Sensitive content signatures found: $($findings -join ', ')" }
        'no sensitive signatures'
    }
    Add-Check 'compose-config' {
        $bridgeEnv = 'bridge-service/.env'
        $createdBridgeEnv = $false
        try {
            if (-not (Test-Path -LiteralPath $bridgeEnv)) {
                Copy-Item -LiteralPath 'bridge-service/.env.example' -Destination $bridgeEnv
                $createdBridgeEnv = $true
            }
            $result = Invoke-Native docker @('compose', '--env-file', '.env.example', 'config', '--quiet') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }
        } finally {
            if ($createdBridgeEnv -and (Test-Path -LiteralPath $bridgeEnv)) { Remove-Item -LiteralPath $bridgeEnv -Force }
        }
        'standard compose valid with public template'
    }
    if (-not $Quick) {
        Add-Check 'backend-tests' {
            $python = if (Test-Path 'bridge-service/venv/Scripts/python.exe') { 'bridge-service/venv/Scripts/python.exe' } elseif (Test-Path 'bridge-service/.venv/Scripts/python.exe') { 'bridge-service/.venv/Scripts/python.exe' } else { 'python' }
            $result = Invoke-Native $python @('-m', 'pytest', 'bridge-service/tests', '-q') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }; 'pytest passed'
        }
        Add-Check 'frontend-tests-and-build' {
            Push-Location 'frontend'
            try {
                foreach ($arguments in @(@('pnpm', 'install', '--frozen-lockfile'), @('pnpm', 'test'), @('pnpm', 'typecheck'), @('pnpm', 'build'))) {
                    $result = Invoke-Native corepack $arguments -AllowFailure
                    if ($result.ExitCode -ne 0) { throw $result.Output }
                }
            } finally { Pop-Location }
            'frontend tests, typecheck and build passed'
        }
        Add-Check 'release-check' {
            $result = Invoke-Native pwsh @('-File', 'scripts/release-check.ps1', '-Quick') -AllowFailure
            if ($result.ExitCode -ne 0) { throw $result.Output }; 'release check passed'
        }
    }
} finally { Pop-Location }

$passed = @($checks | Where-Object status -eq 'failed').Count -eq 0
$report = [pscustomobject]@{ schema_version = 1; generated_at = (Get-Date).ToUniversalTime().ToString('o'); project_root = $ProjectRoot; checks = $checks; passed = $passed }
if ($ReportPath) {
    $fullReport = [IO.Path]::GetFullPath($ReportPath)
    $parent = Split-Path -Parent $fullReport
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $fullReport -Encoding UTF8
}
if (-not $passed) { throw 'Open-source release checks failed.' }
$report
