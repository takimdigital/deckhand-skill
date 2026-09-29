Add-Type -AssemblyName System.Drawing

$W = 1280; $H = 640
$bmp = New-Object System.Drawing.Bitmap($W, $H)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = 'AntiAlias'
$g.TextRenderingHint = 'ClearTypeGridFit'
$g.InterpolationMode = 'HighQualityBicubic'

function RoundRect($x, $y, $w, $h, $r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = 2 * $r
  $p.AddArc($x, $y, $d, $d, 180, 90)
  $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
  $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

# --- background: slate gradient + soft accent glows ---
$bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
  (New-Object System.Drawing.Point(0, 0)),
  (New-Object System.Drawing.Point($W, $H)),
  [System.Drawing.Color]::FromArgb(255, 13, 20, 36),
  [System.Drawing.Color]::FromArgb(255, 9, 14, 26))
$g.FillRectangle($bg, 0, 0, $W, $H)

foreach ($glow in @(
  @(990, 110, 330, 230, 249, 115, 22, 16),
  @(140, 600, 380, 270, 56, 189, 248, 8)
)) {
  $cx = $glow[0]; $cy = $glow[1]; $rx = $glow[2]; $ry = $glow[3]
  $col = [System.Drawing.Color]::FromArgb($glow[7], $glow[4], $glow[5], $glow[6])
  $br = New-Object System.Drawing.SolidBrush($col)
  $g.FillEllipse($br, $cx - $rx, $cy - $ry, 2 * $rx, 2 * $ry)
  $br.Dispose()
}

# --- logo (scaled 1.625x from the 128 viewBox), placed at (96, 216) ---
$ox = 96; $oy = 216; $s = 1.625

$tilePath = RoundRect ($ox + 8 * $s) ($oy + 8 * $s) (112 * $s) (112 * $s) (26 * $s)
$tileBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
  (New-Object System.Drawing.Point($ox, $oy)),
  (New-Object System.Drawing.Point(($ox + 128 * $s), ($oy + 128 * $s))),
  [System.Drawing.Color]::FromArgb(255, 30, 41, 59),
  [System.Drawing.Color]::FromArgb(255, 15, 23, 42))
$tilePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 51, 65, 85), 2.4)
$g.FillPath($tileBrush, $tilePath)
$g.DrawPath($tilePen, $tilePath)

$padBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 71, 85, 105))
$g.FillPath($padBrush, (RoundRect ($ox + 36 * $s) ($oy + 94 * $s) (56 * $s) (11 * $s) (5.5 * $s)))

$flameBrushRect = New-Object System.Drawing.RectangleF(($ox + 41 * $s), ($oy + 16 * $s), (46 * $s), (78 * $s))
$flameBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
  $flameBrushRect,
  [System.Drawing.Color]::FromArgb(255, 253, 230, 138),
  [System.Drawing.Color]::FromArgb(255, 249, 115, 22),
  [System.Drawing.Drawing2D.LinearGradientMode]::Vertical)
$g.FillPath($flameBrush, (RoundRect ($ox + 57.5 * $s) ($oy + 50 * $s) (13 * $s) (42 * $s) (6.5 * $s)))
$headPts = @(
  (New-Object System.Drawing.PointF(($ox + 64 * $s), ($oy + 16 * $s))),
  (New-Object System.Drawing.PointF(($ox + 87 * $s), ($oy + 50 * $s))),
  (New-Object System.Drawing.PointF(($ox + 41 * $s), ($oy + 50 * $s)))
)
$g.FillPolygon($flameBrush, $headPts)

# --- text block ---
$tx = 96 + 128 * $s + 56
$fWhite  = New-Object System.Drawing.Font('Segoe UI', 72, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$fOrange = New-Object System.Drawing.Font('Segoe UI', 29, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$fSlate  = New-Object System.Drawing.Font('Segoe UI', 29, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$fChip   = New-Object System.Drawing.Font('Segoe UI', 21, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$fUrl    = New-Object System.Drawing.Font('Segoe UI', 21, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)

$brWhite  = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 248, 250, 252))
$brOrange = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 251, 146, 60))
$brSlate  = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 148, 163, 184))
$brMuted  = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 100, 116, 139))

$g.DrawString('Deckhand', $fWhite, $brWhite, [float]$tx, [float]150)

$l1a = 'Bring a $5 server and a $10 domain.'
$l1b = ' Your agent'
$g.DrawString($l1a, $fOrange, $brOrange, [float]$tx, [float]272)
$wA = $g.MeasureString($l1a, $fOrange).Width
$g.DrawString($l1b, $fSlate, $brSlate, [float]($tx + $wA), [float]272)
$g.DrawString('turns it into a live business - you go find the clients.', $fSlate, $brSlate, [float]$tx, [float]316)

# chips
$chipY = 388; $chipH = 48
$chipBorder = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 30, 41, 59), 1.6)
$chipBg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 17, 26, 46))
$brChipText = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 203, 213, 225))
$cx2 = $tx
foreach ($label in @('Claude Code', 'Codex', 'Cursor', 'Hermes')) {
  $tw = $g.MeasureString($label, $fChip).Width
  $cw = $tw + 44
  $g.FillPath($chipBg, (RoundRect $cx2 $chipY $cw $chipH 24))
  $g.DrawPath($chipBorder, (RoundRect $cx2 $chipY $cw $chipH 24))
  $g.DrawString($label, $fChip, $brChipText, [float]($cx2 + 22), [float]($chipY + 10))
  $cx2 = $cx2 + $cw + 12
}

$g.DrawString('github.com/takimdigital/deckhand', $fUrl, $brMuted, [float]$tx, [float]472)

$out = Join-Path $PSScriptRoot 'social-preview.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$fi = Get-Item $out
Write-Output ("done: {0} ({1} bytes)" -f $fi.FullName, $fi.Length)
