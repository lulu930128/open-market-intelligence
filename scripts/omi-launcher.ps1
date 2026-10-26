param(
    [ValidateSet("Run", "Activate", "Exit", "RestartServices", "RestartBackend", "Diagnose")]
    [string]$LauncherAction = "Run",
    [ValidateRange(1, 65535)][int[]]$DiagnosticPorts = @(8400, 3000)
)

$ErrorActionPreference = "Stop"

# This branch must precede GUI initialization, dotenv reads, event signaling,
# log creation and all lifecycle actions. Failure never falls through to Run.
function Get-OmiStopDiagnostic {
    param([string]$Root, [int[]]$Ports)
    $unknown = [System.Collections.Generic.List[string]]::new()
    $rows = @()
    $inventoryStatus = "UNKNOWN"
    try {
        $rows = @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine -OperationTimeoutSec 5 -ErrorAction Stop)
        $inventoryStatus = "OBSERVED_NOT_ATOMIC"
    }
    catch { $unknown.Add("process_inventory_unavailable") }
    $matched = @()
    $unclassified = 0
    foreach ($row in $rows) {
        # Inspect locally; never emit raw command lines, arguments or environment.
        if (-not $row.CommandLine) { $unclassified += 1; continue }
        if ($row.CommandLine.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $role = "repo_process_candidate"
            if ($row.CommandLine -match 'omi-launcher\.ps1') { $role = "launcher_candidate" }
            elseif ($row.CommandLine -match 'run-service-logged\.ps1') { $role = "runner_candidate" }
            $matched += [pscustomobject]@{ pid=[int]$row.ProcessId; parent_pid=[int]$row.ParentProcessId; role=$role; created_at=$row.CreationDate }
        }
    }
    if ($unclassified -gt 0) { $unknown.Add("process_command_line_unavailable") }
    $listeners = @()
    try {
        $lines = @(& "$env:SystemRoot\System32\netstat.exe" -ano -p tcp)
        if ($LASTEXITCODE -ne 0) { throw "netstat failed" }
        foreach ($line in $lines) {
            if ($line -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                $port = [int]$Matches[1]
                if ($port -in $Ports) { $listeners += [pscustomobject]@{ port=$port; pid=[int]$Matches[2] } }
            }
        }
    }
    catch { $unknown.Add("listener_inventory_unavailable") }
    $listenerProcesses = @()
    foreach ($listener in $listeners) {
        try {
            $process = Get-Process -Id $listener.pid -ErrorAction Stop
            $started = $process.StartTime.ToUniversalTime().ToString("o")
            if (-not $started) { throw "Missing start time" }
            $listenerProcesses += [pscustomobject]@{
                pid=$process.Id; name=$process.ProcessName; started_at=$started
                scope="listener_only_not_parent_or_writer_coverage"
            }
        }
        catch { $unknown.Add("listener_process_identity_unavailable") }
    }
    $services = @()
    $serviceStatus = "UNKNOWN"
    try {
        $serviceRows = @(Get-CimInstance Win32_Service -Property ProcessId,State,PathName -OperationTimeoutSec 5 -ErrorAction Stop)
        foreach ($row in $serviceRows) {
            if ($row.PathName -and $row.PathName.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $services += [pscustomobject]@{ pid=[int]$row.ProcessId; state=$row.State; role="repo_service_candidate" }
            }
        }
        $serviceStatus = "OBSERVED_PATH_MATCH_ONLY"
    }
    catch { $unknown.Add("service_inventory_unavailable") }
    $unknown.Add("scheduled_tasks_and_other_checkouts_unverified")
    $unknown.Add("db_wal_shm_handle_inventory_unverified")
    $unknown.Add("background_writer_ownership_and_respawn_unverified")
    $mode = "UNKNOWN"
    try {
        $mode = if (Test-Path -LiteralPath (Join-Path $Root "release-manifest.json") -ErrorAction Stop) { "packaged_candidate" } else { "source_candidate" }
    }
    catch { $unknown.Add("launcher_mode_unavailable") }
    return [pscustomobject]@{
        contract="omi.launcher-stop-diagnostic.v1"; observed_at=[DateTime]::UtcNow.ToString("o")
        verdict="BLOCKED"; dry_run=$true; lifecycle_actions=0
        launcher_mode=$mode; mode_basis="on_disk_marker_only_not_loaded_launcher_identity"
        requested_ports=$Ports; port_basis="explicit_or_default_not_effective_settings"
        listeners=$listeners; listener_processes=$listenerProcesses; process_inventory=$inventoryStatus
        processes_observed=$(if ($inventoryStatus -eq "UNKNOWN") { $null } else { $rows.Count })
        unclassified_processes=$(if ($inventoryStatus -eq "UNKNOWN") { $null } else { $unclassified }); repo_candidates=$matched
        service_inventory=$serviceStatus; service_candidates=$services
        handle_coverage="UNKNOWN"; stop_coverage="UNKNOWN"; writers_drained=$false
        stop_semantics="taskkill_tree_force"; graceful_shutdown_proven=$false
        loaded_launcher_identity="UNATTESTED"; unknown_reasons=@($unknown)
    }
}

if ($LauncherAction -eq "Diagnose") {
    try {
        $diagnosticRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
        Get-OmiStopDiagnostic -Root $diagnosticRoot -Ports $DiagnosticPorts | ConvertTo-Json -Depth 6
    }
    catch {
        # Deliberately exclude exception text, which can contain raw OS arguments.
        '{"contract":"omi.launcher-stop-diagnostic.v1","verdict":"BLOCKED","dry_run":true,"lifecycle_actions":0,"reason":"diagnostic_failed"}'
    }
    exit 2
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if ($null -eq ("OmiTaskbarCreatedListener" -as [type])) {
    $winFormsReferences = @(
        [System.Windows.Forms.Application].Assembly.Location
        [System.Windows.Forms.Message].Assembly.Location
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    Add-Type -ReferencedAssemblies $winFormsReferences -TypeDefinition @"
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
$script:TrayIconPath = Join-Path $script:RepoRoot "OMI.ico"
$script:AppDisplayName = "OMI_search"
$script:TrayIcon = $null
$script:RunEventName = "OpenMarketIntelligenceLauncherRun"
$script:RunEvent = $null
$script:ActivationEventName = "OpenMarketIntelligenceLauncherActivate"
$script:ActivationEvent = $null
$script:ExitEventName = "OpenMarketIntelligenceLauncherExit"
$script:ExitEvent = $null
$script:RestartEventName = "OpenMarketIntelligenceLauncherRestartServices"
$script:RestartEvent = $null
$script:RestartBackendEventName = "OpenMarketIntelligenceLauncherRestartBackend"
$script:RestartBackendEvent = $null
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
$script:OwnedBackendSession = $null
$script:OwnedBackendStartAttempted = $false
$script:RetiredBackendSessions = [Collections.Generic.List[object]]::new()
$script:ManualBackendStartAttemptedSession = $null
$script:FailedStartRecoveryAttempted = $false
$script:LastBackendStartError = $null
$script:FrontendProcess = $null
$script:FrontendRunnerIdentity = $null
$script:LastFrontendStop = $null
$script:FrontendStopUnconfirmed = $false
$script:LastFullServiceRestart = $null
$script:LastStatusText = $null
$script:BackendStopExpected = $false
$script:BackendRecoveryInProgress = $false
$script:BackendPortRecoveryAttempts = 0
$script:ServiceStartRequestInProgress = $false
$script:ServiceStopInProgress = $false
$script:SafeStopAttempted = $false
$script:LastServiceStopError = $null
$script:LauncherExitReady = $false
$script:RuntimeControlInProgress = $false
$script:OwnedBackendRestartRequests = [Collections.Generic.HashSet[string]]::new()
$script:LastBackendRestart = $null
$script:RestartReadyBackendSession = $null
# Debounce explicit requests during startup, including the runner's bounded retries.
# Automatic frontend recovery retains its separate grace and attempt budget.
$script:ServiceStartupGraceSeconds = 120
$script:IsShuttingDown = $false
$script:DashboardAutoOpened = $false
$script:DefaultFrontendHost = "127.0.0.1"
$script:DefaultFrontendPort = 3000
$script:FrontendPortSearchSpan = 1000
$script:FrontendDevBundlerArgument = "--webpack"
$script:FrontendHealthRecoveryGraceSeconds = 30
$script:FrontendHealthStableResetSeconds = 600
$script:MaxFrontendHealthRecoveryAttempts = 1
$script:FrontendHealthRecoveryAttempts = 0
$script:FrontendHealthUnhealthySinceUtc = $null
$script:FrontendHealthHealthySinceUtc = $null
$script:FrontendHealthRecoveryInProgress = $false
$script:FrontendHealthRecoveryExhaustedLogged = $false
$script:FrontendHealthRecoveryAdoptedLogged = $false
$script:DefaultBackendHost = "127.0.0.1"
$script:DefaultBackendPort = 8400
$script:BackendPortSearchSpan = 1000
$script:BackendBindFailureExitCode = 78
$script:MaxBackendPortRecoveryAttempts = 3
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
    $requestedEventName = switch ($LauncherAction) {
        "Run" { $script:RunEventName }
        "Activate" { $script:ActivationEventName }
        "Exit" { $script:ExitEventName }
        "RestartServices" { $script:RestartEventName }
        "RestartBackend" { $script:RestartBackendEventName }
    }
    $requestedAction = switch ($LauncherAction) {
        "Run" { "Run" }
        "Activate" { "activation" }
        "Exit" { "exit" }
        "RestartServices" { "Backend + Frontend restart" }
        "RestartBackend" { "Backend restart" }
    }
    $actionSignaled = $false
    try {
        $existingActionEvent = [System.Threading.EventWaitHandle]::OpenExisting($requestedEventName)
        try {
            $actionSignaled = $existingActionEvent.Set()
        }
        finally {
            $existingActionEvent.Dispose()
        }
    }
    catch {
        Write-LauncherLog "Existing launcher $requestedAction signal failed. error=$($_.Exception.Message)" "WARN"
    }

    if ($actionSignaled) {
        Write-LauncherLog "$($script:AppDisplayName) launcher $requestedAction requested through the existing tray owner."
    }
    else {
        Write-LauncherLog "$($script:AppDisplayName) launcher $requestedAction requested but the existing tray instance did not expose the required control event." "WARN"
        if ($LauncherAction -in @("Run", "Activate")) {
            Show-Message "$($script:AppDisplayName) has an existing launcher owner, but it does not expose the requested '$LauncherAction' control event. Service health is not confirmed. At a safe checkpoint, use Exit Launcher from its tray menu, then reopen the desktop launcher to load the current source."
        }
    }

    $script:Mutex.Dispose()
    if ($actionSignaled) {
        exit 0
    }
    exit 2
}

if ($LauncherAction -in @("Activate", "Exit", "RestartServices", "RestartBackend")) {
    Write-LauncherLog "Launcher action '$LauncherAction' found no existing tray owner; no service lifecycle action was required." "WARN"
    if ($script:OwnsMutex) {
        $script:Mutex.ReleaseMutex()
    }
    $script:Mutex.Dispose()
    if ($LauncherAction -eq "Exit") {
        exit 0
    }
    exit 3
}

$script:RunEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:RunEventName
)
$script:ActivationEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:ActivationEventName
)
$script:ExitEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:ExitEventName
)
$script:RestartEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:RestartEventName
)
$script:RestartBackendEvent = New-Object System.Threading.EventWaitHandle(
    $false,
    [System.Threading.EventResetMode]::AutoReset,
    $script:RestartBackendEventName
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

    $frontendDevBundler = if ($script:IsPackagedRelease) { "packaged" } else { $script:FrontendDevBundlerArgument.TrimStart("-") }
    Write-LauncherLog "Service environment initialized. backend=$($script:BackendBaseUrl) frontend=$($script:DashboardUrl) proxy_path=$($script:ApiProxyPath) backend_reload=$($script:BackendReload) frontend_dev_bundler=$frontendDevBundler"
}

