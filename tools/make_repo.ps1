# Builds the Kodi repository and publishes it to docs/ for GitHub Pages.
#
# Kodi cannot install from a GitHub repo URL. What it understands is a small
# "repository addon" holding three URLs: an index (addons.xml), a checksum of
# that index, and a base directory to fetch zips from. You install the
# repository addon once; after that every version bump shows up in Kodi's
# normal add-on update flow.
#
# Why GitHub Pages rather than raw.githubusercontent.com: adding a source in
# Kodi makes it LIST the directory, and raw.githubusercontent 404s on any
# directory path, so the source can never be added. Pages serves a real site,
# and the index.html files written here give Kodi something to list.
#
# Usage:
#   .\tools\make_repo.ps1 -GitHubUser schrutefarmbeets
#   .\tools\make_repo.ps1 -GitHubUser schrutefarmbeets -RepoName kodi-flighttracker

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GitHubUser,
    [string]$RepoName = 'kodi-flighttracker',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$addonId = 'script.flighttracker'
$repoId = 'repository.flighttracker'
$src = Join-Path $root $addonId
$dist = Join-Path $root 'dist'
$out = Join-Path $root 'docs'

$base = "https://$GitHubUser.github.io/$RepoName/"
Write-Output "Publishing to: $base"

if (-not $SkipBuild) { & (Join-Path $PSScriptRoot 'build.ps1') }

[xml]$addonXml = Get-Content (Join-Path $src 'addon.xml')
$addonVersion = $addonXml.addon.version
$addonZip = Join-Path $dist "$addonId-$addonVersion.zip"
if (-not (Test-Path $addonZip)) { throw "Missing $addonZip - run tools\build.ps1 first" }

# Kodi's XML parser trips over a byte order mark in addons.xml.
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-TextFile([string]$path, [string]$content) {
    [System.IO.File]::WriteAllText($path, $content, $utf8)
}

# ---------------------------------------------------------------- repository addon
$repoVersion = '1.0.0'
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ftrepo_" + [Guid]::NewGuid().ToString('N'))
$repoAddonDir = Join-Path $stage $repoId
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

# ---------------------------------------------------------------- lay out docs/
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

New-AddonZip $stage (Join-Path $repoTarget "$repoId-$repoVersion.zip")
Copy-Item (Join-Path $repoAddonDir 'icon.png') (Join-Path $repoTarget 'icon.png') -Force

Copy-Item $addonZip (Join-Path $addonTarget "$addonId-$addonVersion.zip") -Force
Copy-Item (Join-Path $src 'resources\media\icon.png') (Join-Path $addonTarget 'icon.png') -Force
Copy-Item (Join-Path $src 'resources\media\fanart.jpg') (Join-Path $addonTarget 'fanart.jpg') -Force
Copy-Item (Join-Path $src 'changelog.txt') (Join-Path $addonTarget 'changelog.txt') -Force

# ---------------------------------------------------------------- addons.xml
function Get-AddonBody([string]$path) {
    $text = [System.IO.File]::ReadAllText($path)
    $text = [regex]::Replace($text, '^\s*<\?xml[^>]*\?>\s*', '')
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

# Kodi hashes the bytes it fetches and compares, so this must be the hash of
# exactly the bytes written above.
$md5 = [System.Security.Cryptography.MD5]::Create()
$hash = ($md5.ComputeHash([System.IO.File]::ReadAllBytes($addonsPath)) |
         ForEach-Object { $_.ToString('x2') }) -join ''
Write-TextFile (Join-Path $out 'addons.xml.md5') $hash

# Stops GitHub Pages running the files through Jekyll.
Write-TextFile (Join-Path $out '.nojekyll') ''

Remove-Item $stage -Recurse -Force

# ---------------------------------------------------------------- index pages
# Kodi lists an HTTP source by parsing anchors out of the returned HTML, so
# every directory needs one of these or the source cannot be browsed.
function Write-Index([string]$dir, [string]$title, [string]$parent) {
    $entries = Get-ChildItem $dir | Where-Object { $_.Name -ne 'index.html' -and $_.Name -ne '.nojekyll' } |
        Sort-Object { -not $_.PSIsContainer }, Name
    $rows = foreach ($e in $entries) {
        $name = if ($e.PSIsContainer) { "$($e.Name)/" } else { $e.Name }
        $size = if ($e.PSIsContainer) { '' } else { '{0:N1} KB' -f ($e.Length / 1KB) }
        "  <li><a href=`"$name`">$name</a> <span>$size</span></li>"
    }
    $up = if ($parent) { "  <li><a href=`"$parent`">../</a></li>`n" } else { '' }
    $html = @"
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>$title</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 3rem auto;
         padding: 0 1rem; line-height: 1.6; }
  h1 { font-size: 1.3rem; }
  ul { list-style: none; padding: 0; }
  li { padding: .35rem 0; border-bottom: 1px solid #e5e5e5; display: flex;
       justify-content: space-between; }
  span { color: #777; font-variant-numeric: tabular-nums; }
  code { background: #f4f4f4; padding: .15rem .35rem; border-radius: 3px; }
</style>
<h1>$title</h1>
<ul>
$up$($rows -join "`n")
</ul>
</html>
"@
    Write-TextFile (Join-Path $dir 'index.html') $html
}

Write-Index $repoTarget  "$repoId" '../'
Write-Index $addonTarget "$addonId" '../'
Write-Index $out         "Flight Tracker Kodi repository" ''

# ---------------------------------------------------------------- verify
[xml]$check = Get-Content $addonsPath
$ids = $check.addons.addon | ForEach-Object { $_.id }
if ($ids -notcontains $addonId) { throw "addons.xml is missing $addonId" }
if ($ids -notcontains $repoId) { throw "addons.xml is missing $repoId" }

Write-Output ""
Write-Output "docs/ built:"
Get-ChildItem $out -Recurse -File -Force | ForEach-Object {
    $rel = $_.FullName.Substring($out.Length).TrimStart('\').Replace('\', '/')
    "  {0,-58} {1,8:N1} KB" -f $rel, ($_.Length / 1KB)
}
Write-Output ""
Write-Output "addons.xml.md5 : $hash"
Write-Output ""
Write-Output "Source to add in Kodi:"
Write-Output "  $base"
Write-Output "Repository zip:"
Write-Output "  ${base}$repoId/$repoId-$repoVersion.zip"
