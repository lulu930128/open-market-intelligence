# Loaded only by the existing mutex-owning launcher. Dot-sourcing defines functions only.
function New-OmiDisposableOwnedBackend {
    param([string]$OutputRoot, [string]$Python, [string]$Scenario = 'normal')
    # Disposable rehearsal of the same Runner/ASGI transport. Never projects a
    # fixture capability into RuntimeController or invokes Start-Backend.
    if (-not ('Omi.OwnedShutdown.LauncherSession' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions', 'System.Core')
    }
    $repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    return [Omi.OwnedShutdown.LauncherSession]::StartDisposable($repo, $OutputRoot, $Python, $Scenario)
}

function Get-OmiRuntimeControlUserHash {
    # HKCU belongs to the actual Launcher process account, not an interactive
    # desktop user selected by name/SID. This narrow IO seam is mocked offline.
    return [Environment]::GetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', 'User')
}

function Initialize-OmiRuntimeControlCredential {
    $inherited = [Environment]::GetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', 'Process')
    # Clear first, even if User access or Controller initialization later fails.
    # A failure to clear/set the child environment must prevent service startup.
    [Environment]::SetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', $null, 'Process')
    $hash = $null
    $state = 'source_user_missing'
    try {
        $hash = Get-OmiRuntimeControlUserHash
        if (-not [string]::IsNullOrEmpty($hash)) {
            $state = 'source_user_invalid'
            # PowerShell -match is case-insensitive; $ also accepts a final LF.
            if ($hash -cmatch '\A[0-9a-f]{64}\z') { $state = 'source_user_valid' }
        }
    } catch {
        # Never reflect registry exception text, values or account identity.
        $state = 'source_user_unavailable'
    }
    $parent = 'parent_absent'
    if (-not [string]::IsNullOrEmpty($inherited)) {
        $parent = 'parent_stale'
        if ($state -eq 'source_user_valid' -and $inherited -ceq $hash) { $parent = 'parent_matches' }
    }
    $authorization = 'disabled'
    if ($state -eq 'source_user_valid') {
        [Environment]::SetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', $hash, 'Process')
        $authorization = 'configured'
    }
    # Fixed vocabulary only. Scope is not SID disclosure or an ownership proof.
    Write-LauncherLog "Runtime credential account_scope=launcher_process_user source=hkcu_user state=$state parent=$parent authorization=$authorization"
}

function Initialize-OmiRuntimeControl {
    $script:RuntimeController = $null
    # Must precede Controller construction AND every initial service spawn.
    # Later starts inherit this same snapshot; adoption never hot-rotates it.
    Initialize-OmiRuntimeControlCredential
    try {
        Add-Type -Path @((Join-Path $PSScriptRoot 'OmiRuntimeControl.cs'), (Join-Path $PSScriptRoot 'OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions', 'System.Core', 'System.Windows.Forms')
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes($script:RepoRoot.ToLowerInvariant())
            $suffix = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant().Substring(0, 24)
        } finally { $sha.Dispose() }
        $root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "Open Market Intelligence\runtime-control\$suffix"
        # Canonical User snapshot already applied to the Launcher environment;
        # the existing service runner and Backend inherit exactly this value.
        $hash = [Environment]::GetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', 'Process')
        $script:RuntimeController = [Omi.RuntimeControl.Controller]::new($root, $hash, "omi-runtime-$suffix")
        $script:RuntimeControlStore = $root
        $script:LoadedLifecycleSourceId = Get-OmiLifecycleSourceId
        $owner = [Diagnostics.Process]::GetCurrentProcess()
        $env:OMI_RUNTIME_LAUNCHER_PID = [string]$PID
        $env:OMI_RUNTIME_LAUNCHER_CREATED = [string]$owner.StartTime.ToUniversalTime().ToFileTimeUtc()
        $script:RuntimeControlLastPublish = [DateTime]::MinValue
        Publish-OmiRuntimeControlStatus
        $script:RuntimeController.Start()
        $script:LoadedRuntimeController = $script:RuntimeController
        $script:LoadedRuntimeControllerOwnerId = $script:RuntimeController.OwnerId
    } catch {
        if ($null -ne $script:RuntimeController) { $script:RuntimeController.Dispose() }
        $script:RuntimeController = $null
        Remove-Item Env:OMI_RUNTIME_LAUNCHER_PID -ErrorAction SilentlyContinue
        Remove-Item Env:OMI_RUNTIME_LAUNCHER_CREATED -ErrorAction SilentlyContinue
        Write-LauncherLog 'Runtime control unavailable; no lifecycle authority granted.' 'WARN'
    }
}

function Get-OmiLifecycleSourceId {
    $sha = [Security.Cryptography.SHA256]::Create()
    $buffer = [IO.MemoryStream]::new()
    try {
        foreach ($name in @('scripts/omi-launcher.ps1', 'scripts/omi-runtime-control.ps1',
            'scripts/run-service-logged.ps1', 'scripts/OmiRuntimeControl.cs', 'scripts/OmiOwnedShutdown.cs', 'scripts/apply-omi-update.ps1',
            'backend/owned_backend_entry.py', 'scripts/omi-schema-maintenance.py', 'scripts/backup-omi-sqlite.py',
            'backend/alembic/env.py', '.venv/pyvenv.cfg') +
            @(Get-ChildItem -LiteralPath (Join-Path $script:RepoRoot 'backend/alembic/versions') -Filter '*.py' |
                Sort-Object Name | ForEach-Object { 'backend/alembic/versions/' + $_.Name })) {
            $bytes = [IO.File]::ReadAllBytes((Join-Path $script:RepoRoot $name))
            $hash = $sha.ComputeHash($bytes)
            $buffer.Write($hash, 0, $hash.Length)
        }
        return ([BitConverter]::ToString($sha.ComputeHash($buffer.ToArray()))).Replace('-', '').ToLowerInvariant()
    } finally { $buffer.Dispose(); $sha.Dispose() }
}

function Assert-OmiProductionBackendStartPreflight {
    # Observation only: no session/store creation, Runner, child or UI pump.
    # Cold admission calls this before its irreversible factory-attempt latch.
    if ($null -eq $script:RuntimeController) { throw 'Controller unavailable' }
    if (-not $script:OwnsMutex -or
        $script:BackendReload -or $script:IsPackagedRelease -or
        (Get-OmiLifecycleSourceId) -cne $script:LoadedLifecycleSourceId) { throw 'SOURCE_ADOPTION_NOT_ATTESTED' }
    if (@(Get-ListeningProcessIdsOnPort -Port $script:BackendPort -RequireObservation).Count -ne 0) { throw 'FIXED_PORT_NOT_FREE' }
    if (-not (Test-TcpPortBindable -Port $script:BackendPort -HostName $script:BackendHost -ServiceName 'Backend' -Quiet)) {
        throw 'FIXED_PORT_NOT_BINDABLE'
    }
}

function New-OmiProductionOwnedBackend {
    param([string]$ExpectedRelease)
    # Recheck at the factory boundary. Any failure here remains consumed/unknown
    # to the caller; a previous successful preflight is not a spawn guarantee.
    Assert-OmiProductionBackendStartPreflight
    # Cold startup does not have a successor release pin. Invoke the actual
    # four-argument overload, whose C# implementation supplies a true null.
    if (-not $PSBoundParameters.ContainsKey('ExpectedRelease')) {
        return [Omi.OwnedShutdown.ProductionSession]::Start(
            $script:RepoRoot, $script:RuntimeControlStore, $script:BackendHost, $script:BackendPort)
    }
    # Restart must never fall back to unpinned startup, even if its pin is blank.
    if ([string]::IsNullOrWhiteSpace($ExpectedRelease)) { throw 'RESTART_SOURCE_CHANGED' }
    return [Omi.OwnedShutdown.ProductionSession]::Start(
        $script:RepoRoot, $script:RuntimeControlStore, $script:BackendHost, $script:BackendPort,
        $ExpectedRelease)
}

function Get-OmiBackendApplicationRelease {
    return [Omi.OwnedShutdown.ProductionSession]::ApplicationRelease($script:RepoRoot)
}

function Get-OmiSchemaSourceRelease {
    return [Omi.OwnedShutdown.ProductionSession]::SchemaSourceRelease($script:RepoRoot)
}

function Assert-OmiBackendApplicationRelease {
    param([Parameter(Mandatory = $true)][string]$ExpectedRelease)
    if ((Get-OmiBackendApplicationRelease) -cne $ExpectedRelease) { throw 'RESTART_SOURCE_CHANGED' }
}

function Get-OmiSchemaReceiptHash {
    param([string]$Path)
    try {
        $info=[IO.FileInfo]::new($Path)
        if (-not $info.Exists -or $info.Length -gt 1048576 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) {return $null}
        $sha=[Security.Cryptography.SHA256]::Create()
        try {return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace('-','')}
        finally {$sha.Dispose()}
    } catch {return $null}
}

function Assert-OmiSchemaRecoveryAdmission {
    # A receipt never creates authority. It must match the terminal record this
    # owner persisted, plus the retained worker result; process gates run anew.
    $fence=$script:SchemaRecoveryFence
    if ($null -eq $fence) { return }
    if (-not $fence.TerminalHash -or -not (Test-Path -LiteralPath $fence.Path) -or
        (Get-OmiSchemaReceiptHash -Path $fence.Path) -cne $fence.TerminalHash -or
        (-not $fence.NoEffects -and -not $fence.WorkerSettled)) {
        throw 'SCHEMA_MAINTENANCE_RECONCILIATION_REQUIRED'
    }
}

function Assert-OmiSchemaCompatibility {
    param([Parameter(Mandatory=$true)][string]$ExpectedRelease,
        [string]$DatabasePath, [string]$SchemaLockPath, [switch]$Upgrade, [switch]$PassThru)
    Assert-OmiBackendApplicationRelease -ExpectedRelease $ExpectedRelease
    # The fixed inspector reads configured SQLite metadata only. No migration,
    # shell, data rows, repair or credential values are returned.
    $liveUrl=if ($script:OwnedBackendSession.Alive) {$script:BackendBaseUrl} else {''}
    try {
        $output=[Omi.OwnedShutdown.ProductionSession]::ReadStartCompatibility($script:RepoRoot,$liveUrl,$DatabasePath,$SchemaLockPath,[bool]$Upgrade)
        $proof=$output | ConvertFrom-Json
    } catch { throw 'RESTART_COMPATIBILITY_NOT_ATTESTED' }
    if ($proof.contract -cne 'omi.start-compatibility.v1' -or $proof.compatible -cne $true -or
        ($script:OwnedBackendSession.Alive -and ($proof.backend_pid -ne $script:OwnedBackendSession.ChildPid -or
            $proof.owner_id -cne $script:RuntimeController.OwnerId))) { throw 'RESTART_COMPATIBILITY_NOT_ATTESTED' }
    Assert-OmiBackendApplicationRelease -ExpectedRelease $ExpectedRelease
    if ($PassThru) { return $proof }
}

function Invoke-OmiLauncherCommand {
    param([ValidateSet('Status','ReadOperation','RestartBackend','StartBackend','RecoverFailedStart','SchemaUpgrade')][string]$Action,
        [Parameter(Mandatory=$true)][Diagnostics.Process]$Owner,
        [Parameter(Mandatory=$true)][string]$ExpectedOwnerId, [string]$RequestId='', [string]$Token='')
    # CC must supply its independently attested retained Launcher handle. This
    # adapter neither discovers an owner nor reads/provisions credentials.
    if (-not ('Omi.RuntimeControl.Controller' -as [type])) {
        Add-Type -Path @((Join-Path $PSScriptRoot 'OmiRuntimeControl.cs'),(Join-Path $PSScriptRoot 'OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
    }
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$suffix=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($repo.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24)}
    finally {$sha.Dispose()}
    $message=@{action=$Action;request_id=$RequestId;expected_owner_id=$ExpectedOwnerId;token=$Token}
    if ($Action -notin @('Status','ReadOperation')) {
        $message.confirmation=@{RestartBackend='restart_backend';StartBackend='start_backend';RecoverFailedStart='recover_failed_start';SchemaUpgrade='upgrade_schema'}[$Action]
    }
    return [Omi.RuntimeControl.Controller]::RequestOwner("omi-runtime-$suffix",$Owner,($message|ConvertTo-Json -Compress))
}

function Invoke-OmiRemoteControlOperation {
    param([string]$RequestId,[string]$Action)
    if (-not $script:RuntimeController.BeginRemoteOperation($RequestId)) { return }
    $verified=$false; $migration='NOT_ATTEMPTED'; $successor='NOT_ATTEMPTED'; $after=$null; $stop='NOT_ATTEMPTED'; $failure=$null
    $before=$script:OwnedBackendSession
    $factoryAttemptsBefore=[long]$script:BackendFactoryAttemptCount
    try {
        switch ($Action) {
            'StartBackend' { Invoke-BackendStartRequest -RequestId $RequestId -RemoteRequest }
            'RecoverFailedStart' { Invoke-BackendStartRequest -RequestId $RequestId -FailedStartRecovery -RemoteRequest }
            'SchemaUpgrade' { Invoke-OmiConfiguredSchemaUpgrade -RequestId $RequestId -RemoteRequest }
            default { throw 'UNSUPPORTED_ACTION' }
        }
        $after=Get-OmiOwnedBackendIdentity
        $verified=$null -ne $after -and [object]::ReferenceEquals($script:RestartReadyBackendSession,$script:OwnedBackendSession)
        if ($verified) { $successor='VERIFIED' }
    } catch {
        $failure=$_.Exception.Message
        throw
    } finally {
        if ($null -ne $before.LastStop -and $before.LastStop.RequestId -ceq $RequestId) {$stop=$before.LastStop.State}
        elseif ($null -ne $before.LastStop -and $before.LastStop.ExactExit) {$stop='PREVIOUSLY_STOPPED'}
        if ($Action -eq 'SchemaUpgrade' -and $null -ne $script:LastSchemaOperation -and
            $script:LastSchemaOperation.request_id -ceq $RequestId) {
            $migration=$script:LastSchemaOperation.migration_outcome
            $successor=$script:LastSchemaOperation.successor_outcome
        } elseif (-not $verified -and [long]$script:BackendFactoryAttemptCount -gt $factoryAttemptsBefore) {
            $successor=if ([object]::ReferenceEquals($before,$script:OwnedBackendSession)) {'ATTEMPTED_UNCONFIRMED'} else {'FAILED_UNCONFIRMED'}
        }
        Publish-OmiRuntimeControlStatus
        $script:RuntimeController.CompleteRemoteOperation($RequestId,$verified,$stop,$migration,$successor,$after,$failure)
    }
}

function Assert-OmiManualBackendStartOwner {
    # This is local tray authority inside the original owner, not a new control channel.
    if (-not $script:OwnsMutex -or $null -eq $script:Mutex -or
        $script:Mutex.SafeWaitHandle.IsClosed -or $script:Mutex.SafeWaitHandle.IsInvalid -or
        $null -eq $script:RuntimeController -or
        -not [object]::ReferenceEquals($script:RuntimeController, $script:LoadedRuntimeController) -or
        [string]::IsNullOrWhiteSpace($script:LoadedRuntimeControllerOwnerId) -or
        $script:RuntimeController.OwnerId -cne $script:LoadedRuntimeControllerOwnerId) {
        throw 'BACKEND_START_OWNER_NOT_ATTESTED'
    }
    $owned = $script:OwnedBackendSession
    # Controller initialization precedes service config. The retained session's
    # birth endpoint is the authority, including a non-default selected port.
    if ($null -eq $owned -or $owned.SelectedPort -lt 1 -or $owned.SelectedPort -gt 65535 -or
        $owned.SelectedHost -cnotin @('127.0.0.1', '::1') -or
        $script:BackendPort -ne $owned.SelectedPort -or $script:BackendHost -cne $owned.SelectedHost) {
        throw 'FIXED_ENDPOINT_CHANGED'
    }
    if ($script:BackendReload -or $script:IsPackagedRelease -or
        [string]::IsNullOrWhiteSpace($script:LoadedLifecycleSourceId) -or
        (Get-OmiLifecycleSourceId) -cne $script:LoadedLifecycleSourceId) {
        throw 'SOURCE_ADOPTION_NOT_ATTESTED'
    }
}

function Get-OmiIdentityPath {
    param([string]$Path)
    # Local absolute, canonical spelling only; reject links at every ancestor,
    # including the repo/venv and pyvenv.cfg, rather than resolving through them.
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2).Contains(':') -or
        [IO.Path]::GetFullPath($Path) -ine $Path) { throw 'IDENTITY_PATH_INVALID' }
    $cursor = $Path
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $item.FullName -ine $cursor) { throw 'IDENTITY_PATH_INVALID' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $Path
}

