#requires -Version 7.2
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
    return (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )
    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "Command failed ($exitCode): $FilePath $($Arguments -join ' ')`n$text"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $text }
}

function Read-DotEnv {
    param([Parameter(Mandatory)][string]$Path)
    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $parts = $line -split '=', 2
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Value
    )
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in Get-Content -LiteralPath $Path) { $lines.Add([string]$line) }
    }
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^\s*$([regex]::Escape($Name))=") {
            $lines[$index] = "$Name=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) { $lines.Add("$Name=$Value") }
    $directory = Split-Path -Parent $Path
    if ($directory) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    [IO.File]::WriteAllLines($Path, $lines, [Text.UTF8Encoding]::new($false))
}

function New-SecureHex {
    param([ValidateRange(16, 256)][int]$Bytes = 32)
    $buffer = [byte[]]::new($Bytes)
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToHexString($buffer).ToLowerInvariant()
}

function ConvertTo-ComposeEnvValue {
    param([AllowEmptyString()][string]$Value)
    if ($null -eq $Value) { return '' }
    return $Value.Replace('$', '$$')
}

function Protect-OperationalText {
    param([AllowNull()][string]$Text)
    if ($null -eq $Text) { return "" }
    $result = $Text
    $result = [regex]::Replace($result, '(?im)(authorization\s*[=:]\s*)(?:bearer\s+)?[^\s,;"}]+', '$1***')
    $result = [regex]::Replace($result, '(?im)(password|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)([^\s,;"}]+)', '$1$2***')
    $result = [regex]::Replace($result, '(?i)bearer\s+[a-z0-9._~+/-]+=*', 'Bearer ***')
    $result = [regex]::Replace($result, '(?i)(redis|postgresql)://[^\s@]+@', '$1://***@')
    return $result
}

function Test-PortFree {
    param([ValidateRange(1, 65535)][int]$Port)
    $listener = $null
    try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}

function Get-SystemCapacity {
    param([string]$Path = (Get-ProjectRoot))
    $memoryBytes = 0L
    if ($IsWindows) {
        $memoryBytes = [long](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    } elseif (Test-Path /proc/meminfo) {
        $line = Get-Content /proc/meminfo | Select-String '^MemTotal:' | Select-Object -First 1
        if ($line -and $line.Line -match '(\d+)') { $memoryBytes = [long]$Matches[1] * 1KB }
    }
    $item = Get-Item -LiteralPath $Path
    $drive = Get-PSDrive -Name $item.PSDrive.Name
    return [pscustomobject]@{
        Cpu = [Environment]::ProcessorCount
        MemoryGB = [math]::Round($memoryBytes / 1GB, 2)
        FreeDiskGB = [math]::Round($drive.Free / 1GB, 2)
    }
}

function Test-RequiredEnvironment {
    param([Parameter(Mandatory)][Collections.IDictionary]$Values)
    $placeholders = @('changeme', 'admin', 'replace_with', 'required_change_me', 'your_secure', 'your_', 'example')
    $requirements = [ordered]@{
        POSTGRES_PASSWORD = 24
        REDIS_PASSWORD = 24
        SECRET_KEY_BASE = 64
        SETUP_TOKEN = 32
        CONFIG_ENCRYPTION_KEY = 64
        CHATWOOT_ADAPTER_INGRESS_TOKEN = 32
        CHATWOOT_WEBHOOK_SECRET = 32
    }
    $issues = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in $requirements.GetEnumerator()) {
        $value = [string]$Values[$entry.Key]
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -lt $entry.Value) {
            $issues.Add("$($entry.Key) must contain at least $($entry.Value) characters")
            continue
        }
        if ($placeholders | Where-Object { $value.ToLowerInvariant().Contains($_) }) {
            $issues.Add("$($entry.Key) still contains a placeholder/default value")
        }
    }
    return $issues.ToArray()
}

