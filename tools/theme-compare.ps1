param(
    [string]$FactoryThemeRoot = "C:\Code\vanjaro-ai\website\Portals\0\vThemes\Basic",
    [string]$BaselineThemeRoot = "C:\Websites\vanjarobaseline\Website\Portals\0\vThemes\Basic",
    [string]$CurrentThemeRoot = "C:\Websites\vanjarocli\Website\Portals\0\vThemes\Basic",
    [string]$BaselineSitePath = "C:\Websites\vanjarobaseline\Website",
    [string]$CurrentSitePath = "C:\Websites\vanjarocli\Website",
    [string]$BaselineDb = "vanjarobaseline",
    [string]$CurrentDb = "vanjarocli",
    [string]$SqlServer = "localhost\CB2016SQLSERVER",
    [string]$BaselineUrl = "http://vanjarobaseline.local/Test-Page",
    [string]$CurrentUrl = "http://vanjarocli.local/VGRT-Home",
    [string]$OutputPath = ""
)

function Get-ThemeFileInfo {
    param([string]$Path)

    if (!(Test-Path $Path)) {
        return [pscustomobject]@{
            Path = $Path
            Exists = $false
            Length = $null
            LastWriteTime = $null
            Hash = $null
        }
    }

    $item = Get-Item $Path
    $hash = (Get-FileHash $Path -Algorithm SHA256).Hash
    [pscustomobject]@{
        Path = $Path
        Exists = $true
        Length = $item.Length
        LastWriteTime = $item.LastWriteTime
        Hash = $hash
    }
}

function Get-ThemeJsonSummary {
    param([string]$ThemeRoot)

    $editorRoot = Join-Path $ThemeRoot "editor"
    if (!(Test-Path $editorRoot)) {
        return @()
    }

    Get-ChildItem -Path $editorRoot -Directory | ForEach-Object {
        $jsonPath = Join-Path $_.FullName "theme.json"
        if (Test-Path $jsonPath) {
            $raw = Get-Content $jsonPath -Raw
            $count = 0
            if (![string]::IsNullOrWhiteSpace($raw)) {
                try {
                    $parsed = $raw | ConvertFrom-Json
                    if ($parsed -is [System.Array]) {
                        $count = $parsed.Count
                    }
                    elseif ($parsed) {
                        $count = 1
                    }
                }
                catch {
                    $count = -1
                }
            }

            [pscustomobject]@{
                CategoryGuid = $_.Name
                Path = $jsonPath
                Count = $count
                Length = (Get-Item $jsonPath).Length
                Hash = (Get-FileHash $jsonPath -Algorithm SHA256).Hash
            }
        }
    }
}

function Invoke-SqlText {
    param(
        [string]$Database,
        [string]$Query
    )

    sqlcmd -S $SqlServer -d $Database -E -W -s "|" -Q $Query
}

function Get-TabShellSummary {
    param([string]$Database)

    Invoke-SqlText -Database $Database -Query "SET NOCOUNT ON; SELECT TabID, TabName, ISNULL(SkinSrc,''), ISNULL(ContainerSrc,'') FROM dbo.Tabs WHERE SkinSrc LIKE '%vanjaro%' OR ContainerSrc LIKE '%vanjaro%' OR TabID IN (21,33,34,35) ORDER BY TabID;"
}

function Get-PortalSummary {
    param([string]$Database)

    Invoke-SqlText -Database $Database -Query "SET NOCOUNT ON; SELECT TOP 1 PortalID, GUID, CreatedOnDate, LastModifiedOnDate FROM dbo.Portals;"
}

function Get-BundleSummary {
    param(
        [string]$Url,
        [string]$SitePath
    )

    $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 15
    $matches = [regex]::Matches($response.Content, 'DependencyHandler\.axd/([^/]+)/([0-9]+)/css')
    $bundles = @()
    foreach ($match in $matches) {
        $bundles += [pscustomobject]@{
            Key = $match.Groups[1].Value
            Version = $match.Groups[2].Value
        }
    }

    $mapPath = Get-ChildItem -Path (Join-Path $SitePath "App_Data\ClientDependency") -Filter "*-map.xml" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName

    [pscustomobject]@{
        Url = $Url
        Bundles = $bundles
        MapPath = $mapPath
    }
}