function Get-OmiIdentityProcess {
    param([int]$ProcessId)
    # Small OS boundary for disposable evidence tests; never a fallback for CIM.
    $process = [Diagnostics.Process]::GetProcessById($ProcessId)
    try { $null = $process.Handle; return $process }
    catch { $process.Dispose(); throw }
}

function Test-OmiCreationEvidence {
    param([DateTime]$CimTime, [DateTime]$OsTime)
    # WMI DMTF truncates FILETIME to microseconds. A millisecond tolerance can
    # accept a different observation; permit only the lost sub-microsecond ticks.
    $delta = $OsTime.ToUniversalTime().Ticks - $CimTime.ToUniversalTime().Ticks
    return $delta -ge 0 -and $delta -lt 10
}

function Get-OmiOwnedBackendIdentity {
    # A listening PID is never ownership. Bind listener -> fixed interpreter ->
    # bounded parent chain -> tracked runner -> this mutex-owning launcher.
    $processes = @()
    $records = @()
    $script:BackendOwnershipReason = 'OWNER_MUTEX_NOT_HELD'
    try {
        if (-not $script:OwnsMutex) { return $null }
        if ($null -ne $script:OwnedBackendSession) {
            $script:BackendOwnershipReason = 'OWNED_CHANNEL_IDENTITY_UNAVAILABLE'
            $owned = $script:OwnedBackendSession
            if ($script:BackendReload -or -not $owned.HasRetainedIdentity -or
                $script:BackendProcess.Id -ne $owned.RunnerProcess.Id) { return $null }
            if (-not $owned.HasRetainedIdentity -or
                -not [object]::ReferenceEquals($script:BackendProcess, $owned.RunnerProcess)) { return $null }
            $identity = [Omi.RuntimeControl.Identity]::new()
            $identity.pid = $owned.ChildPid; $identity.created_at = $owned.ChildCreated
            $script:BackendOwnershipReason = 'ATTESTED'
            return $identity
        }
        $script:BackendOwnershipReason = 'RELOAD_UNSUPPORTED'
        if ($script:BackendReload) { return $null }
        $script:BackendOwnershipReason = 'RUNNER_UNAVAILABLE'
        if ($null -eq $script:BackendProcess -or $script:BackendProcess.HasExited) { return $null }
        $runner = Get-CimInstance Win32_Process -Filter "ProcessId = $($script:BackendProcess.Id)" -ErrorAction Stop
        $runnerProcess = Get-OmiIdentityProcess $script:BackendProcess.Id
        $processes += $runnerProcess
        $records += $runner
        $script:BackendOwnershipReason = 'RUNNER_IDENTITY_MISMATCH'
        if ($null -eq $runner -or $runner.ProcessId -ne $script:BackendProcess.Id -or $runner.ParentProcessId -ne $PID -or
            $runnerProcess.HasExited -or $null -eq $runner.CreationDate -or
            $runnerProcess.StartTime.ToUniversalTime() -ne $script:BackendProcess.StartTime.ToUniversalTime() -or
            $runnerProcess.StartTime.ToUniversalTime() -lt [Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime() -or
            -not (Test-OmiCreationEvidence $runner.CreationDate $runnerProcess.StartTime)) { return $null }
        $script:BackendOwnershipReason = 'LISTENER_NOT_UNIQUE'
        $listeners = @(Get-ListeningProcessIdsOnPort -Port $script:BackendPort)
        if ($listeners.Count -ne 1) { return $null }
        $chain = @()
        $nextId = [int]$listeners[0]
        # Fixed shapes below use at most three nodes below runner. The fourth
        # observation detects an unsupported supervisor/worker without widening it.
        for ($hop = 0; $hop -lt 4; $hop++) {
            $script:BackendOwnershipReason = 'PROCESS_EVIDENCE_UNAVAILABLE'
            $node = Get-CimInstance Win32_Process -Filter "ProcessId = $nextId" -ErrorAction Stop
            if ($null -eq $node -or $node.ProcessId -ne $nextId -or $null -eq $node.CreationDate -or
                $nextId -le 0 -or $nextId -eq $PID -or $nextId -in $records.ProcessId) { return $null }
            $process = Get-OmiIdentityProcess $nextId
            $processes += $process
            $records += $node
            $script:BackendOwnershipReason = 'PROCESS_IDENTITY_MISMATCH'
            if ($process.HasExited -or $process.Id -ne $nextId -or
                -not (Test-OmiCreationEvidence $node.CreationDate $process.StartTime)) { return $null }
            $script:BackendOwnershipReason = 'PROCESS_CREATION_ORDER_INVALID'
            if ($process.StartTime.ToUniversalTime() -lt $runnerProcess.StartTime.ToUniversalTime() -or
                ($chain.Count -gt 0 -and $process.StartTime.ToUniversalTime() -gt $processes[$processes.Count - 2].StartTime.ToUniversalTime())) { return $null }
            $chain += $node
            if ($node.ParentProcessId -eq $runner.ProcessId) { break }
            $nextId = [int]$node.ParentProcessId
        }
        $script:BackendOwnershipReason = 'ANCESTRY_UNSUPPORTED'
        if ($chain[-1].ParentProcessId -ne $runner.ProcessId) { return $null }
        $script:BackendOwnershipReason = 'INTERPRETER_PATH_MISMATCH'
        $expected = Get-OmiIdentityPath (Get-ExpectedBackendPython)
        $paths = @($chain | ForEach-Object { Get-OmiIdentityPath $_.ExecutablePath })
        $pythonCount = $chain.Count
        if ($paths[-1] -ieq (Join-Path $env:SystemRoot 'System32\cmd.exe')) { $pythonCount-- }
        $script:BackendOwnershipReason = 'ANCESTRY_UNSUPPORTED'
        if ($pythonCount -lt 1 -or $pythonCount -gt 2) { return $null }
        for ($index = 0; $index -lt $pythonCount; $index++) {
            $script:BackendOwnershipReason = 'PROCESS_EVIDENCE_UNAVAILABLE'
            if ([string]::IsNullOrWhiteSpace($chain[$index].CommandLine)) { return $null }
            $script:BackendOwnershipReason = 'WORKER_MODE_UNSUPPORTED'
            if ($chain[$index].CommandLine -match '(?i)(?:^|[\s"''])--(?:reload|workers)(?:[=\s"'']|$)') { return $null }
        }
        $script:BackendOwnershipReason = 'INTERPRETER_PATH_MISMATCH'
        if ($paths[$pythonCount - 1] -ine $expected) { return $null }
        $venvConfigPath = $null
        $venvConfigText = $null
        if ($pythonCount -eq 2) {
            # Only a repo venv redirector may delegate to its configured base.
            # Packaged Python keeps its own-path support, never this exception.
            if ($script:IsPackagedRelease -or $expected -ine (Join-Path $script:RepoRoot '.venv\Scripts\python.exe')) { return $null }
            $script:BackendOwnershipReason = 'VENV_CONFIG_INVALID'
            $venvConfigPath = Get-OmiIdentityPath (Join-Path $script:RepoRoot '.venv\pyvenv.cfg')
            if ((Get-Item -LiteralPath $venvConfigPath -ErrorAction Stop).Length -gt 16384) { return $null }
            $venvConfigText = Get-Content -LiteralPath $venvConfigPath -Encoding UTF8 -Raw -ErrorAction Stop
            $entries = @($venvConfigText -split '\r?\n' | Where-Object { $_ -match '^\s*executable\s*=' })
            if ($entries.Count -ne 1) { return $null }
            $base = Get-OmiIdentityPath (($entries[0] -split '=', 2)[1].Trim())
            if ($base -ieq $expected -or $paths[0] -ine $base) { return $null }
        }
        $script:BackendOwnershipReason = 'BACKEND_COMMAND_MISMATCH'
        for ($index = 0; $index -lt $pythonCount; $index++) {
            $argv = [Omi.RuntimeControl.ProcessEvidence]::Arguments($chain[$index].CommandLine)
            if ($argv.Count -ne 8 -or $argv[0] -ine $expected -or
                $argv[1] -cne '-m' -or $argv[2] -cne 'uvicorn' -or $argv[3] -cne 'app.main:app' -or
                $argv[4] -cne '--host' -or $argv[5] -cne $script:BackendHost -or
                $argv[6] -cne '--port' -or $argv[7] -cne [string]$script:BackendPort) { return $null }
        }
        # Re-observe the same bounded records and handles before publishing; PID
        # reuse, a departed intermediate or a changed listener invalidates proof.
        $script:BackendOwnershipReason = 'PROCESS_EVIDENCE_CHANGED'
        for ($index = 0; $index -lt $records.Count; $index++) {
            $record = $records[$index]
            $again = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.ProcessId)" -ErrorAction Stop
            $processes[$index].Refresh()
            if ($processes[$index].HasExited -or $null -eq $again -or $again.ProcessId -ne $record.ProcessId -or
                $again.ParentProcessId -ne $record.ParentProcessId -or $again.CreationDate -ne $record.CreationDate -or
                $again.ExecutablePath -ine $record.ExecutablePath -or $again.CommandLine -cne $record.CommandLine) { return $null }
        }
        $listenersAgain = @(Get-ListeningProcessIdsOnPort -Port $script:BackendPort)
        if ($listenersAgain.Count -ne 1 -or $listenersAgain[0] -ne $listeners[0]) { return $null }
        if (-not $script:OwnsMutex -or $script:BackendReload -or $script:BackendProcess.HasExited -or
            $script:BackendProcess.Id -ne $runner.ProcessId -or
            $script:BackendProcess.StartTime.ToUniversalTime() -ne $runnerProcess.StartTime.ToUniversalTime()) { return $null }
        foreach ($path in $paths) { $null = Get-OmiIdentityPath $path }
        if ($null -ne $venvConfigPath) {
            $null = Get-OmiIdentityPath $venvConfigPath
            if ((Get-Content -LiteralPath $venvConfigPath -Encoding UTF8 -Raw -ErrorAction Stop) -cne $venvConfigText) { return $null }
        }
        $childProcess = $processes[1]
        $identity = [Omi.RuntimeControl.Identity]::new()
        $identity.pid = [int]$chain[0].ProcessId
        $identity.created_at = $childProcess.StartTime.ToUniversalTime().ToString('o')
        $script:BackendOwnershipReason = 'ATTESTED'
        return $identity
    } catch {
        # Only the fixed stage code crosses the status boundary. Never exception
        # text, paths, command lines, provider data or credentials.
        return $null
    } finally {
        foreach ($process in $processes) {
            if ($null -ne $process) { try { $process.Dispose() } catch { } }
        }
    }
}

