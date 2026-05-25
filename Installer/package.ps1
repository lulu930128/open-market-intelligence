param(
    [string]$Version = "1.0.0",
    [string]$PythonVersion = "3.12.3",
    [switch]$IncludeSeedData,
    [switch]$SkipStockMasterSeed,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$installerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $installerRoot "..")).Path
$cacheRoot = Join-Path $installerRoot "cache"
$runtimeCacheRoot = Join-Path $installerRoot "runtimes"
$stagingRoot = Join-Path $installerRoot "staging"
$outputRoot = Join-Path $installerRoot "output"
$packageName = "OpenMarketIntelligence-TW-v$Version-win-x64"
$packageRoot = Join-Path $stagingRoot $packageName
$zipPath = Join-Path $outputRoot "$packageName.zip"

function New-CleanDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source directory: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source file: $Source"
    }

    $destinationParent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Invoke-Logged {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-GitCommit {
    try {
        $commit = & git -C $repoRoot rev-parse --short HEAD
        if ($LASTEXITCODE -eq 0) {
            return $commit.Trim()
        }
    }
    catch {
    }

    return "unknown"
}

function Ensure-PythonRuntime {
    $runtimeZip = Join-Path $cacheRoot "python-$PythonVersion-embed-amd64.zip"
    $runtimeUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    $pythonTarget = Join-Path $packageRoot "runtime\python"

    New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null

    if (-not (Test-Path -LiteralPath $runtimeZip)) {
        Write-Host "Downloading Python embeddable runtime: $runtimeUrl"
        Invoke-WebRequest -Uri $runtimeUrl -OutFile $runtimeZip
    }

    New-Item -ItemType Directory -Force -Path $pythonTarget | Out-Null
    Expand-Archive -LiteralPath $runtimeZip -DestinationPath $pythonTarget -Force

    $sitePackagesSource = Join-Path $repoRoot ".venv\Lib\site-packages"
    $sitePackagesTarget = Join-Path $pythonTarget "Lib\site-packages"

    if (-not (Test-Path -LiteralPath $sitePackagesSource)) {
        throw "Missing backend dependency cache: $sitePackagesSource. Recreate the repo .venv before packaging."
    }

    New-Item -ItemType Directory -Force -Path $sitePackagesTarget | Out-Null
    Write-Host "Copying backend Python packages..."
    Get-ChildItem -LiteralPath $sitePackagesSource -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $sitePackagesTarget -Recurse -Force
    }

    $pthFile = Get-ChildItem -LiteralPath $pythonTarget -Filter "python*._pth" | Select-Object -First 1
    if ($null -eq $pthFile) {
        throw "Python embeddable ._pth file was not found in $pythonTarget"
    }

    @(
        "python312.zip",
        ".",
        "Lib",
        "Lib\site-packages",
        "..\..\backend",
        "import site"
    ) | Set-Content -LiteralPath $pthFile.FullName -Encoding ASCII

    return (Join-Path $pythonTarget "python.exe")
}

function Copy-NodeRuntime {
    $nodeCommand = Get-Command "node.exe" -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand) {
        throw "node.exe was not found on PATH. Install Node.js on the packaging machine."
    }

    $nodeTarget = Join-Path $packageRoot "runtime\node\node.exe"
    Copy-RequiredFile -Source $nodeCommand.Source -Destination $nodeTarget
    return $nodeTarget
}

function Build-FrontendStandalone {
    $frontendRoot = Join-Path $repoRoot "frontend"

    if (-not $SkipFrontendBuild) {
        Invoke-Logged -FilePath "npm.cmd" -Arguments @("run", "build") -WorkingDirectory $frontendRoot
    }

    $standaloneRoot = Join-Path $frontendRoot ".next\standalone"
    if (-not (Test-Path -LiteralPath $standaloneRoot)) {
        throw "Next standalone output was not found: $standaloneRoot"
    }

    $standaloneAppRoot = if (Test-Path -LiteralPath (Join-Path $standaloneRoot "server.js")) {
        $standaloneRoot
    }
    elseif (Test-Path -LiteralPath (Join-Path $standaloneRoot "frontend\server.js")) {
        Join-Path $standaloneRoot "frontend"
    }
    else {
        throw "Could not locate Next standalone server.js under $standaloneRoot"
    }

    $frontendTarget = Join-Path $packageRoot "frontend"
    Copy-Directory -Source $standaloneAppRoot -Destination $frontendTarget

    $staticSource = Join-Path $frontendRoot ".next\static"
    $staticTarget = Join-Path $frontendTarget ".next\static"
    if (Test-Path -LiteralPath $staticSource) {
        Copy-Directory -Source $staticSource -Destination $staticTarget
    }

    $publicSource = Join-Path $frontendRoot "public"
    $publicTarget = Join-Path $frontendTarget "public"
    if (Test-Path -LiteralPath $publicSource) {
        Copy-Directory -Source $publicSource -Destination $publicTarget
    }

    $envSource = Join-Path $frontendRoot ".env.local"
    if (Test-Path -LiteralPath $envSource) {
        Copy-RequiredFile -Source $envSource -Destination (Join-Path $frontendTarget ".env.local")
    }
}

