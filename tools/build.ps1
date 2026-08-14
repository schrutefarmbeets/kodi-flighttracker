# Validates and packages script.flighttracker into an installable Kodi zip.

$ErrorActionPreference = 'Stop'

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$addonId = 'script.flighttracker'
$src = Join-Path $root $addonId
$dist = Join-Path $root 'dist'

$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}

# ---------------------------------------------------------------- version
[xml]$addonXml = Get-Content (Join-Path $src 'addon.xml')
$version = $addonXml.addon.version
Write-Output "Packaging $addonId v$version"

# ---------------------------------------------------------------- validate XML
$xmlFiles = Get-ChildItem $src -Filter *.xml -Recurse
foreach ($file in $xmlFiles) {
    try {
        [xml](Get-Content $file.FullName -Raw) | Out-Null
    } catch {
        throw "Malformed XML: $($file.FullName) - $($_.Exception.Message)"
    }
}
Write-Output "  XML ok ($($xmlFiles.Count) files)"

# ---------------------------------------------------------------- validate Python
if ($python) {
    $pyFiles = Get-ChildItem $src -Filter *.py -Recurse | ForEach-Object { $_.FullName }
    & $python -m py_compile @pyFiles
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed" }
    Write-Output "  Python ok ($($pyFiles.Count) files)"
} else {
    Write-Output "  Python not found, skipping syntax check"
}

# ---------------------------------------------------------------- media present
$required = @('icon.png', 'fanart.jpg', 'radar_bg.png', 'white.png', 'dot.png', 'home.png',
              'airport.png', 'flap_panel.png', 'plate.png')
0..23 | ForEach-Object { $required += ('plane_{0:d3}.png' -f ($_ * 15)) }
$mediaDir = Join-Path $src 'resources\media'
$missing = $required | Where-Object { -not (Test-Path (Join-Path $mediaDir $_)) }
if ($missing) { throw "Missing media: $($missing -join ', ')" }
Write-Output "  media ok ($($required.Count) files)"

# ---------------------------------------------------------------- stage and zip
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ftbuild_" + [Guid]::NewGuid().ToString('N'))
$stageAddon = Join-Path $stage $addonId
New-Item -ItemType Directory -Path $stageAddon -Force | Out-Null

Copy-Item "$src\*" $stageAddon -Recurse -Force

# Strip build and test leftovers that must not ship.
Get-ChildItem $stageAddon -Include '__pycache__' -Recurse -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem $stageAddon -Include '*.pyc', '*.pyo' -Recurse -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
$testProfile = Join-Path $stageAddon '.testprofile'
if (Test-Path $testProfile) { Remove-Item $testProfile -Recurse -Force }

if (-not (Test-Path $dist)) { New-Item -ItemType Directory -Path $dist | Out-Null }
$zipPath = Join-Path $dist "$addonId-$version.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Entries are written one at a time rather than with CreateFromDirectory,
# because on Windows that helper stores paths with backslashes and Kodi's
# installer only understands forward slashes.
$archive = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in (Get-ChildItem $stage -Recurse -File)) {
        $relative = $file.FullName.Substring($stage.Length).TrimStart('\', '/').Replace('\', '/')
        $entry = $archive.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)
        $entryStream = $entry.Open()
        $fileStream = [System.IO.File]::OpenRead($file.FullName)
        try { $fileStream.CopyTo($entryStream) }
        finally { $fileStream.Dispose(); $entryStream.Dispose() }
    }
} finally {
    $archive.Dispose()
}

Remove-Item $stage -Recurse -Force

$size = [Math]::Round((Get-Item $zipPath).Length / 1KB, 1)
Write-Output "  wrote $zipPath ($size KB)"

# ---------------------------------------------------------------- verify zip
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $names = $zip.Entries | ForEach-Object { $_.FullName }
    $expected = @(
        "$addonId/addon.xml",
        "$addonId/default.py",
        "$addonId/service.py",
        "$addonId/resources/settings.xml",
        "$addonId/resources/lib/gui.py",
        "$addonId/resources/language/resource.language.en_gb/strings.po",
        "$addonId/resources/skins/Default/1080i/script-flighttracker-main.xml",
        "$addonId/resources/media/icon.png"
    )
    $absent = $expected | Where-Object { $names -notcontains $_ }
    if ($absent) { throw "Zip is missing: $($absent -join ', ')" }
    $junk = $names | Where-Object { $_ -match '__pycache__|\.pyc$|\.testprofile' }
    if ($junk) { throw "Zip contains build leftovers: $($junk -join ', ')" }
    Write-Output "  zip verified ($($names.Count) entries)"
} finally {
    $zip.Dispose()
}

Write-Output "Done."
