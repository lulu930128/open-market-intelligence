<#
.SYNOPSIS
KGI simulator qualification ONLY. No production login, actual probe or order is
enabled in this release. Exit 0: offline tests passed; 1: failed; 2: BLOCKED.
Preflight reads fixed SDK source/metadata; credentials are never read here.
ContractTest uses a closed local fake. Probe/Send fail closed until reviewed
broker environment/account/CA/entitlement/transport proof exists in source.
#>
param(
    [string]$Mode = 'Preflight',
    [string]$TimeoutSeconds = '60'
)
$ErrorActionPreference = 'Stop'

function Assert-KgiQualificationResponse($Response, [int]$ChildExit, [string]$RequestedMode) {
    if ($Response -isnot [pscustomobject] -or $Response.mode -cne $RequestedMode) {
        throw 'INVALID_WORKER_RESPONSE'
    }
    foreach ($key in @('broker_calls','orders_sent','scheduled_orders')) {
        if (($Response.$key -isnot [int] -and $Response.$key -isnot [long]) -or $Response.$key -ne 0) {
            throw 'INVALID_WORKER_RESPONSE'
        }
    }
    if ($Response.sdk_imported -isnot [bool] -or $Response.sdk_imported) { throw 'INVALID_WORKER_RESPONSE' }
    if ($RequestedMode -ceq 'ContractTest') {
        if ($Response.schema -cne 'omi.kgi-sim.contract.v1' -or $Response.origin -cne 'LOCAL_MOCK' -or
            $Response.real_simulator -cne 'BLOCKED' -or $Response.real_production -cne 'FORBIDDEN') {
            throw 'INVALID_WORKER_RESPONSE'
        }
        foreach ($key in @('tests','failures','errors','skipped')) {
            if (($Response.$key -isnot [int] -and $Response.$key -isnot [long]) -or $Response.$key -lt 0) {
                throw 'INVALID_WORKER_RESPONSE'
            }
        }
        $failed = $Response.failures + $Response.errors
        if ($Response.tests -le 0 -or $Response.skipped -ge $Response.tests -or
            -not (($Response.status -ceq 'PASS' -and $ChildExit -eq 0 -and $failed -eq 0) -or
                  ($Response.status -ceq 'FAIL' -and $ChildExit -eq 1 -and $failed -gt 0))) {
            throw 'INVALID_WORKER_RESPONSE'
        }
    } else {
        if ($RequestedMode -cnotin @('Preflight','Probe','Send','RealSimPreflight','RealSimProbe') -or
            $Response.status -cne 'BLOCKED' -or $ChildExit -ne 2 -or
            ($Response.login_attempts -isnot [long] -and $Response.login_attempts -isnot [int]) -or
            $Response.login_attempts -ne 0 -or $Response.probe.status -cne 'BLOCKED' -or
            $Response.order.status -cne 'BLOCKED' -or
            $Response.gates.REAL_SIMULATOR -cne 'BLOCKED' -or $Response.gates.REAL_PRODUCTION -cne 'FORBIDDEN') {
            throw 'INVALID_WORKER_RESPONSE'
        }
        if ($RequestedMode -cin @('RealSimPreflight','RealSimProbe')) {
            if ($Response.schema -cne 'omi.kgi-real-sim.qualification.v1' -or
                $Response.origin -cne 'SOURCE_INSPECTION' -or $Response.runtime_origin -cne 'NOT_CONNECTED' -or
                $Response.target -cne 'REAL_SIM' -or $Response.connector -cne 'NOT_IMPLEMENTED' -or
                $Response.session_reuse -cne 'FORBIDDEN' -or $Response.execution_ingress -cne 'BLOCKED' -or
                $Response.broker_connected -isnot [bool] -or $Response.broker_connected) {
                throw 'INVALID_WORKER_RESPONSE'
            }
            foreach ($key in @('native_probe_attempts','cancel_requests')) {
                if (($Response.$key -isnot [int] -and $Response.$key -isnot [long]) -or $Response.$key -ne 0) {
                    throw 'INVALID_WORKER_RESPONSE'
                }
            }
            $native = $Response.native_readiness
            if ($native -isnot [pscustomobject] -or $native.schema -cne 'omi.kgi-native-readiness.v1' -or
                $native.status -cne 'BLOCKED' -or $native.runtime_origin -cne 'NOT_CONNECTED' -or
                $native.official_target.status -cne 'UNVERIFIED' -or
                $native.official_target.pinned_destinations -ne 0 -or
                $native.containment.status -cne 'NOT_IMPLEMENTED') { throw 'INVALID_WORKER_RESPONSE' }
            foreach ($key in @('G1','G2','G3')) {
                if ($native.gates.$key -cne 'BLOCKED') { throw 'INVALID_WORKER_RESPONSE' }
            }
            foreach ($key in @('sdk_imported','credential_values_read')) {
                if ($native.$key -isnot [bool] -or $native.$key) { throw 'INVALID_WORKER_RESPONSE' }
            }
            foreach ($key in @('login_attempts','broker_calls','orders_sent','cancel_requests','native_probe_attempts')) {
                if (($native.$key -isnot [int] -and $native.$key -isnot [long]) -or $native.$key -ne 0) {
                    throw 'INVALID_WORKER_RESPONSE'
                }
            }
        } elseif ($Response.schema -cne 'omi.kgi-sim.preflight.v1' -or $Response.target -cne 'REAL_SIMULATOR') {
            throw 'INVALID_WORKER_RESPONSE'
        }
    }
}

