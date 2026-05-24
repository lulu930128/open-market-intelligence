$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Application]::EnableVisualStyles()

$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$script:BackendDir = Join-Path $script:RepoRoot "backend"
$script:FrontendDir = Join-Path $script:RepoRoot "frontend"
$script:TrayIconPath = Join-Path $script:RepoRoot "ATRI-MyDearMoments.ico"
$script:TrayIcon = $null
$script:IsPackagedRelease = Test-Path -LiteralPath (Join-Path $script:RepoRoot "release-manifest.json")
$script:AppDataRoot = if ($script:IsPackagedRelease) {
    Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Open Market Intelligence"
}
else {
    $script:RepoRoot
}
$script:LogRoot = Join-Path $script:AppDataRoot "logs"
$script:DataRoot = Join-Path $script:AppDataRoot "data"
$script:DatabasePath = Join-Path $script:DataRoot "open_market_intelligence.db"
$script:ServiceRunner = Join-Path $PSScriptRoot "run-service-logged.ps1"
$script:PackagedPython = Join-Path $script:RepoRoot "runtime\python\python.exe"
$script:PackagedNode = Join-Path $script:RepoRoot "runtime\node\node.exe"
$script:BackendProcess = $null
$script:FrontendProcess = $null
$script:LastStatusText = $null
$script:IsShuttingDown = $false
$script:DashboardAutoOpened = $false

New-Item -ItemType Directory -Force -Path $script:LogRoot | Out-Null
New-Item -ItemType Directory -Force -Path $script:DataRoot | Out-Null

function Get-DailyLogPath {
    param(
        [Parameter(Mandatory = $true)][string]$Category,
        [Parameter(Mandatory = $true)][string]$FileName
    )

    $dateFolder = Get-Date -Format "yyyy-MM-dd"
    $directory = Join-Path (Join-Path $script:LogRoot $Category) $dateFolder
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    return (Join-Path $directory $FileName)
}

function Write-LauncherLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$Level = "INFO"
    )

    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath (Get-DailyLogPath "launcher" "launcher.log") -Value $line -Encoding UTF8
}

function Show-Message {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$Title = "Open Market Intelligence"
    )

    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

$script:Mutex = New-Object System.Threading.Mutex($false, "OpenMarketIntelligenceLauncher")
if (-not $script:Mutex.WaitOne(0, $false)) {
    Show-Message "OMI Launcher is already running."
    exit 0
}

Write-LauncherLog "Launcher started. repo_root=$($script:RepoRoot)"
Write-LauncherLog "Logs root: $($script:LogRoot). Daily folders: backend, frontend, launcher."
Write-LauncherLog "Packaged release mode: $($script:IsPackagedRelease). app_data_root=$($script:AppDataRoot)"

function ConvertTo-SqliteUrl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $absolutePath = [System.IO.Path]::GetFullPath($Path)
    return "sqlite:///$($absolutePath.Replace('\', '/'))"
}

function Initialize-ReleaseEnvironment {
    if (-not $script:IsPackagedRelease) {
        return
    }

    $seedDatabasePath = Join-Path $script:RepoRoot "data\open_market_intelligence.db"

    if ((-not (Test-Path -LiteralPath $script:DatabasePath)) -and
        (Test-Path -LiteralPath $seedDatabasePath)) {
        Write-LauncherLog "Copying seed database to app data. source=$seedDatabasePath target=$($script:DatabasePath)"
        Copy-Item -LiteralPath $seedDatabasePath -Destination $script:DatabasePath -Force
    }

    $env:APP_ENV = "production"
    $env:DATABASE_URL = ConvertTo-SqliteUrl $script:DatabasePath
    $env:API_PROXY_TARGET = "http://127.0.0.1:8300"
    $env:API_PROXY_PATH = "/omi-data"
    $env:NEXT_PUBLIC_API_PROXY_PATH = "/omi-data"
    $env:NEXT_PUBLIC_API_BASE_URL = ""
    $env:HOSTNAME = "127.0.0.1"
    $env:PORT = "3000"

    Write-LauncherLog "Release environment initialized. database=$($script:DatabasePath)"
}