function Test-ProductionIngressEnvironment {
    param(
        [Parameter(Mandatory)][Collections.IDictionary]$Values,
        [switch]$AllowLocalhost
    )

    $issues = [System.Collections.Generic.List[string]]::new()
    $hostNames = @('ADMIN_HOST', 'AGENT_HOST', 'WIDGET_HOST', 'CHATWOOT_HOST')
    foreach ($name in $hostNames) {
        $value = [string]$Values[$name]
        if ([string]::IsNullOrWhiteSpace($value)) {
            $issues.Add("$name is required")
            continue
        }
        $isLocalhost = $value -match '(?i)^(localhost|.*\.localhost)$'
        if ($value -match '://|[/:?#]' -or (($isLocalhost) -and -not $AllowLocalhost) -or $value -match '(?i)example') {
            $issues.Add("$name must be a real hostname without scheme, path, port or example placeholder")
            continue
        }
        if ($value -notmatch '^(?=.{1,253}$)(?:(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$') {
            $issues.Add("$name is not a valid DNS hostname")
        }
    }
    $hostValues = @($hostNames | ForEach-Object { [string]$Values[$_] } | Where-Object { $_ })
    if (@($hostValues | Sort-Object -Unique).Count -ne $hostValues.Count) {
        $issues.Add('ADMIN_HOST, AGENT_HOST, WIDGET_HOST and CHATWOOT_HOST must be distinct')
    }

    $email = [string]$Values.ACME_EMAIL
    if ($email -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { $issues.Add('ACME_EMAIL is invalid') }

    $cidrValue = [string]$Values.ADMIN_ALLOWED_CIDRS
    $cidrItems = @($cidrValue -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if (-not $cidrItems) {
        $issues.Add('ADMIN_ALLOWED_CIDRS must contain at least one address or CIDR')
    } else {
        foreach ($item in $cidrItems) {
            $parts = $item -split '/', 2
            $address = $null
            if (-not [Net.IPAddress]::TryParse($parts[0], [ref]$address)) {
                $issues.Add("ADMIN_ALLOWED_CIDRS contains invalid address: $item")
                continue
            }
            $maxPrefix = if ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) { 32 } else { 128 }
            $prefix = if ($parts.Count -eq 1) { $maxPrefix } else { 0 }
            if ($parts.Count -eq 2 -and $parts[1] -notmatch '^\d+$') { $issues.Add("ADMIN_ALLOWED_CIDRS contains invalid prefix: $item"); continue }
            if ($parts.Count -eq 2) { $prefix = [int]$parts[1] }
            if ($prefix -lt 0 -or $prefix -gt $maxPrefix) { $issues.Add("ADMIN_ALLOWED_CIDRS prefix is out of range: $item"); continue }
            if (($prefix -eq 0) -and (($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) -or ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetworkV6))) {
                $issues.Add("ADMIN_ALLOWED_CIDRS must not allow the entire address space: $item")
            }
        }
    }

    $bindAddress = [string]$Values.HOST_BIND_ADDRESS
    if ($bindAddress -notin @('127.0.0.1', '::1')) { $issues.Add('HOST_BIND_ADDRESS must be 127.0.0.1 or ::1 in production') }

    $widgetUrl = [string]$Values.WIDGET_PUBLIC_BASE_URL
    $widgetUri = $null
    if (-not [Uri]::TryCreate($widgetUrl, [UriKind]::Absolute, [ref]$widgetUri) -or
        $widgetUri.Scheme -ne 'https' -or [string]::IsNullOrWhiteSpace($widgetUri.Host) -or
        $widgetUri.AbsolutePath -notin @('', '/') -or $widgetUri.Query -or $widgetUri.Fragment -or
        $widgetUri.UserInfo -or ($widgetUri.Port -notin @(-1, 443)) -or
        $widgetUri.Host -ne [string]$Values.WIDGET_HOST) {
        $issues.Add('WIDGET_PUBLIC_BASE_URL must be an HTTPS origin matching WIDGET_HOST')
    }

    $caddyImage = [string]$Values.CADDY_IMAGE
    if ($caddyImage -notmatch '^\S+@sha256:[a-f0-9]{64}$') { $issues.Add('CADDY_IMAGE must include an immutable sha256 digest') }

    foreach ($issue in @(Test-RequiredEnvironment $Values)) { $issues.Add($issue) }
    return $issues.ToArray()
}

function Get-ComposeFileArguments {
    param([switch]$Production)
    if ($Production) { return @('-f', 'docker-compose.yml', '-f', 'docker-compose.production.yml') }
    return @('-f', 'docker-compose.yml')
}