function Initialize-ReleaseEnvironment {
    if (-not $script:IsPackagedRelease) {
        return
    }

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
    $owned = $script:OwnedBackendSession
    if ($null -ne $owned -and -not $script:BackendReload -and -not $script:IsPackagedRelease) {
        if (-not $script:OwnsMutex -or -not $owned.Alive -or
            -not [object]::ReferenceEquals($script:BackendProcess, $owned.RunnerProcess)) { return $false }
        # Captured from FixedPython at this retained session's birth, never an
        # arbitrary base interpreter or a new interpretation of pyvenv.cfg.
        $expectedPython = ConvertTo-NormalizedPath $owned.PythonExecutable
        if ([string]::IsNullOrWhiteSpace($expectedPython)) { return $false }
        $identity = Get-OmiOwnedBackendIdentity
        if ($null -eq $identity -or $identity.pid -ne $owned.ChildPid -or
            $identity.created_at -cne $owned.ChildCreated) { return $false }
        if ($null -ne $runtime.pid -and [int]$runtime.pid -ne $owned.ChildPid) { return $false }
        if ($null -ne $runtime.created_at -and [string]$runtime.created_at -cne $owned.ChildCreated) { return $false }
    }
    $actualPython = ConvertTo-NormalizedPath ([string]$runtime.python_executable)
    if ($actualPython -ne $expectedPython) {
        Write-LauncherLog "Backend Python runtime mismatch. expected=$ExpectedPythonPath actual=$($runtime.python_executable)" "WARN"
        return $false
    }

    if ($null -ne $owned -and -not $script:BackendReload -and -not $script:IsPackagedRelease -and -not $owned.Alive) { return $false }
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
    param([Parameter(Mandatory = $true)][int]$Port, [switch]$RequireObservation)

    $netstat = Join-Path $env:SystemRoot "System32\netstat.exe"
    if (-not (Test-Path -LiteralPath $netstat)) {
        if ($RequireObservation) { throw 'PORT_OBSERVATION_UNAVAILABLE' }
        return @()
    }

    $processIds = @()
    $lines = & $netstat -ano -p TCP 2>$null
    if ($RequireObservation -and ($LASTEXITCODE -ne 0 -or @($lines).Count -eq 0)) {
        throw 'PORT_OBSERVATION_UNAVAILABLE'
    }
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

function Find-ExpectedFrontendPort {
    param([Parameter(Mandatory = $true)][int]$PreferredPort)

    $maxPort = [Math]::Min($PreferredPort + $script:FrontendPortSearchSpan, 65535)
    $netstat = Join-Path $env:SystemRoot "System32\netstat.exe"
    if (-not (Test-Path -LiteralPath $netstat)) {
        return $null
    }

    $candidatePorts = @()
    $lines = & $netstat -ano -p TCP 2>$null
    foreach ($line in $lines) {
        if ($line -notmatch "^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+\d+\s*$") {
            continue
        }

        $port = [int]$Matches[1]
        if ($port -ge $PreferredPort -and $port -le $maxPort) {
            $candidatePorts += $port
        }
    }

    $urlHost = Format-UrlHost -HostName $script:FrontendHost
    foreach ($port in @($candidatePorts | Sort-Object -Unique)) {
        $healthUrl = "http://$urlHost`:$port/omi-ui-health"
        $health = Get-FrontendHealth -Url $healthUrl
        if ($null -ne $health -and (Test-FrontendHealthMatchesExpected -Health $health)) {
            return $port
        }
    }

    return $null
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

function Get-ExitedProcessCode {
    param($Process)

    if ($null -eq $Process) {
        return $null
    }

    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            return $null
        }
        return [int]$Process.ExitCode
    }
    catch {
        return $null
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

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $runnerArguments `
        -WorkingDirectory $script:RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    if ($ServiceName -ceq 'frontend') {
        # Retain the actual birth handle, never adopt a PID discovered by health.
        $script:FrontendProcess = $process
        $null = $process.Handle
        $script:FrontendRunnerIdentity = [pscustomobject]@{
            Process=$process; Pid=$process.Id; Created=$process.StartTime.ToUniversalTime();
            Path=$process.Path; Arguments=$runnerArguments; LauncherPid=$PID;
            Handle=$process.Handle; LauncherCreated=[Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime()
        }
        $script:FrontendStopUnconfirmed = $false
    }
    return $process
}

function Start-Backend {
    if ($script:SafeStopAttempted) { throw 'SAFE_STOP_NO_START_OR_RECOVERY' }
    if (-not $script:OwnsMutex) { throw 'BACKEND_START_OWNER_NOT_ATTESTED' }
    if ($null -ne $script:OwnedBackendSession -and $script:OwnedBackendSession.StartupFailure) {
        throw $script:OwnedBackendSession.StartupFailure
    }
    if ($null -ne $script:OwnedBackendSession -and
        ($script:OwnedBackendSession.Terminal -or -not $script:OwnedBackendSession.Alive)) {
        throw 'OWNED_START_NO_AUTOMATIC_REPLAY'
    }
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

    if (-not $script:BackendReload -and -not $script:IsPackagedRelease) {
        if ($script:OwnedBackendStartAttempted) { throw 'OWNED_START_NO_AUTOMATIC_REPLAY' }
        Assert-OmiProductionBackendStartPreflight
        # From this point a factory exception may hide a spawned Runner/child.
        # Never clear this latch merely because no session was returned.
        $script:OwnedBackendStartAttempted = $true
        $script:OwnedBackendSession = New-OmiProductionOwnedBackend
        if ($null -eq $script:OwnedBackendSession) { throw 'OWNED_START_UNKNOWN' }
        $script:BackendProcess = $script:OwnedBackendSession.RunnerProcess
        if ($script:OwnedBackendSession.StartupFailure) { throw $script:OwnedBackendSession.StartupFailure }
        Write-LauncherLog "Owned Backend started runner=$($script:BackendProcess.Id) child=$($script:OwnedBackendSession.ChildPid)."
        Publish-OmiRuntimeControlStatus
        return
    }

    # Legacy/reload cold starts may use a free fixed endpoint, but service
    # actions must never reach the historical port-owner force cleanup.
    if (@(Get-ListeningProcessIdsOnPort -Port $script:BackendPort -RequireObservation).Count -ne 0) { throw 'FIXED_PORT_NOT_FREE' }
    if (-not (Test-TcpPortBindable -Port $script:BackendPort -HostName $script:BackendHost -ServiceName 'Backend' -Quiet)) {
        throw 'FIXED_PORT_NOT_BINDABLE'
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

function Start-OmiBackendAfterExactStop {
    param([string]$ExpectedRelease)
    Assert-OmiManualBackendStartOwner
    if ($ExpectedRelease) { Assert-OmiBackendApplicationRelease -ExpectedRelease $ExpectedRelease }
    $old = $script:OwnedBackendSession
    if (-not $script:SafeStopAttempted -or $null -eq $old -or
        -not [object]::ReferenceEquals($script:BackendProcess, $old.RunnerProcess) -or
        -not $old.CanStartAfterStop) { throw 'PREVIOUS_EXACT_STOP_NOT_ATTESTED' }
    if ([object]::ReferenceEquals($old, $script:ManualBackendStartAttemptedSession)) {
        throw 'BACKEND_START_NO_REPLAY'
    }
    if (@(Get-ListeningProcessIdsOnPort -Port $script:BackendPort -RequireObservation).Count -ne 0) { throw 'FIXED_PORT_NOT_FREE' }
    if (-not (Test-TcpPortBindable -Port $script:BackendPort -HostName $script:BackendHost -ServiceName 'Backend' -Quiet)) {
        throw 'FIXED_PORT_NOT_BINDABLE'
    }

    # Archive before retiring; a Dispose/spawn failure keeps the old owner
    # and receipt reachable, and consumes this attempt without a retry.
    $script:RetiredBackendSessions.Add($old)
    $script:ManualBackendStartAttemptedSession = $old
    $script:LastBackendStartError = 'BACKEND_START_UNCONFIRMED'
    $old.DisposeAfterConfirmedStop()
    return Start-OmiBackendSuccessor -ExpectedRelease $ExpectedRelease
}

function Start-OmiBackendSuccessor {
    param([string]$ExpectedRelease)
    # Called only after the original owner has consumed a retirement gate.
    if (-not $script:ServiceStartRequestInProgress -or $null -eq $script:ManualBackendStartAttemptedSession -or
        $script:RetiredBackendSessions.Count -eq 0 -or
        -not [object]::ReferenceEquals($script:ManualBackendStartAttemptedSession,
            $script:RetiredBackendSessions[$script:RetiredBackendSessions.Count - 1])) {
        throw 'BACKEND_START_RETIREMENT_REQUIRED'
    }
    $script:OwnedBackendStartAttempted = $true
    if ($script:SchemaSuccessorPending) { $script:SchemaSuccessorAttempted = $true }
    $script:BackendFactoryAttemptCount++
    $next = New-OmiProductionOwnedBackend -ExpectedRelease $ExpectedRelease
    if ($null -eq $next) { throw 'BACKEND_START_UNCONFIRMED' }
    $script:OwnedBackendSession = $next
    $script:BackendProcess = $next.RunnerProcess
    $script:BackendStopExpected = $false
    $script:LastServiceStopError = $null
    if ($next.StartupFailure) { throw $next.StartupFailure }
    $pending = $next.WaitForStartReadinessAsync(30000)
    while (-not $pending.IsCompleted) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 25
    }
    if (-not $pending.GetAwaiter().GetResult()) { throw 'BACKEND_START_READINESS_UNCONFIRMED' }
    Assert-OmiManualBackendStartOwner
    if ($ExpectedRelease) {
        Assert-OmiBackendApplicationRelease -ExpectedRelease $ExpectedRelease
        if ($next.ReleaseId -cne $ExpectedRelease) { throw 'RESTART_RELEASE_NOT_ADOPTED' }
    }
    $identity = Get-OmiOwnedBackendIdentity
    if (-not [object]::ReferenceEquals($next, $script:OwnedBackendSession) -or
        -not [object]::ReferenceEquals($script:BackendProcess, $next.RunnerProcess) -or
        -not $next.Alive -or $next.Terminal -or $null -eq $identity -or
        $identity.pid -ne $next.ChildPid -or $identity.created_at -cne $next.ChildCreated) {
        throw 'BACKEND_START_IDENTITY_UNCONFIRMED'
    }
    $script:LastBackendStartError = $null
    $script:LastStatusText = $null
    $script:RestartReadyBackendSession = $next
    try { Publish-OmiRuntimeControlStatus }
    catch {
        $script:RestartReadyBackendSession = $null
        $script:LastBackendStartError = 'BACKEND_START_UNCONFIRMED'; throw
    }
    return $identity
}

function Assert-OmiFailedStartProcessExclusion {
    # Read-only inventory; missing command lines/permissions are unknown, not empty.
    # Never open/adopt a discovered process handle or touch the Frontend tree.
    $rows = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%.exe' OR Name = 'uvicorn.exe' OR Name = 'powershell.exe' OR Name = 'pwsh.exe' OR Name = 'cmd.exe'" -Property ProcessId,CommandLine -OperationTimeoutSec 3 -ErrorAction Stop)
    if (@($rows | Where-Object { $_.ProcessId -eq $PID }).Count -ne 1) { throw 'FAILED_START_PROCESS_OBSERVATION_UNKNOWN' }
    foreach ($row in $rows) {
        if ($row.ProcessId -eq $PID) { continue }
        if ($row.ProcessId -le 0 -or [string]::IsNullOrWhiteSpace($row.CommandLine)) { throw 'FAILED_START_PROCESS_OBSERVATION_UNKNOWN' }
        if ($row.CommandLine -match 'owned_backend_entry\.py|uvicorn\s+app\.main:app' -or
            ($row.CommandLine -match 'run-service-logged\.ps1' -and $row.CommandLine -match '-ServiceName\s+"?backend\b')) {
            throw 'FAILED_START_OTHER_BACKEND_PRESENT'
        }
    }
}

function Start-OmiBackendAfterFailedStart {
    param([Parameter(Mandatory = $true)][string]$RequestId)
    $RequestId=[Guid]::ParseExact($RequestId,'D').ToString('D')
    Assert-OmiManualBackendStartOwner
    if (-not $script:ServiceStartRequestInProgress) { throw 'FAILED_START_MANUAL_GUARD_REQUIRED' }
    $old = $script:OwnedBackendSession
    if ([object]::ReferenceEquals($old, $script:ManualBackendStartAttemptedSession) -or
        $script:OwnedBackendRestartRequests.Contains($RequestId)) { throw 'FAILED_START_RECOVERY_REPLAY' }
    if ($null -eq $old -or -not $script:OwnedBackendStartAttempted -or
        -not [object]::ReferenceEquals($script:BackendProcess, $old.RunnerProcess) -or
        -not $old.CanRecoverFailedStart) { throw 'FAILED_START_RECOVERY_NOT_ATTESTED' }
    $targetRelease = Get-OmiBackendApplicationRelease
    Assert-OmiSchemaCompatibility -ExpectedRelease $targetRelease
    Assert-OmiProductionBackendStartPreflight
    Assert-OmiFailedStartProcessExclusion
    Assert-OmiManualBackendStartOwner
    Assert-OmiBackendApplicationRelease -ExpectedRelease $targetRelease
    # One retirement per retained generation; a new failed generation must prove
    # its own exact exit. Unknown factory results cannot manufacture that proof.
    $null=$script:OwnedBackendRestartRequests.Add($RequestId)
    $script:FailedStartRecoveryAttempted = $true
    $script:SafeStopAttempted = $true
    $script:RetiredBackendSessions.Add($old)
    $script:ManualBackendStartAttemptedSession = $old
    $script:LastBackendStartError = 'FAILED_START_RECOVERY_UNCONFIRMED'
    Write-LauncherLog "Manual failed-start recovery accepted request=$RequestId; original startup failure retained."
    $old.RetireFailedStart($RequestId, $targetRelease)
    Assert-OmiFailedStartProcessExclusion
    return Start-OmiBackendSuccessor -ExpectedRelease $targetRelease
}

function Write-OmiSchemaOperation {
    param([string]$Path, $Record, [switch]$Create)
    $Record.updated_at=[DateTime]::UtcNow.ToString('o')
    $mode = if ($Create) { [IO.FileMode]::CreateNew } else { [IO.FileMode]::Append }
    $file = [IO.FileStream]::new($Path, $mode, [IO.FileAccess]::Write, [IO.FileShare]::Read,
        4096, [IO.FileOptions]::WriteThrough)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Record | ConvertTo-Json -Depth 8 -Compress) + "`n")
        $file.Write($bytes, 0, $bytes.Length); $file.Flush($true)
    } finally { $file.Dispose() }
}