function Copy-AppFiles {
    Copy-Directory -Source (Join-Path $repoRoot "backend\app") -Destination (Join-Path $packageRoot "backend\app")
    Copy-Directory -Source (Join-Path $repoRoot "backend\alembic") -Destination (Join-Path $packageRoot "backend\alembic")
    Copy-RequiredFile -Source (Join-Path $repoRoot "backend\requirements.txt") -Destination (Join-Path $packageRoot "backend\requirements.txt")
    Copy-RequiredFile -Source (Join-Path $repoRoot "alembic.ini") -Destination (Join-Path $packageRoot "alembic.ini")
    Copy-RequiredFile -Source (Join-Path $repoRoot "Start-OMI-Launcher.cmd") -Destination (Join-Path $packageRoot "Start-OMI-Launcher.cmd")
    Copy-RequiredFile -Source (Join-Path $repoRoot "ATRI-MyDearMoments.ico") -Destination (Join-Path $packageRoot "ATRI-MyDearMoments.ico")

    Copy-Directory -Source (Join-Path $repoRoot "scripts") -Destination (Join-Path $packageRoot "scripts")

    $dataTarget = Join-Path $packageRoot "data"
    New-Item -ItemType Directory -Force -Path $dataTarget | Out-Null

    if ($IncludeSeedData) {
        Copy-RequiredFile `
            -Source (Join-Path $repoRoot "data\open_market_intelligence.db") `
            -Destination (Join-Path $dataTarget "open_market_intelligence.db")
    }

    $seedDescription = if ($IncludeSeedData) {
        "- The package includes the current local SQLite database as seed data."
    }
    elseif (-not $SkipStockMasterSeed) {
        "- The package includes a lightweight stock master seed so stock search works on first launch."
    }
    else {
        "- No seed database is included. Users must import or sync market data before searching stocks."
    }

    @"
Open Market Intelligence - Taiwan Market Watchstation
Version: $Version

How to start:
1. Extract the whole zip folder to a writable location. Do not run the launcher from inside the zip preview.
2. Run Start-OMI-Launcher.cmd.
3. Wait for the tray icon. The dashboard opens automatically after backend and frontend are ready.

Tray menu:
- Open Dashboard: http://127.0.0.1:3000
- Open API Health: http://127.0.0.1:8300/api/system/health
- Open Logs Folder
- Restart Services
- Stop Services

Runtime and data:
- Python and Node are bundled in this package.
- Logs and the writable SQLite database are stored under:
  %LOCALAPPDATA%\Open Market Intelligence
- The package folder itself is treated as read-only application files.
$seedDescription

If Windows blocks the script, right click Start-OMI-Launcher.cmd and choose Run anyway,
or run it from PowerShell after unblocking the downloaded zip.
"@ | Set-Content -LiteralPath (Join-Path $packageRoot "README-FIRST.txt") -Encoding UTF8
}

function New-StockMasterSeedData {
    param([Parameter(Mandatory = $true)][string]$PythonExe)

    if ($IncludeSeedData) {
        Write-Host "Full seed database requested; skipping lightweight stock master seed."
        return
    }

    if ($SkipStockMasterSeed) {
        Write-Host "Lightweight stock master seed disabled."
        return
    }

    $sourceDb = Join-Path $repoRoot "data\open_market_intelligence.db"
    $targetDb = Join-Path $packageRoot "data\open_market_intelligence.db"
    $seedScript = Join-Path $repoRoot "scripts\stock-master-seed.py"

    if (-not (Test-Path -LiteralPath $sourceDb)) {
        throw "Missing source database for stock master seed: $sourceDb"
    }

    if (-not (Test-Path -LiteralPath $seedScript)) {
        throw "Missing stock master seed script: $seedScript"
    }

    Invoke-Logged `
        -FilePath $PythonExe `
        -Arguments @(
            $seedScript,
            "create",
            "--source-db",
            $sourceDb,
            "--target-db",
            $targetDb,
            "--require-stock",
            "2330"
        ) `
        -WorkingDirectory $repoRoot
}

function Write-ReleaseManifest {
    $manifest = [ordered]@{
        app = "Open Market Intelligence"
        edition = "Taiwan Market Watchstation"
        version = $Version
        build_time = (Get-Date).ToString("o")
        commit = Get-GitCommit
        python_version = $PythonVersion
        include_seed_data = [bool]$IncludeSeedData
        stock_master_seed = [bool]((-not $IncludeSeedData) -and (-not $SkipStockMasterSeed))
        frontend_mode = "next-standalone"
        backend_mode = "python-embeddable"
    }

    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $packageRoot "release-manifest.json") -Encoding UTF8
}

function Test-PackagedRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$NodeExe
    )

    Invoke-Logged -FilePath $NodeExe -Arguments @("--version") -WorkingDirectory $packageRoot

    $backendTarget = Join-Path $packageRoot "backend"
    Invoke-Logged `
        -FilePath $PythonExe `
        -Arguments @("-c", "import alembic, fastapi, uvicorn, pandas, sqlalchemy; import app.main; from app.db.migrations import get_head_revision; print('python-runtime-ok', get_head_revision())") `
        -WorkingDirectory $backendTarget
}

New-Item -ItemType Directory -Force -Path $runtimeCacheRoot, $outputRoot | Out-Null
New-CleanDirectory -Path $stagingRoot
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

Write-Host "Packaging $packageName"

Build-FrontendStandalone
Copy-AppFiles
$pythonExe = Ensure-PythonRuntime
$nodeExe = Copy-NodeRuntime
New-StockMasterSeedData -PythonExe $pythonExe
Write-ReleaseManifest
Test-PackagedRuntime -PythonExe $pythonExe -NodeExe $nodeExe

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Creating zip: $zipPath"
Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal

$zipInfo = Get-Item -LiteralPath $zipPath
[PSCustomObject]@{
    Package = $zipInfo.FullName
    SizeMB = [math]::Round($zipInfo.Length / 1MB, 2)
    Version = $Version
    IncludeSeedData = [bool]$IncludeSeedData
}