function Ensure-ExternalVolumes {
    param([switch]$Production)
    $names = @(
        'ai_postgres_data',
        'ai_redis_data',
        'ai_chatwoot_storage',
        'ai_qdrant_data',
        'ai_prometheus_data',
        'ai_grafana_data'
    )
    if ($Production) { $names += @('ai_caddy_data', 'ai_caddy_config') }
    foreach ($name in $names) {
        $inspect = Invoke-Native docker @('volume', 'inspect', $name) -AllowFailure
        if ($inspect.ExitCode -ne 0) { Invoke-Native docker @('volume', 'create', $name) | Out-Null }
    }
}

function Get-ComposeImages {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    Push-Location $ProjectRoot
    try {
        $result = Invoke-Native docker @('compose', 'config', '--images')
        return @($result.Output -split "`r?`n" | Where-Object { $_ })
    } finally { Pop-Location }
}

function Get-BackupConsistencyServices {
    return @(
        'webhook-gateway',
        'webhook-worker',
        'bridge',
        'admin',
        'agent',
        'chatwoot-web',
        'chatwoot-worker',
        'redis',
        'qdrant'
    )
}

function Wait-ComposeHealthy {
    param(
        [string]$ProjectRoot = (Get-ProjectRoot),
        [string[]]$Services = @('postgres', 'redis', 'qdrant', 'chatwoot-web', 'webhook-gateway', 'webhook-worker', 'bridge', 'admin', 'agent'),
        [ValidateRange(10, 1800)][int]$TimeoutSeconds = 300
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    Push-Location $ProjectRoot
    try {
        do {
            $pending = [System.Collections.Generic.List[string]]::new()
            foreach ($service in $Services) {
                $id = Invoke-Native docker @('compose', 'ps', '-q', $service) -AllowFailure
                if ($id.ExitCode -ne 0 -or -not $id.Output.Trim()) { $pending.Add("${service}:missing"); continue }
                $state = Invoke-Native docker @('inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', $id.Output.Trim()) -AllowFailure
                if ($state.ExitCode -ne 0 -or $state.Output.Trim() -notin @('healthy', 'running')) {
                    $pending.Add("${service}:$($state.Output.Trim())")
                }
            }
            if ($pending.Count -eq 0) { return }
            Start-Sleep -Seconds 3
        } while ([DateTime]::UtcNow -lt $deadline)
        throw "Services did not become healthy: $($pending -join ', ')"
    } finally { Pop-Location }
}

function Get-SafeChildPath {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Child
    )
    $parentPath = [IO.Path]::GetFullPath($Parent).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $childPath = [IO.Path]::GetFullPath($Child)
    if (-not $childPath.StartsWith($parentPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the allowed directory: $childPath"
    }
    return $childPath
}

function Resolve-PathWithinRoot {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath
    )
    if ([IO.Path]::IsPathRooted($RelativePath) -or $RelativePath -split '[\\/]' -contains '..') {
        throw "Public export path must be project-relative: $RelativePath"
    }
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $candidate = [IO.Path]::GetFullPath((Join-Path $rootPath $RelativePath))
    $boundary = $rootPath + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Public export path escapes the project root: $RelativePath"
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Public export path does not exist: $RelativePath"
    }
    $item = Get-Item -LiteralPath $candidate -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Public export path cannot be a symbolic link or reparse point: $RelativePath"
    }
    return $item
}