function Get-OmiSchemaWorkerOutcome {
    param([string]$Path, [string]$RequestId)
    # Diagnostic only: never grants Apply/start/replay authority.
    try {
        $info=[IO.FileInfo]::new($Path)
        if (-not $info.Exists -or $info.Length -gt 262144) { return 'UNKNOWN' }
        $text=[IO.File]::ReadAllText($Path)
        if (-not $text.EndsWith("`n")) { return 'UNKNOWN' }
        $sequence=0; $last=$null
        foreach ($line in ($text.TrimEnd("`n") -split "`n")) {
            $row=$line | ConvertFrom-Json
            $sequence++
            if ($row.contract -cne 'omi.schema-apply.v1' -or $row.request_id -cne $RequestId -or
                $row.sequence -ne $sequence -or $row.retry_allowed -isnot [bool] -or $row.retry_allowed) { return 'UNKNOWN' }
            $last=$row
        }
        if ($last.migration -ceq 'COMMITTED' -and $last.phase -cin @('COMMITTED','FAILED')) { return 'COMMITTED' }
        if ($last.phase -ceq 'FAILED' -and $last.migration -ceq 'NOT_ATTEMPTED') { return 'NOT_ATTEMPTED' }
        if ($last.phase -ceq 'FAILED' -and $last.migration -ceq 'FAILED_TRANSACTION_REQUIRES_INSPECTION') {
            return 'FAILED_TRANSACTION_REQUIRES_INSPECTION'
        }
    } catch { }
    return 'UNKNOWN'
}

function Invoke-OwnedSchemaUpgrade {
    param([Parameter(Mandatory=$true)][string]$RequestId,
        [Parameter(Mandatory=$true)][string]$DatabasePath,
        [Parameter(Mandatory=$true)][string]$SchemaLockPath,[switch]$RemoteRequest)
    $RequestId=[Guid]::ParseExact($RequestId,'D').ToString('D')
    if ($script:IsShuttingDown -or $script:ServiceStartRequestInProgress -or
        $script:ServiceStopInProgress -or ($script:RuntimeControlInProgress -and -not $RemoteRequest) -or
        $script:BackendRecoveryInProgress -or $script:FrontendHealthRecoveryInProgress) {
        throw 'SERVICE_OPERATION_IN_PROGRESS'
    }
    $existingReceipt=Join-Path (Join-Path $script:RuntimeControlStore 'schema-maintenance') ($RequestId + '.operation.jsonl')
    if ((Test-Path -LiteralPath $existingReceipt) -or $script:OwnedBackendRestartRequests.Contains($RequestId)) { throw 'SCHEMA_MAINTENANCE_NO_REPLAY' }
    Assert-OmiSchemaRecoveryAdmission
    $script:ServiceStartRequestInProgress = $true
    $timerEnabled = $null -ne $script:Timer -and $script:Timer.Enabled
    $activationEnabled = $null -ne $script:ActivationTimer -and $script:ActivationTimer.Enabled
    $record = $null; $receipt = $null; $intentCreated=$false; $terminalPersisted=$false
    $effectsPossible=$false
    $previousSchemaFailure=$script:SchemaMaintenanceFailed
    $previousSafeStop=$script:SafeStopAttempted
    $previousStopExpected=$script:BackendStopExpected
    $previousReadySession=$script:RestartReadyBackendSession
    $script:SchemaSuccessorAttempted=$false
    try {
        if ($null -ne $script:Timer) { $script:Timer.Stop() }
        if ($null -ne $script:ActivationTimer) { $script:ActivationTimer.Stop() }
        # Every admission, including refusal, has a durable, non-overwriting intent.
        $directory = Join-Path $script:RuntimeControlStore 'schema-maintenance'
        [void][IO.Directory]::CreateDirectory($directory)
        $receipt = Join-Path $directory ($RequestId + '.operation.jsonl')
        $record = [ordered]@{contract='omi.schema-operation.v1'; request_id=$RequestId;
            phase='INTENT'; status='UNKNOWN'; retry_allowed=$false; sequence=1;
            migration_outcome='NOT_ATTEMPTED'; successor_outcome='NOT_ATTEMPTED';
            frontend_interrupted=$false; admission=$null; stop=$null; after=$null;
            worker_receipt=(Join-Path $directory ($RequestId + '.apply.jsonl'))}
        Write-OmiSchemaOperation -Path $receipt -Record $record -Create
        $intentCreated=$true
        $null=$script:OwnedBackendRestartRequests.Add($RequestId)
        $script:SchemaRecoveryFence=@{Path=$receipt;TerminalHash=$null;NoEffects=$false;WorkerSettled=$false}
        $script:SchemaMaintenanceAttempted = $true
        $script:SchemaMaintenanceFailed = $true
        Assert-OmiManualBackendStartOwner
        $old = $script:OwnedBackendSession
        if ($null -eq $old -or -not [object]::ReferenceEquals($script:BackendProcess, $old.RunnerProcess)) {
            throw 'SCHEMA_OWNER_AMBIGUOUS'
        }
        $targetRelease = Get-OmiBackendApplicationRelease
        Assert-OmiSchemaCompatibility -ExpectedRelease $targetRelease -Upgrade -DatabasePath $DatabasePath -SchemaLockPath $SchemaLockPath
        $failedStart = [bool]$old.StartupFailure
        $schemaRelease = Get-OmiSchemaSourceRelease
        $record.admission = if ($failedStart) { 'FAILED_START_EXACT_EXIT' } else { 'RUNNING_GRACEFUL_STOP' }
        $record.target_release = $targetRelease
        $record.schema_source_release = $schemaRelease
        $record.before = @{pid=$old.ChildPid; created_at=$old.ChildCreated}
        $record.phase='ADMISSION'; $record.sequence++
        Write-OmiSchemaOperation -Path $receipt -Record $record
        if ($failedStart) {
            if (-not $old.CanRecoverFailedStart) { throw 'SCHEMA_FAILED_START_NOT_ATTESTED' }
            Assert-OmiFailedStartProcessExclusion
            $old.AdmitFailedStartSchemaMaintenance($RequestId, $targetRelease)
        } elseif ($old.CanStartAfterStop) {
            Assert-OmiFailedStartProcessExclusion
            $old.AdmitStoppedSchemaMaintenance($RequestId,$targetRelease)
            $record.admission='RETAINED_GRACEFUL_EXIT'
        } else {
            if (-not $old.HasRetainedIdentity -or ($null -ne $old.LastStop -and -not $old.CanResumeAfterSchemaStopRefusal) -or $old.Terminal) {
                throw 'SCHEMA_RUNNING_OWNER_NOT_ATTESTED'
            }
            $effectsPossible=$true # From first possible STOP dispatch, delivery can be unknown.
            $script:SafeStopAttempted=$true
            $script:RestartReadyBackendSession=$null
            $script:BackendStopExpected=$true
            $pending=$old.StopForSchemaMaintenanceAsync($RequestId, $targetRelease)
            while (-not $pending.IsCompleted) { Start-Sleep -Milliseconds 25 }
            $stop=$pending.GetAwaiter().GetResult()
            $record.stop=@{request_id=$stop.RequestId; state=$stop.State; reason=$stop.Reason;
                exact_exit=$stop.ExactExit; forced=$stop.Forced; before_pid=$stop.BeforePid;
                before_created=$stop.BeforeCreated}
            if ($old.CanResumeAfterSchemaStopRefusal -and $stop.RequestId -ceq $RequestId) {
                $effectsPossible=$false # Native retained STOP-not-sent/rearm evidence, not an inferred reset.
            }
            if ($stop.RequestId -cne $RequestId -or -not $stop.ExactExit -or $stop.Forced -or
                $stop.ForcedExitConfirmed -or $stop.Rearmed -or $stop.State -cne 'stopped' -or
                $stop.Reason -cne 'LIFESPAN_AND_EXACT_EXIT' -or
                $stop.BeforePid -ne $old.ChildPid -or $stop.BeforeCreated -cne $old.ChildCreated -or
                -not $old.CanStartAfterStop) { throw 'SCHEMA_GRACEFUL_EXIT_REQUIRED' }
        }
        Assert-OmiManualBackendStartOwner
        Assert-OmiBackendApplicationRelease -ExpectedRelease $targetRelease
        $record.phase='APPLY_STOPPED'; $record.sequence++
        $record.migration_outcome='UNKNOWN'
        Write-OmiSchemaOperation -Path $receipt -Record $record
        try {
            $effectsPossible=$true
            $script:SafeStopAttempted=$true
            $script:RestartReadyBackendSession=$null
            $script:BackendStopExpected=$true
            $pending=$old.ApplyStoppedSchemaAsync($RequestId, $targetRelease, $schemaRelease, $DatabasePath, $SchemaLockPath,
                (Join-Path $directory ($RequestId + '.backup.db')), $record.worker_receipt)
            while (-not $pending.IsCompleted) { Start-Sleep -Milliseconds 25 }
            $applied=$pending.GetAwaiter().GetResult()
        } finally {
            $record.migration_outcome=Get-OmiSchemaWorkerOutcome -Path $record.worker_receipt -RequestId $RequestId
        }
        # Receipt observation alone cannot authorize a successor after a lost
        # worker channel. Require the retained worker's validated terminal reply.
        if (-not $applied -or $record.migration_outcome -cne 'COMMITTED') { throw 'SCHEMA_APPLY_UNCONFIRMED' }
        Assert-OmiManualBackendStartOwner
        Assert-OmiBackendApplicationRelease -ExpectedRelease $targetRelease
        $record.phase='STARTING_ONCE'; $record.sequence++
        $record.successor_outcome='STARTING'
        Write-OmiSchemaOperation -Path $receipt -Record $record
        $script:SchemaSuccessorPending=$true
        if ($failedStart) {
            Assert-OmiFailedStartProcessExclusion
            Assert-OmiProductionBackendStartPreflight
            $script:FailedStartRecoveryAttempted=$true
            $script:RetiredBackendSessions.Add($old)
            $script:ManualBackendStartAttemptedSession=$old
            $old.RetireFailedStart($RequestId, $targetRelease)
            $verified=Start-OmiBackendSuccessor -ExpectedRelease $targetRelease
        } else {
            $verified=Start-OmiBackendAfterExactStop -ExpectedRelease $targetRelease
        }
        $record.after=@{pid=$verified.pid; created_at=$verified.created_at; release=$targetRelease; readyz='VERIFIED'}
        $record.phase='COMPLETE'; $record.status='SUCCEEDED'; $record.sequence++
        $record.successor_outcome='VERIFIED'
        Write-OmiSchemaOperation -Path $receipt -Record $record
        $terminalPersisted=$true
        $script:SchemaMaintenanceFailed=$false
    } catch {
        if ($intentCreated) {
            $script:SchemaMaintenanceFailed=$true
            $script:RestartReadyBackendSession=$null
            if ($null -ne $record) {
                $record.failed_phase=$record.phase; $record.phase='FAILED'; $record.sequence++
                if ($script:SchemaSuccessorAttempted -and $record.successor_outcome -ne 'VERIFIED') {
                    $record.successor_outcome='FAILED_UNCONFIRMED'
                }
                elseif ($record.successor_outcome -eq 'STARTING') { $record.successor_outcome='NOT_ATTEMPTED' }
                $record.status = switch ($record.migration_outcome) {
                    'COMMITTED' {
                        if ($record.successor_outcome -eq 'VERIFIED') { 'UNKNOWN_RECONCILIATION_REQUIRED' }
                        elseif ($script:SchemaSuccessorAttempted) { 'MIGRATED_START_FAILED' }
                        else { 'MIGRATED_START_UNVERIFIED' }
                    }
                    'NOT_ATTEMPTED' { 'BLOCKED_NO_DB_CHANGE' }
                    default { 'UNKNOWN_RECONCILIATION_REQUIRED' }
                }
                $record.error_type=$_.Exception.GetType().Name
                $record.next_action=if (-not $effectsPossible -or ($null -ne $old -and $old.SchemaWorkerSettled -and
                    $record.migration_outcome -cin @('NOT_ATTEMPTED','COMMITTED'))) {
                    'CheckStart_then_new_UUID_with_retained_generation'
                } else {'ReadOperation_and_Plan_then_reconcile_worker_and_generation'}
                Write-OmiSchemaOperation -Path $receipt -Record $record
                $terminalPersisted=$true
            }
        }
        if (-not $effectsPossible) {
            # Pure preflight refusal consumes only this schema request. Restore
            # normal maintenance admission; no STOP/worker/factory was dispatched.
            $script:SchemaMaintenanceFailed=$previousSchemaFailure
            $script:SafeStopAttempted=$previousSafeStop
            $script:BackendStopExpected=$previousStopExpected
            $script:RestartReadyBackendSession=$previousReadySession
        }
        throw
    } finally {
        if ($intentCreated) {
            $script:LastSchemaOperation=$record
            $script:SchemaRecoveryFence=@{Path=$receipt;
                TerminalHash=$(if ($terminalPersisted) {Get-OmiSchemaReceiptHash -Path $receipt} else {$null});
                NoEffects=(-not $effectsPossible);WorkerSettled=($null -ne $old -and $old.SchemaWorkerSettled -and
                    $record.migration_outcome -cin @('NOT_ATTEMPTED','COMMITTED'))}
        }
        try {
            [System.Windows.Forms.Application]::DoEvents()
            foreach ($event in @($script:RunEvent,$script:RestartEvent,$script:RestartBackendEvent,$script:ExitEvent)) {
                if ($null -ne $event) { [void]$event.Reset() }
            }
        } finally {
            $script:SchemaSuccessorPending=$false
            $script:ServiceStartRequestInProgress=$false
            if ($timerEnabled) { $script:Timer.Start() }
            if ($activationEnabled) { $script:ActivationTimer.Start() }
        }
    }
}

