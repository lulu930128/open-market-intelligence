[CmdletBinding()]
param(
    [ValidateSet("SourceOnly", "Check", "Prepare", "RestartServices")]
    [string]$RuntimeAction = "Check",
    [ValidateSet("off", "shadow", "compare")]
    [string]$ExpectedMode = "compare",
    [string]$ExpectedDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$ExpectedCheckpointSha256 = "8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2",
    [string]$ExpectedExtensionCheckpointSha256 = "2ec7456200c310a778621df31747974cc468839c560d025680d870bc7d478619",
    [string]$ExpectedConvergenceCheckpointSha256 = "460903c9692e09e3e81315b12a6c39fac3f36fcfa3eb5c4176516b4190e453ba",
    [string]$ExpectedSharedCoreCheckpointSha256 = "5eec32a6e49a5e3e7d58c3b63d4a02dfdbda12d653430229d1339314188edf8d",
    [string]$ExpectedFreezeCheckpointSha256 = "fd68817a88287d8001f3c1e3a1ca5358adebc642327e1abd0f35dc345acf5a27",
    [string]$ExpectedLiveRemediationCheckpointSha256 = "3de4da962ae589dbef85a8fa5aaa7f177b89ddcfcb39da7caca803c8ab5c4a8c",
    [string]$ExpectedReleaseCheckpointSha256 = "69f37f4fb71306ec783e75355514110562067df21c1ced6769ff62d821196bc4",
    [string]$Symbol = "2330",
    [switch]$RunViewerReadiness,
    [ValidateRange(15, 180)][int]$StartupTimeoutSeconds = 90,
    [ValidateRange(5, 120)][int]$FrontendStartupTimeoutSeconds = 30,
    [ValidateRange(30, 240)][int]$ViewerCleanupTimeoutSeconds = 150,
    [string]$ArtifactPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$script:LauncherPath = Join-Path $script:RepoRoot "scripts\omi-launcher.ps1"
$script:McpSmokePath = Join-Path $script:RepoRoot "scripts\smoke-omi-mcp-stdio.py"
$script:TaskRoot = Join-Path $script:RepoRoot "docs\agent-runs\market-data-foundation-closure-runtime-acceptance-v1-20260819"
$script:CheckpointPath = Join-Path $script:TaskRoot "artifacts\source-checkpoint.json"
$script:ExtensionTaskRoot = Join-Path $script:RepoRoot "docs\agent-runs\tw-realtime-market-state-remediation-20260824"
$script:ExtensionCheckpointPath = Join-Path $script:ExtensionTaskRoot "artifacts\acceptance-extension-checkpoint.json"
$script:ConvergenceCheckpointPath = Join-Path $script:RepoRoot "docs\agent-runs\tw-market-data-platform-convergence-20260825\artifacts\foundation-extension-checkpoint.json"
$script:SharedCoreCheckpointPath = Join-Path $script:RepoRoot "docs\agent-runs\tw-shared-data-core-convergence-20260826\artifacts\precommit-remediation-source-checkpoint.json"
$script:FreezeCheckpointPath = Join-Path $script:RepoRoot "docs\agent-runs\tw-architecture-freeze-gate-20260826\artifacts\freeze-source-checkpoint.json"
$script:LiveRemediationCheckpointPath = Join-Path $script:ExtensionTaskRoot "artifacts\live-remediation-source-checkpoint-20260827.json"
$script:ReleaseCheckpointPath = Join-Path $script:ExtensionTaskRoot "artifacts\tw-4.3.0-source-checkpoint-20260827.json"
$script:ArtifactsRoot = Join-Path $script:TaskRoot "artifacts"
$script:LauncherMutexName = "OpenMarketIntelligenceLauncher"
$script:ExpectedProjectRoot = $script:RepoRoot.TrimEnd('\')
$script:ExpectedPython = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"

function Throw-GateFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Message
    )

    throw "[$Code] $Message"
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $sourceBytes = [System.IO.File]::ReadAllBytes($Path)
    $canonicalBytes = New-Object System.Collections.Generic.List[byte]
    for ($index = 0; $index -lt $sourceBytes.Length; $index++) {
        if (
            $sourceBytes[$index] -eq 13 -and
            ($index + 1) -lt $sourceBytes.Length -and
            $sourceBytes[$index + 1] -eq 10
        ) {
            $canonicalBytes.Add(10)
            $index++
            continue
        }
        $canonicalBytes.Add($sourceBytes[$index])
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha256.ComputeHash($canonicalBytes.ToArray()) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $sha256.Dispose()
    }
}

function Write-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if (Test-Path -LiteralPath $Path) {
        Throw-GateFailure -Code "ARTIFACT_ALREADY_EXISTS" -Message "Artifact already exists: $Path"
    }
    $tempPath = "$Path.tmp.$PID"
    try {
        $json = $Payload | ConvertTo-Json -Depth 16
        [System.IO.File]::WriteAllText(
            $tempPath,
            $json + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
        [System.IO.File]::Move($tempPath, $Path)
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}

function Invoke-JsonRequest {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        $Body = $null,
        [int]$TimeoutSeconds = 15
    )

    $parameters = @{
        Uri = $Url
        Method = $Method
        TimeoutSec = $TimeoutSeconds
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $parameters["Body"] = ($Body | ConvertTo-Json -Depth 8 -Compress)
        $parameters["ContentType"] = "application/json"
    }
    if ($Method -eq "DELETE") {
        Invoke-WebRequest @parameters | Out-Null
        return $null
    }
    return Invoke-RestMethod @parameters
}