function Assert-SafeExternalDestination {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$Destination
    )
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $target = [IO.Path]::GetFullPath($Destination).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $projectBoundary = $project + [IO.Path]::DirectorySeparatorChar
    $targetBoundary = $target + [IO.Path]::DirectorySeparatorChar
    if ($target -eq $project -or $target.StartsWith($projectBoundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Public export destination must be outside the source project.'
    }
    if ($project.StartsWith($targetBoundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Public export destination cannot be an ancestor of the source project.'
    }
    $root = [IO.Path]::GetPathRoot($target).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if ($target.TrimEnd([IO.Path]::DirectorySeparatorChar) -eq $root) {
        throw 'Public export destination cannot be a drive root.'
    }
    $profile = [Environment]::GetFolderPath('UserProfile').TrimEnd([IO.Path]::DirectorySeparatorChar)
    if ($profile -and $target -eq $profile) {
        throw 'Public export destination cannot be the user profile directory.'
    }
    return $target
}

function Copy-BridgeBackupData {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [string[]]$ExcludedTopLevelNames = @('model_cache')
    )
    $sourcePath = [IO.Path]::GetFullPath($Source)
    $destinationPath = [IO.Path]::GetFullPath($Destination)
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        return [pscustomobject]@{
            SourceExists = $false
            ExcludedPaths = @()
        }
    }
    foreach ($name in $ExcludedTopLevelNames) {
        if ([string]::IsNullOrWhiteSpace($name) -or $name -in @('.', '..') -or $name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
            throw "Invalid Bridge backup exclusion name: $name"
        }
    }

    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
    $excludedPaths = [System.Collections.Generic.List[string]]::new()
    foreach ($item in Get-ChildItem -LiteralPath $sourcePath -Force) {
        if ($item.Name -in $ExcludedTopLevelNames) {
            $excludedPaths.Add("bridge-data/$($item.Name)")
            continue
        }
        Copy-Item -LiteralPath $item.FullName -Destination $destinationPath -Recurse -Force
    }
    return [pscustomobject]@{
        SourceExists = $true
        ExcludedPaths = @($excludedPaths)
    }
}

function New-ChecksumManifest {
    param([Parameter(Mandatory)][string]$Root)
    $rootPath = [IO.Path]::GetFullPath($Root)
    $entries = Get-ChildItem -LiteralPath $rootPath -Recurse -File |
        Where-Object { $_.Name -ne 'checksums.sha256' } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($rootPath.Length).TrimStart('\', '/').Replace('\', '/')
            "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $relative
        }
    [IO.File]::WriteAllLines((Join-Path $rootPath 'checksums.sha256'), [string[]]$entries, [Text.UTF8Encoding]::new($false))
}

function Test-ChecksumManifest {
    param([Parameter(Mandatory)][string]$Root)
    $manifest = Join-Path $Root 'checksums.sha256'
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw 'Backup checksum manifest is missing' }
    foreach ($line in Get-Content -LiteralPath $manifest) {
        if ($line -notmatch '^([a-fA-F0-9]{64})\s{2}(.+)$') { throw "Invalid checksum entry: $line" }
        $path = Get-SafeChildPath -Parent $Root -Child (Join-Path $Root $Matches[2])
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Backup file is missing: $($Matches[2])" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $Matches[1]) { throw "Checksum mismatch: $($Matches[2])" }
    }
    return $true
}

function Export-DockerVolume {
    param(
        [Parameter(Mandatory)][string]$Volume,
        [Parameter(Mandatory)][string]$DestinationDirectory,
        [Parameter(Mandatory)][string]$HelperImage
    )
    if ($Volume -notin @('ai_redis_data', 'ai_chatwoot_storage', 'ai_qdrant_data')) { throw "Unsupported volume: $Volume" }
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
    $hostPath = [IO.Path]::GetFullPath($DestinationDirectory)
    Invoke-Native docker @('run', '--rm', '-v', "${Volume}:/source:ro", '-v', "${hostPath}:/backup", '--entrypoint', 'sh', $HelperImage, '-c', "tar -C /source -czf /backup/$Volume.tar.gz .") | Out-Null
}

function Import-DockerVolume {
    param(
        [Parameter(Mandatory)][string]$Volume,
        [Parameter(Mandatory)][string]$ArchiveDirectory,
        [Parameter(Mandatory)][string]$HelperImage
    )
    if ($Volume -notin @('ai_redis_data', 'ai_chatwoot_storage', 'ai_qdrant_data')) { throw "Unsupported volume: $Volume" }
    $archive = Join-Path $ArchiveDirectory "$Volume.tar.gz"
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "Volume archive is missing: $archive" }
    $hostPath = [IO.Path]::GetFullPath($ArchiveDirectory)
    Invoke-Native docker @('run', '--rm', '-v', "${Volume}:/target", '-v', "${hostPath}:/backup:ro", '--entrypoint', 'sh', $HelperImage, '-c', "find /target -mindepth 1 -delete && tar -C /target -xzf /backup/$Volume.tar.gz") | Out-Null
}

Export-ModuleMember -Function *
