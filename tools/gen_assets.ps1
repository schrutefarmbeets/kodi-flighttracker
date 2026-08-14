# Generates the PNG assets for script.flighttracker.
# Pure System.Drawing so it runs on stock Windows PowerShell 5.1 (no Python needed).
# Sprites are drawn WHITE with a BLACK outline: Kodi's colorDiffuse multiplies, so the
# white body takes the tint while the black outline stays black and keeps the shape
# readable against a bright radar background.

Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'
$outDir = Join-Path $PSScriptRoot '..\script.flighttracker\resources\media'
$outDir = [System.IO.Path]::GetFullPath($outDir)
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

$SS = 4   # supersample factor for smooth edges

function New-Canvas([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.Clear([System.Drawing.Color]::Transparent)
    return @($bmp, $g)
}

function Save-Downsampled($bmp, [int]$target, [string]$path) {
    $out = New-Object System.Drawing.Bitmap($target, $target, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($out)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0, 0, $target, $target)))
    $g.Dispose()
    $out.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $out.Dispose()
}

# ---------------------------------------------------------------- plane sprites
# Airliner plan view, nose pointing up (heading 0 = north) in a 64x64 box.
$planePts = @(
    @(32,3), @(36,17), @(36,25), @(61,40), @(61,47), @(36,39), @(36,52),
    @(45,59), @(45,63), @(32,58), @(19,63), @(19,59), @(28,52), @(28,39),
    @(3,47), @(3,40), @(28,25), @(28,17)
)

$TARGET = 64
$big = $TARGET * $SS

$whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$outlinePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 0, 0, 0), [float](3 * $SS))
$outlinePen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round

for ($deg = 0; $deg -lt 360; $deg += 15) {
    $pair = New-Canvas $big
    $bmp = $pair[0]; $g = $pair[1]

    $c = [float]($big / 2)
    $g.TranslateTransform($c, $c)
    $g.RotateTransform([float]$deg)
    $g.TranslateTransform(-$c, -$c)

    $pts = New-Object 'System.Drawing.PointF[]' $planePts.Count
    for ($i = 0; $i -lt $planePts.Count; $i++) {
        $pts[$i] = New-Object System.Drawing.PointF([float]($planePts[$i][0] * $SS), [float]($planePts[$i][1] * $SS))
    }

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddPolygon($pts)
    $g.DrawPath($outlinePen, $path)
    $g.FillPath($whiteBrush, $path)
    $path.Dispose()
    $g.Dispose()

    $name = 'plane_{0:d3}.png' -f $deg
    Save-Downsampled $bmp $TARGET (Join-Path $outDir $name)
    $bmp.Dispose()
}

# ---------------------------------------------------------------- unknown-heading dot
$pair = New-Canvas (24 * $SS); $bmp = $pair[0]; $g = $pair[1]
$g.FillEllipse($whiteBrush, [float](5 * $SS), [float](5 * $SS), [float](14 * $SS), [float](14 * $SS))
$g.DrawEllipse($outlinePen, [float](5 * $SS), [float](5 * $SS), [float](14 * $SS), [float](14 * $SS))
$g.Dispose()
Save-Downsampled $bmp 24 (Join-Path $outDir 'dot.png')
$bmp.Dispose()

# ---------------------------------------------------------------- home marker (your window)
$pair = New-Canvas (32 * $SS); $bmp = $pair[0]; $g = $pair[1]
$penW = New-Object System.Drawing.Pen([System.Drawing.Color]::White, [float](2.5 * $SS))
$g.DrawEllipse($penW, [float](6 * $SS), [float](6 * $SS), [float](20 * $SS), [float](20 * $SS))
$g.FillEllipse($whiteBrush, [float](12 * $SS), [float](12 * $SS), [float](8 * $SS), [float](8 * $SS))
$g.Dispose()
Save-Downsampled $bmp 32 (Join-Path $outDir 'home.png')
$bmp.Dispose()