function Test-OmiRemoteRestartGeneration {
    # The legacy recovery fence is sticky. Only a fully verified successor
    # session may admit fresh remote intent after a stop attempt.
    $owned = $script:OwnedBackendSession
    return ($null -ne $owned -and $owned.Alive -and -not $owned.Terminal -and
        -not $script:LastBackendStartError -and (-not $script:SafeStopAttempted -or
        [object]::ReferenceEquals($owned, $script:RestartReadyBackendSession)))
}

function Publish-OmiRuntimeControlStatus {
    if ($null -eq $script:RuntimeController) { return }
    $identity = Get-OmiOwnedBackendIdentity
    $owner = [Diagnostics.Process]::GetCurrentProcess()
    $backend = @{ status = 'unknown'; identity = 'UNATTESTED'; pid = $null; created_at = $null
        ownership_reason = $script:BackendOwnershipReason
        selected_host = $script:BackendHost; selected_port = $script:BackendPort; readiness = 'UNATTESTED' }
    if ($null -ne $identity) {
        $backend.status = 'observed'; $backend.identity = 'PROCESS_IDENTITY'
        $backend.pid = $identity.pid; $backend.created_at = $identity.created_at
    }
    $owned = $script:OwnedBackendSession
    if ($null -ne $owned -and $owned.StartupFailure) { $null = $owned.RefreshStartupExit() }
    if ($null -ne $owned -and $owned.Terminal -and (-not $owned.HasRetainedIdentity -or
        ($null -ne $owned.LastStop -and ($owned.LastStop.ExactExit -or $owned.LastStop.ForcedExitConfirmed)))) {
        # A retained exit receipt describes this owned instance, never whatever
        # might later occupy its port. Terminal ambiguity grants no live owner.
        $identity = $null
        $backend.status = 'unknown'; $backend.identity = 'UNATTESTED'
        $backend.pid = $null; $backend.created_at = $null
        $backend.ownership_reason = 'OWNED_TERMINAL_UNKNOWN'
        if ($owned.StartupExitConfirmed -or ($null -ne $owned.LastStop -and $owned.LastStop.ExactExit -and
            $owned.LastStop.State -eq 'stopped' -and $owned.LastStop.Reason -eq 'LIFESPAN_AND_EXACT_EXIT')) {
            $backend.status = 'stopped'; $backend.identity = 'RETAINED_EXACT_EXIT'
            $backend.ownership_reason = $(if ($owned.StartupExitConfirmed) { 'OWNED_START_EXIT_CONFIRMED' } else { 'LIFESPAN_AND_EXACT_EXIT' })
        }
    }
    elseif ($null -ne $owned -and $script:LastBackendStartError) {
        # The new owner is retained even when its readiness could not be proved.
        # Never publish the retired session's stopped state as the new outcome.
        $backend.status = 'unknown'
        $backend.ownership_reason = 'OWNED_START_READINESS_UNCONFIRMED'
    }
    $blockers = @()
    if ($script:ServiceStopInProgress -or $script:ServiceStartRequestInProgress) { $blockers += 'BUSY' }
    if ($null -eq $identity) { $blockers += 'OWNER_NOT_ATTESTED' }
    elseif ($null -eq $script:OwnedBackendSession) { $blockers += 'OWNED_BOOTSTRAP_REQUIRED' }
    if ($null -ne $owned -and ($owned.Terminal -or $owned.StartupFailure -or $script:LastBackendStartError)) {
        $blockers += 'READINESS_NOT_ATTESTED'
    }
    $status = @{
        observed_at = [DateTime]::UtcNow.ToString('o')
        loaded_lifecycle_source_id = $script:LoadedLifecycleSourceId
        application_release_id = $(if ($null -ne $owned) { $owned.ReleaseId } else { $null })
        launcher = @{ status = 'observed'; identity = 'PIPE_SERVER_PID_AND_CREATION'; pid = $PID; created_at = $owner.StartTime.ToUniversalTime().ToString('o') }
        backend = $backend
        frontend = @{ status = 'unknown'; identity = 'UNATTESTED'; pid = $null; created_at = $null
            selected_host = $script:FrontendHost; selected_port = $script:FrontendPort; readiness = 'UNATTESTED' }
        mcp_dependency = @{ status = 'unknown'; identity = 'UNATTESTED'; reason = 'EXTERNAL_ADAPTER_NOT_ATTESTED' }
        restart = @{ available = ($blockers.Count -eq 0); reason = $(if ($blockers.Count) { $blockers[0] } else { 'AUTHENTICATED_REMOTE_INTENT_REQUIRED' })
            blockers = $blockers; approval = 'authenticated_remote_intent'; writer_drain = 'graceful_then_owned_cutoff_180s' }
    }
    $script:RuntimeController.Publish(($status | ConvertTo-Json -Depth 6 -Compress), $identity, ($null -ne $identity))
    $script:RuntimeControlLastPublish = [DateTime]::UtcNow
}