Initialize-ReleaseEnvironment

function Test-HttpOk {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 1500
        $request.ReadWriteTimeout = 1500
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode
        $response.Close()
        return ($statusCode -ge 200 -and $statusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Test-ProcessRunning {
    param($Process)

    if ($null -eq $Process) {
        return $false
    }

    try {
        $Process.Refresh()
        return (-not $Process.HasExited)
    }
    catch {
        return $false
    }
}

function Get-TrayIcon {
    if ($null -ne $script:TrayIcon) {
        return $script:TrayIcon
    }

    if (Test-Path -LiteralPath $script:TrayIconPath) {
        try {
            $script:TrayIcon = New-Object System.Drawing.Icon($script:TrayIconPath)
            Write-LauncherLog "Loaded tray icon: $($script:TrayIconPath)"
            return $script:TrayIcon
        }
        catch {
            Write-LauncherLog "Failed to load tray icon. path=$($script:TrayIconPath) error=$($_.Exception.Message)" "ERROR"
        }
    }
    else {
        Write-LauncherLog "Tray icon file not found: $($script:TrayIconPath)" "WARN"
    }

    return [System.Drawing.SystemIcons]::Application
}

function Stop-ProcessTree {
    param(
        $Process,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-ProcessRunning $Process)) {
        Write-LauncherLog "$Name is not running."
        return
    }

    try {
        Write-LauncherLog "Stopping $Name pid=$($Process.Id)."
        $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
        Start-Process -FilePath $taskkill -ArgumentList @("/PID", "$($Process.Id)", "/T", "/F") -Wait -WindowStyle Hidden | Out-Null
        Write-LauncherLog "$Name stopped."
    }
    catch {
        Write-LauncherLog "Failed to stop $Name. error=$($_.Exception.Message)" "ERROR"
    }
}

function Start-LoggedService {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    if (-not (Test-Path -LiteralPath $script:ServiceRunner)) {
        throw "Missing service log runner: $($script:ServiceRunner)"
    }

    $argumentsJson = $Arguments | ConvertTo-Json -Compress
    $argumentsJsonBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($argumentsJson))
    $runnerArguments = @(
        "-NoProfile",
        "-ExecutionPolicy Bypass",
        "-File `"$($script:ServiceRunner)`"",
        "-ServiceName `"$ServiceName`"",
        "-RepoRoot `"$($script:RepoRoot)`"",
        "-WorkingDirectory `"$WorkingDirectory`"",
        "-FilePath `"$FilePath`"",
        "-ArgumentsJsonBase64 $argumentsJsonBase64"
    ) -join " "

    return Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $runnerArguments `
        -WorkingDirectory $script:RepoRoot `
        -WindowStyle Hidden `
        -PassThru
}

function Start-Backend {
    if (Test-HttpOk "http://127.0.0.1:8300/api/system/health") {
        Write-LauncherLog "Backend health endpoint already responds; skipping backend start."
        return
    }

    if (Test-ProcessRunning $script:BackendProcess) {
        Write-LauncherLog "Backend process is already tracked pid=$($script:BackendProcess.Id)."
        return
    }

    $python = if ($script:IsPackagedRelease -and (Test-Path -LiteralPath $script:PackagedPython)) {
        $script:PackagedPython
    }
    else {
        Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    }

    if (-not (Test-Path -LiteralPath $python)) {
        throw "Missing Python executable: $python"
    }

    if (-not (Test-Path -LiteralPath $script:BackendDir)) {
        throw "Missing backend directory: $($script:BackendDir)"
    }

    Write-LauncherLog "Starting backend with $python."
    $backendArguments = if ($script:IsPackagedRelease) {
        @("-m", "uvicorn", "app.main:app", "--port", "8300")
    }
    else {
        @("-m", "uvicorn", "app.main:app", "--reload", "--port", "8300")
    }

    $script:BackendProcess = Start-LoggedService `
        -ServiceName "backend" `
        -FilePath $python `
        -Arguments $backendArguments `
        -WorkingDirectory $script:BackendDir
    Write-LauncherLog "Backend started pid=$($script:BackendProcess.Id)."
}

function Start-Frontend {
    if (Test-HttpOk "http://127.0.0.1:3000") {
        Write-LauncherLog "Frontend already responds; skipping frontend start."
        return
    }

    if (Test-ProcessRunning $script:FrontendProcess) {
        Write-LauncherLog "Frontend process is already tracked pid=$($script:FrontendProcess.Id)."
        return
    }

    if (-not (Test-Path -LiteralPath $script:FrontendDir)) {
        throw "Missing frontend directory: $($script:FrontendDir)"
    }

    if ($script:IsPackagedRelease) {
        $serverScript = Join-Path $script:FrontendDir "server.js"

        if (-not (Test-Path -LiteralPath $script:PackagedNode)) {
            throw "Missing packaged Node executable: $($script:PackagedNode)"
        }

        if (-not (Test-Path -LiteralPath $serverScript)) {
            throw "Missing packaged frontend server: $serverScript"
        }

        Write-LauncherLog "Starting packaged frontend with $($script:PackagedNode)."
        $script:FrontendProcess = Start-LoggedService `
            -ServiceName "frontend" `
            -FilePath $script:PackagedNode `
            -Arguments @($serverScript) `
            -WorkingDirectory $script:FrontendDir
        Write-LauncherLog "Frontend started pid=$($script:FrontendProcess.Id)."
        return
    }

    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $npm) {
        throw "npm.cmd was not found on PATH. Install Node.js/npm or open the launcher from a shell with npm available."
    }

    Write-LauncherLog "Starting frontend with $($npm.Source)."
    $script:FrontendProcess = Start-LoggedService `
        -ServiceName "frontend" `
        -FilePath $npm.Source `
        -Arguments @("run", "dev") `
        -WorkingDirectory $script:FrontendDir
    Write-LauncherLog "Frontend started pid=$($script:FrontendProcess.Id)."
}

