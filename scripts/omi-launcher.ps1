$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if ($null -eq ("OmiTaskbarCreatedListener" -as [type])) {
    Add-Type -ReferencedAssemblies @("System.Windows.Forms") -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public sealed class OmiTaskbarCreatedListener : NativeWindow, IDisposable
{
    private readonly int taskbarCreatedMessage;

    public event EventHandler TaskbarCreated;

    public OmiTaskbarCreatedListener()
    {
        taskbarCreatedMessage = unchecked((int)RegisterWindowMessage("TaskbarCreated"));
        CreateParams createParams = new CreateParams();
        createParams.Caption = "Open Market Intelligence Taskbar Listener";
        CreateHandle(createParams);
    }

    public int TaskbarCreatedMessage
    {
        get { return taskbarCreatedMessage; }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern uint RegisterWindowMessage(string message);

    protected override void WndProc(ref Message message)
    {
        if (message.Msg == taskbarCreatedMessage)
        {
            EventHandler handler = TaskbarCreated;
            if (handler != null)
            {
                handler(this, EventArgs.Empty);
            }
        }

        base.WndProc(ref message);
    }

    public void Dispose()
    {
        if (Handle != IntPtr.Zero)
        {
            DestroyHandle();
        }

        GC.SuppressFinalize(this);
    }
}
"@
}

[System.Windows.Forms.Application]::EnableVisualStyles()

$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$script:BackendDir = Join-Path $script:RepoRoot "backend"
$script:FrontendDir = Join-Path $script:RepoRoot "frontend"
$script:TrayIconPath = Join-Path $script:RepoRoot "ATRI-MyDearMoments.ico"
$script:AppDisplayName = "OMI_search"
$script:TrayIcon = $null
$script:ActivationEventName = "OpenMarketIntelligenceLauncherActivate"
$script:ActivationEvent = $null
$script:ActivationTimer = $null
$script:TaskbarListener = $null
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
$script:RepoEnvPath = Join-Path $script:RepoRoot ".env"
$script:FrontendEnvPath = Join-Path $script:FrontendDir ".env.local"
$script:PackagedPython = Join-Path $script:RepoRoot "runtime\python\python.exe"
$script:PackagedNode = Join-Path $script:RepoRoot "runtime\node\node.exe"
$script:BackendProcess = $null
$script:FrontendProcess = $null
$script:LastStatusText = $null
$script:BackendStopExpected = $false
$script:IsShuttingDown = $false
$script:DashboardAutoOpened = $false
$script:DefaultFrontendHost = "127.0.0.1"
$script:DefaultFrontendPort = 3000
$script:FrontendPortSearchSpan = 1000
$script:DefaultBackendHost = "127.0.0.1"
$script:DefaultBackendPort = 8400
$script:BackendPortSearchSpan = 1000
$script:DefaultApiProxyPath = "/omi-data"
$script:BackendReload = $false
$script:BackendSourceStaleToleranceSeconds = 2
$script:ExpectedAskSchemaProperties = @("market_data_params")
$script:ExpectedAskTargetTypes = @("kr_stock", "crypto_asset")
$script:FrontendHost = $script:DefaultFrontendHost
$script:FrontendPort = $script:DefaultFrontendPort
$script:DashboardUrl = "http://$($script:DefaultFrontendHost):$($script:DefaultFrontendPort)"
$script:FrontendHealthUrl = "$($script:DashboardUrl)/omi-ui-health"
$script:BackendHost = $script:DefaultBackendHost
$script:BackendPort = $script:DefaultBackendPort
$script:ApiProxyPath = $script:DefaultApiProxyPath
$script:BackendBaseUrl = "http://$($script:DefaultBackendHost):$($script:DefaultBackendPort)"
$script:BackendHealthUrl = "$($script:BackendBaseUrl)/api/system/health"
$script:BackendReadyUrl = "$($script:BackendBaseUrl)/api/system/readyz"

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
        [string]$Title = $script:AppDisplayName
    )

    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

$script:Mutex = New-Object System.Threading.Mutex($false, "OpenMarketIntelligenceLauncher")
$script:OwnsMutex = $false
try {
    $script:OwnsMutex = $script:Mutex.WaitOne(0, $false)
}
catch [System.Threading.AbandonedMutexException] {
    $script:OwnsMutex = $true
    Write-LauncherLog "Recovered ownership of an abandoned launcher mutex." "WARN"
}

if (-not $script:OwnsMutex) {
    $activationSignaled = $false
    try {
        $existingActivationEvent = [System.Threading.EventWaitHandle]::OpenExisting($script:ActivationEventName)
        try {
            $activationSignaled = $existingActivationEvent.Set()
        }
        finally {
            $existingActivationEvent.Dispose()
        }
    }
    catch {
        Write-LauncherLog "Existing launcher activation signal failed. error=$($_.Exception.Message)" "WARN"
    }

    if ($activationSignaled) {
        Write-LauncherLog "$($script:AppDisplayName) launcher activation requested; the existing tray instance will re-register its icon."
    }
    else {
        Write-LauncherLog "$($script:AppDisplayName) launcher start requested but an existing tray instance is already running and could not be activated; services were not restarted." "WARN"
        Show-Message "$($script:AppDisplayName) is already running, but its tray icon could not be restored automatically. End the existing launcher process before starting it again."
    }

    $script:Mutex.Dispose()
    exit 0
}

$script:ActivationEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:ActivationEventName
)

Write-LauncherLog "Launcher started. repo_root=$($script:RepoRoot)"
Write-LauncherLog "Logs root: $($script:LogRoot). Daily folders: backend, frontend, launcher."
Write-LauncherLog "Packaged release mode: $($script:IsPackagedRelease). app_data_root=$($script:AppDataRoot)"

function ConvertTo-SqliteUrl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $absolutePath = [System.IO.Path]::GetFullPath($Path)
    return "sqlite:///$($absolutePath.Replace('\', '/'))"
}

function Get-ProcessEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string[]]$Names,
        [string]$DefaultValue = $null
    )

    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name, [EnvironmentVariableTarget]::Process)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }

    return $DefaultValue
}