function Get-LatestLauncherEndpoints {
    $log = Get-ChildItem -LiteralPath (Join-Path $script:RepoRoot "logs\launcher") -Recurse -Filter "launcher.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $log) {
        return $null
    }
    $lines = @(Get-Content -LiteralPath $log.FullName -Encoding UTF8)
    $startIndex = -1
    for ($index = $lines.Count - 1; $index -ge 0; $index--) {
        if ($lines[$index] -match "Launcher started\. repo_root=(.+)$") {
            $startIndex = $index
            break
        }
    }
    if ($startIndex -lt 0) {
        # A launcher that remains alive across midnight writes a component-owned
        # RestartServices event into the new day's log without repeating the
        # original "Launcher started" line.  Accept that rollover only when the
        # current log contains a fresh service-environment marker; later runtime
        # lineage checks still prove the owning launcher process.
        if (@($lines | Where-Object { $_ -match "Service environment initialized\. backend=" }).Count -eq 0) {
            return $null
        }
        $startIndex = 0
    }

    $backendUrl = $null
    $frontendUrl = $null
    for ($index = $startIndex; $index -lt $lines.Count; $index++) {
        $line = $lines[$index]
        if ($line -match "Service environment initialized\. backend=(https?://\S+) frontend=(https?://\S+)") {
            $backendUrl = $Matches[1].TrimEnd('.')
            $frontendUrl = $Matches[2].TrimEnd('.')
        }
        if ($line -match "Backend .+ selected=(https?://\S+)") {
            $backendUrl = $Matches[1].TrimEnd('.')
        }
        if ($line -match "Frontend .+ selected=(https?://\S+)") {
            $frontendUrl = $Matches[1].TrimEnd('.')
        }
    }
    if ([string]::IsNullOrWhiteSpace($backendUrl) -or [string]::IsNullOrWhiteSpace($frontendUrl)) {
        return $null
    }
    return [ordered]@{
        backend_url = $backendUrl
        frontend_url = $frontendUrl
        launcher_log = $log.FullName.Substring($script:RepoRoot.Length + 1)
    }
}

function Get-BackendHealthOrNull {
    param([Parameter(Mandatory = $true)][string]$BackendUrl)

    try {
        return Invoke-JsonRequest -Method GET -Url "$BackendUrl/api/system/health" -TimeoutSeconds 3
    }
    catch {
        return $null
    }
}

function Wait-ExpectedFrontend {
    param(
        [Parameter(Mandatory = $true)][string]$FrontendUrl,
        [Parameter(Mandatory = $true)][string]$BackendUrl,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $attempts = 0
    $lastHealth = $null
    $lastError = $null
    do {
        $attempts += 1
        try {
            $lastHealth = Invoke-JsonRequest -Method GET -Url "$FrontendUrl/omi-ui-health" -TimeoutSeconds 3
            $lastError = $null
            $matchesExpectedRuntime = [string]$lastHealth.status -eq "ok" -and
                [string]$lastHealth.runtime.frontend_dir -eq (Join-Path $script:RepoRoot "frontend") -and
                [string]$lastHealth.runtime.api_proxy_target -eq $BackendUrl
            if ($matchesExpectedRuntime) {
                $stopwatch.Stop()
                return [ordered]@{
                    status = [string]$lastHealth.status
                    frontend_dir = [string]$lastHealth.runtime.frontend_dir
                    api_proxy_target = [string]$lastHealth.runtime.api_proxy_target
                    attempts = $attempts
                    wait_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
                    last_error = $null
                    result = "passed"
                }
            }
            $lastError = "frontend_runtime_mismatch"
        }
        catch {
            $lastHealth = $null
            $lastError = $_.Exception.Message
        }
        if ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    $stopwatch.Stop()
    return [ordered]@{
        status = if ($null -ne $lastHealth) { [string]$lastHealth.status } else { $null }
        frontend_dir = if ($null -ne $lastHealth) { [string]$lastHealth.runtime.frontend_dir } else { $null }
        api_proxy_target = if ($null -ne $lastHealth) { [string]$lastHealth.runtime.api_proxy_target } else { $null }
        attempts = $attempts
        wait_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        last_error = $lastError
        result = "failed"
    }
}

function Test-LauncherMutexAvailable {
    $mutex = New-Object System.Threading.Mutex($false, $script:LauncherMutexName)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne(0, $false)
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        return $acquired
    }
    finally {
        if ($acquired) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

function Wait-LauncherMutexAvailable {
    param([int]$TimeoutSeconds = 30)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-LauncherMutexAvailable) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    Throw-GateFailure -Code "LAUNCHER_EXIT_TIMEOUT" -Message "The official launcher mutex was not released within $TimeoutSeconds seconds."
}

function Invoke-LauncherControl {
    param([Parameter(Mandatory = $true)][ValidateSet("Exit", "RestartServices")][string]$Action)

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File $script:LauncherPath -LauncherAction $Action
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Throw-GateFailure -Code "OWNER_CONTROL_UNAVAILABLE" -Message "The official launcher did not accept action '$Action' (exit code $exitCode)."
    }
}

function Start-OfficialLauncher {
    param([Parameter(Mandatory = $true)][string]$Mode)

    $powerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powerShellPath
    $startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$($script:LauncherPath)`" -LauncherAction Run"
    $startInfo.WorkingDirectory = $script:RepoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $null = $startInfo.EnvironmentVariables.Count
    $startInfo.EnvironmentVariables["CANONICAL_MARKET_DATA_MODE"] = $Mode
    $process = [System.Diagnostics.Process]::Start($startInfo)
    if ($null -eq $process) {
        Throw-GateFailure -Code "LAUNCHER_START_FAILED" -Message "The official launcher process could not be started."
    }
    return $process.Id
}

function Wait-ExpectedRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [int]$PreviousListenerPid = 0
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastMode = $null
    do {
        $endpoints = Get-LatestLauncherEndpoints
        if ($null -ne $endpoints) {
            $health = Get-BackendHealthOrNull -BackendUrl $endpoints.backend_url
            if ($null -ne $health) {
                $lastMode = [string]$health.runtime.canonical_market_data_mode
                $listenerPid = Get-ListenerPid -Url $endpoints.backend_url
                if ($lastMode -eq $Mode -and
                    ($PreviousListenerPid -le 0 -or $listenerPid -ne $PreviousListenerPid)) {
                    $ready = Invoke-JsonRequest -Method GET -Url "$($endpoints.backend_url)/api/system/readyz" -TimeoutSeconds 5
                    if ([string]$ready.status -eq "ready") {
                        return [ordered]@{
                            endpoints = $endpoints
                            health = $health
                            ready = $ready
                            listener_pid = $listenerPid
                        }
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    Throw-GateFailure -Code "COMPARE_BOOTSTRAP_FAILED" -Message "Runtime did not reach mode=$Mode and ready within $TimeoutSeconds seconds; last observed mode=$lastMode."
}

function Get-ListenerPid {
    param([Parameter(Mandatory = $true)][string]$Url)

    $uri = [Uri]$Url
    $port = $uri.Port
    $escapedHost = [Regex]::Escape($uri.Host)
    $lines = & netstat.exe -ano -p tcp
    foreach ($line in $lines) {
        if ($line -match "^\s*TCP\s+$escapedHost`:$port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return 0
}

function Get-ProcessLineage {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $items = @()
    $seen = @{}
    $currentId = $ProcessId
    for ($depth = 0; $depth -lt 12 -and $currentId -gt 0; $depth++) {
        if ($seen.ContainsKey([string]$currentId)) {
            break
        }
        $seen[[string]$currentId] = $true
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $currentId) -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            break
        }
        $created = if ($null -ne $process.CreationDate) { $process.CreationDate.ToString("o") } else { $null }
        $items += [ordered]@{
            depth = $depth
            pid = [int]$process.ProcessId
            parent_pid = [int]$process.ParentProcessId
            created_at = $created
            executable = [string]$process.ExecutablePath
            command_line = [string]$process.CommandLine
        }
        $currentId = [int]$process.ParentProcessId
    }
    return @($items)
}

