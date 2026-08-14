# Builds the Kodi repository tree that lets Kodi auto-update the addon.
#
# Kodi cannot install from a GitHub repo URL. What it understands is a small
# "repository addon" holding three URLs: an index (addons.xml), a checksum of
# that index, and a base directory to fetch zips from. You install the
# repository addon once; after that every version bump shows up in Kodi's
# normal add-on update flow.
#
# Usage:
#   .\tools\make_repo.ps1 -GitHubUser yourname
#   .\tools\make_repo.ps1 -GitHubUser yourname -RepoName kodi-flighttracker -Branch main
#
# The files must be served over plain HTTPS with no credentials, so the GitHub
# repo has to be public. A private one returns 404 to Kodi.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GitHubUser,
    [string]$RepoName = 'kodi-flighttracker',
    [string]$Branch = 'main',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$addonId = 'script.flighttracker'
$repoId = 'repository.flighttracker'
$src = Join-Path $root $addonId
$dist = Join-Path $root 'dist'
$out = Join-Path $root 'repo'

# Served from a subdirectory, not the repo root: the source tree already has a
# script.flighttracker/ folder, and the published zips need a folder of exactly
# that name too. Keeping them apart avoids the collision.
$base = "https://raw.githubusercontent.com/$GitHubUser/$RepoName/$Branch/repo/"
Write-Output "Repository base URL: $base"

# ---------------------------------------------------------------- build addon zip
if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build.ps1')
}

[xml]$addonXml = Get-Content (Join-Path $src 'addon.xml')
$addonVersion = $addonXml.addon.version
$addonZip = Join-Path $dist "$addonId-$addonVersion.zip"
if (-not (Test-Path $addonZip)) { throw "Missing $addonZip - run tools\build.ps1 first" }

# ---------------------------------------------------------------- utf8, no BOM
# Kodi's XML parser trips over a byte order mark in addons.xml.
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-TextFile([string]$path, [string]$content) {
    [System.IO.File]::WriteAllText($path, $content, $utf8)
}

# ---------------------------------------------------------------- repository addon
$repoVersion = '1.0.0'
$repoStage = Join-Path ([System.IO.Path]::GetTempPath()) ("ftrepo_" + [Guid]::NewGuid().ToString('N'))
$repoAddonDir = Join-Path $repoStage $repoId
New-Item -ItemType Directory -Path $repoAddonDir -Force | Out-Null

$repoAddonXml = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="$repoId"
       name="Flight Tracker Repository"
       version="$repoVersion"
       provider-name="$GitHubUser">
  <extension point="xbmc.addon.repository" name="Flight Tracker Repository">
    <dir>
      <info compressed="false">${base}addons.xml</info>
      <checksum>${base}addons.xml.md5</checksum>
      <datadir zip="true">$base</datadir>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_gb">Updates for Flight Tracker</summary>
    <description lang="en_gb">Install this once and Kodi will offer Flight Tracker updates as they are published.</description>
    <platform>all</platform>
    <license>MIT</license>
    <assets>
      <icon>icon.png</icon>
    </assets>
  </extension>
</addon>
"@

Write-TextFile (Join-Path $repoAddonDir 'addon.xml') $repoAddonXml
Copy-Item (Join-Path $src 'resources\media\icon.png') (Join-Path $repoAddonDir 'icon.png') -Force

# ---------------------------------------------------------------- lay out repo/
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Path $out -Force | Out-Null

$repoTarget = Join-Path $out $repoId
$addonTarget = Join-Path $out $addonId
New-Item -ItemType Directory -Path $repoTarget -Force | Out-Null
New-Item -ItemType Directory -Path $addonTarget -Force | Out-Null

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Entries are written by hand so paths use forward slashes; Kodi's installer
# rejects archives that store Windows-style backslashes.
function New-AddonZip([string]$sourceRoot, [string]$zipPath) {
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    $archive = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in (Get-ChildItem $sourceRoot -Recurse -File)) {
            $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\', '/').Replace('\', '/')
            $entry = $archive.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)
            $entryStream = $entry.Open()
            $fileStream = [System.IO.File]::OpenRead($file.FullName)
            try { $fileStream.CopyTo($entryStream) } finally { $fileStream.Dispose(); $entryStream.Dispose() }
        }
    } finally { $archive.Dispose() }
}

New-AddonZip $repoStage (Join-Path $repoTarget "$repoId-$repoVersion.zip")
Copy-Item (Join-Path $repoAddonDir 'icon.png') (Join-Path $repoTarget 'icon.png') -Force

Copy-Item $addonZip (Join-Path $addonTarget "$addonId-$addonVersion.zip") -Force
Copy-Item (Join-Path $src 'resources\media\icon.png') (Join-Path $addonTarget 'icon.png') -Force
Copy-Item (Join-Path $src 'resources\media\fanart.jpg') (Join-Path $addonTarget 'fanart.jpg') -Force
Copy-Item (Join-Path $src 'changelog.txt') (Join-Path $addonTarget 'changelog.txt') -Force

# ---------------------------------------------------------------- addons.xml
function Get-AddonBody([string]$path) {
    $text = [System.IO.File]::ReadAllText($path)
    # Drop the XML declaration; addons.xml carries its own.
    $text = [regex]::Replace($text, '^\s*<\?xml[^>]*\?>\s*', '')
    # Comments are legal but only add weight to a file Kodi fetches often.
    $text = [regex]::Replace($text, '(?s)<!--.*?-->\s*', '')
    return $text.TrimEnd()
}

$bodies = @(
    (Get-AddonBody (Join-Path $repoAddonDir 'addon.xml'))
    (Get-AddonBody (Join-Path $src 'addon.xml'))
)

$addonsXml = "<?xml version=`"1.0`" encoding=`"UTF-8`" standalone=`"yes`"?>`n<addons>`n" +
             ($bodies -join "`n") + "`n</addons>`n"
$addonsPath = Join-Path $out 'addons.xml'
Write-TextFile $addonsPath $addonsXml

# Kodi compares this against its own hash of the fetched addons.xml, so it must
# be the hash of the exact bytes written above.
$md5 = [System.Security.Cryptography.MD5]::Create()
$hash = ($md5.ComputeHash([System.IO.File]::ReadAllBytes($addonsPath)) |
         ForEach-Object { $_.ToString('x2') }) -join ''
Write-TextFile (Join-Path $out 'addons.xml.md5') $hash

Remove-Item $repoStage -Recurse -Force

# ---------------------------------------------------------------- verify
[xml]$check = Get-Content $addonsPath
$ids = $check.addons.addon | ForEach-Object { $_.id }
if ($ids -notcontains $addonId) { throw "addons.xml is missing $addonId" }
if ($ids -notcontains $repoId) { throw "addons.xml is missing $repoId" }

Write-Output ""
Write-Output "repo/ built:"
Get-ChildItem $out -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($out.Length).TrimStart('\').Replace('\', '/')
    "  {0,-58} {1,8:N1} KB" -f $rel, ($_.Length / 1KB)
}
Write-Output ""
Write-Output "addons.xml lists: $($ids -join ', ')"
Write-Output "addons.xml.md5  : $hash"
Write-Output ""
Write-Output "Install on the TV once:"
Write-Output "  ${base}$repoId/$repoId-$repoVersion.zip"