function Invoke-OmiConfiguredSchemaUpgrade {
    param([string]$RequestId=([Guid]::NewGuid().ToString('D')),[switch]$RemoteRequest)
    Assert-OmiManualBackendStartOwner
    Assert-OmiSchemaRecoveryAdmission
    $release=Get-OmiBackendApplicationRelease
    try {
        $target=Assert-OmiSchemaCompatibility -ExpectedRelease $release -Upgrade -PassThru
        if ($null -eq $target.configured_target -or
            [string]::IsNullOrWhiteSpace($target.configured_target.database_path) -or
            [string]::IsNullOrWhiteSpace($target.configured_target.schema_lock_path)) { throw 'NO_CONFIGURED_TARGET' }
        # Canonical paths are private inspector output, never request fields.
        $database=Get-OmiIdentityPath -Path $target.configured_target.database_path
        $lock=Get-OmiIdentityPath -Path $target.configured_target.schema_lock_path
        if ([IO.Path]::GetFileName($lock) -cne 'schema.lock') { throw 'NO_CONFIGURED_TARGET' }
    } catch { throw 'SCHEMA_CONFIGURED_TARGET_UNAVAILABLE' }
    Invoke-OwnedSchemaUpgrade -RequestId $RequestId -DatabasePath $database -SchemaLockPath $lock -RemoteRequest:$RemoteRequest
}

function Show-OmiSchemaUpgrade {
    # A tray click is local intent; it uses the same configured target and gates.
    Invoke-OmiConfiguredSchemaUpgrade
}

function Invoke-BackendStartRequest {
    param([switch]$FailedStartRecovery,[string]$RequestId=([Guid]::NewGuid().ToString('D')),[switch]$RemoteRequest)
    Assert-OmiSchemaRecoveryAdmission
    $RequestId=[Guid]::ParseExact($RequestId,'D').ToString('D')
    # Dedicated tray clicks or approved, dequeued Controller intent call this.
    # SafeStopAttempted stays sticky for automatic paths:
    # automatic recovery and the Controller's old destructive queue stay fenced.
    if ($script:IsShuttingDown -or $script:ServiceStartRequestInProgress -or
        $script:ServiceStopInProgress -or ($script:RuntimeControlInProgress -and -not $RemoteRequest) -or
        $script:BackendRecoveryInProgress -or $script:FrontendHealthRecoveryInProgress) {
        throw 'SERVICE_OPERATION_IN_PROGRESS'
    }
    $script:ServiceStartRequestInProgress = $true
    $timerEnabled = $null -ne $script:Timer -and $script:Timer.Enabled
    $activationEnabled = $null -ne $script:ActivationTimer -and $script:ActivationTimer.Enabled
    try {
        if ($null -ne $script:Timer) { $script:Timer.Stop() }
        if ($null -ne $script:ActivationTimer) { $script:ActivationTimer.Stop() }
        if ($FailedStartRecovery) {
            $null = Start-OmiBackendAfterFailedStart -RequestId $RequestId
        } else {
            if ($script:OwnedBackendRestartRequests.Contains($RequestId)) {throw 'BACKEND_START_NO_REPLAY'}
            $null=$script:OwnedBackendRestartRequests.Add($RequestId)
            $release=$script:OwnedBackendSession.ReleaseId
            Assert-OmiSchemaCompatibility -ExpectedRelease $release
            $null = Start-OmiBackendAfterExactStop -ExpectedRelease $release
        }
        Write-LauncherLog 'Backend started after explicit tray request; owned READY and HTTP readiness verified; Frontend unchanged.'
    }
    catch {
        # An observation failure never stops, retries or discards a new session.
        Write-LauncherLog 'Explicit Backend start refused or unconfirmed; retained owner; no retry or fallback.' 'WARN'
        throw
    }
    finally {
        try {
            # Drain queued UI clicks while all entrypoints remain fenced, then
            # discard named events. Controller pending requests are never taken.
            [System.Windows.Forms.Application]::DoEvents()
            foreach ($event in @($script:RunEvent, $script:RestartEvent, $script:RestartBackendEvent, $script:ExitEvent)) {
                if ($null -ne $event) { [void]$event.Reset() }
            }
        }
        finally {
            $script:ServiceStartRequestInProgress = $false
            if ($timerEnabled) { $script:Timer.Start() }
            if ($activationEnabled) { $script:ActivationTimer.Start() }
        }
    }
}

function Invoke-OwnedBackendRestart {
    param([Parameter(Mandatory = $true)][string]$RequestId, [switch]$RemoteRequest, $Deadline = $null)
    Assert-OmiSchemaRecoveryAdmission
    if ($null -eq $Deadline) { $Deadline = [Omi.OwnedShutdown.LifecycleDeadline]::new() }
    if ($RemoteRequest) { $Deadline = $script:RuntimeController.OwnedRestartDeadline($RequestId) }
    $null = [Guid]::ParseExact($RequestId, 'D')
    if ($script:IsShuttingDown -or $script:ServiceStartRequestInProgress -or
        $script:ServiceStopInProgress -or $script:BackendRecoveryInProgress -or
        $script:FrontendHealthRecoveryInProgress -or ($script:RuntimeControlInProgress -and -not $RemoteRequest)) {
        throw 'SERVICE_OPERATION_IN_PROGRESS'
    }
    if ($script:OwnedBackendRestartRequests.Contains($RequestId)) { throw 'BACKEND_RESTART_NO_REPLAY' }
    $script:ServiceStartRequestInProgress = $true
    $timerEnabled = $null -ne $script:Timer -and $script:Timer.Enabled
    $activationEnabled = $null -ne $script:ActivationTimer -and $script:ActivationTimer.Enabled
    $begun = $false; $stopped = $null; $next = $null; $verified = $null; $stopDispatched=$false
    $factoryAttemptsBefore=[long]$script:BackendFactoryAttemptCount
    $previousSafeStopAttempted = $script:SafeStopAttempted
    $previousRestartReadySession = $script:RestartReadyBackendSession
    $blocker = 'OWNER_NOT_ATTESTED'
    try {
        if ($null -ne $script:Timer) { $script:Timer.Stop() }
        if ($null -ne $script:ActivationTimer) { $script:ActivationTimer.Stop() }
        if (-not $script:OwnsMutex) { throw 'OWNER_NOT_ATTESTED' }
        $old = $script:OwnedBackendSession
        $identity = Get-OmiOwnedBackendIdentity
        if ($null -eq $old -or $null -eq $identity -or -not $old.HasRetainedIdentity -or
            $old.Terminal -or -not $old.Alive -or $old.StartupFailure -or $script:LastBackendStartError -or
            -not [object]::ReferenceEquals($script:BackendProcess, $old.RunnerProcess) -or
            $identity.pid -ne $old.ChildPid -or $identity.created_at -cne $old.ChildCreated) { throw $blocker }
        # Consume the Controller's authenticated, dequeued remote intent once.
        # A dedicated tray click supplies local intent inside owner.
        if ($RemoteRequest -and -not $script:RuntimeController.BeginAuthenticatedOwnedRestart($RequestId, $identity)) { return }
        $null = $script:OwnedBackendRestartRequests.Add($RequestId)
        $begun = $true
        $script:LastBackendRestart = [pscustomobject]@{ RequestId=$RequestId; State='unknown';
            Reason='LIFECYCLE_FAILED'; Stop=$null; After=$null; PreflightStage=$null }
        # The consumed intent selects the current disk application snapshot.
        # The retained session still owns the OLD process/STOP wire identity;
        # targetRelease is only the successor pin, never the old ReleaseId.
        Assert-OmiManualBackendStartOwner
        $targetRelease = Get-OmiBackendApplicationRelease
        $blocker='RESTART_COMPATIBILITY_NOT_ATTESTED'
        Assert-OmiBackendApplicationRelease -ExpectedRelease $targetRelease
        Assert-OmiSchemaCompatibility -ExpectedRelease $targetRelease
        # Re-observe owner/source before STOP, with
        # the accepted request already consumed so ambiguity cannot replay it.
        $blocker='OWNER_NOT_ATTESTED'
        Assert-OmiManualBackendStartOwner
        Assert-OmiBackendApplicationRelease -ExpectedRelease $targetRelease
        $current = Get-OmiOwnedBackendIdentity
        if ($null -eq $current -or $current.pid -ne $identity.pid -or
            $current.created_at -cne $identity.created_at -or
            -not [object]::ReferenceEquals($old, $script:OwnedBackendSession)) { throw 'OWNER_NOT_ATTESTED' }
        # Never unlock automatic recovery or the Controller's older queue.
        $script:SafeStopAttempted = $true
        $script:RestartReadyBackendSession = $null
        $script:BackendStopExpected = $true
        $stopDispatched=$true
        $pending = $old.StopWithinDeadlineAsync($RequestId, $targetRelease, $Deadline)
        while (-not $pending.IsCompleted) {
            if ($Deadline.ElapsedMilliseconds -gt 185000) { throw 'CUTOFF_RECEIPT_UNAVAILABLE' }
            Start-Sleep -Milliseconds 25
        }
        $stopped = $pending.GetAwaiter().GetResult()
        $script:LastBackendRestart.Stop = $stopped
        $script:LastBackendRestart.PreflightStage = $stopped.PreflightStage
        if ($stopped.Rearmed -or $stopped.StopNotSent) {
            if ($stopped.RequestId -cne $RequestId -or $stopped.BeforePid -ne $old.ChildPid -or
                $stopped.BeforeCreated -cne $old.ChildCreated -or $stopped.State -cne 'blocked' -or
                $stopped.ExactExit -or $old.Terminal -or -not $old.Alive -or
                -not [object]::ReferenceEquals($old, $script:OwnedBackendSession)) { throw 'REARM_NOT_ATTESTED' }
            if (-not $stopped.Rearmed -and ($stopped.PreflightStage -cne 'BEFORE_PREPARE' -or
                $stopped.Reason -cnotin @('RESTART_SOURCE_CHANGED', 'RESTART_ABORT_PROTOCOL_UNAVAILABLE'))) { throw 'REARM_NOT_ATTESTED' }
            $script:SafeStopAttempted = $previousSafeStopAttempted
            $script:RestartReadyBackendSession = $previousRestartReadySession
            $script:BackendStopExpected = $false
            $script:LastBackendRestart.State = 'blocked'
            $script:LastBackendRestart.Reason = $stopped.Reason
            $script:LastServiceStopError = "$($stopped.Reason) stage=$($stopped.PreflightStage)"
            throw $script:LastServiceStopError
        }
        if ($stopped.RequestId -cne $RequestId -or
            (-not $stopped.ExactExit -and -not $stopped.ForcedExitConfirmed) -or
            -not [object]::ReferenceEquals($old, $script:OwnedBackendSession) -or -not $old.CanStartAfterStop) {
            throw 'PREVIOUS_EXACT_STOP_NOT_ATTESTED'
        }
        $verified = Start-OmiBackendAfterExactStop -ExpectedRelease $targetRelease
        $next = $script:OwnedBackendSession
        $script:LastBackendRestart.State = 'succeeded'
        $script:LastBackendRestart.Reason = 'SUCCEEDED'
    }
    catch {
        if ($begun -and -not $stopDispatched) {
            if ($_.Exception.Message -in @('RESTART_SOURCE_CHANGED', 'SOURCE_ADOPTION_NOT_ATTESTED')) {
                $blocker=$_.Exception.Message
            }
            $script:LastBackendRestart.State='blocked'
            $script:LastBackendRestart.Reason=$blocker
            $script:LastBackendRestart.PreflightStage='BEFORE_STOP'
        }
        if ($RemoteRequest -and -not $begun) { $script:RuntimeController.BlockOwnedRestart($RequestId, $blocker) }
        Write-LauncherLog 'Owned Backend restart refused or unconfirmed; retained sessions; no replay.' 'WARN'
        throw
    }
    finally {
        try {
            if ($begun) {
                if (-not [object]::ReferenceEquals($old, $script:OwnedBackendSession)) { $next = $script:OwnedBackendSession }
                $script:LastBackendRestart.After = $next
                if ($RemoteRequest) { $script:RuntimeController.CompleteOwnedRestart($RequestId, $stopped, $next, $verified,
                    $(if (-not $stopDispatched) {$blocker} else {$null}),
                    ([long]$script:BackendFactoryAttemptCount -gt $factoryAttemptsBefore)) }
                Publish-OmiRuntimeControlStatus
            }
        }
        catch {
            if ($begun) {
                $script:LastBackendRestart.State = 'unknown'
                $script:LastBackendRestart.Reason = 'LIFECYCLE_FAILED'
                $script:RestartReadyBackendSession = $null
                if ($null -ne $next) { $script:LastBackendStartError = 'BACKEND_START_UNCONFIRMED' }
            }
            throw
        }
        finally {
            try {
                foreach ($event in @($script:RunEvent, $script:RestartEvent, $script:RestartBackendEvent, $script:ExitEvent)) {
                    if ($null -ne $event) { [void]$event.Reset() }
                }
            }
            finally {
                $script:ServiceStartRequestInProgress = $false
                if ($timerEnabled) { $script:Timer.Start() }
                if ($activationEnabled) { $script:ActivationTimer.Start() }
            }
        }
    }
    Write-LauncherLog 'Backend restart completed; exact old exit and new owned HTTP readiness verified; Frontend unchanged.'
}