function Get-KgiBridgeProcesses {
    $processes = Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { [string]$_.CommandLine -match "kgi_superpy_bridge\.py" }
    return @($processes | ForEach-Object {
        [ordered]@{
            pid = [int]$_.ProcessId
            parent_pid = [int]$_.ParentProcessId
            created_at = if ($null -ne $_.CreationDate) { $_.CreationDate.ToString("o") } else { $null }
        }
    })
}

function Get-StreamSummary {
    param(
        [Parameter(Mandatory = $true)][string]$BackendUrl,
        [Parameter(Mandatory = $true)][string]$StockId
    )

    $stream = Invoke-JsonRequest -Method GET -Url "$BackendUrl/api/market/realtime-quotes/$StockId" -TimeoutSeconds 10
    return [ordered]@{
        provider = [string]$stream.provider
        stock_id = [string]$stream.stock_id
        status = [string]$stream.status
        active_leases = [int]$stream.active_leases
        sequence = [int]$stream.sequence
        event_time = $stream.event_time
        received_at = $stream.received_at
        is_stale = [bool]$stream.is_stale
        capability_status = $stream.capability_status
        warning_count = @($stream.warnings).Count
    }
}

function Get-LeaseSummary {
    param([Parameter(Mandatory = $true)][string]$BackendUrl)

    $summary = Invoke-JsonRequest -Method GET -Url "$BackendUrl/api/market/realtime-quote-leases/summary" -TimeoutSeconds 10
    return [ordered]@{
        provider = [string]$summary.provider
        total_active_leases = [int]$summary.total_active_leases
        active_symbol_count = [int]$summary.active_symbol_count
        leases_by_owner_kind = $summary.leases_by_owner_kind
        leases_by_symbol = $summary.leases_by_symbol
        bridge_process_running = [bool]$summary.bridge_process_running
        idle_shutdown_pending = [bool]$summary.idle_shutdown_pending
        subscription_worker_count = [int]$summary.subscription_worker_count
    }
}

function Get-CleanViewerBaseline {
    param(
        [Parameter(Mandatory = $true)][string]$BackendUrl,
        [Parameter(Mandatory = $true)][string]$StockId,
        [Parameter(Mandatory = $true)][int]$CleanupTimeoutSeconds
    )

    $state = [ordered]@{
        result = "running"
        before = $null
        after_wait = $null
        waited_seconds = 0
        failure_code = $null
        failure_reason = $null
    }
    try {
        $stream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
        $leaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
        $processes = @(Get-KgiBridgeProcesses)
        $state.before = [ordered]@{
            stream = $stream
            lease_summary = $leaseSummary
            bridge_processes = $processes
        }

        if ($leaseSummary.total_active_leases -gt 0 -or $stream.active_leases -gt 0) {
            $state.failure_code = "EXTERNAL_VIEWER_LEASE_PRESENT"
            $state.failure_reason = "Viewer baseline contains active lease(s); preflight will not inspect or release them."
        }
        elseif ($leaseSummary.bridge_process_running -or $processes.Count -gt 0) {
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            $deadline = (Get-Date).AddSeconds($CleanupTimeoutSeconds)
            do {
                Start-Sleep -Seconds 2
                $stream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
                $leaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
                $processes = @(Get-KgiBridgeProcesses)
                if ($leaseSummary.total_active_leases -gt 0 -or $stream.active_leases -gt 0) {
                    $state.failure_code = "EXTERNAL_VIEWER_LEASE_PRESENT"
                    $state.failure_reason = "A viewer lease appeared while waiting for natural bridge idle cleanup."
                    break
                }
                if (-not $leaseSummary.bridge_process_running -and $processes.Count -eq 0) {
                    break
                }
            } while ((Get-Date) -lt $deadline)
            $stopwatch.Stop()
            $state.waited_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            if ($null -eq $state.failure_code -and
                ($leaseSummary.bridge_process_running -or $processes.Count -gt 0)) {
                $state.failure_code = "BRIDGE_IDLE_CLEANUP_TIMEOUT"
                $state.failure_reason = "No viewer lease remained, but the KGI bridge did not exit naturally within $CleanupTimeoutSeconds seconds."
            }
        }

        $state.after_wait = [ordered]@{
            stream = $stream
            lease_summary = $leaseSummary
            bridge_processes = $processes
        }
    }
    catch {
        if ($null -eq $state.failure_code) {
            $state.failure_code = "VIEWER_BASELINE_PROBE_FAILED"
            $state.failure_reason = $_.Exception.Message
        }
    }
    $state.result = if ($null -eq $state.failure_code) { "passed" } else { "failed" }
    return $state
}