function Set-ProcessEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, [EnvironmentVariableTarget]::Process)
}

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Names
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
    }
    catch {
        Write-LauncherLog "Failed to read env file $Path. error=$($_.Exception.Message)" "WARN"
        return $null
    }

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or
            $trimmed.StartsWith("#") -or
            (-not $trimmed.Contains("="))) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        if ($Names -notcontains $key) {
            continue
        }

        $value = $parts[1].Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Get-ConfigurationValue {
    param(
        [Parameter(Mandatory = $true)][string[]]$Names,
        [string]$DefaultValue = $null,
        [string[]]$EnvFilePaths = @($script:RepoEnvPath, $script:FrontendEnvPath)
    )

    $processValue = Get-ProcessEnvironmentValue -Names $Names
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }

    foreach ($path in $EnvFilePaths) {
        $fileValue = Get-EnvFileValue -Path $path -Names $Names
        if (-not [string]::IsNullOrWhiteSpace($fileValue)) {
            return $fileValue
        }
    }

    return $DefaultValue
}

function Get-BooleanConfigurationValue {
    param(
        [Parameter(Mandatory = $true)][string[]]$Names,
        [bool]$DefaultValue = $false
    )

    $rawValue = Get-ConfigurationValue -Names $Names -DefaultValue ([string]$DefaultValue)
    $normalized = ([string]$rawValue).Trim().ToLowerInvariant()
    if ($normalized -in @("1", "true", "yes", "y", "on")) {
        return $true
    }
    if ($normalized -in @("0", "false", "no", "n", "off")) {
        return $false
    }

    Write-LauncherLog "Invalid boolean config '$rawValue' for $($Names -join '/'); using default=$DefaultValue." "WARN"
    return $DefaultValue
}

function Format-UrlHost {
    param([Parameter(Mandatory = $true)][string]$HostName)

    if ($HostName.Contains(":") -and
        (-not $HostName.StartsWith("[")) -and
        (-not $HostName.EndsWith("]"))) {
        return "[$HostName]"
    }

    return $HostName
}

function Resolve-BackendPort {
    $rawPort = Get-ConfigurationValue `
        -Names @("OMI_BACKEND_PORT", "APP_PORT") `
        -DefaultValue ([string]$script:DefaultBackendPort)

    $port = 0
    if ((-not [int]::TryParse($rawPort, [ref]$port)) -or
        $port -lt 1 -or
        $port -gt 65535) {
        throw "Invalid backend port '$rawPort'. Set OMI_BACKEND_PORT or APP_PORT to a TCP port between 1 and 65535."
    }

    return $port
}

function Resolve-FrontendPort {
    $rawPort = Get-ConfigurationValue `
        -Names @("OMI_FRONTEND_PORT", "FRONTEND_PORT", "PORT") `
        -DefaultValue ([string]$script:DefaultFrontendPort)

    $port = 0
    if ((-not [int]::TryParse($rawPort, [ref]$port)) -or
        $port -lt 1 -or
        $port -gt 65535) {
        throw "Invalid frontend port '$rawPort'. Set OMI_FRONTEND_PORT or FRONTEND_PORT to a TCP port between 1 and 65535."
    }

    return $port
}

function Update-FrontendServiceUrls {
    $urlHost = Format-UrlHost -HostName $script:FrontendHost
    $script:DashboardUrl = "http://$urlHost`:$($script:FrontendPort)"
    $script:FrontendHealthUrl = "$($script:DashboardUrl)/omi-ui-health"

    Set-ProcessEnvironmentValue -Name "HOSTNAME" -Value $script:FrontendHost
    Set-ProcessEnvironmentValue -Name "PORT" -Value ([string]$script:FrontendPort)
    Set-ProcessEnvironmentValue -Name "OMI_FRONTEND_HOST" -Value $script:FrontendHost
    Set-ProcessEnvironmentValue -Name "OMI_FRONTEND_PORT" -Value ([string]$script:FrontendPort)
}

function Update-BackendServiceUrls {
    $urlHost = Format-UrlHost -HostName $script:BackendHost
    $script:BackendBaseUrl = "http://$urlHost`:$($script:BackendPort)"
    $script:BackendHealthUrl = "$($script:BackendBaseUrl)/api/system/health"
    $script:BackendReadyUrl = "$($script:BackendBaseUrl)/api/system/readyz"

    Set-ProcessEnvironmentValue -Name "APP_HOST" -Value $script:BackendHost
    Set-ProcessEnvironmentValue -Name "APP_PORT" -Value ([string]$script:BackendPort)
    Set-ProcessEnvironmentValue -Name "OMI_BACKEND_HOST" -Value $script:BackendHost
    Set-ProcessEnvironmentValue -Name "OMI_BACKEND_PORT" -Value ([string]$script:BackendPort)
    Set-ProcessEnvironmentValue -Name "API_PROXY_TARGET" -Value $script:BackendBaseUrl
    Set-ProcessEnvironmentValue -Name "API_PROXY_PATH" -Value $script:ApiProxyPath
    Set-ProcessEnvironmentValue -Name "NEXT_PUBLIC_API_PROXY_PATH" -Value $script:ApiProxyPath
}

function Initialize-ServiceEnvironment {
    $script:FrontendHost = Get-ConfigurationValue `
        -Names @("OMI_FRONTEND_HOST", "FRONTEND_HOST", "HOSTNAME") `
        -DefaultValue $script:DefaultFrontendHost
    $script:FrontendPort = Resolve-FrontendPort
    $script:BackendHost = Get-ConfigurationValue `
        -Names @("OMI_BACKEND_HOST", "APP_HOST") `
        -DefaultValue $script:DefaultBackendHost
    $script:BackendPort = Resolve-BackendPort
    $script:ApiProxyPath = Get-ConfigurationValue `
        -Names @("API_PROXY_PATH", "NEXT_PUBLIC_API_PROXY_PATH") `
        -DefaultValue $script:DefaultApiProxyPath
    $script:BackendReload = Get-BooleanConfigurationValue `
        -Names @("OMI_BACKEND_RELOAD", "BACKEND_RELOAD") `
        -DefaultValue $false

    if (-not $script:ApiProxyPath.StartsWith("/")) {
        $script:ApiProxyPath = "/$($script:ApiProxyPath)"
    }

    Update-FrontendServiceUrls
    Update-BackendServiceUrls

    if ([string]::IsNullOrWhiteSpace((Get-ProcessEnvironmentValue -Names @("NEXT_PUBLIC_API_BASE_URL")))) {
        Set-ProcessEnvironmentValue -Name "NEXT_PUBLIC_API_BASE_URL" -Value ""
    }

    Write-LauncherLog "Service environment initialized. backend=$($script:BackendBaseUrl) frontend=$($script:DashboardUrl) proxy_path=$($script:ApiProxyPath) backend_reload=$($script:BackendReload)"
}

