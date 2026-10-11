<#
.SYNOPSIS
KGI simulator qualification ONLY. No production login, actual probe or order is
enabled in this release. Exit 0: offline tests passed; 1: failed; 2: BLOCKED.
Preflight reads fixed SDK source/metadata and dedicated secret presence only.
ContractTest uses a closed local fake. Probe/Send fail closed until reviewed
broker environment/account/CA/entitlement/transport proof exists in source.
#>
param(
    [ValidateSet('Preflight', 'ContractTest', 'Probe', 'Send')]
    [string]$Mode = 'Preflight',
    [ValidateRange(5, 180)]
    [int]$TimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
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
        $presence = @{}
        foreach ($name in @('KGI_SIM_PERSON_ID','KGI_SIM_PASSWORD','KGI_SIM_ACCOUNT')) {
            # Presence only. Never copy credentials into child environment or arguments.
            $presence[$name] = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))
        }
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
        [System.IO.Directory]::CreateDirectory($tempRoot) | Out-Null
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
        if (-not $child.WaitForExit($TimeoutSeconds * 1000)) {
            # Only this exact owned child; never enumerate/kill OMI or PAOS processes.
            $child.Kill()
            $child.WaitForExit()
            @{status='BLOCKED';reasonCodes=@('OWNED_WORKER_TIMEOUT');broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
        } else {
            $stage = 'RESPONSE_PARSE'
            $output = $stdout.GetAwaiter().GetResult()
            $diagnostic = $stderr.GetAwaiter().GetResult()
            $parsed = $output | ConvertFrom-Json
            if ($parsed.status -notin @('PASS','FAIL','BLOCKED')) { throw 'INVALID_WORKER_RESPONSE' }
            [Console]::Out.WriteLine($output.Trim())
            if ($Mode -eq 'ContractTest' -and $child.ExitCode -eq 1) {
                [Console]::Error.WriteLine($diagnostic)
            }
            $exitCode = $child.ExitCode
        }
    }
} catch {
    @{status='BLOCKED';reasonCodes=@('LAUNCHER_FAILED_CLOSED');stage=$stage;error_type=$_.Exception.GetType().Name;line=$_.InvocationInfo.ScriptLineNumber;broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $child) {
        try { if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit() } } catch {}
        $child.Dispose()
    }
    if ($owned) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
exit $exitCode