function Start-Services {
    try {
        Start-Backend
    }
    catch {
        Write-LauncherLog "Backend start failed. error=$($_.Exception.Message)" "ERROR"
        Show-Message "Backend failed to start. Check logs\launcher for details."
    }

    try {
        Start-Frontend
    }
    catch {
        Write-LauncherLog "Frontend start failed. error=$($_.Exception.Message)" "ERROR"
        Show-Message "Frontend failed to start. Check logs\launcher for details."
    }
}

function Stop-Services {
    Stop-ProcessTree $script:FrontendProcess "frontend"
    Stop-ProcessTree $script:BackendProcess "backend"
    $script:FrontendProcess = $null
    $script:BackendProcess = $null
}

function Restart-Services {
    Write-LauncherLog "Restart requested."
    Stop-Services
    Start-Sleep -Seconds 1
    Start-Services
}

function Open-Url {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        Start-Process $Url | Out-Null
        Write-LauncherLog "Opened URL: $Url"
    }
    catch {
        Write-LauncherLog "Failed to open URL: $Url; error=$($_.Exception.Message)" "ERROR"
    }
}

function Open-LogsFolder {
    try {
        Start-Process explorer.exe $script:LogRoot | Out-Null
        Write-LauncherLog "Opened logs folder: $($script:LogRoot)"
    }
    catch {
        Write-LauncherLog "Failed to open logs folder. error=$($_.Exception.Message)" "ERROR"
    }
}

$script:NotifyIcon = New-Object System.Windows.Forms.NotifyIcon
$script:NotifyIcon.Icon = Get-TrayIcon
$script:NotifyIcon.Text = "OMI Launcher: starting"
$script:NotifyIcon.Visible = $true

$script:Menu = New-Object System.Windows.Forms.ContextMenuStrip
$script:StatusItem = New-Object System.Windows.Forms.ToolStripMenuItem
$script:StatusItem.Text = "Status: starting"
$script:StatusItem.Enabled = $false

