param(
    [string]$OutputDirectory = "tests/fixtures/design-image-benchmarks/references"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function New-ReferenceImage {
    param(
        [string]$Path,
        [int]$Width,
        [int]$Height,
        [bool]$Mobile
    )

    $bitmap = [System.Drawing.Bitmap]::new($Width, $Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

    $nav = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 16, 30, 48))
    $hero = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 233, 244, 255))
    $feature = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $ink = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 16, 30, 48))
    $muted = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 72, 88, 104))
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $accent = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 0, 102, 204))
    $border = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 198, 211, 224), 2)
    $brandFont = [System.Drawing.Font]::new("Arial", $(if ($Mobile) { 15 } else { 18 }), [System.Drawing.FontStyle]::Bold)
    $titleFont = [System.Drawing.Font]::new("Arial", $(if ($Mobile) { 23 } else { 33 }), [System.Drawing.FontStyle]::Bold)
    $bodyFont = [System.Drawing.Font]::new("Arial", $(if ($Mobile) { 14 } else { 15 }), [System.Drawing.FontStyle]::Regular)
    $buttonFont = [System.Drawing.Font]::new("Arial", 14, [System.Drawing.FontStyle]::Bold)
    $cardFont = [System.Drawing.Font]::new("Arial", $(if ($Mobile) { 14 } else { 12 }), [System.Drawing.FontStyle]::Bold)

    try {
        $graphics.FillRectangle($nav, 0, 0, $Width, $(if ($Mobile) { 52 } else { 64 }))
        $graphics.DrawString("STANDARD STUDIO", $brandFont, $white, 24, $(if ($Mobile) { 16 } else { 20 }))
        if ($Mobile) {
            $graphics.DrawLine([System.Drawing.Pens]::White, $Width - 48, 19, $Width - 24, 19)
            $graphics.DrawLine([System.Drawing.Pens]::White, $Width - 48, 27, $Width - 24, 27)
            $graphics.DrawLine([System.Drawing.Pens]::White, $Width - 48, 35, $Width - 24, 35)
            $heroTop = 52
            $heroHeight = 298
        }
        else {
            $graphics.DrawString("SERVICES     ABOUT     CONTACT", $bodyFont, $white, $Width - 330, 21)
            $heroTop = 64
            $heroHeight = 276
        }

        $graphics.FillRectangle($hero, 0, $heroTop, $Width, $heroHeight)
        $left = $(if ($Mobile) { 24 } else { 56 })
        $graphics.DrawString("BUILD WITH EVIDENCE", $titleFont, $ink, $left, $heroTop + $(if ($Mobile) { 44 } else { 48 }))
        $graphics.DrawString("Reusable blocks. Predictable editing.", $bodyFont, $muted, $left, $heroTop + $(if ($Mobile) { 104 } else { 112 }))
        $graphics.FillRectangle($accent, $left, $heroTop + $(if ($Mobile) { 160 } else { 174 }), 132, 46)
        $graphics.DrawString("START NOW", $buttonFont, $white, $left + 20, $heroTop + $(if ($Mobile) { 173 } else { 187 }))

        $featureTop = $heroTop + $heroHeight
        $graphics.FillRectangle($feature, 0, $featureTop, $Width, $Height - $featureTop)
        $graphics.DrawString("SERVICES", $brandFont, $ink, $left, $featureTop + 24)
        if ($Mobile) {
            $graphics.DrawRectangle($border, 24, $featureTop + 62, $Width - 48, 76)
            $graphics.DrawString("FAST SETUP", $cardFont, $ink, 42, $featureTop + 88)
            $graphics.DrawRectangle($border, 24, $featureTop + 152, $Width - 48, 76)
            $graphics.DrawString("STANDARD BLOCKS", $cardFont, $ink, 42, $featureTop + 178)
            $graphics.DrawRectangle($border, 24, $featureTop + 242, $Width - 48, 76)
            $graphics.DrawString("EASY EDITING", $cardFont, $ink, 42, $featureTop + 268)
        }
        else {
            $cardWidth = [int](($Width - 144) / 3)
            $graphics.DrawRectangle($border, 56, $featureTop + 66, $cardWidth, 92)
            $graphics.DrawString("FAST SETUP", $cardFont, $ink, 76, $featureTop + 100)
            $graphics.DrawRectangle($border, 72 + $cardWidth, $featureTop + 66, $cardWidth, 92)
            $graphics.DrawString("STANDARD BLOCKS", $cardFont, $ink, 84 + $cardWidth, $featureTop + 100)
            $graphics.DrawRectangle($border, 88 + (2 * $cardWidth), $featureTop + 66, $cardWidth, 92)
            $graphics.DrawString("EASY EDITING", $cardFont, $ink, 104 + (2 * $cardWidth), $featureTop + 100)
        }

        $parent = Split-Path -Parent $Path
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
        foreach ($item in @($nav, $hero, $feature, $ink, $muted, $white, $accent, $border, $brandFont, $titleFont, $bodyFont, $buttonFont, $cardFont)) {
            $item.Dispose()
        }
    }
}

$root = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
New-ReferenceImage -Path (Join-Path $root "image-assisted-agency-desktop.png") -Width 640 -Height 480 -Mobile $false
New-ReferenceImage -Path (Join-Path $root "image-assisted-agency-mobile.png") -Width 390 -Height 700 -Mobile $true
