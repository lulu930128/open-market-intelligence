# Private implementation of run-service-logged.ps1's opt-in rehearsal branch.
# Not a lifecycle entrypoint: no arbitrary child, existing PID, port or restart.
Set-StrictMode -Version Latest

function Assert-OmiPrivateDirectory {
    param([string]$Path, [Security.Principal.SecurityIdentifier]$Sid)
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'IPC reparse point rejected' }
    $acl = $item.GetAccessControl()
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $Sid.Value -or $rules.Count -ne 1) {
        throw 'IPC private ACL unverified'
    }
    $rule = $rules[0]
    if ($rule.IdentityReference.Value -ne $Sid.Value -or $rule.AccessControlType -ne 'Allow' -or
        $rule.FileSystemRights -ne 'FullControl' -or $rule.InheritanceFlags -ne 'ContainerInherit, ObjectInherit') {
        throw 'IPC ACL unexpected grant'
    }
    return $acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::All)
}

function Write-OmiFixtureMessage {
    param([string]$Path, $Value)
    # New immutable names only; publication is a same-directory atomic rename.
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temporary, $Path)
}

function Read-OmiFixtureMessage {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 16384) { throw 'Invalid IPC file' }
    return [IO.File]::ReadAllText($Path) | ConvertFrom-Json
}

function Test-OmiFixtureIdentity {
    param($Message, $Identity)
    foreach ($key in @('instance', 'runner_pid', 'runner_start', 'child_pid', 'child_start', 'deadline_utc', 'request_id')) {
        if ($null -eq $Message.PSObject.Properties[$key] -or [string]$Message.$key -cne [string]$Identity.$key) { return $false }
    }
    return $true
}

