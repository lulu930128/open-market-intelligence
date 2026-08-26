[CmdletBinding()]
param(
    [ValidateSet("OfflineFixture", "Live")]
    [string]$Mode = "OfflineFixture",
    [string]$BackendUrl,
    [string]$FixturePath,
    [string[]]$Symbols = @("2330", "2303", "2330"),
    [ValidateRange(3, 120)][int]$StepDurationSeconds = 20,
    [ValidateRange(250, 5000)][int]$SampleIntervalMs = 500,
    [ValidateSet("off", "shadow", "compare")][string]$ExpectedMode = "compare",
    [bool]$RequireZeroLeaseBaseline = $true,
    [string]$ArtifactPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$script:TaskRoot = Join-Path $script:RepoRoot "docs\agent-runs\tw-realtime-market-state-remediation-20260824"
$script:CounterKeys = @(
    "callback_count",
    "baseline_only_count",
    "cumulative_advanced_count",
    "same_cumulative_count",
    "decreasing_cumulative_count",
    "missing_cumulative_count",
    "invalid_cumulative_count",
    "trade_addition_count",
    "auction_addition_count",
    "trade_signature_suppression_count",
    "auction_signature_suppression_count",
    "non_trade_suppression_count",
    "trial_leak_count",
    "cross_date_rejected_count"
)
$script:LatencyKeys = @(
    "event_to_bridge_ms",
    "bridge_to_manager_ms",
    "manager_to_stream_ms",
    "event_to_stream_ms"
)

function Throw-HarnessFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Message
    )

    throw "[$Code] $Message"
}