function Invoke-StockMasterSeed {
    param([Parameter(Mandatory = $true)][string]$SeedDatabasePath)

    $seedScriptPath = Join-Path $script:RepoRoot "scripts\stock-master-seed.py"

    if (-not (Test-Path -LiteralPath $SeedDatabasePath)) {
        Write-LauncherLog "No packaged stock master seed database found at $SeedDatabasePath"
        return
    }

    if (-not (Test-Path -LiteralPath $seedScriptPath)) {
        Write-LauncherLog "Stock master seed script was not found: $seedScriptPath" "WARN"
        return
    }

    if (-not (Test-Path -LiteralPath $script:PackagedPython)) {
        Write-LauncherLog "Packaged Python runtime was not found: $($script:PackagedPython)" "WARN"
        return
    }

    Write-LauncherLog "Applying stock master seed if needed. seed=$SeedDatabasePath target=$($script:DatabasePath)"

    $arguments = @(
        $seedScriptPath,
        "apply",
        "--seed-db",
        $SeedDatabasePath,
        "--target-db",
        $script:DatabasePath,
        "--require-stock",
        "2330"
    )

    try {
        $output = & $script:PackagedPython @arguments 2>&1
        $exitCode = $LASTEXITCODE

        foreach ($line in $output) {
            Write-LauncherLog "stock-master-seed: $line"
        }

        if ($exitCode -ne 0) {
            Write-LauncherLog "Stock master seed exited with code $exitCode." "WARN"
        }
    }
    catch {
        Write-LauncherLog "Stock master seed failed: $($_.Exception.Message)" "WARN"
    }
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

    Invoke-StockMasterSeed -SeedDatabasePath $seedDatabasePath

    $env:APP_ENV = "production"
    $env:DATABASE_URL = ConvertTo-SqliteUrl $script:DatabasePath
    Write-LauncherLog "Release environment initialized. database=$($script:DatabasePath)"
}

Initialize-ReleaseEnvironment
Initialize-ServiceEnvironment

function Test-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutMs = 1500
    )

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = $TimeoutMs
        $request.ReadWriteTimeout = $TimeoutMs
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode
        $response.Close()
        return ($statusCode -ge 200 -and $statusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Get-ExpectedBackendPython {
    if ($script:IsPackagedRelease -and (Test-Path -LiteralPath $script:PackagedPython)) {
        return $script:PackagedPython
    }

    return (Join-Path $script:RepoRoot ".venv\Scripts\python.exe")
}

function ConvertTo-NormalizedPath {
    param([AllowNull()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    try {
        $normalized = [System.IO.Path]::GetFullPath($Path)
    }
    catch {
        $normalized = $Path
    }

    return $normalized.TrimEnd([char[]]@('\', '/')).ToLowerInvariant()
}

function Get-BackendHealth {
    param([string]$Url = $script:BackendHealthUrl)

    $response = $null
    $reader = $null

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 1500
        $request.ReadWriteTimeout = 1500
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode

        if ($statusCode -lt 200 -or $statusCode -ge 400) {
            return $null
        }

        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $content = $reader.ReadToEnd()
        return ($content | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }

        if ($null -ne $response) {
            $response.Close()
        }
    }
}

function Get-BackendAiTools {
    param([string]$Url = "$($script:BackendBaseUrl)/api/ai/tools")

    $response = $null
    $reader = $null

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 1500
        $request.ReadWriteTimeout = 1500
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode

        if ($statusCode -lt 200 -or $statusCode -ge 400) {
            return $null
        }

        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $content = $reader.ReadToEnd()
        return ($content | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }

        if ($null -ne $response) {
            $response.Close()
        }
    }
}

function Test-BackendPublicContractMatchesExpected {
    $toolsResponse = Get-BackendAiTools
    if ($null -eq $toolsResponse) {
        Write-LauncherLog "Backend /api/ai/tools did not return a parseable response; treating backend contract as stale." "WARN"
        return $false
    }

    $askTool = @($toolsResponse.tools) |
        Where-Object { $_.name -eq "omi.ask" } |
        Select-Object -First 1
    if ($null -eq $askTool) {
        Write-LauncherLog "Backend /api/ai/tools is missing omi.ask; treating backend contract as stale." "WARN"
        return $false
    }

    $schemaProperties = $askTool.input_schema.properties
    $propertyNames = if ($null -ne $schemaProperties) {
        @($schemaProperties.PSObject.Properties.Name)
    }
    else {
        @()
    }

    $targetTypes = @()
    try {
        $targetTypes = @($askTool.input_schema.properties.target.properties.type.enum)
    }
    catch {
        $targetTypes = @()
    }

    $missingProperties = @()
    foreach ($propertyName in $script:ExpectedAskSchemaProperties) {
        if ($propertyNames -notcontains $propertyName) {
            $missingProperties += $propertyName
        }
    }

    $missingTargetTypes = @()
    foreach ($targetType in $script:ExpectedAskTargetTypes) {
        if ($targetTypes -notcontains $targetType) {
            $missingTargetTypes += $targetType
        }
    }

    if ($missingProperties.Count -gt 0 -or $missingTargetTypes.Count -gt 0) {
        Write-LauncherLog "Backend public AI contract is stale. missing_properties=$($missingProperties -join ',') missing_target_types=$($missingTargetTypes -join ',')" "WARN"
        return $false
    }

    return $true
}

function Get-FrontendHealth {
    param([string]$Url = $script:FrontendHealthUrl)

    $response = $null
    $reader = $null

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 1500
        $request.ReadWriteTimeout = 1500
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode

        if ($statusCode -lt 200 -or $statusCode -ge 400) {
            return $null
        }

        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $content = $reader.ReadToEnd()
        return ($content | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }

        if ($null -ne $response) {
            $response.Close()
        }
    }
}

function Test-BackendHealthMatchesExpected {
    param(
        [Parameter(Mandatory = $true)]$Health,
        [Parameter(Mandatory = $true)][string]$ExpectedPythonPath
    )

    $runtime = $Health.runtime

    if ($null -eq $runtime) {
        Write-LauncherLog "Backend health response has no runtime metadata; treating it as a stale backend." "WARN"
        return $false
    }

    $expectedRepoRoot = ConvertTo-NormalizedPath $script:RepoRoot
    $actualRepoRoot = ConvertTo-NormalizedPath ([string]$runtime.project_root)
    if ($actualRepoRoot -ne $expectedRepoRoot) {
        Write-LauncherLog "Backend project root mismatch. expected=$script:RepoRoot actual=$($runtime.project_root)" "WARN"
        return $false
    }

    $expectedPython = ConvertTo-NormalizedPath $ExpectedPythonPath
    $actualPython = ConvertTo-NormalizedPath ([string]$runtime.python_executable)
    if ($actualPython -ne $expectedPython) {
        Write-LauncherLog "Backend Python runtime mismatch. expected=$ExpectedPythonPath actual=$($runtime.python_executable)" "WARN"
        return $false
    }

    return $true
}

function Get-LatestBackendSourceWriteTimeUtc {
    $sourceRoots = @(
        (Join-Path $script:BackendDir "app"),
        (Join-Path $script:BackendDir "alembic"),
        (Join-Path $script:BackendDir "scripts")
    )
    $latest = [DateTime]::MinValue

    foreach ($root in $sourceRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        try {
            $files = Get-ChildItem -LiteralPath $root -Recurse -File -Filter "*.py" -ErrorAction SilentlyContinue
            foreach ($file in $files) {
                if ($file.LastWriteTimeUtc -gt $latest) {
                    $latest = $file.LastWriteTimeUtc
                }
            }
        }
        catch {
            Write-LauncherLog "Unable to inspect backend source timestamps under $root. error=$($_.Exception.Message)" "WARN"
        }
    }

    return $latest
}

function Test-BackendPortOwnersOlderThanSource {
    param([Parameter(Mandatory = $true)][int]$Port)

    if ($script:IsPackagedRelease) {
        return $false
    }

    $sourceStamp = Get-LatestBackendSourceWriteTimeUtc
    if ($sourceStamp -eq [DateTime]::MinValue) {
        return $false
    }

    $processIds = @(Get-ListeningProcessIdsOnPort -Port $Port)
    foreach ($processId in $processIds) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            $startedAtUtc = $process.StartTime.ToUniversalTime()
            if ($startedAtUtc.AddSeconds($script:BackendSourceStaleToleranceSeconds) -lt $sourceStamp) {
                Write-LauncherLog "Backend process is older than backend source. pid=$processId started_at=$($startedAtUtc.ToString("o")) source_stamp=$($sourceStamp.ToString("o"))" "WARN"
                return $true
            }
        }
        catch {
            Write-LauncherLog "Unable to inspect backend port owner pid=$processId. error=$($_.Exception.Message)" "WARN"
        }
    }

    return $false
}