function Test-FrontendRecoveryAdmission {
    param([switch]$HealthRecovery)
    if ($script:FrontendStopUnconfirmed -or $script:LastBackendStartError -or
        $script:ServiceStopInProgress -or $script:RuntimeControlInProgress -or $script:IsShuttingDown) { return $false }
    if ($null -ne $script:LastFullServiceRestart -and
        $script:LastFullServiceRestart.State -cne 'succeeded') { return $false }
    # Initial service startup owns these guards; automatic recovery never does.
    if (($HealthRecovery -or $script:SafeStopAttempted) -and
        ($script:ServiceStartRequestInProgress -or $script:BackendRecoveryInProgress)) { return $false }
    if (-not $script:SafeStopAttempted) { return $true }
    # Read-only exception for the SAME retained live verified successor. Never
    # rearm Backend admission or clear the sticky stop fence.
    try { return (Test-OmiRemoteRestartGeneration) }
    catch { return $false }
}

function Start-Frontend {
    param([switch]$AfterConfirmedStop)
    if ($AfterConfirmedStop) {
        if (-not $script:ServiceStartRequestInProgress -or $null -eq $script:LastFrontendStop -or
            $script:LastFrontendStop.State -cne 'stopped' -or $script:LastFrontendStop.StartAttempted -or
            $null -ne $script:FrontendProcess -or $script:FrontendStopUnconfirmed -or
            $script:LastFrontendStop.Port -ne $script:FrontendPort) { throw 'FRONTEND_START_NOT_ATTESTED' }
        # One explicit attempt. Do not clear the Backend safe-stop/remote fence.
        $script:LastFrontendStop.StartAttempted = $true
        if (@(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort -RequireObservation).Count -ne 0 -or
            -not (Test-TcpPortBindable -Port $script:FrontendPort -HostName $script:FrontendHost -ServiceName 'Frontend')) {
            throw 'FRONTEND_START_NOT_ATTESTED'
        }
    }
    elseif (-not (Test-FrontendRecoveryAdmission)) { throw 'SAFE_STOP_NO_START_OR_RECOVERY' }
    if (-not $AfterConfirmedStop) {
    $frontendHealth = Get-FrontendHealth
    if ($null -ne $frontendHealth -and (Test-FrontendHealthMatchesExpected -Health $frontendHealth)) {
        Write-LauncherLog "Frontend health endpoint already responds with the expected project/runtime; skipping frontend start."
        return
    }

    $existingFrontendPort = Find-ExpectedFrontendPort -PreferredPort $script:FrontendPort
    if ($null -ne $existingFrontendPort) {
        $previousUrl = $script:DashboardUrl
        $script:FrontendPort = [int]$existingFrontendPort
        Update-FrontendServiceUrls
        Write-LauncherLog "Adopted existing expected frontend runtime. previous=$previousUrl selected=$($script:DashboardUrl)"
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
    }

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

    # The formal long-running Windows launcher favors route stability over the
    # faster Turbopack startup path. Manual development can still opt into the
    # package.json default directly.
    $frontendArguments = @(
        "run",
        "dev",
        "--",
        $script:FrontendDevBundlerArgument,
        "--hostname",
        $script:FrontendHost,
        "--port",
        ([string]$script:FrontendPort)
    )
    Write-LauncherLog "Starting frontend with $($npm.Source) on $($script:DashboardUrl). bundler=$($script:FrontendDevBundlerArgument.TrimStart('-'))"
    $script:FrontendProcess = Start-LoggedService `
        -ServiceName "frontend" `
        -FilePath $npm.Source `
        -Arguments $frontendArguments `
        -WorkingDirectory $script:FrontendDir
    Write-LauncherLog "Frontend started pid=$($script:FrontendProcess.Id)."
}

function Start-Services {
    if ($script:ServiceStopInProgress -or $script:SafeStopAttempted) { throw 'SAFE_STOP_NO_START_OR_RECOVERY' }
    # A previous stopped status must not turn the next Run into another restart
    # before the status timer has observed the new processes.
    $script:LastStatusText = $null
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
        Show-Message "Backend failed to start: $($_.Exception.Message). Check logs\launcher for details."
        return
    }

    try {
        Start-Frontend
    }
    catch {
        Write-LauncherLog "Frontend start failed. error=$($_.Exception.Message)" "ERROR"
        Show-Message "Frontend failed to start. Check logs\launcher for details."
    }
}

function Invoke-BackendBindFailureRecovery {
    if ($script:SafeStopAttempted -or $script:ServiceStopInProgress -or
        $script:OwnedBackendStartAttempted -or $null -ne $script:OwnedBackendSession -or
        $script:BackendStopExpected -or
        $script:IsShuttingDown -or
        $script:BackendRecoveryInProgress) {
        return $false
    }

    if ($script:BackendPortRecoveryAttempts -ge $script:MaxBackendPortRecoveryAttempts) {
        Write-LauncherLog "Backend bind recovery exhausted. attempts=$($script:BackendPortRecoveryAttempts) max_attempts=$($script:MaxBackendPortRecoveryAttempts)" "ERROR"
        return $false
    }

    $script:BackendRecoveryInProgress = $true
    $previousBackendUrl = $script:BackendBaseUrl
    $previousFrontendUrl = $script:DashboardUrl
    try {
        $script:BackendPortRecoveryAttempts += 1
        Stop-FrontendService

        $script:BackendPort = Find-AvailableBackendPort -PreferredPort ($script:BackendPort + 1)
        Update-BackendServiceUrls
        Write-LauncherLog (
            "Backend bind recovery selected a new port. " +
            "attempt=$($script:BackendPortRecoveryAttempts)/$($script:MaxBackendPortRecoveryAttempts) " +
            "previous=$previousBackendUrl selected=$($script:BackendBaseUrl) " +
            "frontend=$previousFrontendUrl"
        ) "WARN"

        Start-Backend
        Start-Frontend
        return $true
    }
    catch {
        Write-LauncherLog "Backend bind recovery failed. previous=$previousBackendUrl error=$($_.Exception.Message)" "ERROR"
        return $false
    }
    finally {
        $script:BackendRecoveryInProgress = $false
    }
}