function Get-PropertyValue {
    param($Object, [Parameter(Mandatory = $true)][string]$Name)

    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Convert-ToNonNegativeInt {
    param($Value)

    if ($null -eq $Value) { return 0 }
    $parsed = 0L
    if (-not [long]::TryParse([string]$Value, [ref]$parsed)) { return 0 }
    return [math]::Max($parsed, 0)
}

function New-ZeroCounters {
    $result = [ordered]@{}
    foreach ($key in $script:CounterKeys) { $result[$key] = 0L }
    return $result
}

function Get-CounterDelta {
    param($Current, $Baseline)

    $result = New-ZeroCounters
    foreach ($key in $script:CounterKeys) {
        $currentValue = Convert-ToNonNegativeInt (Get-PropertyValue $Current $key)
        $baselineValue = Convert-ToNonNegativeInt (Get-PropertyValue $Baseline $key)
        $result[$key] = [math]::Max($currentValue - $baselineValue, 0)
    }
    return $result
}

function Add-Counters {
    param(
        [Parameter(Mandatory = $true)]$Target,
        [Parameter(Mandatory = $true)]$Source
    )

    foreach ($key in $script:CounterKeys) {
        $Target[$key] = (Convert-ToNonNegativeInt $Target[$key]) +
            (Convert-ToNonNegativeInt $Source[$key])
    }
}

function Get-Percentile {
    param(
        [double[]]$Values,
        [ValidateRange(0, 1)][double]$Percentile
    )

    if ($null -eq $Values -or $Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $index = [math]::Ceiling($Percentile * $sorted.Count) - 1
    $index = [math]::Max([math]::Min($index, $sorted.Count - 1), 0)
    return [math]::Round([double]$sorted[$index], 3)
}

function Get-LatencySummary {
    param([Parameter(Mandatory = $true)]$Samples)

    $result = [ordered]@{}
    foreach ($key in $script:LatencyKeys) {
        $values = New-Object System.Collections.Generic.List[double]
        $missing = 0
        $negative = 0
        foreach ($sample in @($Samples)) {
            $latency = Get-PropertyValue $sample "latency"
            $value = Get-PropertyValue $latency $key
            if ($null -eq $value) {
                $missing += 1
                continue
            }
            $parsed = 0.0
            if (-not [double]::TryParse([string]$value, [ref]$parsed)) {
                $missing += 1
                continue
            }
            if ($parsed -lt 0) {
                $negative += 1
                continue
            }
            $values.Add($parsed)
        }
        $result[$key] = [ordered]@{
            sample_count = $values.Count
            missing_count = $missing
            negative_count = $negative
            p50_ms = Get-Percentile -Values $values.ToArray() -Percentile 0.50
            p95_ms = Get-Percentile -Values $values.ToArray() -Percentile 0.95
            max_ms = if ($values.Count -gt 0) {
                [math]::Round([double](($values.ToArray() | Measure-Object -Maximum).Maximum), 3)
            } else { $null }
        }
    }
    return $result
}

function Test-UsefulDepth {
    param($Sample)

    $capabilities = Get-PropertyValue $Sample "capability_status"
    $depth = Get-PropertyValue $Sample "depth"
    if ([string](Get-PropertyValue $capabilities "depth") -ne "available") { return $false }
    if ($null -eq $depth -or (Get-PropertyValue $depth "is_stale") -eq $true) { return $false }
    $bids = @(Get-PropertyValue $depth "bid_levels")
    $asks = @(Get-PropertyValue $depth "ask_levels")
    return ($bids.Count + $asks.Count) -gt 0
}

function Get-FirstUsefulDepthMs {
    param([Parameter(Mandatory = $true)]$Samples)

    foreach ($sample in @($Samples)) {
        if (Test-UsefulDepth $sample) {
            $offset = Get-PropertyValue $sample "captured_offset_ms"
            if ($null -ne $offset) { return [math]::Max([int]$offset, 0) }
        }
    }
    return $null
}

function Invoke-JsonRequest {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        $Body = $null,
        [ValidateRange(1, 60)][int]$TimeoutSeconds = 10
    )

    $parameters = @{
        Uri = $Url
        Method = $Method
        TimeoutSec = $TimeoutSeconds
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $parameters["Body"] = $Body | ConvertTo-Json -Depth 6 -Compress
        $parameters["ContentType"] = "application/json"
    }
    if ($Method -eq "DELETE") {
        Invoke-WebRequest @parameters | Out-Null
        return $null
    }
    return Invoke-RestMethod @parameters
}

function Write-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if (Test-Path -LiteralPath $Path) {
        Throw-HarnessFailure -Code "ARTIFACT_ALREADY_EXISTS" -Message "Artifact already exists: $Path"
    }
    $temporaryPath = "$Path.tmp.$PID"
    try {
        $json = $Payload | ConvertTo-Json -Depth 16
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $json + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
        [System.IO.File]::Move($temporaryPath, $Path)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Get-StepResult {
    param(
        [Parameter(Mandatory = $true)][int]$SwitchIndex,
        [Parameter(Mandatory = $true)][string]$Symbol,
        [Parameter(Mandatory = $true)]$Samples,
        $DiagnosticBaseline = $null,
        [int]$RequestErrorCount = 0
    )

    $sampleArray = @($Samples)
    $lastCounters = if ($sampleArray.Count -gt 0) {
        Get-PropertyValue $sampleArray[-1] "diagnostic_counters"
    } else { $null }
    $counterDelta = Get-CounterDelta -Current $lastCounters -Baseline $DiagnosticBaseline
    return [ordered]@{
        switch_index = $SwitchIndex
        symbol = $Symbol
        sample_count = $sampleArray.Count
        request_error_count = $RequestErrorCount
        first_useful_depth_ms = Get-FirstUsefulDepthMs -Samples $sampleArray
        diagnostic_counters = $counterDelta
        latency = Get-LatencySummary -Samples $sampleArray
    }
}

function Get-OfflineSteps {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Throw-HarnessFailure -Code "FIXTURE_NOT_FOUND" -Message "Offline fixture was not found: $Path"
    }
    $fixture = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string](Get-PropertyValue $fixture "effective_mode") -ne $ExpectedMode) {
        Throw-HarnessFailure -Code "EFFECTIVE_MODE_MISMATCH" -Message "Fixture effective mode does not match $ExpectedMode."
    }
    $baseline = Get-PropertyValue $fixture "lease_baseline"
    $baselineCount = Convert-ToNonNegativeInt (Get-PropertyValue $baseline "total_active_leases")
    if ($RequireZeroLeaseBaseline -and $baselineCount -ne 0) {
        Throw-HarnessFailure -Code "LEASE_BASELINE_NOT_ZERO" -Message "Fixture lease baseline is not zero."
    }
    return [ordered]@{
        effective_mode = [string](Get-PropertyValue $fixture "effective_mode")
        lease_baseline_count = $baselineCount
        lease_cleanup_count = Convert-ToNonNegativeInt (Get-PropertyValue (Get-PropertyValue $fixture "lease_cleanup") "total_active_leases")
        steps = @(Get-PropertyValue $fixture "steps")
    }
}