# ---------------------------------------------------------------- airport marker (diamond)
$pair = New-Canvas (24 * $SS); $bmp = $pair[0]; $g = $pair[1]
$dia = New-Object 'System.Drawing.PointF[]' 4
$dia[0] = New-Object System.Drawing.PointF([float](12 * $SS), [float](2 * $SS))
$dia[1] = New-Object System.Drawing.PointF([float](22 * $SS), [float](12 * $SS))
$dia[2] = New-Object System.Drawing.PointF([float](12 * $SS), [float](22 * $SS))
$dia[3] = New-Object System.Drawing.PointF([float](2 * $SS), [float](12 * $SS))
$g.FillPolygon($whiteBrush, $dia)
$g.Dispose()
Save-Downsampled $bmp 24 (Join-Path $outDir 'airport.png')
$bmp.Dispose()

# ---------------------------------------------------------------- 8x8 white (tinted bars/rays)
$sq = New-Object System.Drawing.Bitmap(8, 8, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($sq)
$g.Clear([System.Drawing.Color]::White)
$g.Dispose()
$sq.Save((Join-Path $outDir 'white.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$sq.Dispose()

# ---------------------------------------------------------------- radar background
# No baked compass letters: the radar can be rotated to match the window bearing,
# so N/E/S/W are drawn at runtime as labels that move with the rotation.
$R = 900
$pair = New-Canvas ($R * 2); $bmp = $pair[0]; $g = $pair[1]
$cx = [float]$R; $cy = [float]$R
$maxR = [float]($R - 8)

$ringPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(70, 150, 200, 255), 3.0)
$ringPenBright = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(120, 170, 215, 255), 4.0)
foreach ($f in @(0.25, 0.5, 0.75, 1.0)) {
    $rr = $maxR * $f
    $pen = if ($f -eq 1.0) { $ringPenBright } else { $ringPen }
    $g.DrawEllipse($pen, $cx - $rr, $cy - $rr, $rr * 2, $rr * 2)
}

# cardinal spokes, dashed
$spokePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(45, 150, 200, 255), 2.5)
$spokePen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
for ($a = 0; $a -lt 360; $a += 45) {
    $rad = $a * [Math]::PI / 180.0
    $x2 = $cx + $maxR * [Math]::Sin($rad)
    $y2 = $cy - $maxR * [Math]::Cos($rad)
    $g.DrawLine($spokePen, $cx, $cy, [float]$x2, [float]$y2)
}
$g.Dispose()
Save-Downsampled $bmp 900 (Join-Path $outDir 'radar_bg.png')
$bmp.Dispose()

# ---------------------------------------------------------------- addon icon (512x512)
$pair = New-Canvas (512 * 2); $bmp = $pair[0]; $g = $pair[1]
$g.FillRectangle((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 12, 20, 34))), 0, 0, 1024, 1024)
$icx = 512.0; $icy = 512.0
foreach ($f in @(0.32, 0.58, 0.84)) {
    $rr = 460.0 * $f
    $p = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(90, 120, 190, 255), 7.0)
    $g.DrawEllipse($p, [float]($icx - $rr), [float]($icy - $rr), [float]($rr * 2), [float]($rr * 2))
}
# plane silhouette, nose up-right
$g.TranslateTransform($icx, $icy)
$g.RotateTransform(38.0)
$g.ScaleTransform(11.0, 11.0)
$g.TranslateTransform(-32.0, -32.0)
$ip = New-Object 'System.Drawing.PointF[]' $planePts.Count
for ($i = 0; $i -lt $planePts.Count; $i++) {
    $ip[$i] = New-Object System.Drawing.PointF([float]$planePts[$i][0], [float]$planePts[$i][1])
}
$g.FillPolygon((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 235, 245, 255))), $ip)
$g.ResetTransform()
$g.Dispose()
Save-Downsampled $bmp 512 (Join-Path $outDir 'icon.png')
$bmp.Dispose()

