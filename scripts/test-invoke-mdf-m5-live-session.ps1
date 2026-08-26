[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$harnessPath = Join-Path $PSScriptRoot "invoke-mdf-m5-live-session.ps1"
$fixturePath = Join-Path $repoRoot "docs\agent-runs\tw-realtime-market-state-remediation-20260824\fixtures\m5-offline-session.json"
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("omi-m5-harness-test-" + [guid]::NewGuid().ToString("N"))
$artifactPath = Join-Path $temporaryRoot "artifact.json"

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    $harnessText = Get-Content -LiteralPath $harnessPath -Raw -Encoding UTF8
    if ($harnessText.Contains('$encodedSymbol?diagnostic_limit=')) {
        throw "Live URL interpolation must delimit encodedSymbol before the query string."
    }
    if ([regex]::Matches($harnessText, '\$\{encodedSymbol\}\?diagnostic_limit=').Count -ne 2) {
        throw "Expected both live snapshot URLs to delimit encodedSymbol before the query string."
    }

    & $harnessPath -Mode OfflineFixture -FixturePath $fixturePath -ArtifactPath $artifactPath -ExpectedMode compare | Out-Null
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Offline harness returned exit code $LASTEXITCODE."
    }
    $artifactText = Get-Content -LiteralPath $artifactPath -Raw -Encoding UTF8
    $artifact = $artifactText | ConvertFrom-Json

    if ($artifact.status -ne "passed") { throw "Offline artifact did not pass." }
    if (@($artifact.steps).Count -ne 3) { throw "Expected three switch steps." }
    if ([int]$artifact.diagnostic_counters.callback_count -ne 10) { throw "Callback aggregation mismatch." }
    if ([int]$artifact.diagnostic_counters.same_cumulative_count -ne 2) { throw "Same cumulative aggregation mismatch." }
    if ([int]$artifact.diagnostic_counters.decreasing_cumulative_count -ne 1) { throw "Decreasing cumulative aggregation mismatch." }
    if (-not $artifact.assertions.callbacks_categorized) { throw "Callback actions were not conserved." }
    if (-not $artifact.assertions.depth_ready_for_every_switch) { throw "Depth readiness was not observed for every switch." }
    if ($artifactText -match "must-not-leak|raw_payload|lease-secret-|account_id") { throw "Artifact allowlist leaked fixture-only sensitive fields." }
    if ($artifact.artifact_policy.diagnostic_events_included) { throw "Diagnostic events must not be persisted." }

    [ordered]@{
        status = "passed"
        tested_script = $harnessPath
        fixture = $fixturePath
        callback_count = [int]$artifact.diagnostic_counters.callback_count
    } | ConvertTo-Json -Depth 4
}
finally {
    if (Test-Path -LiteralPath $artifactPath) {
        Remove-Item -LiteralPath $artifactPath -Force
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Force
    }
}
