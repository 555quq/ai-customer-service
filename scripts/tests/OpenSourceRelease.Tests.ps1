$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

Describe 'Open-source documentation' -Tag Documentation {
    It 'contains every required public document' {
        foreach ($path in @('README.md', 'LICENSE', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'docs/installation.md', 'docs/configuration.md', 'docs/widget-integration.md', 'docs/operations.md', 'docs/security-hardening.md', 'docs/troubleshooting.md', 'docs/api.md')) {
            Test-Path (Join-Path $script:ProjectRoot $path) | Should Be $true
        }
    }
    It 'uses the Apache 2.0 license' {
        Get-Content -Raw (Join-Path $script:ProjectRoot 'LICENSE') | Should Match 'Apache License\s+Version 2.0, January 2004'
    }
}

Describe 'Public GitHub workflow' -Tag GitHub {
    It 'uses read-only permissions and no repository secrets' {
        $workflow = Get-Content -Raw (Join-Path $script:ProjectRoot '.github/workflows/ci-cd.yml')
        $workflow | Should Match 'contents:\s*read'
        $workflow | Should Not Match 'secrets\.'
        $workflow | Should Not Match '(?i)ssh|slack|docker/login-action|docker push'
    }
    It 'contains issue and pull request templates' {
        foreach ($path in @('.github/ISSUE_TEMPLATE/bug_report.yml', '.github/ISSUE_TEMPLATE/feature_request.yml', '.github/ISSUE_TEMPLATE/config.yml', '.github/pull_request_template.md')) {
            Test-Path (Join-Path $script:ProjectRoot $path) | Should Be $true
        }
    }
}

Describe 'Open-source release checker' -Tag Security {
    It 'passes against an exported public copy' {
        $destination = Join-Path $TestDrive 'ai-customer-service-public'
        & (Join-Path $script:ProjectRoot 'scripts/export-open-source.ps1') -Destination $destination | Out-Null
        $failed = $false
        try { & (Join-Path $destination 'scripts/open-source-check.ps1') -ProjectRoot $destination -Quick | Out-Null } catch { $failed = $true }
        $failed | Should Be $false
    }
}