function Test-FrontendHealthMatchesExpected {
    param([Parameter(Mandatory = $true)]$Health)

    $runtime = $Health.runtime

    if ($null -eq $runtime) {
        Write-LauncherLog "Frontend health response has no runtime metadata; treating it as a stale frontend." "WARN"
        return $false
    }

    $expectedFrontendDir = ConvertTo-NormalizedPath $script:FrontendDir
    $actualFrontendDir = ConvertTo-NormalizedPath ([string]$runtime.frontend_dir)
    if ($actualFrontendDir -ne $expectedFrontendDir) {
        Write-LauncherLog "Frontend directory mismatch. expected=$($script:FrontendDir) actual=$($runtime.frontend_dir)" "WARN"
        return $false
    }

    $expectedProxyTarget = $script:BackendBaseUrl.TrimEnd("/").ToLowerInvariant()
    $actualProxyTarget = ([string]$runtime.api_proxy_target).TrimEnd("/").ToLowerInvariant()
    if ($actualProxyTarget -ne $expectedProxyTarget) {
        Write-LauncherLog "Frontend API proxy target mismatch. expected=$($script:BackendBaseUrl) actual=$($runtime.api_proxy_target)" "WARN"
        return $false
    }

    $expectedProxyPath = $script:ApiProxyPath.TrimEnd("/").ToLowerInvariant()
    $actualProxyPath = ([string]$runtime.api_proxy_path).TrimEnd("/").ToLowerInvariant()
    if ($actualProxyPath -ne $expectedProxyPath) {
        Write-LauncherLog "Frontend API proxy path mismatch. expected=$($script:ApiProxyPath) actual=$($runtime.api_proxy_path)" "WARN"
        return $false
    }

    return $true
}

function Test-FrontendOk {
    $frontendHealth = Get-FrontendHealth
    return ($null -ne $frontendHealth -and (Test-FrontendHealthMatchesExpected -Health $frontendHealth))
}

function Get-ListeningProcessIdsOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $netstat = Join-Path $env:SystemRoot "System32\netstat.exe"
    if (-not (Test-Path -LiteralPath $netstat)) {
        return @()
    }

    $processIds = @()
    $lines = & $netstat -ano -p TCP 2>$null
    foreach ($line in $lines) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $processIds += [int]$Matches[1]
        }
    }

    return ($processIds | Sort-Object -Unique)
}

function Get-TcpExcludedPortRanges {
    param([switch]$Quiet)

    $netsh = Join-Path $env:SystemRoot "System32\netsh.exe"
    if (-not (Test-Path -LiteralPath $netsh)) {
        if (-not $Quiet) {
            Write-LauncherLog "netsh.exe was not found; skipping TCP excluded port range check." "WARN"
        }
        return @()
    }

    $ranges = @()
    foreach ($addressFamily in @("ipv4", "ipv6")) {
        $lines = & $netsh interface $addressFamily show excludedportrange protocol=tcp 2>$null
        foreach ($line in $lines) {
            if ($line -match "^\s*(\d+)\s+(\d+)\s*(?:\*)?\s*$") {
                $ranges += [pscustomobject]@{
                    AddressFamily = $addressFamily
                    StartPort = [int]$Matches[1]
                    EndPort = [int]$Matches[2]
                }
            }
        }
    }

    return $ranges
}