function Invoke-OmiGracefulStopFixture {
    param([string]$OutputRoot, [string]$Python, [string]$Scenario, [switch]$Uvicorn)
    if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'Windows transport unavailable' }
    $repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $allowed = [IO.Path]::GetFullPath((Join-Path $repository '.tmp')) + [IO.Path]::DirectorySeparatorChar
    $directory = [IO.Path]::GetFullPath($OutputRoot)
    if ($Uvicorn -and -not $directory.StartsWith(
        (Join-Path $allowed 'us-r1-b4-disposable-20261011') + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) { throw 'B4 task-private fixture root required' }
    if (-not $directory.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $directory)) {
        throw 'Fresh disposable directory under repository .tmp required; recovery/rearm refused'
    }
    $ancestor = [IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName($directory))
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Linked ancestor rejected' }
        $ancestor = $ancestor.Parent
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Fixture interpreter missing' }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($sid)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    $null = [IO.Directory]::CreateDirectory($directory, $acl)
    $sddl = Assert-OmiPrivateDirectory $directory $sid
    $instance = [guid]::NewGuid().ToString('N')
    $self = Get-Process -Id $PID -ErrorAction Stop
    $runnerStart = $self.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
    $fixture = Join-Path $repository 'backend\tests\fixtures\r1e_stop_child.py'
    $sourceHashes = @{}
    if ($Uvicorn) {
        $fixture = Join-Path $repository 'backend\tests\fixtures\b4_lifespan_child.py'
        foreach ($relative in @('backend/app/runtime.py', 'backend/app/runtime_admission.py', 'backend/app/db/session.py',
            'backend/app/jobs/us_intraday_materializer_scheduler.py', 'backend/tests/fixtures/r1e_stop_child.py',
            'backend/tests/fixtures/b4_lifespan_child.py', 'scripts/run-service-logged.ps1',
            'scripts/omi-graceful-stop-fixture.ps1')) {
            $sourceHashes[$relative] = (Get-FileHash -LiteralPath (Join-Path $repository $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        Write-OmiFixtureMessage (Join-Path $directory 'source.json') $sourceHashes
    }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Python
    # All arguments are fixed or Windows paths (quotes cannot occur in paths).
    $start.Arguments = '-I -S "' + $fixture + '" "' + $directory + '" ' + $instance + ' ' + $PID + ' ' + $runnerStart + ' ' + $Scenario
    if ($Uvicorn) { $start.Arguments = '-B ' + $start.Arguments }
    $start.WorkingDirectory = $directory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $child = [Diagnostics.Process]::new()
    $child.StartInfo = $start
    $stopIntent = $false
    $result = [ordered]@{ scope='DISPOSABLE_WINDOWS_ONLY'; scenario=$Scenario; formal_R1='BLOCKED'; verdict='BLOCKED'; reason='IDENTITY_UNKNOWN'; instance=$instance; acl_sddl=$sddl; stop_intent_latched=$false; respawn_inhibited=$true; force_fallback=$false; child_starts=0; exact_exit=$false; exit_code=$null; exit_utc=$null; exit_observed_utc=$null; launched_identity=$null; identity=$null; ack=$null }
    if ($Uvicorn) { $result.scope = 'B4_SOURCE_FIXTURE_ONLY'; $result.source_hashes = $sourceHashes }
    try {
        if (-not $child.Start()) { throw 'Child start failed' }
        $result.child_starts = 1
        # Retain the OS process handle; never reopen a PID to establish exit.
        $null = $child.Handle
        $childStart = $child.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
        $result.launched_identity = @{ child_pid=$child.Id; child_start=$childStart }
        if ($Uvicorn) {
            $executable = $child.MainModule.FileName
            if ($executable -ine [IO.Path]::GetFullPath($Python)) { throw 'Exact child executable mismatch' }
            $result.launched_identity.executable = $executable
            $result.launched_identity.executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
            $result.launched_identity.argv = $start.Arguments
        }
        $readyPath = Join-Path $directory 'ready.json'
        $clock = [Diagnostics.Stopwatch]::StartNew()
        while (-not (Test-Path -LiteralPath $readyPath) -and -not $child.HasExited -and $clock.Elapsed.TotalSeconds -lt 5) { Start-Sleep -Milliseconds 10 }
        if (-not (Test-Path -LiteralPath $readyPath)) { throw 'Child identity unavailable' }
        $ready = Read-OmiFixtureMessage $readyPath
        if ($ready.child_pid -ne $child.Id -or $ready.child_start -cne $childStart -or $ready.instance -cne $instance) { throw 'Child OS identity mismatch' }
        if ($Uvicorn -and $Scenario -eq 'parent-disappearance') { [Environment]::Exit(77) }
        $identity = [pscustomobject]@{ instance=$instance; runner_pid=$PID; runner_start=$runnerStart; child_pid=$child.Id; child_start=$childStart; deadline_utc=[DateTime]::UtcNow.AddSeconds(2).ToString('o'); request_id=[guid]::NewGuid().ToString('N') }
        $result.identity = $identity
        # Terminal latch BEFORE durable intent and signal. This branch has no
        # recovery loop; a later invocation rejects this directory unconditionally.
        $stopIntent = $true
        $result.stop_intent_latched = $true
        Write-OmiFixtureMessage (Join-Path $directory 'stop-intent.json') $identity
        if ($Scenario -eq 'runner-crash') { [Environment]::Exit(77) } # abrupt own fixture runner loss; bypass finally
        $null = Assert-OmiPrivateDirectory $directory $sid
        if ($child.HasExited -or $child.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -cne $childStart) { throw 'Exact child no longer alive' }
        $request = $identity
        if ($Uvicorn -and $Scenario.StartsWith('request-')) {
            $request = $identity | ConvertTo-Json | ConvertFrom-Json
            switch ($Scenario) {
                'request-wrong-pid' { $request.child_pid += 1 }
                'request-wrong-start' { $request.child_start = '0' }
                'request-wrong-token' { $request.request_id = 'wrong' }
                'request-expired' { $request.deadline_utc = [DateTime]::UtcNow.AddSeconds(-1).ToString('o') }
                'request-wrong-runner' { $request.runner_pid += 1 }
            }
        }
        if (-not ($Uvicorn -and $Scenario -eq 'orphan')) {
            Write-OmiFixtureMessage (Join-Path $directory 'request.json') $request
        }
        if ($Scenario -eq 'double-signal') { Write-OmiFixtureMessage (Join-Path $directory 'request-duplicate.json') $identity }
        $clock.Restart()
        $ackPath = Join-Path $directory 'ack.json'
        $result.reason = 'DEADLINE_EXCEEDED'
        while ($clock.Elapsed.TotalSeconds -lt 2 -and [DateTime]::UtcNow -lt [DateTime]::Parse($identity.deadline_utc).ToUniversalTime()) {
            if ($child.HasExited) {
                $result.exact_exit = $true
                $result.exit_code = $child.ExitCode
                $result.exit_utc = $child.ExitTime.ToUniversalTime().ToString('o')
                $result.exit_observed_utc = [DateTime]::UtcNow.ToString('o')
                if ($child.ExitCode -ne 0) { $result.reason = 'UNCLEAN_EXIT'; break }
                if (-not (Test-Path -LiteralPath $ackPath)) { $result.reason = 'MISSING_ACK'; break }
                $null = Assert-OmiPrivateDirectory $directory $sid
                $ack = Read-OmiFixtureMessage $ackPath
                $result.ack = $ack
                if (-not (Test-OmiFixtureIdentity $ack $identity)) { $result.reason = 'ACK_IDENTITY_MISMATCH'; break }
                if ($Uvicorn) {
                    if (-not (Test-OmiLifespanReceipt $ack $sourceHashes)) { $result.reason = 'INCOMPLETE_LIFESPAN_OR_OWNER_DRAIN'; break }
                    foreach ($relative in $sourceHashes.Keys) {
                        if ((Get-FileHash -LiteralPath (Join-Path $repository $relative) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sourceHashes[$relative]) {
                            throw 'SOURCE_DRIFT'
                        }
                    }
                }
                elseif ($ack.forced -isnot [bool] -or $ack.forced -ne $false -or $ack.drain.state -cne 'FIXTURE_DRAINED' -or
                    $ack.drain.worker_joined -isnot [bool] -or $ack.drain.admission_closed -isnot [bool] -or
                    $ack.drain.worker_joined -ne $true -or $ack.drain.admission_closed -ne $true -or
                    $ack.drain.accepted -lt 1 -or $ack.drain.accepted -ne $ack.drain.completed -or
                    $ack.drain.stop_count -ne 1) { $result.reason = 'INCOMPLETE_OR_FORCED_DRAIN'; break }
                if ($clock.Elapsed.TotalSeconds -ge 2 -or [DateTime]::UtcNow -ge [DateTime]::Parse($identity.deadline_utc).ToUniversalTime()) { $result.reason = 'DEADLINE_EXCEEDED'; break }
                $result.verdict = 'PASS_FIXTURE_ONLY'
                $result.reason = 'IDENTITY_ACK_DRAIN_EXACT_EXIT'
                break
            }
            Start-Sleep -Milliseconds 10
        }
    }
    catch { $result.reason = $_.Exception.Message }
    finally {
        # No termination, retries or respawn, even on protocol/ACL/deadline error.
        # The fixture has its own finite lease; expiration is never a drain ACK.
        if ($Uvicorn -and $Scenario -eq 'orphan' -and $result.child_starts -eq 1) {
            $result.orphan_exit_observed = $child.WaitForExit(8000)
            # A late self-expiration must never upgrade the terminal verdict.
        }
        $child.Dispose()
        Write-OmiFixtureMessage (Join-Path $directory 'verdict.json') $result
    }
    if ($result.verdict -eq 'PASS_FIXTURE_ONLY' -and $stopIntent) { return 0 }
    return 79
}

function Test-OmiLifespanReceipt {
    param($Ack, $Hashes)
    # Typed, complete receipt only. Missing fields throw under StrictMode and
    # are converted to a terminal BLOCKED by the existing runner owner.
    if ($Ack.forced -isnot [bool] -or $Ack.forced -or
        $Ack.lifespan_complete -isnot [bool] -or -not $Ack.lifespan_complete -or
        $Ack.server_returned -isnot [bool] -or -not $Ack.server_returned -or
        $Ack.workers_exited -isnot [bool] -or -not $Ack.workers_exited -or
        $Ack.scope -cne 'B4_SOURCE_FIXTURE_ONLY' -or $Ack.stop_count -ne 1 -or
        $Ack.stop_count -isnot [int] -or
        $Ack.drain.state -cne 'REGISTERED_DRAINED' -or
        $Ack.drain.background_leader -isnot [bool] -or $Ack.drain.background_leader -or
        $Ack.drain.background_ownership_retained -isnot [bool] -or $Ack.drain.background_ownership_retained -or
        $Ack.drain.scheduler_state -cne 'not_owned' -or $null -ne $Ack.drain.scheduler_admission_stopped -or
        $Ack.drain.collectors -isnot [pscustomobject] -or @($Ack.drain.collectors.PSObject.Properties).Count -ne 0 -or
        $Ack.drain.all_writers_drained -isnot [bool] -or $Ack.drain.all_writers_drained -or
        $Ack.drain.unknown_writers -isnot [Array] -or
        @($Ack.drain.unknown_writers).Count -eq 0 -or
        $Ack.drain.job_executor_state -cne 'drained' -or
        $Ack.drain.jobs.drained -isnot [bool] -or -not $Ack.drain.jobs.drained -or
        $Ack.drain.sessions.state -cne 'drained' -or
        $Ack.drain.sessions.admission_closed -isnot [bool] -or -not $Ack.drain.sessions.admission_closed -or
        $Ack.drain.sessions.all_writers_drained -isnot [bool] -or $Ack.drain.sessions.all_writers_drained -or
        $Ack.drain.sessions.evidence_scope -cne 'explicit_session_scopes_only' -or
        $Ack.drain.sessions.active_owners -isnot [Array] -or @($Ack.drain.sessions.active_owners).Count -ne 0 -or
        $Ack.drain.sessions.uncertain_owners -isnot [Array] -or @($Ack.drain.sessions.uncertain_owners).Count -ne 0 -or
        $Ack.drain.sessions.pending_constructors -isnot [int] -or $Ack.drain.sessions.pending_constructors -ne 0 -or
        $Ack.drain.sessions.close_failures -isnot [int] -or $Ack.drain.sessions.close_failures -ne 0 -or
        $Ack.drain.publisher.state -cne 'drained' -or
        $Ack.drain.publisher.admission_closed -isnot [bool] -or -not $Ack.drain.publisher.admission_closed -or
        $Ack.drain.publisher.retained_symbols -isnot [Array] -or
        @($Ack.drain.publisher.retained_symbols).Count -ne 0 -or
        $Ack.drain.publisher.unclosed_sessions -isnot [Array] -or
        @($Ack.drain.publisher.unclosed_sessions).Count -ne 0 -or
        $Ack.drain.publisher.unknown_symbols -isnot [Array] -or @($Ack.drain.publisher.unknown_symbols).Count -ne 0 -or
        $Ack.drain.publisher.completed -isnot [int] -or $Ack.drain.publisher.completed -ne 1 -or
        $Ack.drain.publisher.ownership_failures -isnot [int] -or $Ack.drain.publisher.ownership_failures -ne 0 -or
        $Ack.unknown_fixture_work -isnot [bool] -or $Ack.unknown_fixture_work) { return $false }
    foreach ($relative in $Hashes.Keys) {
        if ($Ack.source_hashes.$relative -cne $Hashes[$relative]) { return $false }
    }
    return $true
}
