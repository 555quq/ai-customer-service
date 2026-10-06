#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Destination,
    [string]$ManifestPath = "",
    [switch]$Force,
    [switch]$PassThru
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$projectRoot = Get-ProjectRoot
if (-not $ManifestPath) { $ManifestPath = Join-Path $projectRoot 'config/open-source-export.json' }
$manifestItem = Resolve-PathWithinRoot -Root $projectRoot -RelativePath ([IO.Path]::GetRelativePath($projectRoot, $ManifestPath))
$manifest = Get-Content -Raw -LiteralPath $manifestItem.FullName | ConvertFrom-Json
if ([int]$manifest.schema_version -ne 1) { throw "Unsupported open-source export schema: $($manifest.schema_version)" }

$destinationPath = Assert-SafeExternalDestination -ProjectRoot $projectRoot -Destination $Destination
$destinationParent = Split-Path -Parent $destinationPath
if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
}
if ((Test-Path -LiteralPath $destinationPath) -and -not $Force) {
    throw "Destination already exists. Use -Force to replace it: $destinationPath"
}

$stage = Join-Path $destinationParent (".{0}.{1}.staging" -f (Split-Path -Leaf $destinationPath), [guid]::NewGuid().ToString('N'))
$stage = Assert-SafeExternalDestination -ProjectRoot $projectRoot -Destination $stage

function Test-Excluded([string]$RelativePath) {
    $normalized = $RelativePath.Replace('\', '/')
    $excluded = $false
    foreach ($patternValue in @($manifest.exclude_globs)) {
        $pattern = [string]$patternValue
        $negated = $pattern.StartsWith('!')
        if ($negated) { $pattern = $pattern.Substring(1) }
        if ($normalized -like $pattern) { $excluded = -not $negated }
    }
    return $excluded
}

function Copy-PublicFile([IO.FileInfo]$File) {
    $relative = [IO.Path]::GetRelativePath($projectRoot, $File.FullName).Replace('\', '/')
    if (Test-Excluded $relative) { return }
    if ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Public export refuses symbolic links and reparse points: $($File.FullName)"
    }
    $target = Join-Path $stage $relative
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $target
}

try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    foreach ($relativeRoot in @($manifest.include_roots)) {
        $rootItem = Resolve-PathWithinRoot -Root $projectRoot -RelativePath ([string]$relativeRoot)
        if (-not $rootItem.PSIsContainer) { throw "include_roots entry is not a directory: $relativeRoot" }
        $listed = & git -c core.quotepath=false -C $projectRoot ls-files --cached --others --exclude-standard -- ([string]$relativeRoot)
        if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate public files under: $relativeRoot" }
        foreach ($relativeFile in @($listed)) {
            if ([string]::IsNullOrWhiteSpace($relativeFile)) { continue }
            $fileItem = Resolve-PathWithinRoot -Root $projectRoot -RelativePath ([string]$relativeFile)
            if (-not $fileItem.PSIsContainer) { Copy-PublicFile $fileItem }
        }
    }
    foreach ($relativeFile in @($manifest.include_files)) {
        $fileItem = Resolve-PathWithinRoot -Root $projectRoot -RelativePath ([string]$relativeFile)
        if ($fileItem.PSIsContainer) { throw "include_files entry is not a file: $relativeFile" }
        Copy-PublicFile $fileItem
    }
    foreach ($required in @($manifest.required_files)) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage ([string]$required)) -PathType Leaf)) {
            throw "Required public file was not exported: $required"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $stage '.git')) { throw 'The public export contains .git metadata.' }

    if ($PSCmdlet.ShouldProcess($destinationPath, 'replace with validated open-source export')) {
        if (Test-Path -LiteralPath $destinationPath) {
            $validatedAgain = Assert-SafeExternalDestination -ProjectRoot $projectRoot -Destination $destinationPath
            Remove-Item -LiteralPath $validatedAgain -Recurse -Force
        }
        Move-Item -LiteralPath $stage -Destination $destinationPath
    }

    $files = @(Get-ChildItem -LiteralPath $destinationPath -Recurse -File)
    $result = [pscustomobject]@{
        destination = $destinationPath
        file_count = $files.Count
        total_bytes = [long](($files | Measure-Object Length -Sum).Sum)
        manifest_sha256 = (Get-FileHash -LiteralPath $manifestItem.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if ($PassThru) { $result }
    else { Write-Host "Public export created: $destinationPath ($($result.file_count) files)" -ForegroundColor Green }
} catch {
    if (Test-Path -LiteralPath $stage) {
        $validatedStage = Assert-SafeExternalDestination -ProjectRoot $projectRoot -Destination $stage
        Remove-Item -LiteralPath $validatedStage -Recurse -Force
    }
    throw
}