function Add-MarkdownTable {
    param(
        [string]$Title,
        [object[]]$Rows,
        [string[]]$Columns
    )

    $lines = @("## $Title", "", ("| " + ($Columns -join " | ") + " |"), ("| " + (($Columns | ForEach-Object { "---" }) -join " | ") + " |"))
    foreach ($row in $Rows) {
        $values = foreach ($column in $Columns) {
            $value = $row.$column
            if ($value -is [datetime]) {
                $value.ToString("yyyy-MM-dd HH:mm:ss")
            }
            else {
                [string]$value
            }
        }
        $lines += "| " + ($values -join " | ") + " |"
    }
    $lines += ""
    return $lines
}

$themeFiles = @(
    (Get-ThemeFileInfo (Join-Path $FactoryThemeRoot "Theme.css")),
    (Get-ThemeFileInfo (Join-Path $BaselineThemeRoot "Theme.css")),
    (Get-ThemeFileInfo (Join-Path $CurrentThemeRoot "Theme.css")),
    (Get-ThemeFileInfo (Join-Path $FactoryThemeRoot "Theme.scss")),
    (Get-ThemeFileInfo (Join-Path $BaselineThemeRoot "Theme.scss")),
    (Get-ThemeFileInfo (Join-Path $CurrentThemeRoot "Theme.scss")),
    (Get-ThemeFileInfo (Join-Path $BaselineThemeRoot "theme.editor.js")),
    (Get-ThemeFileInfo (Join-Path $CurrentThemeRoot "theme.editor.js"))
)

$baselineJson = Get-ThemeJsonSummary -ThemeRoot $BaselineThemeRoot
$currentJson = Get-ThemeJsonSummary -ThemeRoot $CurrentThemeRoot
$baselinePortal = Get-PortalSummary -Database $BaselineDb
$currentPortal = Get-PortalSummary -Database $CurrentDb
$baselineTabs = Get-TabShellSummary -Database $BaselineDb
$currentTabs = Get-TabShellSummary -Database $CurrentDb
$baselineBundle = Get-BundleSummary -Url $BaselineUrl -SitePath $BaselineSitePath
$currentBundle = Get-BundleSummary -Url $CurrentUrl -SitePath $CurrentSitePath

$lines = @(
    "# Theme Site Comparison",
    "",
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "",
    "Baseline URL: $BaselineUrl",
    "Current URL: $CurrentUrl",
    ""
)

$lines += Add-MarkdownTable -Title "Theme Files" -Rows $themeFiles -Columns @("Path", "Exists", "Length", "LastWriteTime", "Hash")
$lines += "## Portal Summary"
$lines += ""
$lines += "### Baseline DB (`$BaselineDb`)"
$lines += '```text'
$lines += $baselinePortal
$lines += '```'
$lines += ""
$lines += "### Current DB (`$CurrentDb`)"
$lines += '```text'
$lines += $currentPortal
$lines += '```'
$lines += ""
$lines += "## Tab Shell Summary"
$lines += ""
$lines += "### Baseline"
$lines += '```text'
$lines += $baselineTabs
$lines += '```'
$lines += ""
$lines += "### Current"
$lines += '```text'
$lines += $currentTabs
$lines += '```'
$lines += ""
$lines += Add-MarkdownTable -Title "Baseline Theme JSON" -Rows $baselineJson -Columns @("CategoryGuid", "Count", "Length", "Hash")
$lines += Add-MarkdownTable -Title "Current Theme JSON" -Rows $currentJson -Columns @("CategoryGuid", "Count", "Length", "Hash")
$lines += "## Published Bundles"
$lines += ""
$lines += "### Baseline"
$lines += '```text'
$lines += ($baselineBundle.Bundles | ForEach-Object { "$($_.Key) version $($_.Version)" })
$lines += "Map: $($baselineBundle.MapPath)"
$lines += '```'
$lines += ""
$lines += "### Current"
$lines += '```text'
$lines += ($currentBundle.Bundles | ForEach-Object { "$($_.Key) version $($_.Version)" })
$lines += "Map: $($currentBundle.MapPath)"
$lines += '```'
$lines += ""

$output = $lines -join [Environment]::NewLine
if ($OutputPath) {
    Set-Content -LiteralPath $OutputPath -Value $output
}
else {
    $output
}