function Invoke-ViewerReadiness {
    param(
        [Parameter(Mandatory = $true)][string]$BackendUrl,
        [Parameter(Mandatory = $true)][string]$StockId,
        [Parameter(Mandatory = $true)][int]$CleanupTimeoutSeconds
    )

    $state = [ordered]@{
        result = "running"
        provider = "kgi_superpy"
        symbol = $StockId
        before = $null
        active = $null
        after_release = $null
        after_idle_cleanup = $null
        lease_acquired = $false
        release_attempted = $false
        release_succeeded = $false
        failure_code = $null
        failure_reason = $null
    }
    $leaseId = $null
    try {
        $beforeStream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
        $beforeLeaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
        $beforeProcesses = @(Get-KgiBridgeProcesses)
        $state.before = [ordered]@{
            stream = $beforeStream
            lease_summary = $beforeLeaseSummary
            bridge_processes = $beforeProcesses
        }
        if ($beforeStream.active_leases -ne 0 -or $beforeLeaseSummary.total_active_leases -ne 0) {
            Throw-GateFailure -Code "EXTERNAL_VIEWER_LEASE_PRESENT" -Message "Viewer readiness baseline contains an external lease."
        }
        if ($beforeLeaseSummary.bridge_process_running -or $beforeProcesses.Count -ne 0) {
            Throw-GateFailure -Code "BRIDGE_IDLE_CLEANUP_TIMEOUT" -Message "Viewer readiness baseline still contains a KGI bridge process."
        }

        $lease = Invoke-JsonRequest -Method POST -Url "$BackendUrl/api/market/realtime-quote-leases" -Body @{
            stock_id = $StockId
            owner_kind = "acceptance_probe"
        } -TimeoutSeconds 20
        $leaseId = [string]$lease.lease_id
        if ([string]::IsNullOrWhiteSpace($leaseId)) {
            Throw-GateFailure -Code "VIEWER_LEASE_ACQUIRE_FAILED" -Message "Viewer lease response did not contain a lease id."
        }
        if ([string]$lease.owner_kind -ne "acceptance_probe") {
            Throw-GateFailure -Code "VIEWER_LEASE_OWNER_MISMATCH" -Message "Viewer lease response did not preserve acceptance_probe ownership."
        }
        $state.lease_acquired = $true

        $activeDeadline = (Get-Date).AddSeconds(35)
        do {
            $activeStream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
            $activeLeaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
            $activeProcesses = @(Get-KgiBridgeProcesses)
            $state.active = [ordered]@{
                stream = $activeStream
                lease_summary = $activeLeaseSummary
                bridge_processes = $activeProcesses
            }
            if ($activeStream.status -in @("subscribing", "live", "stale") -and
                $activeStream.active_leases -eq 1 -and
                $activeLeaseSummary.total_active_leases -eq 1 -and
                [int]$activeLeaseSummary.leases_by_owner_kind.acceptance_probe -eq 1 -and
                $activeProcesses.Count -gt 0) {
                break
            }
            if ($activeStream.status -in @("disabled", "unavailable", "reconnect_failed")) {
                Throw-GateFailure -Code "KGI_QUOTE_RUNTIME_UNAVAILABLE" -Message "KGI viewer lifecycle reached status=$($activeStream.status)."
            }
            Start-Sleep -Seconds 2
        } while ((Get-Date) -lt $activeDeadline)

        if ($null -eq $state.active -or
            $state.active.stream.status -notin @("subscribing", "live", "stale") -or
            $state.active.stream.active_leases -ne 1 -or
            $state.active.lease_summary.total_active_leases -ne 1 -or
            [int]$state.active.lease_summary.leases_by_owner_kind.acceptance_probe -ne 1 -or
            @($state.active.bridge_processes).Count -eq 0) {
            Throw-GateFailure -Code "KGI_VIEWER_READINESS_TIMEOUT" -Message "KGI quote runtime did not reach a bounded subscribing/live/stale state."
        }
    }
    catch {
        $message = $_.Exception.Message
        $code = if ($message -match "^\[([^\]]+)\]") { $Matches[1] } else { "KGI_VIEWER_READINESS_FAILED" }
        $state.failure_code = $code
        $state.failure_reason = $message
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($leaseId)) {
            $state.release_attempted = $true
            try {
                Invoke-JsonRequest -Method DELETE -Url "$BackendUrl/api/market/realtime-quote-leases/$leaseId" -TimeoutSeconds 15 | Out-Null
                $state.release_succeeded = $true
            }
            catch {
                $state.release_succeeded = $false
                if ($null -eq $state.failure_code) {
                    $state.failure_code = "VIEWER_LEASE_RELEASE_FAILED"
                    $state.failure_reason = $_.Exception.Message
                }
            }
        }

        try {
            $releaseDeadline = (Get-Date).AddSeconds(20)
            do {
                $afterReleaseStream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
                $afterReleaseLeaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
                if ($afterReleaseStream.active_leases -eq 0 -and $afterReleaseLeaseSummary.total_active_leases -eq 0) {
                    break
                }
                Start-Sleep -Seconds 1
            } while ((Get-Date) -lt $releaseDeadline)
            $state.after_release = [ordered]@{
                stream = $afterReleaseStream
                lease_summary = $afterReleaseLeaseSummary
                bridge_processes = @(Get-KgiBridgeProcesses)
            }
            if (($afterReleaseStream.active_leases -ne 0 -or $afterReleaseLeaseSummary.total_active_leases -ne 0) -and $null -eq $state.failure_code) {
                $state.failure_code = "OWNED_VIEWER_LEASE_LEAK"
                $state.failure_reason = "The acceptance-owned viewer lease did not return the global baseline to zero."
            }

            $cleanupDeadline = (Get-Date).AddSeconds($CleanupTimeoutSeconds)
            do {
                $afterProcesses = @(Get-KgiBridgeProcesses)
                if ($afterProcesses.Count -eq 0) {
                    break
                }
                Start-Sleep -Seconds 5
            } while ((Get-Date) -lt $cleanupDeadline)
            $afterIdleStream = Get-StreamSummary -BackendUrl $BackendUrl -StockId $StockId
            $afterIdleLeaseSummary = Get-LeaseSummary -BackendUrl $BackendUrl
            $state.after_idle_cleanup = [ordered]@{
                stream = $afterIdleStream
                lease_summary = $afterIdleLeaseSummary
                bridge_processes = $afterProcesses
            }
            if (($afterIdleStream.active_leases -ne 0 -or
                $afterIdleLeaseSummary.total_active_leases -ne 0 -or
                $afterIdleLeaseSummary.bridge_process_running -or
                $afterProcesses.Count -ne 0) -and $null -eq $state.failure_code) {
                $state.failure_code = "BRIDGE_IDLE_CLEANUP_TIMEOUT"
                $state.failure_reason = "Viewer lease or KGI bridge process did not return to baseline within $CleanupTimeoutSeconds seconds."
            }
        }
        catch {
            if ($null -eq $state.failure_code) {
                $state.failure_code = "KGI_CLEANUP_PROBE_FAILED"
                $state.failure_reason = $_.Exception.Message
            }
        }
    }

    $state.result = if ($null -eq $state.failure_code -and $state.release_succeeded) { "passed" } else { "failed" }
    return $state
}