if ($MyInvocation.InvocationName -eq '.') { return }
if ($args.Count -ne 0 -or $Mode -cnotin @('Preflight','ContractTest','Probe','Send','RealSimPreflight','RealSimProbe') -or
    $TimeoutSeconds -cnotmatch '^(?:[5-9]|[1-9][0-9]|1[0-7][0-9]|180)$') {
    @{status='BLOCKED';reasonCodes=@('INVALID_LAUNCHER_ARGUMENTS');broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
    exit 2
}
$waitMilliseconds = ([int]$TimeoutSeconds) * 1000
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
# Source qualification uses the ordinary stdlib worker, not the SDK interpreter.
# Running it does not establish .venv-kgi/native ABI availability.
$worker = Join-Path $repo 'execution_kgi_simulator\worker.py'
$mutex = $null
$owned = $false
$child = $null
$exitCode = 2
$stage = 'MUTEX'
try {
    $mutex = [System.Threading.Mutex]::new($false, 'Local\OMI_KGI_OFFICIAL_SIM_QUALIFICATION_V1')
    try { $owned = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) {
        @{status='BLOCKED';reasonCodes=@('DEDICATED_WORKER_ALREADY_OWNED');broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
    } else {
        $stage = 'PROCESS_SETUP'
        foreach ($fixedPath in @($python, $worker)) {
            $item = Get-Item -LiteralPath $fixedPath -Force
            while ($null -ne $item) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_PATH_FORBIDDEN' }
                if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
            }
        }
        # No Settings import, env presence/value lookup or credentials before
        # native endpoint/egress/log/filesystem confinement has been attested.
        $presence = @{}
        $info = [System.Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $python
        $info.Arguments = '-I -S -B "' + $worker + '" ' + $Mode
        $info.WorkingDirectory = $repo
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        # .NET Framework may partially initialize its dictionary and then throw
        # on inherited PATH/Path duplicates. Clear that initialized dictionary;
        # never fall back to inheriting credentials or change the parent env.
        try { $childEnvironment = $info.get_Environment() }
        catch [System.ArgumentException] { $childEnvironment = $info.get_Environment() }
        $childEnvironment.Clear()
        foreach ($name in @('SystemRoot','WINDIR','COMSPEC')) {
            $value = [Environment]::GetEnvironmentVariable($name, 'Process')
            if ($value) { $childEnvironment[$name] = $value }
        }
        $tempRoot = Join-Path $repo '.tmp\kgi-official-simulator'
        if ($Mode -eq 'ContractTest') {
            [System.IO.Directory]::CreateDirectory($tempRoot) | Out-Null
        }
        $childEnvironment['TEMP'] = $tempRoot
        $childEnvironment['TMP'] = $tempRoot
        $child = [System.Diagnostics.Process]::new()
        $child.StartInfo = $info
        $stage = 'PROCESS_START'
        if (-not $child.Start()) { throw 'WORKER_START_FAILED' }
        $stdout = $child.StandardOutput.ReadToEndAsync()
        $stderr = $child.StandardError.ReadToEndAsync()
        $stage = 'PRESENCE_PIPE'
        $child.StandardInput.Write(($presence | ConvertTo-Json -Compress))
        $child.StandardInput.Close()
        if (-not $child.WaitForExit($waitMilliseconds)) {
            # Only this exact owned child; never enumerate/kill OMI or PAOS processes.
            $child.Kill()
            if (-not $child.WaitForExit(5000)) { throw 'OWNED_WORKER_STOP_TIMEOUT' }
            @{status='BLOCKED';reasonCodes=@('OWNED_WORKER_TIMEOUT');broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
        } else {
            $stage = 'RESPONSE_PARSE'
            $output = $stdout.GetAwaiter().GetResult()
            $diagnostic = $stderr.GetAwaiter().GetResult()
            # One outer schema, plus exactly one typed native-readiness schema
            # in REAL_SIM. Both objects are validated above. Duplicates rejected.
            foreach ($key in @('schema','mode')) {
                $expectedCount = 1
                if ($key -ceq 'schema' -and $Mode -cin @('RealSimPreflight','RealSimProbe')) { $expectedCount = 2 }
                if ([regex]::Matches($output, ('"' + $key + '"\s*:')).Count -ne $expectedCount) {
                    throw 'INVALID_WORKER_RESPONSE'
                }
            }
            $parsed = $output | ConvertFrom-Json
            Assert-KgiQualificationResponse $parsed $child.ExitCode $Mode
            # Emit the validated object, not raw JSON with duplicate-key ambiguity.
            [Console]::Out.WriteLine(($parsed | ConvertTo-Json -Depth 20 -Compress))
            if ($Mode -eq 'ContractTest' -and $child.ExitCode -eq 1) {
                [Console]::Error.WriteLine($diagnostic)
            }
            $exitCode = $child.ExitCode
        }
    }
} catch {
    $exitCode = 2
    @{status='BLOCKED';reasonCodes=@('LAUNCHER_FAILED_CLOSED');stage=$stage;error_type=$_.Exception.GetType().Name;line=$_.InvocationInfo.ScriptLineNumber;broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $child) {
        try { if (-not $child.HasExited) { $child.Kill(); $null = $child.WaitForExit(5000) } } catch {}
        $child.Dispose()
    }
    if ($owned) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
exit $exitCode