function Stop-BackendService {
    param($Deadline = $null)
    if ($null -eq $Deadline) { $Deadline = [Omi.OwnedShutdown.LifecycleDeadline]::new() }
    # The tray owns this local action; it grants no remote restart authority.
    # Keep the original session/handles even after unknown or completed STOP.
    if (-not $script:OwnsMutex) { throw 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED' }
    $owned = $script:OwnedBackendSession
    if ($null -eq $owned) {
        # Only a structurally never-attempted cold owner may close without a
        # Stop receipt. Null session alone says nothing about child existence.
        if ($script:OwnedBackendStartAttempted -cne $false -or $script:BackendReload -or $script:IsPackagedRelease -or
            $null -ne $script:BackendProcess -or $script:RetiredBackendSessions.Count -gt 0 -or
            $null -ne $script:ManualBackendStartAttemptedSession) { throw 'BACKEND_SAFE_STOP_OWNED_CHANNEL_REQUIRED' }
        if ($null -eq $script:Mutex -or $script:Mutex.SafeWaitHandle.IsClosed -or $script:Mutex.SafeWaitHandle.IsInvalid) {
            throw 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'
        }
        # This narrow no-op requires no Frontend history and no observed direct
        # child of this Launcher, including an untracked Runner. Observation
        # errors fail closed; no PID lookup/kill or port-owner cleanup follows.
        if ($null -ne $script:FrontendProcess -or $null -ne $script:FrontendRunnerIdentity -or
            ($null -ne $script:LastFrontendStop -and ($script:LastFrontendStop.State -cne 'stopped' -or
                $null -ne $script:LastFrontendStop.Runner -or $script:LastFrontendStop.Nodes.Count -gt 0 -or
                $script:LastFrontendStop.StartAttempted))) { throw 'BACKEND_COLD_STOP_NOT_ATTESTED' }
        Assert-FrontendSafeStopAvailable
        if (@(Get-FrontendProcessSnapshot | Where-Object { $_.ParentProcessId -eq $PID }).Count -ne 0) {
            throw 'BACKEND_COLD_STOP_NOT_ATTESTED'
        }
        if (@(Get-ListeningProcessIdsOnPort -Port $script:BackendPort -RequireObservation).Count -ne 0) { throw 'FIXED_PORT_NOT_FREE' }
        if (-not (Test-TcpPortBindable -Port $script:BackendPort -HostName $script:BackendHost -ServiceName 'Backend' -Quiet)) {
            throw 'FIXED_PORT_NOT_BINDABLE'
        }
        $script:BackendStopExpected = $true
        Write-LauncherLog 'OWNED_COLD_START_NOT_ATTEMPTED; empty owner observed; no Backend Safe Stop receipt.'
        return
    }
    if (-not [object]::ReferenceEquals($script:BackendProcess, $owned.RunnerProcess)) {
        throw 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'
    }
    if ($owned.StartupFailure) { $null = $owned.RefreshStartupExit() }
    if ($owned.StartupExitConfirmed) {
        $script:BackendStopExpected = $true
        $script:LastBackendStartError = $null
        Write-LauncherLog 'OWNED_START_EXIT_CONFIRMED; failed startup closed without a Safe Stop receipt.'
        return
    }
    $evidence = $owned.LastStop
    if ($null -eq $evidence -or (-not $evidence.ExactExit -and -not $evidence.ForcedExitConfirmed)) {
        $script:BackendStopExpected = $true
        $requestId = [Guid]::NewGuid().ToString('D')
        Write-LauncherLog "Backend safe stop requested. request_id=$requestId"
        try {
            $pending = $owned.StopWithinDeadlineAsync($requestId, $null, $Deadline)
            while (-not $pending.IsCompleted) {
                # Only UI messages run here. Lifecycle timers and entrypoints
                # are fenced until this same request has returned evidence.
                if ($Deadline.ElapsedMilliseconds -gt 185000) { throw 'CUTOFF_RECEIPT_UNAVAILABLE' }
                Start-Sleep -Milliseconds 25
            }
            $evidence = $pending.GetAwaiter().GetResult()
        }
        catch { throw 'BACKEND_SAFE_STOP_UNKNOWN' }
    }
    if (-not $script:OwnsMutex -or -not [object]::ReferenceEquals($owned, $script:OwnedBackendSession) -or
        -not [object]::ReferenceEquals($script:BackendProcess, $owned.RunnerProcess)) {
        throw 'BACKEND_SAFE_STOP_OWNER_NOT_ATTESTED'
    }
    if ($null -eq $evidence) { throw 'BACKEND_SAFE_STOP_UNKNOWN' }
    Write-LauncherLog "Backend safe stop result. request_id=$($evidence.RequestId) state=$($evidence.State) reason=$($evidence.Reason) stage=$($evidence.PreflightStage)"
    if ($evidence.ForcedExitConfirmed -and $evidence.State -eq 'forced_stopped') {
        $script:BackendStopExpected = $true
        $script:LastBackendStartError = $null
        Write-LauncherLog "BACKEND_HARD_CUTOFF request_id=$($evidence.RequestId) pid=$($evidence.BeforePid) generation=$($evidence.ProcessGeneration) cutoff=$($evidence.CutoffAt) recovery=RECONCILIATION_REQUIRED" 'WARN'
        return
    }
    if ($evidence.Rearmed -and $evidence.State -eq 'blocked') {
        $script:BackendStopExpected = $false
        throw 'BACKEND_SAFE_STOP_PREFLIGHT_REARMED'
    }
    if ($evidence.State -ne 'stopped' -or -not $evidence.ExactExit -or $evidence.Reason -ne 'LIFESPAN_AND_EXACT_EXIT') {
        if ($evidence.Reason -eq 'STOP_TIMEOUT') { throw 'BACKEND_SAFE_STOP_TIMEOUT' }
        throw 'BACKEND_SAFE_STOP_UNKNOWN'
    }
    $script:BackendStopExpected = $true
    $script:LastBackendStartError = $null
}

function Stop-LegacyBackendService {
    # Historical recovery implementation only. No normal tray call reaches it.
    if ($null -ne $script:OwnedBackendSession -or $script:OwnedBackendStartAttempted) {
        throw 'OWNED_BACKEND_REQUIRES_APPROVED_RUNTIME_OPERATION'
    }
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

function Get-FrontendProcessSnapshot {
    # Failure is unknown, never an empty process inventory.
    return @(Get-CimInstance Win32_Process -OperationTimeoutSec 3 -ErrorAction Stop |
        Select-Object ProcessId, ParentProcessId, CreationDate)
}

function Get-FrontendCreationTicks {
    param([DateTime]$Created)
    # CIM exposes microseconds, Process.StartTime exposes 100 ns FILETIME ticks.
    $ticks = $Created.ToUniversalTime().Ticks
    return ($ticks - ($ticks % 10))
}

function Assert-FrontendRunnerIdentity {
    param([Parameter(Mandatory = $true)]$Identity)
    # Only the original birth handle grants termination authority. No PID lookup.
    try {
        if (-not $script:OwnsMutex -or $null -eq $script:Mutex -or $null -eq $script:Mutex.SafeWaitHandle -or
            $script:Mutex.SafeWaitHandle.IsClosed -or $script:Mutex.SafeWaitHandle.IsInvalid -or
            -not [object]::ReferenceEquals($Identity, $script:FrontendRunnerIdentity) -or
            -not [object]::ReferenceEquals($Identity.Process, $script:FrontendProcess) -or
            $Identity.LauncherPid -ne $PID -or
            $Identity.LauncherCreated -ne [Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime() -or
            $Identity.Pid -le 0 -or $Identity.Pid -eq $PID -or $Identity.Process.Id -ne $Identity.Pid -or
            $Identity.Handle -eq [IntPtr]::Zero -or $Identity.Process.Handle -ne $Identity.Handle -or
            $Identity.Process.HasExited -or $Identity.Process.StartTime.ToUniversalTime() -ne $Identity.Created) {
            throw 'FRONTEND_STOP_UNCONFIRMED'
        }
    }
    catch { throw 'FRONTEND_STOP_UNCONFIRMED' }
}

function Assert-FrontendSafeStopAvailable {
    try {
        if ($script:FrontendStopUnconfirmed) { throw 'FRONTEND_STOP_UNCONFIRMED' }
        if ($null -eq $script:FrontendProcess) {
            if (@(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort -RequireObservation).Count -ne 0 -or
                -not (Test-TcpPortBindable -Port $script:FrontendPort -HostName $script:FrontendHost -ServiceName 'Frontend')) {
                throw 'FRONTEND_STOP_UNCONFIRMED'
            }
            return
        }
        Assert-FrontendRunnerIdentity -Identity $script:FrontendRunnerIdentity
    }
    catch { throw 'FRONTEND_STOP_UNCONFIRMED' }
}

function Assert-FrontendListenerOwnership {
    # Readiness evidence only: one snapshot, listener-to-root ancestry, no tree
    # inventory/handles or pre/post termination scans. Never supplies a kill PID.
    Assert-FrontendRunnerIdentity -Identity $script:FrontendRunnerIdentity
    try {
        $listeners = @(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort -RequireObservation)
        if ($listeners.Count -eq 0) { throw 'FRONTEND_OBSERVATION_UNAVAILABLE' }
        $rows = @(Get-FrontendProcessSnapshot)
    }
    catch { throw 'FRONTEND_OBSERVATION_UNAVAILABLE' }
    $identity = $script:FrontendRunnerIdentity
    $root = @($rows | Where-Object { $_.ProcessId -eq $identity.Pid })
    if ($root.Count -eq 0) { throw 'FRONTEND_OBSERVATION_UNAVAILABLE' }
    if ($root.Count -ne 1 -or $root[0].ParentProcessId -ne $PID -or
        (Get-FrontendCreationTicks $root[0].CreationDate) -ne (Get-FrontendCreationTicks $identity.Created)) {
        throw 'FRONTEND_OWNER_MISMATCH'
    }
    foreach ($listener in $listeners) {
        $seen = [Collections.Generic.HashSet[int]]::new()
        $currentId = [int]$listener
        $childCreated = [DateTime]::MaxValue
        while ($true) {
            if ($currentId -eq $PID) { throw 'FRONTEND_FOREIGN_LISTENER' }
            if ($seen.Count -ge 256 -or -not $seen.Add($currentId)) { throw 'FRONTEND_OWNER_MISMATCH' }
            $node = @($rows | Where-Object { $_.ProcessId -eq $currentId })
            if ($node.Count -eq 0) { throw 'FRONTEND_OBSERVATION_UNAVAILABLE' }
            if ($node.Count -ne 1 -or $null -eq $node[0].CreationDate -or
                $node[0].CreationDate -gt $childCreated) { throw 'FRONTEND_OWNER_MISMATCH' }
            if ($currentId -eq $identity.Pid) { break }
            if ($node[0].ParentProcessId -le 0 -or
                $node[0].CreationDate -lt $root[0].CreationDate) { throw 'FRONTEND_FOREIGN_LISTENER' }
            $childCreated = $node[0].CreationDate
            $currentId = [int]$node[0].ParentProcessId
        }
    }
    Assert-FrontendRunnerIdentity -Identity $identity
}

function Invoke-FrontendTreeTermination {
    param([Parameter(Mandatory = $true)]$Identity)
    Assert-FrontendRunnerIdentity -Identity $Identity
    $rows=@(Get-OmiCutoffSnapshot)
    $root=@($rows | Where-Object { $_.ProcessId -eq $Identity.Pid })
    if($root.Count -ne 1 -or $root[0].ParentProcessId -ne $PID -or
        -not (Test-OmiCutoffCreation $root[0].CreationDate $Identity.Created)){throw 'FRONTEND_OWNER_MISMATCH'}
    $captured=[pscustomobject]@{Process=$Identity.Process;Pid=$Identity.Pid;Created=$Identity.Created;
        CommandLine=$root[0].CommandLine;ExecutablePath=$root[0].ExecutablePath;Nodes=@();Repo=$script:RepoRoot;RootRole='frontend_runner'}
    $captured.Nodes=@(Get-OmiCutoffTree -Identity $captured -Rows $rows)
    try {
        $script:LastFrontendStop.Nodes=@(Stop-OmiCapturedTree -Identity $captured)
    } finally {
        foreach($node in $captured.Nodes){if(-not [object]::ReferenceEquals($node.Process,$Identity.Process)){$node.Process.Dispose()}}
    }
}

function Stop-FrontendService {
    param([switch]$RequireSafeStop)
    # The compatibility switch no longer selects a weaker legacy force path.
    if ($script:FrontendStopUnconfirmed) { throw 'FRONTEND_STOP_UNCONFIRMED' }
    $stage = 'ownership-preflight'
    try {
        if ($null -ne $script:FrontendProcess) { Assert-FrontendRunnerIdentity -Identity $script:FrontendRunnerIdentity }
        else { Assert-FrontendSafeStopAvailable }
        $identity = $script:FrontendRunnerIdentity
        $script:LastFrontendStop = [pscustomobject]@{ State='unknown'; Reason='FRONTEND_STOP_UNCONFIRMED';
            Port=$script:FrontendPort; Runner=$identity; Nodes=@(); StartAttempted=$false }
        if ($null -ne $script:FrontendProcess) {
            $script:FrontendStopUnconfirmed = $true
            $stage = 'tree-termination'
            Invoke-FrontendTreeTermination -Identity $identity
        }
        $stage = 'runner-exit-and-port-release'
        $clock = [Diagnostics.Stopwatch]::StartNew()
        do {
            $runnerExited = $null -eq $script:FrontendProcess -or $identity.Process.HasExited
            if ($runnerExited -and
                @(Get-ListeningProcessIdsOnPort -Port $script:FrontendPort -RequireObservation).Count -eq 0 -and
                (Test-TcpPortBindable -Port $script:FrontendPort -HostName $script:FrontendHost -ServiceName 'Frontend')) {
                $script:LastFrontendStop.State = 'stopped'
                $script:LastFrontendStop.Reason = 'OWNED_RUNNER_EXIT_AND_PORT_RELEASED'
                $script:FrontendProcess = $null
                $script:FrontendStopUnconfirmed = $false
                Write-LauncherLog "Frontend stopped; owned runner exit and port release verified after tree termination. port=$($script:FrontendPort)"
                return
            }
            Start-Sleep -Milliseconds 150
        } while ($clock.ElapsedMilliseconds -lt 5000)
        throw 'FRONTEND_STOP_UNCONFIRMED'
    }
    catch {
        $script:FrontendStopUnconfirmed = $true
        if ($null -eq $script:LastFrontendStop) {
            $script:LastFrontendStop = [pscustomobject]@{ State='unknown'; Reason='FRONTEND_STOP_UNCONFIRMED';
                Port=$script:FrontendPort; Runner=$script:FrontendRunnerIdentity; Nodes=@(); StartAttempted=$false }
        }
        $script:LastFrontendStop.State = 'unknown'
        $script:LastFrontendStop.Reason = 'FRONTEND_STOP_UNCONFIRMED'
        Write-LauncherLog "FRONTEND_STOP_UNCONFIRMED stage=$stage port=$($script:FrontendPort); retained frontend evidence; no port cleanup or retry." 'WARN'
        throw 'FRONTEND_STOP_UNCONFIRMED'
    }
}

function Restart-Frontend {
    if (-not $script:ServiceStartRequestInProgress) { throw 'SERVICE_OPERATION_NOT_SERIALIZED' }
    Stop-FrontendService -RequireSafeStop
    Start-Frontend -AfterConfirmedStop
    $identity = $script:FrontendRunnerIdentity
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        Assert-FrontendRunnerIdentity -Identity $identity
        try {
            if (Test-FrontendOk) {
                Assert-FrontendListenerOwnership
                Assert-FrontendRunnerIdentity -Identity $identity
                if ($clock.ElapsedMilliseconds -lt 30000) { return }
            }
        }
        catch {
            # Only unavailable observations may settle during the original budget.
            # A known mismatch is terminal; unknown never becomes success.
            if ($_.Exception.Message -cne 'FRONTEND_OBSERVATION_UNAVAILABLE') { throw }
        }
        Start-Sleep -Milliseconds 500
    } while ($clock.ElapsedMilliseconds -lt 30000)
    throw 'FRONTEND_START_READINESS_UNCONFIRMED'
}

function Clear-FrontendDevOutput {
    if ($script:IsPackagedRelease) {
        return
    }

    $frontendRoot = [System.IO.Path]::GetFullPath($script:FrontendDir).TrimEnd('\')
    $nextOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $frontendRoot ".next"))
    $devOutputPath = [System.IO.Path]::GetFullPath((Join-Path $nextOutputRoot "dev"))
    $expectedPrefix = $frontendRoot + '\'
    if ((-not $devOutputPath.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) -or
        (-not ([System.IO.Path]::GetDirectoryName($devOutputPath)).Equals($nextOutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ([System.IO.Path]::GetFileName($devOutputPath) -ne "dev")) {
        throw "Refusing to clear unexpected frontend dev output path: $devOutputPath"
    }
    if (-not (Test-Path -LiteralPath $devOutputPath)) {
        Write-LauncherLog "Frontend dev output reset skipped because the directory does not exist. path=$devOutputPath"
        return
    }

    $devOutputItem = Get-Item -LiteralPath $devOutputPath -Force
    if (-not [string]::IsNullOrWhiteSpace([string]$devOutputItem.LinkType)) {
        throw "Refusing to clear linked frontend dev output path: $devOutputPath link_type=$($devOutputItem.LinkType)"
    }

    Remove-Item -LiteralPath $devOutputPath -Recurse -Force
    Write-LauncherLog "Frontend dev output reset. path=$devOutputPath" "WARN"
}

function Invoke-FrontendHealthRecovery {
    if (-not (Test-FrontendRecoveryAdmission -HealthRecovery) -or $script:IsPackagedRelease -or
        $script:FrontendHealthRecoveryInProgress) {
        return $false
    }

    if ($script:FrontendHealthRecoveryAttempts -ge $script:MaxFrontendHealthRecoveryAttempts) {
        if (-not $script:FrontendHealthRecoveryExhaustedLogged) {
            Write-LauncherLog "Frontend health recovery exhausted. attempts=$($script:FrontendHealthRecoveryAttempts) max_attempts=$($script:MaxFrontendHealthRecoveryAttempts)" "ERROR"
            $script:FrontendHealthRecoveryExhaustedLogged = $true
        }
        return $false
    }

    $script:FrontendHealthRecoveryInProgress = $true
    $script:FrontendHealthRecoveryAttempts += 1
    try {
        Write-LauncherLog (
            "Frontend remained unhealthy while its tracked process was running. " +
            "attempt=$($script:FrontendHealthRecoveryAttempts)/$($script:MaxFrontendHealthRecoveryAttempts) " +
            "grace_seconds=$($script:FrontendHealthRecoveryGraceSeconds) url=$($script:FrontendHealthUrl)"
        ) "WARN"
        Stop-FrontendService
        Clear-FrontendDevOutput
        Start-Frontend
        $script:FrontendHealthUnhealthySinceUtc = [DateTime]::UtcNow
        $script:FrontendHealthHealthySinceUtc = $null
        $script:FrontendHealthRecoveryAdoptedLogged = $false
        return $true
    }
    catch {
        Write-LauncherLog "Frontend health recovery failed. error=$($_.Exception.Message)" "ERROR"
        return $false
    }
    finally {
        $script:FrontendHealthRecoveryInProgress = $false
    }
}

function Stop-Services {
    param([switch]$BackendOnly, $Deadline = $null)
    if ($null -eq $Deadline) { $Deadline = [Omi.OwnedShutdown.LifecycleDeadline]::new() }

    if ($script:ServiceStopInProgress) { throw 'SAFE_STOP_IN_PROGRESS' }
    if ($script:RuntimeControlInProgress -or $script:ServiceStartRequestInProgress -or $script:BackendRecoveryInProgress -or $script:FrontendHealthRecoveryInProgress) {
        throw 'SERVICE_OPERATION_IN_PROGRESS'
    }
    $script:ServiceStopInProgress = $true
    $script:SafeStopAttempted = $true
    $script:RestartReadyBackendSession = $null
    $script:LastServiceStopError = $null
    $timerEnabled = $null -ne $script:Timer -and $script:Timer.Enabled
    $activationEnabled = $null -ne $script:ActivationTimer -and $script:ActivationTimer.Enabled
    try {
        if ($null -ne $script:Timer) { $script:Timer.Stop() }
        if ($null -ne $script:ActivationTimer) { $script:ActivationTimer.Stop() }
        # Read-only preflight before any irreversible Backend command. Repeat
        # after STOP so a later Frontend start cannot become false full success.
        Stop-BackendService -Deadline $Deadline
        if ($BackendOnly) {
            if ($script:OwnedBackendSession.StartupExitConfirmed) {
                Write-LauncherLog 'Backend startup failed and exited; Launcher retains ownership until explicit exit.'
            } else {
                Write-LauncherLog 'Backend stopped; Frontend unchanged; Launcher retains ownership until explicit exit.'
            }
        }
        else {
            Stop-FrontendService -RequireSafeStop
            if ($script:OwnedBackendSession.StartupExitConfirmed) {
                Write-LauncherLog 'OWNED_START_EXIT_CONFIRMED; services have exited without Backend Safe Stop; Launcher retains ownership until explicit exit.'
            } else {
                Write-LauncherLog 'Services stopped; Launcher retains ownership until explicit exit.'
            }
        }
    }
    catch {
        $script:LastServiceStopError = $_.Exception.Message
        Write-LauncherLog "Safe stop incomplete; Launcher retained. code=$($script:LastServiceStopError)" 'WARN'
        throw
    }
    finally {
        try {
            # Coalesce clicks/Windows events queued while the UI pumped. A
            # rearmed refusal needs a later, explicit action, never auto retry.
            foreach ($event in @($script:RunEvent, $script:RestartEvent, $script:RestartBackendEvent, $script:ExitEvent)) {
                if ($null -ne $event) { [void]$event.Reset() }
            }
        }
        finally {
            $script:ServiceStopInProgress = $false
            if ($timerEnabled) { $script:Timer.Start() }
            if ($activationEnabled) { $script:ActivationTimer.Start() }
        }
    }
}

function Reset-ServiceRecoveryState {
    $script:BackendPortRecoveryAttempts = 0
    $script:FrontendHealthRecoveryAttempts = 0
    $script:FrontendHealthUnhealthySinceUtc = $null
    $script:FrontendHealthHealthySinceUtc = $null
    $script:FrontendHealthRecoveryExhaustedLogged = $false
    $script:FrontendHealthRecoveryAdoptedLogged = $false
    Write-LauncherLog "Service recovery rearmed. backend_attempts=0 frontend_attempts=0"
}

function Restart-Services {
    $deadline = [Omi.OwnedShutdown.LifecycleDeadline]::new()
    Write-LauncherLog "Restart requested."
    if ($script:RuntimeControlInProgress -or $script:ServiceStopInProgress -or $script:IsShuttingDown) { throw 'SAFE_STOP_IN_PROGRESS' }
    if ($script:OwnedBackendStartAttempted -or $null -ne $script:OwnedBackendSession) {
        if ($script:ServiceStartRequestInProgress -or $script:BackendRecoveryInProgress -or
            $script:FrontendHealthRecoveryInProgress) { throw 'SERVICE_OPERATION_IN_PROGRESS' }
        $requestId = [Guid]::NewGuid().ToString('D')
        $script:LastFullServiceRestart = [pscustomobject]@{ RequestId=$requestId; State='unknown';
            Stage='frontend-preflight'; Backend='unchanged'; Frontend='unchanged'; Reason=$null }
        $timerEnabled = $null -ne $script:Timer -and $script:Timer.Enabled
        $activationEnabled = $null -ne $script:ActivationTimer -and $script:ActivationTimer.Enabled
        try {
            if ($null -ne $script:Timer) { $script:Timer.Stop() }
            if ($null -ne $script:ActivationTimer) { $script:ActivationTimer.Stop() }
            $script:LastFullServiceRestart.Stage = 'backend-restart'
            $script:LastFullServiceRestart.Backend = 'unconfirmed'
            # Local UUID; no remote intent, changed transport or force fallback.
            Invoke-OwnedBackendRestart -RequestId $requestId -Deadline $deadline
            if ($null -eq $script:LastBackendRestart -or $script:LastBackendRestart.RequestId -cne $requestId -or
                $script:LastBackendRestart.State -cne 'succeeded') { throw 'BACKEND_RESTART_UNCONFIRMED' }
            $script:LastFullServiceRestart.Backend = 'ready'
            # Backend's function has released its entry guard; no UI pumping or
            # enabled timer occurs in the handoff to the Frontend phase.
            $script:ServiceStartRequestInProgress = $true
            $script:LastFullServiceRestart.Stage = 'frontend-restart'
            $script:LastFullServiceRestart.Frontend = 'unconfirmed'
            Restart-Frontend
            $script:LastFullServiceRestart.Frontend = 'ready'
            $script:LastFullServiceRestart.Stage = 'final-readiness'
            if (-not $script:OwnedBackendSession.VerifyReadiness() -or -not (Test-HttpOk $script:BackendReadyUrl)) {
                $script:LastFullServiceRestart.Backend = 'unconfirmed'
                throw 'BACKEND_FINAL_READINESS_UNCONFIRMED'
            }
            $script:LastFullServiceRestart.Frontend = 'unconfirmed'
            if (-not (Test-FrontendOk)) {
                throw 'FRONTEND_START_READINESS_UNCONFIRMED'
            }
            Assert-FrontendRunnerIdentity -Identity $script:FrontendRunnerIdentity
            $script:LastFullServiceRestart.Frontend = 'ready'
            $script:LastFullServiceRestart.State = 'succeeded'
            $script:LastFullServiceRestart.Stage = 'complete'
            $script:LastFullServiceRestart.Reason = 'BOTH_READY'
            Write-LauncherLog "Full service restart succeeded; both services ready. request_id=$requestId"
        }
        catch {
            $script:LastFullServiceRestart.State = if ($script:LastFullServiceRestart.Stage -in @('frontend-restart', 'final-readiness')) { 'partial' } else { 'blocked_or_unconfirmed' }
            $script:LastFullServiceRestart.Reason = $_.Exception.Message
            $result = $script:LastFullServiceRestart
            $message = "FULL_SERVICE_RESTART_INCOMPLETE request_id=$requestId state=$($result.State) stage=$($result.Stage) backend=$($result.Backend) frontend=$($result.Frontend) reason=$($result.Reason)"
            Write-LauncherLog $message 'WARN'
            throw $message
        }
        finally {
            $script:ServiceStartRequestInProgress = $true
            try {
                foreach ($event in @($script:RunEvent, $script:RestartEvent, $script:RestartBackendEvent, $script:ExitEvent)) {
                    if ($null -ne $event) { [void]$event.Reset() }
                }
            }
            finally {
                $script:ServiceStartRequestInProgress = $false
                if ($timerEnabled) { $script:Timer.Start() }
                if ($activationEnabled) { $script:ActivationTimer.Start() }
            }
        }
        return
    }
    Stop-Services
    Reset-ServiceRecoveryState
    Start-Sleep -Seconds 1
    Start-Services
}

function Test-TrackedServiceStarting {
    param($Process)

    if ($null -eq $Process) {
        return $false
    }
    try {
        $ageSeconds = ([DateTime]::UtcNow - $Process.StartTime.ToUniversalTime()).TotalSeconds
        return ($ageSeconds -ge 0 -and $ageSeconds -lt $script:ServiceStartupGraceSeconds)
    }
    catch {
        return $false
    }
}

function Invoke-ServiceStartRequest {
    param([Parameter(Mandatory = $true)][string]$Reason)

    Restore-TrayIcon -Reason $Reason
    if ($script:RuntimeControlInProgress -or $script:ServiceStopInProgress -or $script:SafeStopAttempted) {
        Write-LauncherLog 'Start refused after safe stop request; retained owner requires explicit lifecycle adoption.' 'WARN'
        if ($script:SafeStopAttempted -and -not $script:ServiceStopInProgress) {
            Show-Message 'SAFE_STOP_NO_START_OR_RECOVERY: use Start Backend only after a confirmed Safe Stop in this loaded Launcher.'
        }
        return
    }
    if ($script:IsShuttingDown) {
        return
    }
    if ($script:ServiceStartRequestInProgress -or
        $script:BackendRecoveryInProgress -or
        $script:FrontendHealthRecoveryInProgress) {
        Write-LauncherLog "Explicit service start coalesced; recovery in progress. reason=$Reason"
        return
    }

    $restartRequested = $false
    $script:ServiceStartRequestInProgress = $true
    try {
        $backendHealth = Get-BackendHealth
        $backendHealthy = ($null -ne $backendHealth -and
            (Test-BackendHealthMatchesExpected -Health $backendHealth -ExpectedPythonPath (Get-ExpectedBackendPython)) -and
            (Test-HttpOk $script:BackendReadyUrl))
        $frontendHealthy = Test-FrontendOk
        $backendRunning = Test-ProcessRunning $script:BackendProcess
        $frontendRunning = Test-ProcessRunning $script:FrontendProcess

        $stateDetails = "reason=$Reason backend_healthy=$backendHealthy frontend_healthy=$frontendHealthy backend_tracked_running=$backendRunning frontend_tracked_running=$frontendRunning last_status=$($script:LastStatusText)"
        if ($backendHealthy -and $frontendHealthy) {
            Write-LauncherLog "Explicit service start: services healthy; activated only. $stateDetails"
            return
        }

        # Spending the last attempt is not exhaustion while that attempt is
        # still inside its normal frontend health grace period.
        $frontendRecoveryExhausted = (-not $frontendHealthy) -and (
            $script:FrontendHealthRecoveryExhaustedLogged -or (
                $script:FrontendHealthRecoveryAttempts -ge $script:MaxFrontendHealthRecoveryAttempts -and
                $null -ne $script:FrontendHealthUnhealthySinceUtc -and
                ([DateTime]::UtcNow - $script:FrontendHealthUnhealthySinceUtc).TotalSeconds -ge $script:FrontendHealthRecoveryGraceSeconds
            )
        )
        $serviceStopped = $script:BackendStopExpected -or
            $script:LastStatusText -match '(API|UI) stopped' -or
            ((-not $backendHealthy) -and (-not $backendRunning)) -or
            ((-not $frontendHealthy) -and (-not $frontendRunning)) -or
            ($null -ne $script:BackendProcess -and (-not $backendRunning)) -or
            ($null -ne $script:FrontendProcess -and (-not $frontendRunning))
        $servicesStarting = (-not $serviceStopped) -and (-not $frontendRecoveryExhausted) -and
            ($backendHealthy -or ($backendRunning -and (Test-TrackedServiceStarting $script:BackendProcess))) -and
            ($frontendHealthy -or ($frontendRunning -and (Test-TrackedServiceStarting $script:FrontendProcess)))
        if ($servicesStarting) {
            Write-LauncherLog "Explicit service start: services starting; activated only. $stateDetails"
            return
        }

        Write-LauncherLog "Explicit service start: services degraded. $stateDetails frontend_recovery_exhausted=$frontendRecoveryExhausted" "WARN"
        if ((-not $backendRunning) -and (-not $frontendRunning)) {
            Write-LauncherLog "Explicit service start taking Start-Services; both tracked services stopped. reason=$Reason"
            Reset-ServiceRecoveryState
            Start-Services
        }
        else {
            Write-LauncherLog "Explicit service start taking Restart-Services; tracked services remain alive. reason=$Reason"
            # Decide under the request guard; dispatch only after its finally
            # has coalesced events and released it. Restart owns its own guard.
            $restartRequested = $true
        }
    }
    catch {
        Write-LauncherLog "Explicit service start failed. reason=$Reason error=$($_.Exception.Message)" "ERROR"
    }
    finally {
        # AutoReset collapses simultaneous requests; discard requests queued
        # during this synchronous operation, including a failed start dialog.
        try {
            if ($null -ne $script:RunEvent -and (-not $script:IsShuttingDown)) {
                [void]$script:RunEvent.Reset()
            }
        }
        finally {
            $script:ServiceStartRequestInProgress = $false
        }
    }
    if ($restartRequested) {
        # Synchronous handoff: no DoEvents, wait or callback between guard
        # release and Restart's admission. Its existing guards stay intact.
        try { Restart-Services }
        catch { Write-LauncherLog "Explicit service start failed. reason=$Reason error=$($_.Exception.Message)" 'ERROR' }
    }
}

function Exit-Launcher {
    param([Parameter(Mandatory = $true)][string]$Reason)

    if ($script:IsShuttingDown -or $script:RuntimeControlInProgress -or $script:ServiceStopInProgress -or $script:ServiceStartRequestInProgress) {
        return
    }

    $deadline = [Omi.OwnedShutdown.LifecycleDeadline]::new()
    $script:IsShuttingDown = $true
    Write-LauncherLog "Exit requested. reason=$Reason"
    try {
        Stop-Services -Deadline $deadline
        $script:LauncherExitReady = $true
        [System.Windows.Forms.Application]::Exit()
    }
    catch {
        $script:LauncherExitReady = $false
        Write-LauncherLog "LAUNCHER_EXIT_BLOCKED reason=$Reason code=$($_.Exception.Message)" 'WARN'
        Show-Message "LAUNCHER_EXIT_BLOCKED: $($_.Exception.Message). Launcher remains available; see launcher logs."
    }
    finally {
        if (-not $script:LauncherExitReady) {
            $script:IsShuttingDown = $false
            Restore-TrayIcon -Reason 'safe-stop-refused'
        }
    }
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
$startItem.add_Click({ Invoke-ServiceStartRequest -Reason "tray-start" })

$startBackendItem = New-Object System.Windows.Forms.MenuItem
$startBackendItem.Text = "Start Backend"
$startBackendItem.add_Click({
    try {
        Invoke-BackendStartRequest
        Show-Message 'Backend started. Owned READY and HTTP readiness verified; Frontend unchanged.'
    }
    catch { Show-Message $_.Exception.Message }
})

$recoverFailedBackendItem = New-Object System.Windows.Forms.MenuItem
$recoverFailedBackendItem.Text = "Recover Failed Backend Start"
$recoverFailedBackendItem.add_Click({
    try {
        Invoke-BackendStartRequest -FailedStartRecovery
        Show-Message 'Backend recovery verified. Original startup failure retained; Frontend unchanged.'
    }
    catch { Show-Message $_.Exception.Message }
})

$schemaUpgradeItem = New-Object System.Windows.Forms.MenuItem
$schemaUpgradeItem.Text = "Upgrade DB Schema"
$schemaUpgradeItem.add_Click({
    try { Show-OmiSchemaUpgrade }
    catch { Show-Message 'DB schema upgrade refused or unconfirmed. Inspect schema-maintenance receipts; no automatic retry or restore.' }
})

$restartBackendItem = New-Object System.Windows.Forms.MenuItem
$restartBackendItem.Text = "Restart Backend"
$restartBackendItem.add_Click({
    try {
        Invoke-OwnedBackendRestart -RequestId ([Guid]::NewGuid().ToString('D'))
        Show-Message 'Backend restarted. Exact exit and new owned HTTP readiness verified; Frontend unchanged.'
    }
    catch { Show-Message $_.Exception.Message }
})

$restartItem = New-Object System.Windows.Forms.MenuItem
$restartItem.Text = "Restart Backend + Frontend"
$restartItem.add_Click({ try { Restart-Services } catch { Show-Message $_.Exception.Message } })

$stopItem = New-Object System.Windows.Forms.MenuItem
$stopItem.Text = "Stop Services"
$stopItem.add_Click({ try { Stop-Services } catch { Show-Message $_.Exception.Message } })

$safeStopBackendItem = New-Object System.Windows.Forms.MenuItem
$safeStopBackendItem.Text = "Safe Stop Backend"
$safeStopBackendItem.add_Click({
    try {
        Stop-Services -BackendOnly
        if ($script:OwnedBackendSession.StartupExitConfirmed) {
            Show-Message 'OWNED_START_EXIT_CONFIRMED: Backend startup failed and both owned processes exited; no Safe Stop was executed.'
        } else {
            Show-Message 'Backend stopped. Any running Frontend/UI services remain running; Launcher remains available.'
        }
    }
    catch { Show-Message $_.Exception.Message }
})

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
    Exit-Launcher -Reason "tray-menu"
})

[void]$script:Menu.MenuItems.Add($script:TitleItem)
[void]$script:Menu.MenuItems.Add($script:StatusItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($openDashboardItem)
[void]$script:Menu.MenuItems.Add($openApiItem)
[void]$script:Menu.MenuItems.Add($openLogsItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($startItem)
[void]$script:Menu.MenuItems.Add($startBackendItem)
[void]$script:Menu.MenuItems.Add($recoverFailedBackendItem)
[void]$script:Menu.MenuItems.Add($schemaUpgradeItem)
[void]$script:Menu.MenuItems.Add($restartItem)
[void]$script:Menu.MenuItems.Add($restartBackendItem)
[void]$script:Menu.MenuItems.Add($safeStopBackendItem)
[void]$script:Menu.MenuItems.Add($stopItem)
[void]$script:Menu.MenuItems.Add((New-Object System.Windows.Forms.MenuItem "-"))
[void]$script:Menu.MenuItems.Add($exitItem)

$script:NotifyIcon.ContextMenu = $script:Menu
$script:NotifyIcon.add_DoubleClick({ Open-Url $script:DashboardUrl })

$script:Timer = New-Object System.Windows.Forms.Timer
$script:Timer.Interval = 5000
$script:Timer.add_Tick({
    if ($script:IsShuttingDown -or $script:ServiceStartRequestInProgress -or $script:ServiceStopInProgress) {
        return
    }
    $backendRunnerExitCode = Get-ExitedProcessCode $script:BackendProcess
    if ($backendRunnerExitCode -eq $script:BackendBindFailureExitCode -and
        (-not $script:SafeStopAttempted) -and (-not $script:OwnedBackendStartAttempted) -and
        (-not $script:BackendStopExpected)) {
        $script:BackendProcess = $null
        if (Invoke-BackendBindFailureRecovery) {
            return
        }
    }

    $backendHttp = Test-HttpOk $script:BackendReadyUrl
    if ($null -ne $script:OwnedBackendSession) {
        $backendHttp = $backendHttp -and -not $script:LastBackendStartError -and
            -not $script:OwnedBackendSession.StartupFailure -and -not $script:OwnedBackendSession.Terminal -and
            $null -ne (Get-OmiOwnedBackendIdentity)
    }
    $frontendHttp = Test-FrontendOk
    $backendProc = Test-ProcessRunning $script:BackendProcess
    $frontendProc = Test-ProcessRunning $script:FrontendProcess

    if ($frontendHttp) {
        $script:FrontendHealthUnhealthySinceUtc = $null
        if ($null -eq $script:FrontendHealthHealthySinceUtc) {
            $script:FrontendHealthHealthySinceUtc = [DateTime]::UtcNow
        }
        if ($script:FrontendHealthRecoveryAttempts -gt 0 -and
            (-not $script:FrontendHealthRecoveryAdoptedLogged)) {
            Write-LauncherLog "Frontend health recovery adopted. attempts=$($script:FrontendHealthRecoveryAttempts) selected=$($script:DashboardUrl)"
            $script:FrontendHealthRecoveryAdoptedLogged = $true
        }
        $healthySeconds = ([DateTime]::UtcNow - $script:FrontendHealthHealthySinceUtc).TotalSeconds
        if ($script:FrontendHealthRecoveryAttempts -gt 0 -and
            $healthySeconds -ge $script:FrontendHealthStableResetSeconds) {
            Write-LauncherLog "Frontend remained healthy past the stable reset threshold; clearing prior recovery count. healthy_seconds=$([int]$healthySeconds) threshold_seconds=$($script:FrontendHealthStableResetSeconds)"
            $script:FrontendHealthRecoveryAttempts = 0
            $script:FrontendHealthRecoveryExhaustedLogged = $false
            $script:FrontendHealthRecoveryAdoptedLogged = $false
        }
    }
    elseif ($frontendProc -and (-not $script:IsPackagedRelease)) {
        $script:FrontendHealthHealthySinceUtc = $null
        $script:FrontendHealthRecoveryAdoptedLogged = $false
        if ($null -eq $script:FrontendHealthUnhealthySinceUtc) {
            $script:FrontendHealthUnhealthySinceUtc = [DateTime]::UtcNow
        }
        $unhealthySeconds = ([DateTime]::UtcNow - $script:FrontendHealthUnhealthySinceUtc).TotalSeconds
        if ($unhealthySeconds -ge $script:FrontendHealthRecoveryGraceSeconds) {
            if (Invoke-FrontendHealthRecovery) {
                return
            }
        }
    }
    else {
        $script:FrontendHealthUnhealthySinceUtc = $null
        $script:FrontendHealthHealthySinceUtc = $null
        $script:FrontendHealthRecoveryAdoptedLogged = $false
    }

    $backendState = if ($backendHttp) { "API OK" } elseif ($backendProc) { "API starting" } else { "API stopped" }
    if ($script:LastBackendStartError) { $backendState = "API start unconfirmed" }
    $frontendState = if ($frontendHttp) { "UI OK" } elseif ($frontendProc) { "UI starting" } else { "UI stopped" }
    $statusText = "$backendState; $frontendState"
    if ($script:LastServiceStopError) { $statusText = "Safe stop: $($script:LastServiceStopError)" }

    if ($backendHttp -and $script:BackendPortRecoveryAttempts -gt 0) {
        Write-LauncherLog "Backend bind recovery adopted. selected=$($script:BackendBaseUrl) attempts=$($script:BackendPortRecoveryAttempts)"
        $script:BackendPortRecoveryAttempts = 0
    }

    $script:StatusItem.Text = "Status: $statusText"
    $script:NotifyIcon.Text = ("$($script:AppDisplayName): $statusText").Substring(0, [Math]::Min(63, "$($script:AppDisplayName): $statusText".Length))

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
    if ($script:RuntimeControlInProgress -or $script:ServiceStartRequestInProgress -or $script:ServiceStopInProgress -or $script:IsShuttingDown) { return }
    if (-not $script:RuntimeControlInProgress) {
        $script:RuntimeControlInProgress = $true
        try { Invoke-OmiRuntimeControlTick }
        finally { $script:RuntimeControlInProgress = $false }
    }
    if ($null -ne $script:ExitEvent -and $script:ExitEvent.WaitOne(0)) {
        Exit-Launcher -Reason "command-event"
        return
    }
    if ($null -ne $script:RestartEvent -and $script:RestartEvent.WaitOne(0)) {
        try { Restart-Services } catch { Show-Message $_.Exception.Message }
        return
    }
    if ($null -ne $script:RestartBackendEvent -and $script:RestartBackendEvent.WaitOne(0)) {
        try { Invoke-OwnedBackendRestart -RequestId ([Guid]::NewGuid().ToString('D')) }
        catch { Write-LauncherLog "Backend restart request failed. error=$($_.Exception.Message)" 'WARN' }
        return
    }
    if ($null -ne $script:RunEvent -and $script:RunEvent.WaitOne(0)) {
        Write-LauncherLog "Secondary Run received by existing tray owner."
        Invoke-ServiceStartRequest -Reason "secondary-run"
        return
    }
    if ($null -ne $script:ActivationEvent -and $script:ActivationEvent.WaitOne(0)) {
        Restore-TrayIcon -Reason "secondary-launch"
    }
})

[System.Windows.Forms.Application]::add_ApplicationExit({
    # Cleanup is permitted only after the explicit exit path proved both stops.
    if (-not $script:LauncherExitReady) {
        Write-LauncherLog 'LAUNCHER_EXIT_UNCONFIRMED: retaining lifecycle resources.' 'ERROR'
        return
    }
    if ($null -ne $script:RuntimeController) { $script:RuntimeController.Dispose() }

    $script:Timer.Stop()
    $script:ActivationTimer.Stop()
    if ($null -ne $script:TaskbarListener) {
        $script:TaskbarListener.Dispose()
    }
    $script:NotifyIcon.Dispose()
    if ($null -ne $script:TrayIcon) {
        $script:TrayIcon.Dispose()
    }
    if ($null -ne $script:RunEvent) {
        $script:RunEvent.Dispose()
    }
    if ($null -ne $script:ActivationEvent) {
        $script:ActivationEvent.Dispose()
    }
    if ($null -ne $script:ExitEvent) {
        $script:ExitEvent.Dispose()
    }
    if ($null -ne $script:RestartEvent) {
        $script:RestartEvent.Dispose()
    }
    if ($null -ne $script:RestartBackendEvent) { $script:RestartBackendEvent.Dispose() }
    if ($script:OwnsMutex) {
        $script:Mutex.ReleaseMutex()
    }
    $script:Mutex.Dispose()
    if ($null -ne $script:OwnedBackendSession -and $null -ne $script:OwnedBackendSession.LastStop -and $script:OwnedBackendSession.LastStop.Forced) {
        Write-LauncherLog 'Launcher stopped after HARD_CUTOFF; recovery=RECONCILIATION_REQUIRED.' 'WARN'
    } else { Write-LauncherLog "Launcher stopped." }
})

. (Join-Path $PSScriptRoot 'omi-runtime-control.ps1')
. (Join-Path $PSScriptRoot 'apply-omi-update.ps1')
Initialize-OmiRuntimeControl
Start-Services
$script:Timer.Start()
$script:ActivationTimer.Start()
Write-LauncherLog "Tray recovery initialized. run_event=$($script:RunEventName) activation_event=$($script:ActivationEventName) exit_event=$($script:ExitEventName) restart_event=$($script:RestartEventName) taskbar_message=$($script:TaskbarListener.TaskbarCreatedMessage)"
$script:NotifyIcon.ShowBalloonTip(3000, $script:AppDisplayName, "$($script:AppDisplayName) tray controls are available. Check Status for API/UI health.", [System.Windows.Forms.ToolTipIcon]::Info)

[System.Windows.Forms.Application]::Run()