function Restart-Backend {
    param([Parameter(Mandatory = $true)][string]$RequestId)
    if ($null -eq $script:OwnedBackendSession) {
        $script:RuntimeController.BlockOwnedRestart($RequestId, 'OWNED_BOOTSTRAP_REQUIRED'); return
    }
    Invoke-OwnedBackendRestart -RequestId $RequestId -RemoteRequest
}

function Invoke-OmiRuntimeControlTick {
    if ($null -eq $script:RuntimeController) { return }
    try {
        if (([DateTime]::UtcNow - $script:RuntimeControlLastPublish).TotalSeconds -ge 5) { Publish-OmiRuntimeControlStatus }
        # Publication continues after Stop. Never dequeue/replay a destructive
        # request while this retained session is stopped, unknown or terminal.
        if ($script:ServiceStopInProgress -or $script:ServiceStartRequestInProgress) { return }
        $requestId = $script:RuntimeController.TakePending()
        if ($null -ne $requestId) {
            $action=$script:RuntimeController.PendingAction($requestId)
            if ($action -eq 'RestartBackend') { Restart-Backend -RequestId $requestId }
            else { Invoke-OmiRemoteControlOperation -RequestId $requestId -Action $action }
        }
    } catch {
        # Receipt persistence or proof failures never fall through to a legacy action.
        Write-LauncherLog 'Runtime control tick failed closed; receipt may be unknown.' 'WARN'
    }
}