function Get-LiveSteps {
    param([Parameter(Mandatory = $true)][string]$Url)

    $normalizedUrl = $Url.TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($normalizedUrl)) {
        Throw-HarnessFailure -Code "BACKEND_URL_REQUIRED" -Message "Live mode requires BackendUrl."
    }
    $health = Invoke-JsonRequest -Method GET -Url "$normalizedUrl/api/system/health" -TimeoutSeconds 5
    $effectiveMode = [string](Get-PropertyValue (Get-PropertyValue $health "runtime") "canonical_market_data_mode")
    if ($effectiveMode -ne $ExpectedMode) {
        Throw-HarnessFailure -Code "EFFECTIVE_MODE_MISMATCH" -Message "Runtime effective mode is '$effectiveMode', expected '$ExpectedMode'."
    }
    $leaseSummary = Invoke-JsonRequest -Method GET -Url "$normalizedUrl/api/market/realtime-quote-leases/summary" -TimeoutSeconds 5
    $baselineCount = Convert-ToNonNegativeInt (Get-PropertyValue $leaseSummary "total_active_leases")
    if ($RequireZeroLeaseBaseline -and $baselineCount -ne 0) {
        Throw-HarnessFailure -Code "LEASE_BASELINE_NOT_ZERO" -Message "Runtime has $baselineCount active realtime leases before acceptance."
    }

    $stepResults = New-Object System.Collections.Generic.List[object]
    $ownedLeaseIds = New-Object System.Collections.Generic.List[string]
    try {
        for ($switchIndex = 0; $switchIndex -lt $Symbols.Count; $switchIndex++) {
            $symbol = [string]$Symbols[$switchIndex]
            if ($symbol -notmatch '^\d{4,6}$') {
                Throw-HarnessFailure -Code "INVALID_SYMBOL" -Message "Invalid Taiwan symbol: $symbol"
            }
            $encodedSymbol = [uri]::EscapeDataString($symbol)
            $preLeaseSnapshot = Invoke-JsonRequest -Method GET -Url "$normalizedUrl/api/market/realtime-quotes/${encodedSymbol}?diagnostic_limit=0" -TimeoutSeconds 5
            $diagnosticBaseline = Get-PropertyValue $preLeaseSnapshot "diagnostic_counters"
            $lease = Invoke-JsonRequest -Method POST -Url "$normalizedUrl/api/market/realtime-quote-leases" -Body @{
                stock_id = $symbol
                owner_kind = "acceptance_probe"
            } -TimeoutSeconds 15
            $leaseId = [string](Get-PropertyValue $lease "lease_id")
            if ([string]::IsNullOrWhiteSpace($leaseId)) {
                Throw-HarnessFailure -Code "LEASE_ACQUIRE_FAILED" -Message "Acceptance lease did not return an owned lease id for $symbol."
            }
            $ownedLeaseIds.Add($leaseId)
            $samples = New-Object System.Collections.Generic.List[object]
            $requestErrors = 0
            $stepClock = [System.Diagnostics.Stopwatch]::StartNew()
            $nextHeartbeatMs = 15000
            while ($stepClock.Elapsed.TotalSeconds -lt $StepDurationSeconds) {
                try {
                    $snapshot = Invoke-JsonRequest -Method GET -Url "$normalizedUrl/api/market/realtime-quotes/${encodedSymbol}?diagnostic_limit=120" -TimeoutSeconds 5
                    $snapshot | Add-Member -NotePropertyName "captured_offset_ms" -NotePropertyValue ([int]$stepClock.Elapsed.TotalMilliseconds) -Force
                    $samples.Add($snapshot)
                }
                catch {
                    $requestErrors += 1
                }
                if ($stepClock.Elapsed.TotalMilliseconds -ge $nextHeartbeatMs) {
                    Invoke-JsonRequest -Method PATCH -Url "$normalizedUrl/api/market/realtime-quote-leases/$([uri]::EscapeDataString($leaseId))" -TimeoutSeconds 5 | Out-Null
                    $nextHeartbeatMs += 15000
                }
                Start-Sleep -Milliseconds $SampleIntervalMs
            }
            $stepClock.Stop()
            $stepResults.Add((Get-StepResult -SwitchIndex $switchIndex -Symbol $symbol -Samples $samples.ToArray() -DiagnosticBaseline $diagnosticBaseline -RequestErrorCount $requestErrors))
            Invoke-JsonRequest -Method DELETE -Url "$normalizedUrl/api/market/realtime-quote-leases/$([uri]::EscapeDataString($leaseId))" -TimeoutSeconds 5 | Out-Null
            $ownedLeaseIds.Remove($leaseId) | Out-Null
        }
    }
    finally {
        foreach ($leaseId in @($ownedLeaseIds.ToArray())) {
            try {
                Invoke-JsonRequest -Method DELETE -Url "$normalizedUrl/api/market/realtime-quote-leases/$([uri]::EscapeDataString($leaseId))" -TimeoutSeconds 5 | Out-Null
            }
            catch {
                # Cleanup is proved by the post-run summary below.
            }
        }
    }
    $cleanupSummary = Invoke-JsonRequest -Method GET -Url "$normalizedUrl/api/market/realtime-quote-leases/summary" -TimeoutSeconds 5
    return [ordered]@{
        effective_mode = $effectiveMode
        lease_baseline_count = $baselineCount
        lease_cleanup_count = Convert-ToNonNegativeInt (Get-PropertyValue $cleanupSummary "total_active_leases")
        step_results = $stepResults.ToArray()
    }
}

