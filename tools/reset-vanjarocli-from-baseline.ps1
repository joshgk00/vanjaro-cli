[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SourceSiteRoot = 'C:\Websites\vanjarobaseline',
    [string]$TargetSiteRoot = 'C:\Websites\vanjarocli',
    [string]$SourceDb = 'vanjarobaseline',
    [string]$TargetDb = 'vanjarocli',
    [string]$SqlServer = 'localhost\CB2016SQLSERVER',
    [string]$SourceAlias = 'vanjarobaseline.local',
    [string]$TargetAlias = 'vanjarocli.local',
    [string]$BackupRoot = 'C:\Websites\backups\vanjarocli-reset',
    [string]$AppPoolSuffix = '_nvQuickSite',
    [switch]$SkipWebsiteCopy,
    [switch]$SkipDatabaseRestore
)

$ErrorActionPreference = 'Stop'

function Invoke-SqlScalar {
    param(
        [string]$Query
    )

    & 'C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE' `
        -S $SqlServer -E -h -1 -W -Q $Query
}

function Invoke-SqlFileLike {
    param(
        [string]$Query
    )

    & 'C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE' `
        -S $SqlServer -E -b -Q $Query
}

function Get-ConnectionStringPath {
    param(
        [string]$Root
    )

    Join-Path $Root 'Website\web.config'
}

function Set-AppOffline {
    param(
        [string]$WebsiteRoot
    )

    $offlinePath = Join-Path $WebsiteRoot 'app_offline.htm'
    Set-Content -Path $offlinePath -Value '<html><body>Resetting site...</body></html>' -Encoding ASCII
    return $offlinePath
}

function Remove-AppOffline {
    param(
        [string]$Path
    )

    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Update-WebConfigDatabase {
    param(
        [string]$ConfigPath
    )

    $content = Get-Content -Path $ConfigPath -Raw
    $updated = $content -replace [regex]::Escape("Initial Catalog=$SourceDb"), "Initial Catalog=$TargetDb"
    Set-Content -Path $ConfigPath -Value $updated -Encoding UTF8
}

function Backup-Database {
    param(
        [string]$DatabaseName,
        [string]$DestinationPath
    )

    $escapedPath = $DestinationPath.Replace("'", "''")
    $query = "BACKUP DATABASE [$DatabaseName] TO DISK = N'$escapedPath' WITH INIT, COPY_ONLY, FORMAT;"
    Invoke-SqlFileLike -Query $query | Out-Null
}

function Restore-DatabaseFromBackup {
    param(
        [string]$BackupPath
    )

    $escapedBackup = $BackupPath.Replace("'", "''")
    $targetData = (Join-Path $TargetSiteRoot "Database\$($TargetDb)_Data.mdf").Replace("'", "''")
    $targetLog = (Join-Path $TargetSiteRoot "Database\$($TargetDb)_Log.ldf").Replace("'", "''")

    $sourceDbUser = "$SourceAlias$AppPoolSuffix"
    $targetDbUser = "IIS APPPOOL\$TargetAlias$AppPoolSuffix"
    $query = @"
USE [master];
IF DB_ID(N'$TargetDb') IS NOT NULL
BEGIN
    ALTER DATABASE [$TargetDb] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
END;
RESTORE DATABASE [$TargetDb]
FROM DISK = N'$escapedBackup'
WITH REPLACE,
MOVE N'${SourceDb}_Data' TO N'$targetData',
MOVE N'${SourceDb}_Log' TO N'$targetLog';
ALTER DATABASE [$TargetDb] SET MULTI_USER;
UPDATE [$TargetDb].dbo.PortalAlias
SET HTTPAlias = '$TargetAlias'
WHERE HTTPAlias = '$SourceAlias';
USE [$TargetDb];
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$sourceDbUser')
   AND EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'$targetDbUser')
BEGIN
    ALTER USER [$sourceDbUser] WITH LOGIN = [$targetDbUser];
END;
"@

    Invoke-SqlFileLike -Query $query | Out-Null
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runBackupRoot = Join-Path $BackupRoot $timestamp
$currentSiteBackup = Join-Path $runBackupRoot 'current-site'
$dbBackupRoot = Join-Path $runBackupRoot 'database'
$currentDbBackup = Join-Path $dbBackupRoot "$TargetDb-before-reset.bak"
$sourceDbBackup = Join-Path $dbBackupRoot "$SourceDb-source-snapshot.bak"

New-Item -ItemType Directory -Force -Path $currentSiteBackup | Out-Null
New-Item -ItemType Directory -Force -Path $dbBackupRoot | Out-Null

$sourceWebsite = Join-Path $SourceSiteRoot 'Website'
$targetWebsite = Join-Path $TargetSiteRoot 'Website'
$sourceDatabaseDir = Join-Path $SourceSiteRoot 'Database'
$targetDatabaseDir = Join-Path $TargetSiteRoot 'Database'

if (-not (Test-Path $sourceWebsite)) {
    throw "Source website path not found: $sourceWebsite"
}
if (-not (Test-Path $targetWebsite)) {
    throw "Target website path not found: $targetWebsite"
}

Write-Host "Backup root: $runBackupRoot"
Write-Host "Source site: $sourceWebsite"
Write-Host "Target site: $targetWebsite"
Write-Host "Source DB: $SourceDb"
Write-Host "Target DB: $TargetDb"

if (-not $SkipDatabaseRestore) {
    if ($PSCmdlet.ShouldProcess($TargetDb, 'Backup current target database')) {
        Backup-Database -DatabaseName $TargetDb -DestinationPath $currentDbBackup
    }
    if ($PSCmdlet.ShouldProcess($SourceDb, 'Backup source baseline database')) {
        Backup-Database -DatabaseName $SourceDb -DestinationPath $sourceDbBackup
    }
}

$offlinePath = $null

try {
    if (-not $SkipWebsiteCopy) {
        if ($PSCmdlet.ShouldProcess($targetWebsite, 'Take target site offline and back up website files')) {
            $offlinePath = Set-AppOffline -WebsiteRoot $targetWebsite
            robocopy $targetWebsite $currentSiteBackup /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        }

        if ($PSCmdlet.ShouldProcess($targetWebsite, 'Copy baseline website files to target')) {
            robocopy $sourceWebsite $targetWebsite /MIR /R:1 /W:1 /XD 'App_Data\ClientDependency' 'bin' /NFL /NDL /NJH /NJS /NP | Out-Null
            robocopy (Join-Path $sourceWebsite 'bin') (Join-Path $targetWebsite 'bin') /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
            Update-WebConfigDatabase -ConfigPath (Get-ConnectionStringPath -Root $TargetSiteRoot)
        }
    }

    if (-not $SkipDatabaseRestore) {
        if (-not (Test-Path $targetDatabaseDir)) {
            New-Item -ItemType Directory -Force -Path $targetDatabaseDir | Out-Null
        }

        if ($PSCmdlet.ShouldProcess($TargetDb, 'Restore baseline database into target database')) {
            Restore-DatabaseFromBackup -BackupPath $sourceDbBackup
        }
    }
}
finally {
    if ($offlinePath) {
        Remove-AppOffline -Path $offlinePath
    }
}

Write-Host 'Reset complete.'
Write-Host "Website backup: $currentSiteBackup"
Write-Host "Current DB backup: $currentDbBackup"
Write-Host "Source DB backup: $sourceDbBackup"
Write-Host ''
Write-Host 'Post-reset CLI steps:'
Write-Host "  vanjaro auth login --url http://$TargetAlias"
Write-Host '  vanjaro api-key generate'