function Test-SourceCheckpoint {
    if ($ExpectedExtensionCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "EXTENSION_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedExtensionCheckpointSha256 must be replaced after validation."
    }
    if ($ExpectedConvergenceCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "CONVERGENCE_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedConvergenceCheckpointSha256 must be replaced after validation."
    }
    if ($ExpectedSharedCoreCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "SHARED_CORE_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedSharedCoreCheckpointSha256 must be replaced after validation."
    }
    if ($ExpectedFreezeCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "FREEZE_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedFreezeCheckpointSha256 must be replaced after validation."
    }
    if ($ExpectedLiveRemediationCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "LIVE_REMEDIATION_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedLiveRemediationCheckpointSha256 must be replaced after validation."
    }
    if ($ExpectedReleaseCheckpointSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        Throw-GateFailure -Code "RELEASE_CHECKPOINT_NOT_CAPTURED" -Message "ExpectedReleaseCheckpointSha256 must be replaced after validation."
    }
    $actualExtensionHash = Get-Sha256 -Path $script:ExtensionCheckpointPath
    if ($actualExtensionHash -ne $ExpectedExtensionCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "EXTENSION_CHECKPOINT_CHANGED" -Message "Expected extension checkpoint $ExpectedExtensionCheckpointSha256 but found $actualExtensionHash."
    }
    $extension = Get-Content -LiteralPath $script:ExtensionCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$extension.validation.result -ne "passed") {
        Throw-GateFailure -Code "EXTENSION_VALIDATION_NOT_PASSED" -Message "Extension checkpoint validation result must be passed; found $([string]$extension.validation.result)."
    }
    $actualConvergenceHash = Get-Sha256 -Path $script:ConvergenceCheckpointPath
    if ($actualConvergenceHash -ne $ExpectedConvergenceCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "CONVERGENCE_CHECKPOINT_CHANGED" -Message "Expected convergence checkpoint $ExpectedConvergenceCheckpointSha256 but found $actualConvergenceHash."
    }
    $convergence = Get-Content -LiteralPath $script:ConvergenceCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$convergence.validation.result -ne "passed") {
        Throw-GateFailure -Code "CONVERGENCE_VALIDATION_NOT_PASSED" -Message "Convergence checkpoint validation result must be passed; found $([string]$convergence.validation.result)."
    }
    $actualSharedCoreHash = Get-Sha256 -Path $script:SharedCoreCheckpointPath
    if ($actualSharedCoreHash -ne $ExpectedSharedCoreCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "SHARED_CORE_CHECKPOINT_CHANGED" -Message "Expected shared-core checkpoint $ExpectedSharedCoreCheckpointSha256 but found $actualSharedCoreHash."
    }
    $sharedCore = Get-Content -LiteralPath $script:SharedCoreCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$sharedCore.validation.result -ne "passed") {
        Throw-GateFailure -Code "SHARED_CORE_VALIDATION_NOT_PASSED" -Message "Shared-core checkpoint validation result must be passed; found $([string]$sharedCore.validation.result)."
    }
    $actualFreezeHash = Get-Sha256 -Path $script:FreezeCheckpointPath
    if ($actualFreezeHash -ne $ExpectedFreezeCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "FREEZE_CHECKPOINT_CHANGED" -Message "Expected freeze checkpoint $ExpectedFreezeCheckpointSha256 but found $actualFreezeHash."
    }
    $freeze = Get-Content -LiteralPath $script:FreezeCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$freeze.validation.result -ne "passed") {
        Throw-GateFailure -Code "FREEZE_VALIDATION_NOT_PASSED" -Message "Freeze checkpoint validation result must be passed; found $([string]$freeze.validation.result)."
    }
    $actualLiveRemediationHash = Get-Sha256 -Path $script:LiveRemediationCheckpointPath
    if ($actualLiveRemediationHash -ne $ExpectedLiveRemediationCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "LIVE_REMEDIATION_CHECKPOINT_CHANGED" -Message "Expected live-remediation checkpoint $ExpectedLiveRemediationCheckpointSha256 but found $actualLiveRemediationHash."
    }
    $liveRemediation = Get-Content -LiteralPath $script:LiveRemediationCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$liveRemediation.validation.result -ne "passed") {
        Throw-GateFailure -Code "LIVE_REMEDIATION_VALIDATION_NOT_PASSED" -Message "Live-remediation checkpoint validation result must be passed; found $([string]$liveRemediation.validation.result)."
    }
    $actualReleaseHash = Get-Sha256 -Path $script:ReleaseCheckpointPath
    if ($actualReleaseHash -ne $ExpectedReleaseCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "RELEASE_CHECKPOINT_CHANGED" -Message "Expected release checkpoint $ExpectedReleaseCheckpointSha256 but found $actualReleaseHash."
    }
    $release = Get-Content -LiteralPath $script:ReleaseCheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$release.validation.result -ne "passed") {
        Throw-GateFailure -Code "RELEASE_VALIDATION_NOT_PASSED" -Message "Release checkpoint validation result must be passed; found $([string]$release.validation.result)."
    }
    $extensionMismatches = @()
    $extensionPaths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $effectiveExtensionEntries = @{}
    foreach ($entry in $extension.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    foreach ($entry in $convergence.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    $sharedCoreSupersededPriorTargetCount = @(
        $sharedCore.files | Where-Object { $extensionPaths.Contains([string]$_.path) }
    ).Count
    foreach ($entry in $sharedCore.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    $freezeSupersededPriorTargetCount = @(
        $freeze.files | Where-Object { $extensionPaths.Contains([string]$_.path) }
    ).Count
    foreach ($entry in $freeze.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    $liveRemediationSupersededPriorTargetCount = @(
        $liveRemediation.files | Where-Object { $extensionPaths.Contains([string]$_.path) }
    ).Count
    foreach ($entry in $liveRemediation.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    $releaseSupersededPriorTargetCount = @(
        $release.files | Where-Object { $extensionPaths.Contains([string]$_.path) }
    ).Count
    foreach ($entry in $release.files) {
        $relativePath = [string]$entry.path
        [void]$extensionPaths.Add($relativePath)
        $effectiveExtensionEntries[$relativePath] = $entry
    }
    foreach ($entry in $effectiveExtensionEntries.Values) {
        $relativePath = [string]$entry.path
        $path = Join-Path $script:RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $extensionMismatches += [ordered]@{ path = $relativePath; expected = [string]$entry.sha256; actual = "missing" }
            continue
        }
        $actual = Get-Sha256 -Path $path
        if ($actual -ne [string]$entry.sha256) {
            $extensionMismatches += [ordered]@{ path = $relativePath; expected = [string]$entry.sha256; actual = $actual }
        }
    }
    if ($extensionMismatches.Count -gt 0) {
        $mismatchSummary = @(
            $extensionMismatches | ForEach-Object {
                "$([string]$_.path)|expected=$([string]$_.expected)|actual=$([string]$_.actual)"
            }
        ) -join "; "
        Throw-GateFailure -Code "EXTENSION_TARGET_CHANGED" -Message "$($extensionMismatches.Count) acceptance extension target file(s) changed: $mismatchSummary"
    }

    $actualCheckpointHash = Get-Sha256 -Path $script:CheckpointPath
    if ($actualCheckpointHash -ne $ExpectedCheckpointSha256.ToLowerInvariant()) {
        Throw-GateFailure -Code "SOURCE_CHECKPOINT_CHANGED" -Message "Expected checkpoint $ExpectedCheckpointSha256 but found $actualCheckpointHash."
    }
    $checkpoint = Get-Content -LiteralPath $script:CheckpointPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$checkpoint.validation.result -ne "passed") {
        Throw-GateFailure -Code "SOURCE_VALIDATION_NOT_PASSED" -Message "Source checkpoint validation result must be passed; found $([string]$checkpoint.validation.result)."
    }
    $mismatches = @()
    foreach ($entry in $checkpoint.files) {
        $relativePath = [string]$entry.path
        if ($extensionPaths.Contains($relativePath)) {
            continue
        }
        $path = Join-Path $script:RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $mismatches += [ordered]@{ path = $relativePath; expected = [string]$entry.sha256; actual = "missing" }
            continue
        }
        $actual = Get-Sha256 -Path $path
        if ($actual -ne [string]$entry.sha256) {
            $mismatches += [ordered]@{
                path = $relativePath
                expected = [string]$entry.sha256
                actual = $actual
            }
        }
    }
    if ($mismatches.Count -gt 0) {
        Throw-GateFailure -Code "FOUNDATION_TARGET_CHANGED" -Message "$($mismatches.Count) Foundation checkpoint target file(s) changed."
    }
    return [ordered]@{
        checkpoint_file_sha256 = $actualCheckpointHash
        target_count = @($checkpoint.files).Count
        target_mismatch_count = 0
        public_contract_digest = [string]$checkpoint.public_contract_digest
        extension_checkpoint_file_sha256 = $actualExtensionHash
        extension_target_count = @($extension.files).Count
        extension_target_mismatch_count = 0
        convergence_checkpoint_file_sha256 = $actualConvergenceHash
        convergence_target_count = @($convergence.files).Count
        convergence_target_mismatch_count = 0
        convergence_superseded_extension_target_count = @(
            $extension.files | Where-Object {
                $convergence.files.path -contains [string]$_.path
            }
        ).Count
        shared_core_checkpoint_file_sha256 = $actualSharedCoreHash
        shared_core_target_count = @($sharedCore.files).Count
        shared_core_target_mismatch_count = 0
        shared_core_superseded_prior_target_count = $sharedCoreSupersededPriorTargetCount
        freeze_checkpoint_file_sha256 = $actualFreezeHash
        freeze_target_count = @($freeze.files).Count
        freeze_target_mismatch_count = 0
        freeze_superseded_prior_target_count = $freezeSupersededPriorTargetCount
        live_remediation_checkpoint_file_sha256 = $actualLiveRemediationHash
        live_remediation_target_count = @($liveRemediation.files).Count
        live_remediation_target_mismatch_count = 0
        live_remediation_superseded_prior_target_count = $liveRemediationSupersededPriorTargetCount
        release_checkpoint_file_sha256 = $actualReleaseHash
        release_target_count = @($release.files).Count
        release_target_mismatch_count = 0
        release_superseded_prior_target_count = $releaseSupersededPriorTargetCount
        effective_extension_target_count = $effectiveExtensionEntries.Count
        extension_superseded_base_target_count = @(
            $checkpoint.files | Where-Object { $extensionPaths.Contains([string]$_.path) }
        ).Count
    }
}

if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $ArtifactPath = Join-Path $script:ArtifactsRoot "m5-preflight-$stamp.json"
}
elseif (-not [System.IO.Path]::IsPathRooted($ArtifactPath)) {
    $ArtifactPath = Join-Path $script:RepoRoot $ArtifactPath
}

