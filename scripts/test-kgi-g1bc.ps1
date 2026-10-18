<#
No-secret G1-B/C acceptance. Default is non-mutating capability detection.
Stage creates/removes only a new owned workspace. Probe requires a separately
approved source-enrolled existing profile. This script never provisions one.
#>
param([string]$Mode = 'Preflight')
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0 -or $Mode -notin @('Preflight', 'Stage', 'Probe')) {
    Write-Output '{"status":"BLOCKED","reasonCodes":["UNEXPECTED_ARGUMENTS"]}'
    exit 2
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$operation = @{ Preflight = 'sandbox-preflight'; Stage = 'sandbox-stage'; Probe = 'sandbox-probe' }[$Mode]
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = Join-Path $repo '.venv\Scripts\python.exe'
$start.Arguments = '-I -S -B execution_kgi_simulator/native/parent.py ' + $operation
$start.WorkingDirectory = $repo
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.EnvironmentVariables.Clear()
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
$resultExit = 2
$started = $false
try {
    if (-not $process.Start()) { throw 'OWNED_PARENT_START_FAILED' }
    $started = $true
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(45000)) {
        $process.Kill()
        $stopped = $process.WaitForExit(5000)
        Write-Output ('{"status":"BLOCKED","reasonCodes":["PARENT_TIMEOUT"],"parent_stop_observed":' + $stopped.ToString().ToLowerInvariant() + ',"child_teardown":"UNVERIFIED","workspace_cleanup":"UNVERIFIED"}')
    } elseif (-not ($stdout.Wait(2000) -and $stderr.Wait(2000))) {
        Write-Output '{"status":"BLOCKED","reasonCodes":["OUTPUT_DRAIN_UNVERIFIED"]}'
    } else {
        # Redact unexpected interpreter errors; only emit the bounded JSON contract.
        if ($stdout.Result.Length -gt 32768 -or $stderr.Result.Length -ne 0) { throw 'OUTPUT_CONTRACT_REJECTED' }
        $report = $stdout.Result | ConvertFrom-Json
        if ($process.ExitCode -ne 2 -or $report.status -ne 'BLOCKED' -or
            $report.gates.G1 -ne 'BLOCKED' -or $report.gates.G2 -ne 'BLOCKED' -or $report.gates.G3 -ne 'BLOCKED' -or
            $report.credential_values_read -ne $false -or $report.sdk_imported -ne $false -or
            $report.broker_calls -ne 0 -or $report.orders_sent -ne 0) { throw 'OUTPUT_CONTRACT_REJECTED' }
        Write-Output ('parent_actual_exit=' + $process.ExitCode)
        Write-Output $stdout.Result.Trim()
    }
} catch {
    Write-Output '{"status":"BLOCKED","reasonCodes":["BOUNDED_PARENT_LAUNCH_OR_CONTRACT_FAILURE"]}'
} finally {
    if ($started -and -not $process.HasExited) {
        $process.Kill()
        $null = $process.WaitForExit(5000)
    }
    $process.Dispose()
}
exit $resultExit