function Test-TcpPortExcluded {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$ServiceName = "service",
        [object[]]$Ranges = $null,
        [switch]$Quiet
    )

    $excludedRanges = if ($null -ne $Ranges) { $Ranges } else { @(Get-TcpExcludedPortRanges -Quiet:$Quiet) }
    foreach ($range in $excludedRanges) {
        $startPort = [int]$range.StartPort
        $endPort = [int]$range.EndPort
        if ($Port -ge $startPort -and $Port -le $endPort) {
            if (-not $Quiet) {
                Write-LauncherLog "$ServiceName port $Port is inside Windows $($range.AddressFamily) TCP excluded range $startPort-$endPort." "WARN"
            }
            return $true
        }
    }

    return $false
}

function Test-TcpPortBindable {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$HostName = $script:FrontendHost,
        [string]$ServiceName = "Service",
        [switch]$Quiet
    )

    $normalizedHost = $HostName.Trim("[", "]")
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($normalizedHost, [ref]$address)) {
        $address = [System.Net.IPAddress]::Loopback
    }

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
        $listener.Start()
        return $true
    }
    catch {
        if (-not $Quiet) {
            $errorMessage = $_.Exception.Message
            if ($null -ne $_.Exception.InnerException) {
                $errorMessage = $_.Exception.InnerException.Message
            }
            Write-LauncherLog "$ServiceName port $Port cannot be bound on $HostName. error=$errorMessage" "WARN"
        }
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Find-AvailableFrontendPort {
    param([Parameter(Mandatory = $true)][int]$PreferredPort)

    $maxPort = [Math]::Min($PreferredPort + $script:FrontendPortSearchSpan, 65535)
    $excludedRanges = @(Get-TcpExcludedPortRanges -Quiet)
    for ($port = $PreferredPort; $port -le $maxPort; $port++) {
        if (Test-TcpPortExcluded -Port $port -ServiceName "Frontend" -Ranges $excludedRanges -Quiet) {
            continue
        }

        $processIds = @(Get-ListeningProcessIdsOnPort -Port $port)
        if ($processIds.Count -gt 0) {
            continue
        }

        if (-not (Test-TcpPortBindable -Port $port -HostName $script:FrontendHost -ServiceName "Frontend" -Quiet)) {
            continue
        }

        return $port
    }

    throw "Could not find an available frontend port from $PreferredPort to $maxPort. Set OMI_FRONTEND_PORT to an available port and restart OMI."
}

function Find-AvailableBackendPort {
    param([Parameter(Mandatory = $true)][int]$PreferredPort)

    $maxPort = [Math]::Min($PreferredPort + $script:BackendPortSearchSpan, 65535)
    $excludedRanges = @(Get-TcpExcludedPortRanges -Quiet)
    for ($port = $PreferredPort; $port -le $maxPort; $port++) {
        if (Test-TcpPortExcluded -Port $port -ServiceName "Backend" -Ranges $excludedRanges -Quiet) {
            continue
        }

        $processIds = @(Get-ListeningProcessIdsOnPort -Port $port)
        if ($processIds.Count -gt 0) {
            continue
        }

        if (-not (Test-TcpPortBindable -Port $port -HostName $script:BackendHost -ServiceName "Backend" -Quiet)) {
            continue
        }

        return $port
    }

    throw "Could not find an available backend port from $PreferredPort to $maxPort. Set OMI_BACKEND_PORT or APP_PORT to an available port and restart OMI."
}

function Select-AvailableFrontendPortForStart {
    $reasons = @()
    if (Test-TcpPortExcluded -Port $script:FrontendPort -ServiceName "Frontend") {
        $reasons += "Windows TCP excluded range"
    }

    $processIds = @(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort)
    if ($processIds.Count -gt 0) {
        $reasons += "listening process pid=$($processIds -join ',')"
    }

    if ($reasons.Count -eq 0 -and
        (-not (Test-TcpPortBindable -Port $script:FrontendPort -HostName $script:FrontendHost -ServiceName "Frontend"))) {
        $reasons += "bind probe failed"
    }

    if ($reasons.Count -eq 0) {
        return
    }

    $previousUrl = $script:DashboardUrl
    $script:FrontendPort = Find-AvailableFrontendPort -PreferredPort ($script:FrontendPort + 1)
    Update-FrontendServiceUrls
    Write-LauncherLog "Frontend port is not bindable ($($reasons -join '; ')). previous=$previousUrl selected=$($script:DashboardUrl)" "WARN"
}

function Select-AvailableBackendPortForStart {
    param([Parameter(Mandatory = $true)][string]$ExpectedPythonPath)

    $reasons = @()
    if (Test-TcpPortExcluded -Port $script:BackendPort -ServiceName "Backend") {
        $reasons += "Windows TCP excluded range"
    }

    if ($reasons.Count -eq 0) {
        $backendHealth = Get-BackendHealth
        if ($null -ne $backendHealth) {
            if (Test-BackendHealthMatchesExpected -Health $backendHealth -ExpectedPythonPath $ExpectedPythonPath) {
                $restartReasons = @()
                if (Test-BackendPortOwnersOlderThanSource -Port $script:BackendPort) {
                    $restartReasons += "backend source changed"
                }
                if (-not (Test-BackendPublicContractMatchesExpected)) {
                    $restartReasons += "backend public contract stale"
                }

                if ($restartReasons.Count -gt 0) {
                    $restartReason = $restartReasons -join "; "
                    Write-LauncherLog "Existing OMI backend matches this project but must be restarted. reason=$restartReason" "WARN"
                    Stop-BackendPortOwners -Port $script:BackendPort -Reason $restartReason
                    Start-Sleep -Milliseconds 750

                    if (Test-HttpOk $script:BackendHealthUrl) {
                        $reasons += "stale OMI runtime still responded after backend restart cleanup"
                    }
                    else {
                        return $false
                    }
                }
                else {
                    Write-LauncherLog "Backend health endpoint already responds with the expected project/runtime; skipping backend start."
                    return $true
                }
            }
            elseif ([string]$backendHealth.app_name -eq "Open Market Intelligence") {
                Write-LauncherLog "Existing OMI backend did not match the expected project/runtime. Clearing stale backend before start." "WARN"
                Stop-BackendPortOwners -Port $script:BackendPort -Reason "runtime mismatch"
                Start-Sleep -Milliseconds 750

                if (Test-HttpOk $script:BackendHealthUrl) {
                    $reasons += "unexpected OMI runtime still responded after cleanup"
                }
            }
            else {
                $reasons += "HTTP service is not this OMI backend"
            }
        }
        elseif (Test-HttpOk $script:BackendHealthUrl) {
            $reasons += "unparseable backend health response"
        }
    }

    if ($reasons.Count -eq 0) {
        $processIds = @(Get-ListeningProcessIdsOnPort -Port $script:BackendPort)
        if ($processIds.Count -gt 0) {
            $reasons += "listening process pid=$($processIds -join ',')"
        }
    }

    if ($reasons.Count -eq 0 -and
        (-not (Test-TcpPortBindable -Port $script:BackendPort -HostName $script:BackendHost -ServiceName "Backend"))) {
        $reasons += "bind probe failed"
    }

    if ($reasons.Count -eq 0) {
        return $false
    }

    $previousUrl = $script:BackendBaseUrl
    $script:BackendPort = Find-AvailableBackendPort -PreferredPort ($script:BackendPort + 1)
    Update-BackendServiceUrls
    Write-LauncherLog "Backend port is not bindable ($($reasons -join '; ')). previous=$previousUrl selected=$($script:BackendBaseUrl)" "WARN"
    return $false
}

function Stop-BackendPortOwners {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $processIds = @(Get-ListeningProcessIdsOnPort -Port $Port)
    if ($processIds.Count -eq 0) {
        Write-LauncherLog "No listening process was found on backend port $Port."
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    foreach ($processId in $processIds) {
        if ($processId -eq $PID) {
            Write-LauncherLog "Skipping current launcher process while clearing backend port $Port." "WARN"
            continue
        }

        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-LauncherLog "Stopping stale OMI backend port owner. port=$Port pid=$processId process=$($process.ProcessName) reason=$Reason" "WARN"
            Start-Process -FilePath $taskkill -ArgumentList @("/PID", "$processId", "/T", "/F") -Wait -WindowStyle Hidden | Out-Null
        }
        catch {
            throw "Failed to stop stale backend port owner pid=$processId on port $Port. error=$($_.Exception.Message)"
        }
    }
}

function Stop-FrontendPortOwners {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $processIds = @(Get-ListeningProcessIdsOnPort -Port $Port)
    if ($processIds.Count -eq 0) {
        Write-LauncherLog "No listening process was found on frontend port $Port."
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    foreach ($processId in $processIds) {
        if ($processId -eq $PID) {
            Write-LauncherLog "Skipping current launcher process while clearing frontend port $Port." "WARN"
            continue
        }

        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-LauncherLog "Stopping OMI frontend port owner. port=$Port pid=$processId process=$($process.ProcessName) reason=$Reason" "WARN"
            Start-Process -FilePath $taskkill -ArgumentList @("/PID", "$processId", "/T", "/F") -Wait -WindowStyle Hidden | Out-Null
        }
        catch {
            throw "Failed to stop frontend port owner pid=$processId on port $Port. error=$($_.Exception.Message)"
        }
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

function Invoke-BackendPythonRuntimeCheck {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Missing Python executable: $PythonPath"
    }

    $probeScript = @'
import importlib.util
import sys

print("executable=" + sys.executable)
print("version=" + sys.version.replace("\n", " "))

missing_modules = [
    module_name
    for module_name in ("fastapi", "uvicorn", "pydantic_core")
    if importlib.util.find_spec(module_name) is None
]
if missing_modules:
    raise SystemExit("missing modules: " + ", ".join(missing_modules))
'@

    Write-LauncherLog "Checking backend Python runtime. python=$PythonPath"

    try {
        $env:OMI_BACKEND_PYTHON_PROBE = $probeScript
        $output = & $PythonPath -c "import os; exec(os.environ['OMI_BACKEND_PYTHON_PROBE'])" 2>&1
        $exitCode = $LASTEXITCODE

        foreach ($line in $output) {
            Write-LauncherLog "backend-python-check: $line"
        }

        if ($exitCode -ne 0) {
            throw "runtime check exited with code $exitCode"
        }
    }
    catch {
        throw "Backend Python runtime is invalid. python=$PythonPath error=$($_.Exception.Message). Rebuild .venv from the repo root and install backend requirements."
    }
    finally {
        Remove-Item Env:\OMI_BACKEND_PYTHON_PROBE -ErrorAction SilentlyContinue
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

function Restore-TrayIcon {
    param([Parameter(Mandatory = $true)][string]$Reason)

    if ($script:IsShuttingDown -or $null -eq $script:NotifyIcon) {
        return
    }

    try {
        $script:NotifyIcon.Visible = $false
        $script:NotifyIcon.Icon = Get-TrayIcon
        $script:NotifyIcon.Visible = $true
        Write-LauncherLog "Tray icon re-registered. reason=$Reason"

        try {
            $script:NotifyIcon.ShowBalloonTip(
                3000,
                $script:AppDisplayName,
                "$($script:AppDisplayName) tray controls are available again.",
                [System.Windows.Forms.ToolTipIcon]::Info
            )
        }
        catch {
            Write-LauncherLog "Tray icon restored but its notification could not be shown. reason=$Reason error=$($_.Exception.Message)" "WARN"
        }
    }
    catch {
        Write-LauncherLog "Tray icon re-registration failed. reason=$Reason error=$($_.Exception.Message)" "ERROR"
    }
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
        "-ArgumentsJsonBase64 $argumentsJsonBase64",
        "-LauncherPid $PID"
    ) -join " "

    return Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $runnerArguments `
        -WorkingDirectory $script:RepoRoot `
        -WindowStyle Hidden `
        -PassThru
}

function Start-Backend {
    $script:BackendStopExpected = $false

    if (Test-ProcessRunning $script:BackendProcess) {
        Write-LauncherLog "Backend process is already tracked pid=$($script:BackendProcess.Id)."
        return
    }

    $python = Get-ExpectedBackendPython

    if (-not (Test-Path -LiteralPath $python)) {
        throw "Missing Python executable: $python"
    }

    if (-not (Test-Path -LiteralPath $script:BackendDir)) {
        throw "Missing backend directory: $($script:BackendDir)"
    }

    if (Select-AvailableBackendPortForStart -ExpectedPythonPath $python) {
        return
    }

    Invoke-BackendPythonRuntimeCheck -PythonPath $python

    Write-LauncherLog "Starting backend with $python on $($script:BackendBaseUrl). reload=$($script:BackendReload)"
    $backendArguments = @("-m", "uvicorn", "app.main:app")
    if ((-not $script:IsPackagedRelease) -and $script:BackendReload) {
        $backendArguments += "--reload"
    }
    $backendArguments += @("--host", $script:BackendHost, "--port", ([string]$script:BackendPort))

    $script:BackendProcess = Start-LoggedService `
        -ServiceName "backend" `
        -FilePath $python `
        -Arguments $backendArguments `
        -WorkingDirectory $script:BackendDir
    Write-LauncherLog "Backend started pid=$($script:BackendProcess.Id)."
}

function Start-Frontend {
    $frontendHealth = Get-FrontendHealth
    if ($null -ne $frontendHealth -and (Test-FrontendHealthMatchesExpected -Health $frontendHealth)) {
        Write-LauncherLog "Frontend health endpoint already responds with the expected project/runtime; skipping frontend start."
        return
    }

    if (Test-ProcessRunning $script:FrontendProcess) {
        Write-LauncherLog "Frontend process is already tracked pid=$($script:FrontendProcess.Id)."
        return
    }

    if (-not (Test-Path -LiteralPath $script:FrontendDir)) {
        throw "Missing frontend directory: $($script:FrontendDir)"
    }

    if (($null -ne $frontendHealth) -or (Test-HttpOk -Url $script:DashboardUrl -TimeoutMs 2000)) {
        $previousUrl = $script:DashboardUrl
        $script:FrontendPort = Find-AvailableFrontendPort -PreferredPort ($script:FrontendPort + 1)
        Update-FrontendServiceUrls
        Write-LauncherLog "Frontend port already responds but is not the expected runtime. previous=$previousUrl selected=$($script:DashboardUrl)" "WARN"
    }

    Select-AvailableFrontendPortForStart

    if ($script:IsPackagedRelease) {
        $serverScript = Join-Path $script:FrontendDir "server.js"

        if (-not (Test-Path -LiteralPath $script:PackagedNode)) {
            throw "Missing packaged Node executable: $($script:PackagedNode)"
        }

        if (-not (Test-Path -LiteralPath $serverScript)) {
            throw "Missing packaged frontend server: $serverScript"
        }

        Write-LauncherLog "Starting packaged frontend with $($script:PackagedNode) on $($script:DashboardUrl)."
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

    Write-LauncherLog "Starting frontend with $($npm.Source) on $($script:DashboardUrl)."
    $script:FrontendProcess = Start-LoggedService `
        -ServiceName "frontend" `
        -FilePath $npm.Source `
        -Arguments @("run", "dev", "--", "--hostname", $script:FrontendHost, "--port", ([string]$script:FrontendPort)) `
        -WorkingDirectory $script:FrontendDir
    Write-LauncherLog "Frontend started pid=$($script:FrontendProcess.Id)."
}

function Start-Services {
    if ((-not (Test-ProcessRunning $script:BackendProcess)) -and
        (-not (Test-ProcessRunning $script:FrontendProcess))) {
        try {
            Initialize-ServiceEnvironment
        }
        catch {
            Write-LauncherLog "Service environment initialization failed. error=$($_.Exception.Message)" "ERROR"
            Show-Message "OMI service configuration is invalid. Check logs\launcher for details."
            return
        }
    }

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

function Stop-BackendService {
    $script:BackendStopExpected = $true
    Stop-ProcessTree $script:BackendProcess "backend"
    $script:BackendProcess = $null

    $expectedPython = Get-ExpectedBackendPython
    $backendHealth = Get-BackendHealth
    if ($null -eq $backendHealth) {
        return
    }

    if (Test-BackendHealthMatchesExpected -Health $backendHealth -ExpectedPythonPath $expectedPython) {
        Write-LauncherLog "Backend still responds after tracked stop; clearing expected backend port owners."
        Stop-BackendPortOwners -Port $script:BackendPort -Reason "launcher stop"
        Start-Sleep -Milliseconds 750
        if (Test-HttpOk $script:BackendHealthUrl) {
            Write-LauncherLog "Backend health still responds after launcher stop cleanup." "WARN"
        }
    }
    else {
        Write-LauncherLog "Backend port still responds but does not match this launcher; leaving it running." "WARN"
    }
}

function Stop-FrontendService {
    Stop-ProcessTree $script:FrontendProcess "frontend"
    $script:FrontendProcess = $null

    $frontendHealth = Get-FrontendHealth
    if ($null -eq $frontendHealth) {
        return
    }

    if (Test-FrontendHealthMatchesExpected -Health $frontendHealth) {
        Write-LauncherLog "Frontend still responds after tracked stop; clearing expected frontend port owners."
        Stop-FrontendPortOwners -Port $script:FrontendPort -Reason "launcher stop"
        Start-Sleep -Milliseconds 750
        if (Test-FrontendOk) {
            Write-LauncherLog "Frontend health still responds after launcher stop cleanup." "WARN"
        }
    }
    else {
        Write-LauncherLog "Frontend port still responds but does not match this launcher; leaving it running." "WARN"
    }
}

function Stop-Services {
    Stop-FrontendService
    Stop-BackendService
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
$script:NotifyIcon.Text = "$($script:AppDisplayName): starting"
$script:NotifyIcon.Visible = $true

$script:TaskbarListener = New-Object OmiTaskbarCreatedListener
$script:TaskbarListener.add_TaskbarCreated({
    Restore-TrayIcon -Reason "taskbar-created"
})

# ContextMenuStrip can be pushed behind the Windows 11 hidden-icons flyout
# because this tray-only process has no foreground top-level window. The
# native ContextMenu integration keeps the menu in the tray foreground.
$script:Menu = New-Object System.Windows.Forms.ContextMenu
$script:TitleItem = New-Object System.Windows.Forms.MenuItem
$script:TitleItem.Text = $script:AppDisplayName
$script:TitleItem.Enabled = $false

$script:StatusItem = New-Object System.Windows.Forms.MenuItem
$script:StatusItem.Text = "Status: starting"
$script:StatusItem.Enabled = $false

$startItem = New-Object System.Windows.Forms.MenuItem
$startItem.Text = "Start Services"
$startItem.add_Click({ Start-Services })

$restartItem = New-Object System.Windows.Forms.MenuItem
$restartItem.Text = "Restart Services"
$restartItem.add_Click({ Restart-Services })

$stopItem = New-Object System.Windows.Forms.MenuItem
$stopItem.Text = "Stop Services"
$stopItem.add_Click({ Stop-Services })

$openDashboardItem = New-Object System.Windows.Forms.MenuItem
$openDashboardItem.Text = "Open Dashboard"
$openDashboardItem.add_Click({ Open-Url $script:DashboardUrl })

$openApiItem = New-Object System.Windows.Forms.MenuItem
$openApiItem.Text = "Open API Health"
$openApiItem.add_Click({ Open-Url $script:BackendHealthUrl })

$openLogsItem = New-Object System.Windows.Forms.MenuItem
$openLogsItem.Text = "Open Logs Folder"
$openLogsItem.add_Click({ Open-LogsFolder })

$exitItem = New-Object System.Windows.Forms.MenuItem
$exitItem.Text = "Exit Launcher"
$exitItem.add_Click({
    if ($script:IsShuttingDown) {
        return
    }

    $script:IsShuttingDown = $true
    Write-LauncherLog "Exit requested from tray menu."
    $script:Timer.Stop()
    $script:ActivationTimer.Stop()
    $script:NotifyIcon.Visible = $false
    try {
        Stop-Services
    }
    catch {
        Write-LauncherLog "Service shutdown failed during launcher exit. error=$($_.Exception.Message)" "ERROR"
    }
    finally {
        [System.Windows.Forms.Application]::Exit()
    }
})

[void]$script:Menu.MenuItems.Add($script:TitleItem)
[void]$script:Menu.MenuItems.Add($script:StatusItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($openDashboardItem)
[void]$script:Menu.MenuItems.Add($openApiItem)
[void]$script:Menu.MenuItems.Add($openLogsItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($startItem)
[void]$script:Menu.MenuItems.Add($restartItem)
[void]$script:Menu.MenuItems.Add($stopItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($exitItem)

$script:NotifyIcon.ContextMenu = $script:Menu
$script:NotifyIcon.add_DoubleClick({ Open-Url $script:DashboardUrl })

$script:Timer = New-Object System.Windows.Forms.Timer
$script:Timer.Interval = 5000
$script:Timer.add_Tick({
    $backendHttp = Test-HttpOk $script:BackendReadyUrl
    $frontendHttp = Test-FrontendOk
    $backendProc = Test-ProcessRunning $script:BackendProcess
    $frontendProc = Test-ProcessRunning $script:FrontendProcess

    $backendState = if ($backendHttp) { "API OK" } elseif ($backendProc) { "API starting" } else { "API stopped" }
    $frontendState = if ($frontendHttp) { "UI OK" } elseif ($frontendProc) { "UI starting" } else { "UI stopped" }
    $statusText = "$backendState; $frontendState"

    $script:StatusItem.Text = "Status: $statusText"
    $script:NotifyIcon.Text = "$($script:AppDisplayName): $statusText"

    if ($script:LastStatusText -ne $statusText) {
        Write-LauncherLog "Status changed: $statusText"
        if ($null -ne $script:LastStatusText -and
            $backendState -eq "API stopped" -and
            (-not $script:BackendStopExpected) -and
            (-not $script:LastStatusText.StartsWith("API stopped"))) {
            $script:NotifyIcon.ShowBalloonTip(
                5000,
                $script:AppDisplayName,
                "Backend recovery stopped. Open launcher logs for crash details, then use Restart Services.",
                [System.Windows.Forms.ToolTipIcon]::Warning
            )
        }
        $script:LastStatusText = $statusText
    }

    if ($script:IsPackagedRelease -and
        (-not $script:DashboardAutoOpened) -and
        $backendHttp -and
        $frontendHttp) {
        $script:DashboardAutoOpened = $true
        Open-Url $script:DashboardUrl
    }
})

$script:ActivationTimer = New-Object System.Windows.Forms.Timer
$script:ActivationTimer.Interval = 250
$script:ActivationTimer.add_Tick({
    if ($null -ne $script:ActivationEvent -and $script:ActivationEvent.WaitOne(0)) {
        Restore-TrayIcon -Reason "secondary-launch"
    }
})

[System.Windows.Forms.Application]::add_ApplicationExit({
    if (-not $script:IsShuttingDown) {
        Write-LauncherLog "Application exit detected."
        Stop-Services
    }

    $script:Timer.Stop()
    $script:ActivationTimer.Stop()
    if ($null -ne $script:TaskbarListener) {
        $script:TaskbarListener.Dispose()
    }
    $script:NotifyIcon.Dispose()
    if ($null -ne $script:TrayIcon) {
        $script:TrayIcon.Dispose()
    }
    if ($null -ne $script:ActivationEvent) {
        $script:ActivationEvent.Dispose()
    }
    if ($script:OwnsMutex) {
        $script:Mutex.ReleaseMutex()
    }
    $script:Mutex.Dispose()
    Write-LauncherLog "Launcher stopped."
})

Start-Services
$script:Timer.Start()
$script:ActivationTimer.Start()
Write-LauncherLog "Tray recovery initialized. activation_event=$($script:ActivationEventName) taskbar_message=$($script:TaskbarListener.TaskbarCreatedMessage)"
$script:NotifyIcon.ShowBalloonTip(3000, $script:AppDisplayName, "$($script:AppDisplayName) is running in the system tray.", [System.Windows.Forms.ToolTipIcon]::Info)

[System.Windows.Forms.Application]::Run()