# ---------------------------------------------------------------- fanart (1280x720)
$fb = New-Object System.Drawing.Bitmap(1280, 720, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($fb)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    (New-Object System.Drawing.Point(0, 0)),
    (New-Object System.Drawing.Point(0, 720)),
    [System.Drawing.Color]::FromArgb(255, 16, 28, 48),
    [System.Drawing.Color]::FromArgb(255, 6, 10, 18))
$g.FillRectangle($grad, 0, 0, 1280, 720)
foreach ($f in @(0.3, 0.55, 0.8, 1.05)) {
    $rr = 420.0 * $f
    $p = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(38, 120, 190, 255), 3.0)
    $g.DrawEllipse($p, [float](200 - $rr), [float](620 - $rr), [float]($rr * 2), [float]($rr * 2))
}
$g.Dispose()
$fb.Save((Join-Path $outDir 'fanart.jpg'), [System.Drawing.Imaging.ImageFormat]::Jpeg)
$fb.Dispose()

# ---------------------------------------------------------------- split-flap panel
# One tall strip, stretched to whatever a board row needs. The seam across the
# middle is the signature of a Solari board: two flap halves meeting.
$fh = 256
$flap = New-Object System.Drawing.Bitmap(8, $fh, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
for ($y = 0; $y -lt $fh; $y++) {
    if ($y -eq 127 -or $y -eq 128) {
        $col = [System.Drawing.Color]::FromArgb(255, 6, 6, 5)          # the seam
    } elseif ($y -lt 127) {
        $t = $y / 127.0                                                # upper flap
        $r = [int](42 - 16 * $t); $g = [int](40 - 15 * $t); $b = [int](36 - 14 * $t)
        $col = [System.Drawing.Color]::FromArgb(255, $r, $g, $b)
    } elseif ($y -eq 129) {
        $col = [System.Drawing.Color]::FromArgb(255, 48, 46, 42)       # highlight below seam
    } else {
        $t = ($y - 129) / 126.0                                        # lower flap
        $r = [int](34 - 20 * $t); $g = [int](33 - 19 * $t); $b = [int](30 - 18 * $t)
        $col = [System.Drawing.Color]::FromArgb(255, $r, $g, $b)
    }
    for ($x = 0; $x -lt 8; $x++) { $flap.SetPixel($x, $y, $col) }
}
$flap.Save((Join-Path $outDir 'flap_panel.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$flap.Dispose()

# ---------------------------------------------------------------- logo placard
# Airline logos are full colour and many are dark, so they need a light card to
# sit on. Reads as a printed placard slotted into the board.
$pw = 320; $ph = 170; $radius = 18
# New-Canvas only makes squares, and squashing a square down to 320x170 would
# leave the card filling just the top half of the file. Build it at the real
# aspect instead.
$bmp = New-Object System.Drawing.Bitmap(($pw * $SS), ($ph * $SS), [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)
$plate = New-Object System.Drawing.Drawing2D.GraphicsPath
$d = $radius * 2 * $SS
$w = ($pw - 2) * $SS; $h = ($ph - 2) * $SS; $o = 1 * $SS
$plate.AddArc($o, $o, $d, $d, 180, 90)
$plate.AddArc($o + $w - $d, $o, $d, $d, 270, 90)
$plate.AddArc($o + $w - $d, $o + $h - $d, $d, $d, 0, 90)
$plate.AddArc($o, $o + $h - $d, $d, $d, 90, 90)
$plate.CloseFigure()
$g.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 238, 233, 221))), $plate)
$g.DrawPath((New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 196, 188, 172), [float](2 * $SS))), $plate)
$plate.Dispose()
$g.Dispose()
# non-square, so downsample by hand rather than with the square helper
$plateOut = New-Object System.Drawing.Bitmap($pw, $ph, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g2 = [System.Drawing.Graphics]::FromImage($plateOut)
$g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g2.Clear([System.Drawing.Color]::Transparent)
$g2.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0, 0, $pw, $ph)))
$g2.Dispose()
$plateOut.Save((Join-Path $outDir 'plate.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$plateOut.Dispose()
$bmp.Dispose()

Write-Output ("Wrote {0} files to {1}" -f (Get-ChildItem $outDir).Count, $outDir)