$startItem = New-Object System.Windows.Forms.ToolStripMenuItem
$startItem.Text = "Start Services"
$startItem.add_Click({ Start-Services })

$restartItem = New-Object System.Windows.Forms.ToolStripMenuItem
$restartItem.Text = "Restart Services"
$restartItem.add_Click({ Restart-Services })

$stopItem = New-Object System.Windows.Forms.ToolStripMenuItem
$stopItem.Text = "Stop Services"
$stopItem.add_Click({ Stop-Services })

$openDashboardItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openDashboardItem.Text = "Open Dashboard"
$openDashboardItem.add_Click({ Open-Url "http://127.0.0.1:3000" })

$openApiItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openApiItem.Text = "Open API Health"
$openApiItem.add_Click({ Open-Url "http://127.0.0.1:8300/api/system/health" })

$openLogsItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openLogsItem.Text = "Open Logs Folder"
$openLogsItem.add_Click({ Open-LogsFolder })

$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem
$exitItem.Text = "Exit Launcher"
$exitItem.add_Click({
    $script:IsShuttingDown = $true
    Write-LauncherLog "Exit requested from tray menu."
    Stop-Services
    $script:NotifyIcon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})

[void]$script:Menu.Items.Add($script:StatusItem)
[void]$script:Menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$script:Menu.Items.Add($openDashboardItem)
[void]$script:Menu.Items.Add($openApiItem)
[void]$script:Menu.Items.Add($openLogsItem)
[void]$script:Menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$script:Menu.Items.Add($startItem)
[void]$script:Menu.Items.Add($restartItem)
[void]$script:Menu.Items.Add($stopItem)
[void]$script:Menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$script:Menu.Items.Add($exitItem)

$script:NotifyIcon.ContextMenuStrip = $script:Menu
$script:NotifyIcon.add_DoubleClick({ Open-Url "http://127.0.0.1:3000" })

$script:Timer = New-Object System.Windows.Forms.Timer
$script:Timer.Interval = 5000
$script:Timer.add_Tick({
    $backendHttp = Test-HttpOk "http://127.0.0.1:8300/api/system/health"
    $frontendHttp = Test-HttpOk "http://127.0.0.1:3000"
    $backendProc = Test-ProcessRunning $script:BackendProcess
    $frontendProc = Test-ProcessRunning $script:FrontendProcess

    $backendState = if ($backendHttp) { "API OK" } elseif ($backendProc) { "API starting" } else { "API stopped" }
    $frontendState = if ($frontendHttp) { "UI OK" } elseif ($frontendProc) { "UI starting" } else { "UI stopped" }
    $statusText = "$backendState; $frontendState"

    $script:StatusItem.Text = "Status: $statusText"
    $script:NotifyIcon.Text = "OMI: $statusText"

    if ($script:LastStatusText -ne $statusText) {
        Write-LauncherLog "Status changed: $statusText"
        $script:LastStatusText = $statusText
    }

    if ($script:IsPackagedRelease -and
        (-not $script:DashboardAutoOpened) -and
        $backendHttp -and
        $frontendHttp) {
        $script:DashboardAutoOpened = $true
        Open-Url "http://127.0.0.1:3000"
    }
})

[System.Windows.Forms.Application]::add_ApplicationExit({
    if (-not $script:IsShuttingDown) {
        Write-LauncherLog "Application exit detected."
        Stop-Services
    }

    $script:Timer.Stop()
    $script:NotifyIcon.Dispose()
    if ($null -ne $script:TrayIcon) {
        $script:TrayIcon.Dispose()
    }
    $script:Mutex.ReleaseMutex()
    $script:Mutex.Dispose()
    Write-LauncherLog "Launcher stopped."
})

Start-Services
$script:Timer.Start()
$script:NotifyIcon.ShowBalloonTip(3000, "Open Market Intelligence", "Launcher is running in the system tray.", [System.Windows.Forms.ToolTipIcon]::Info)

[System.Windows.Forms.Application]::Run()