$artifact = [ordered]@{
    schema_version = "omi.market_data_foundation.m5_preflight.v2"
    captured_at = (Get-Date).ToString("o")
    timezone = "Asia/Taipei"
    expected_date = $ExpectedDate
    runtime_action = $RuntimeAction
    expected_mode = $ExpectedMode
    target = [ordered]@{ market = "TW"; symbol = $Symbol }
    source = $null
    acceptance_harness = $null
    runtime = $null
    calendar = $null
    public_contract = $null
    frontend = $null
    mcp = $null
    viewer_baseline = $null
    viewer_readiness = $null
    result = "running"
    failure_code = $null
    failure_reason = $null
    limitations = @()
}

$exitCode = 0
try {
    $actualDate = Get-Date -Format "yyyy-MM-dd"
    if ($actualDate -ne $ExpectedDate) {
        Throw-GateFailure -Code "LOCAL_DATE_MISMATCH" -Message "Expected local date $ExpectedDate but found $actualDate."
    }

    $artifact.source = Test-SourceCheckpoint
    $artifact.source.branch = (& git -C $script:RepoRoot branch --show-current).Trim()
    $artifact.source.head = (& git -C $script:RepoRoot rev-parse HEAD).Trim()
    $artifact.source.dirty_count = @(& git -C $script:RepoRoot status --short).Count
    $artifact.acceptance_harness = [ordered]@{
        launcher_sha256 = Get-Sha256 -Path $script:LauncherPath
        preflight_sha256 = Get-Sha256 -Path $MyInvocation.MyCommand.Path
        mcp_smoke_sha256 = Get-Sha256 -Path $script:McpSmokePath
        live_session_sha256 = Get-Sha256 -Path (Join-Path $script:RepoRoot "scripts\invoke-mdf-m5-live-session.ps1")
        live_session_test_sha256 = Get-Sha256 -Path (Join-Path $script:RepoRoot "scripts\test-invoke-mdf-m5-live-session.ps1")
    }

    if ($RuntimeAction -eq "SourceOnly") {
        $sourceOnlyReason = "SourceOnly validates the dated source checkpoint and acceptance harness without reading or mutating runtime state."
        $artifact.runtime = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.calendar = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.public_contract = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.frontend = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.mcp = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.viewer_baseline = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.viewer_readiness = [ordered]@{ result = "not_run"; reason = $sourceOnlyReason }
        $artifact.limitations += "Runtime identity, calendar, frontend, MCP, viewer leases, and bridge cleanup remain unverified until the same-day runtime stages."
    }
    else {
    $endpoints = Get-LatestLauncherEndpoints
    if ($RuntimeAction -eq "Prepare") {
        $currentHealth = if ($null -ne $endpoints) { Get-BackendHealthOrNull -BackendUrl $endpoints.backend_url } else { $null }
        $currentLeaseSummary = if ($null -ne $currentHealth) {
            try { Get-LeaseSummary -BackendUrl $endpoints.backend_url } catch { $null }
        } else { $null }
        if ($null -eq $currentHealth -or [string]$currentHealth.runtime.canonical_market_data_mode -ne $ExpectedMode) {
            Invoke-LauncherControl -Action Exit
            Wait-LauncherMutexAvailable -TimeoutSeconds 30
            $startedLauncherPid = Start-OfficialLauncher -Mode $ExpectedMode
            $runtimeState = Wait-ExpectedRuntime -Mode $ExpectedMode -TimeoutSeconds $StartupTimeoutSeconds
            $runtimeState["started_launcher_pid"] = $startedLauncherPid
        }
        elseif ($null -eq $currentLeaseSummary) {
            $previousListenerPid = Get-ListenerPid -Url $endpoints.backend_url
            Invoke-LauncherControl -Action RestartServices
            $runtimeState = Wait-ExpectedRuntime -Mode $ExpectedMode -TimeoutSeconds $StartupTimeoutSeconds -PreviousListenerPid $previousListenerPid
            $runtimeState["started_launcher_pid"] = $null
            $runtimeState["previous_listener_pid"] = $previousListenerPid
        }
        else {
            $runtimeState = Wait-ExpectedRuntime -Mode $ExpectedMode -TimeoutSeconds 15
            $runtimeState["started_launcher_pid"] = $null
        }
    }
    elseif ($RuntimeAction -eq "RestartServices") {
        if ($null -eq $endpoints) {
            Throw-GateFailure -Code "RUNTIME_IDENTITY_MISMATCH" -Message "No official launcher endpoint could be discovered."
        }
        $currentHealth = Get-BackendHealthOrNull -BackendUrl $endpoints.backend_url
        if ($null -eq $currentHealth -or [string]$currentHealth.runtime.canonical_market_data_mode -ne $ExpectedMode) {
            Throw-GateFailure -Code "EFFECTIVE_MODE_MISMATCH" -Message "RestartServices requires current effective mode=$ExpectedMode."
        }
        $previousListenerPid = Get-ListenerPid -Url $endpoints.backend_url
        Invoke-LauncherControl -Action RestartServices
        $runtimeState = Wait-ExpectedRuntime -Mode $ExpectedMode -TimeoutSeconds $StartupTimeoutSeconds -PreviousListenerPid $previousListenerPid
        $runtimeState["started_launcher_pid"] = $null
        $runtimeState["previous_listener_pid"] = $previousListenerPid
    }
    else {
        if ($null -eq $endpoints) {
            Throw-GateFailure -Code "RUNTIME_IDENTITY_MISMATCH" -Message "No official launcher endpoint could be discovered."
        }
        $runtimeState = Wait-ExpectedRuntime -Mode $ExpectedMode -TimeoutSeconds 15
        $runtimeState["started_launcher_pid"] = $null
    }

    $endpoints = $runtimeState.endpoints
    $health = $runtimeState.health
    $listenerPid = [int]$runtimeState.listener_pid
    if ($listenerPid -le 0) {
        Throw-GateFailure -Code "RUNTIME_LINEAGE_PROBE_UNAVAILABLE" -Message "Backend health/ready passed, but the selected listener PID was not observable in this execution environment."
    }
    $lineage = @(Get-ProcessLineage -ProcessId $listenerPid)
    if ($lineage.Count -eq 0) {
        Throw-GateFailure -Code "RUNTIME_LINEAGE_PROBE_UNAVAILABLE" -Message "Backend listener PID=$listenerPid was observed, but its process lineage was not readable in this execution environment."
    }
    $launcherNode = @($lineage | Where-Object { [string]$_.command_line -match "scripts[\\/]omi-launcher\.ps1" } | Select-Object -First 1)
    if ($launcherNode.Count -ne 1) {
        Throw-GateFailure -Code "RUNTIME_IDENTITY_MISMATCH" -Message "Backend listener lineage did not resolve to the official OMI launcher."
    }
    if ([string]$health.runtime.project_root -ne $script:ExpectedProjectRoot -or
        [string]$health.runtime.python_executable -ne $script:ExpectedPython) {
        Throw-GateFailure -Code "RUNTIME_IDENTITY_MISMATCH" -Message "Backend health project_root/python did not match the repo runtime."
    }
    $artifact.runtime = [ordered]@{
        backend_url = $endpoints.backend_url
        frontend_url = $endpoints.frontend_url
        launcher_log = $endpoints.launcher_log
        listener_pid = $listenerPid
        launcher_pid = [int]$launcherNode[0].pid
        effective_mode = [string]$health.runtime.canonical_market_data_mode
        health = [string]$health.status
        ready = [string]$runtimeState.ready.status
        project_root = [string]$health.runtime.project_root
        python = [string]$health.runtime.python_executable
        started_launcher_pid = $runtimeState.started_launcher_pid
        previous_listener_pid = $runtimeState.previous_listener_pid
        lineage = $lineage
    }

    $calendarResponse = Invoke-JsonRequest -Method GET -Url "$($endpoints.backend_url)/api/market/calendar-status?market=all" -TimeoutSeconds 10
    $tw = $calendarResponse.markets.tw
    $calendarPass = [string]$tw.date -eq $ExpectedDate -and
        [bool]$tw.is_trading_day -and
        [string]$tw.calendar_cache_status -eq "current" -and
        @($tw.calendar_verified_years) -contains [int]$ExpectedDate.Substring(0, 4) -and
        [string]::IsNullOrWhiteSpace([string]$tw.calendar_warning)
    $artifact.calendar = [ordered]@{
        date = [string]$tw.date
        is_trading_day = [bool]$tw.is_trading_day
        phase = [string]$tw.phase
        reason = [string]$tw.reason
        next_trading_day = [string]$tw.next_trading_day
        source = [string]$tw.calendar_source
        cache_status = [string]$tw.calendar_cache_status
        verified_years = @($tw.calendar_verified_years)
        warning = $tw.calendar_warning
        result = if ($calendarPass) { "passed" } else { "failed" }
    }
    if (-not $calendarPass) {
        Throw-GateFailure -Code "TW_CALENDAR_GATE_FAILED" -Message "TW authoritative calendar did not confirm the expected trading day."
    }

    $tools = Invoke-JsonRequest -Method GET -Url "$($endpoints.backend_url)/api/ai/tools" -TimeoutSeconds 15
    $ask = @($tools.tools | Where-Object { $_.name -eq "omi.ask" } | Select-Object -First 1)
    $liveDigest = if ($ask.Count -eq 1) { [string]$ask[0].input_schema.'x-omi-public-contract-digest' } else { "" }
    $artifact.public_contract = [ordered]@{
        expected_digest = [string]$artifact.source.public_contract_digest
        live_digest = $liveDigest
        omi_ask_present = $ask.Count -eq 1
        result = if ($liveDigest -eq [string]$artifact.source.public_contract_digest) { "passed" } else { "failed" }
    }
    if ($artifact.public_contract.result -ne "passed") {
        Throw-GateFailure -Code "PUBLIC_CATALOG_MISMATCH" -Message "Live /api/ai/tools digest did not match the source checkpoint."
    }

    $artifact.frontend = Wait-ExpectedFrontend `
        -FrontendUrl $endpoints.frontend_url `
        -BackendUrl $endpoints.backend_url `
        -TimeoutSeconds $FrontendStartupTimeoutSeconds
    if ($artifact.frontend.result -ne "passed") {
        Throw-GateFailure -Code "FRONTEND_READINESS_TIMEOUT" -Message "Frontend health did not match the selected backend/runtime within $FrontendStartupTimeoutSeconds seconds."
    }

    $mcpOutput = & $script:ExpectedPython -X utf8 $script:McpSmokePath --backend-url $endpoints.backend_url --timeout-seconds 30
    if ($LASTEXITCODE -ne 0) {
        Throw-GateFailure -Code "MCP_TRANSPORT_FAILED" -Message "OMI stdio MCP smoke exited with code $LASTEXITCODE."
    }
    $artifact.mcp = [string]($mcpOutput -join "") | ConvertFrom-Json

    $artifact.viewer_baseline = Get-CleanViewerBaseline `
        -BackendUrl $endpoints.backend_url `
        -StockId $Symbol `
        -CleanupTimeoutSeconds $ViewerCleanupTimeoutSeconds
    if ($artifact.viewer_baseline.result -ne "passed") {
        Throw-GateFailure -Code ([string]$artifact.viewer_baseline.failure_code) -Message ([string]$artifact.viewer_baseline.failure_reason)
    }

    if ($RunViewerReadiness) {
        $artifact.viewer_readiness = Invoke-ViewerReadiness -BackendUrl $endpoints.backend_url -StockId $Symbol -CleanupTimeoutSeconds $ViewerCleanupTimeoutSeconds
        if ($artifact.viewer_readiness.result -ne "passed") {
            Throw-GateFailure -Code ([string]$artifact.viewer_readiness.failure_code) -Message ([string]$artifact.viewer_readiness.failure_reason)
        }
    }
    }

    $artifact.result = "passed"
}
catch {
    $message = $_.Exception.Message
    $artifact.result = "failed"
    $artifact.failure_code = if ($message -match "^\[([^\]]+)\]") { $Matches[1] } else { "M5_PREFLIGHT_FAILED" }
    $artifact.failure_reason = $message
    $exitCode = 1
}
finally {
    $artifact.completed_at = (Get-Date).ToString("o")
    Write-JsonArtifact -Path $ArtifactPath -Payload $artifact
    Write-Output ($artifact | ConvertTo-Json -Depth 16 -Compress)
    Write-Output "artifact=$ArtifactPath"
}

exit $exitCode
