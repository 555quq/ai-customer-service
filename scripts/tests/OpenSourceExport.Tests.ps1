$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$script:Manifest = Get-Content -Raw -LiteralPath (Join-Path $script:ProjectRoot 'config/open-source-export.json') | ConvertFrom-Json

Describe 'Open-source export manifest' -Tag Manifest {
    It 'uses schema version 1 and project-relative paths' {
        $script:Manifest.schema_version | Should Be 1
        foreach ($path in @($script:Manifest.include_roots) + @($script:Manifest.include_files) + @($script:Manifest.required_files)) {
            [IO.Path]::IsPathRooted([string]$path) | Should Be $false
            @(([string]$path) -split '[\\/]' | Where-Object { $_ -eq '..' }).Count | Should Be 0
        }
    }

    It 'excludes private and generated paths' {
        $patterns = @($script:Manifest.exclude_globs) -join "`n"
        foreach ($expected in @('.git/**', '.env', '**/*.log.*', '**/diagnostics/**', '**/backups/**', '**/model_cache/**', '**/node_modules/**', 'docs/superpowers/**')) {
            $patterns | Should Match ([regex]::Escape($expected))
        }
    }
}

Describe 'Open-source export script' -Tag Export {
    function Invoke-AndCaptureFailure([scriptblock]$Action) {
        try { & $Action; return $false } catch { return $true }
    }

    It 'exports required files without private paths' {
        $destination = Join-Path $TestDrive 'ai-customer-service-public'
        $result = & (Join-Path $script:ProjectRoot 'scripts/export-open-source.ps1') -Destination $destination -PassThru
        ($result.file_count -gt 50) | Should Be $true
        Test-Path (Join-Path $destination 'README.md') | Should Be $true
        Test-Path (Join-Path $destination '.git') | Should Be $false
        Test-Path (Join-Path $destination 'docs/superpowers') | Should Be $false
        Test-Path (Join-Path $destination '.env') | Should Be $false
    }

    It 'refuses to overwrite a non-empty destination without Force' {
        $destination = Join-Path $TestDrive 'existing-public'
        New-Item -ItemType Directory -Path $destination | Out-Null
        Set-Content -LiteralPath (Join-Path $destination 'keep.txt') -Value 'keep'
        Invoke-AndCaptureFailure { & (Join-Path $script:ProjectRoot 'scripts/export-open-source.ps1') -Destination $destination } | Should Be $true
        Test-Path (Join-Path $destination 'keep.txt') | Should Be $true
    }

    It 'refuses source project descendants and ancestors' {
        Invoke-AndCaptureFailure { & (Join-Path $script:ProjectRoot 'scripts/export-open-source.ps1') -Destination (Join-Path $script:ProjectRoot 'public') } | Should Be $true
        Invoke-AndCaptureFailure { & (Join-Path $script:ProjectRoot 'scripts/export-open-source.ps1') -Destination (Split-Path -Parent $script:ProjectRoot) } | Should Be $true
    }
}