$startedAt = (Get-Date).ToUniversalTime()
if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
    $stamp = $startedAt.ToString("yyyyMMddTHHmmssZ")
    $ArtifactPath = Join-Path $script:TaskRoot "artifacts\m5-live-session-$stamp.json"
}
elseif (-not [System.IO.Path]::IsPathRooted($ArtifactPath)) {
    $ArtifactPath = Join-Path $script:RepoRoot $ArtifactPath
}

$source = if ($Mode -eq "OfflineFixture") {
    if ([string]::IsNullOrWhiteSpace($FixturePath)) {
        $FixturePath = Join-Path $script:TaskRoot "fixtures\m5-offline-session.json"
    }
    elseif (-not [System.IO.Path]::IsPathRooted($FixturePath)) {
        $FixturePath = Join-Path $script:RepoRoot $FixturePath
    }
    Get-OfflineSteps -Path $FixturePath
} else {
    Get-LiveSteps -Url $BackendUrl
}

$stepResults = New-Object System.Collections.Generic.List[object]
if ($Mode -eq "OfflineFixture") {
    $switchIndex = 0
    foreach ($step in @($source.steps)) {
        $stepResults.Add((Get-StepResult -SwitchIndex $switchIndex -Symbol ([string](Get-PropertyValue $step "symbol")) -Samples @(Get-PropertyValue $step "samples") -DiagnosticBaseline (Get-PropertyValue $step "diagnostic_baseline") -RequestErrorCount (Convert-ToNonNegativeInt (Get-PropertyValue $step "request_error_count"))))
        $switchIndex += 1
    }
} else {
    foreach ($step in @($source.step_results)) { $stepResults.Add($step) }
}

$aggregateCounters = New-ZeroCounters
$totalNegativeLatency = 0
$totalRequestErrors = 0
$depthReadyForEverySwitch = $stepResults.Count -gt 0
foreach ($step in @($stepResults.ToArray())) {
    Add-Counters -Target $aggregateCounters -Source $step.diagnostic_counters
    $totalRequestErrors += Convert-ToNonNegativeInt $step.request_error_count
    if ($null -eq $step.first_useful_depth_ms) { $depthReadyForEverySwitch = $false }
    foreach ($key in $script:LatencyKeys) {
        $totalNegativeLatency += Convert-ToNonNegativeInt (Get-PropertyValue (Get-PropertyValue $step.latency $key) "negative_count")
    }
}
$categorizedCallbacks =
    $aggregateCounters.baseline_only_count +
    $aggregateCounters.trade_addition_count +
    $aggregateCounters.auction_addition_count +
    $aggregateCounters.trade_signature_suppression_count +
    $aggregateCounters.auction_signature_suppression_count +
    $aggregateCounters.non_trade_suppression_count +
    $aggregateCounters.cross_date_rejected_count
$callbacksCategorized = $categorizedCallbacks -eq $aggregateCounters.callback_count
$cleanupRestored = $source.lease_cleanup_count -eq $source.lease_baseline_count
$passed =
    $depthReadyForEverySwitch -and
    $aggregateCounters.trial_leak_count -eq 0 -and
    $totalNegativeLatency -eq 0 -and
    $callbacksCategorized -and
    $cleanupRestored

$artifact = [ordered]@{
    schema_version = "omi.mdf.m5.live_session.v1"
    status = if ($passed) { "passed" } else { "failed" }
    mode = $Mode
    started_at = $startedAt.ToString("o")
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    expected_mode = $ExpectedMode
    effective_mode = $source.effective_mode
    symbols = @($stepResults.ToArray() | ForEach-Object { $_.symbol })
    lease_baseline_count = $source.lease_baseline_count
    lease_cleanup_count = $source.lease_cleanup_count
    request_error_count = $totalRequestErrors
    assertions = [ordered]@{
        depth_ready_for_every_switch = $depthReadyForEverySwitch
        no_trial_trade_leak = $aggregateCounters.trial_leak_count -eq 0
        no_negative_latency = $totalNegativeLatency -eq 0
        callbacks_categorized = $callbacksCategorized
        owned_lease_cleanup_restored_baseline = $cleanupRestored
    }
    diagnostic_counters = $aggregateCounters
    steps = $stepResults.ToArray()
    artifact_policy = [ordered]@{
        raw_provider_payload_included = $false
        diagnostic_events_included = $false
        lease_ids_included = $false
        credentials_included = $false
    }
}

Write-JsonArtifact -Path $ArtifactPath -Payload $artifact
$result = [ordered]@{
    status = $artifact.status
    artifact = (Resolve-Path -LiteralPath $ArtifactPath).Path
    step_count = $stepResults.Count
    callback_count = $aggregateCounters.callback_count
}
$result | ConvertTo-Json -Depth 5
if (-not $passed) { exit 1 }
