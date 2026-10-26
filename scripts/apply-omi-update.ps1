param([ValidateSet(180)][int]$TimeoutSeconds = 180)

$ErrorActionPreference = 'Stop'

function Get-OmiCutoffSnapshot {
    return @(Get-CimInstance Win32_Process -OperationTimeoutSec 3 -ErrorAction Stop |
        Select-Object ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine)
}

function Test-OmiCutoffCreation($Left, $Right) {
    $delta = $Right.ToUniversalTime().Ticks - $Left.ToUniversalTime().Ticks
    return ($delta -ge 0 -and $delta -lt 10)
}

function Get-OmiScopedChildRole {
    param($Row, $Parent, $Identity)
    $command=[string]$Row.CommandLine
    $repoPattern=[regex]::Escape($Identity.Repo)
    if($Parent.Role -eq 'launcher'){
        $shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        if($Row.ExecutablePath -ine $shell -or
            $command -notmatch ('(?i)\s-File\s+"'+$repoPattern+'\\scripts\\run-service-logged\.ps1"(?:\s|$)') -or
            $command -notmatch ('(?i)\s-RepoRoot\s+"'+$repoPattern+'"(?:\s|$)') -or
            $command -notmatch ('(?i)\s-LauncherPid\s+'+$Identity.Pid+'(?:\s|$)')){return $null}
        foreach($service in @('backend','frontend')){
            if($command -match ('(?i)\s-ServiceName\s+"?'+$service+'"?(?:\s|$)') -and
                $command -match ('(?i)\s-WorkingDirectory\s+"'+$repoPattern+'\\'+$service+'"(?:\s|$)')){return ($service+'_runner')}
        }
        return $null
    }
    $exe=[IO.Path]::GetFileName([string]$Row.ExecutablePath)
    if($Parent.Role -in @('backend_runner','backend_app')){
        if($exe -ieq 'python.exe' -and ($command -match ($repoPattern+'\\backend\\owned_backend_entry\.py') -or
            $command -match '(?i)\s-m\s+uvicorn\s+app\.main:app(?:\s|$)')){return 'backend_app'}
        if($exe -ieq 'cmd.exe' -and $command -match ($repoPattern+'\\\.venv\\Scripts\\python\.exe') -and
            $command -match '(?i)uvicorn\s+app\.main:app'){return 'backend_app'}
        return $null
    }
    if($Parent.Role -in @('frontend_runner','frontend_app')){
        if($exe -ieq 'cmd.exe' -and ($command -match '(?i)npm(?:\.cmd)?"?\s+run\s+dev(?:\s|$)' -or
            $command -match '(?i)(?:^|\s|\")next\s+dev(?:\s|$)')){return 'frontend_app'}
        if($exe -ieq 'node.exe' -and ($command -match '(?i)npm-cli\.js"?\s+run\s+dev(?:\s|$)' -or
            $command -match ($repoPattern+'[\\/]+frontend[\\/].*(?:next|server\.js)') -or
            $command -match '(?i)next[\\/]dist[\\/](?:bin[\\/]next|server[\\/]lib[\\/]start-server\.js)' -or
            $command -match '^next-server \(v[0-9.]+\)$')){return 'frontend_app'}
    }
    return $null
}

function Get-OmiUpdateOwner {
    param([string]$Repo)
    $entry = Join-Path $Repo 'scripts\omi-launcher.ps1'
    $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    # The VBS's exact -File target, not a process name, port or substring match.
    $rows = @(Get-OmiCutoffSnapshot)
    $owners = @($rows | Where-Object {
        $_.ExecutablePath -ieq $exe -and $_.CommandLine -match ('(?i)\s-File\s+"' + [regex]::Escape($entry) + '"\s*$')
    })
    if ($owners.Count -ne 1) { throw 'UPDATE_EXACT_OWNER_NOT_ATTESTED' }
    $row = $owners[0]
    $process = [Diagnostics.Process]::GetProcessById([int]$row.ProcessId)
    $null = $process.Handle
    if ($process.HasExited -or -not (Test-OmiCutoffCreation $row.CreationDate $process.StartTime)) {
        $process.Dispose(); throw 'UPDATE_EXACT_OWNER_NOT_ATTESTED'
    }
    $identity = [pscustomobject]@{ Process=$process; Pid=$process.Id; Created=$process.StartTime.ToUniversalTime();
        CommandLine=$row.CommandLine; ExecutablePath=$row.ExecutablePath; Nodes=@(); Repo=$Repo; RootRole='launcher' }
    $identity.Nodes = @(Get-OmiCutoffTree -Identity $identity -Rows $rows)
    return $identity
}

function Get-OmiCutoffTree {
    param($Identity, [object[]]$Rows)
    if ($Identity.Process.Id -ne $Identity.Pid -or $Identity.Process.StartTime.ToUniversalTime() -ne $Identity.Created) {
        throw 'UPDATE_OWNER_GENERATION_MISMATCH'
    }
    $root = @($Rows | Where-Object { $_.ProcessId -eq $Identity.Pid })
    if ($Identity.Process.HasExited) { return @($Identity.Nodes) }
    if ($root.Count -ne 1 -or $root[0].CommandLine -cne $Identity.CommandLine -or
        $root[0].ExecutablePath -ine $Identity.ExecutablePath -or
        -not (Test-OmiCutoffCreation $root[0].CreationDate $Identity.Created)) { throw 'UPDATE_OWNER_GENERATION_MISMATCH' }
    $nodes = [Collections.Generic.List[object]]::new()
    $nodes.Add([pscustomobject]@{ Process=$Identity.Process; Pid=$Identity.Pid; Created=$Identity.Created; Parent=0; Role=$Identity.RootRole })
    $seen = [Collections.Generic.HashSet[int]]::new(); $null = $seen.Add($Identity.Pid)
    for ($index=0; $index -lt $nodes.Count; $index++) {
        if ($nodes.Count -gt 256) { throw 'UPDATE_TREE_LIMIT' }
        $parent = $nodes[$index]
        foreach ($row in @($Rows | Where-Object { $_.ParentProcessId -eq $parent.Pid })) {
            $role=Get-OmiScopedChildRole $row $parent $Identity
            if($null -eq $role){continue}
            if (-not $seen.Add([int]$row.ProcessId)) { throw 'UPDATE_TREE_CYCLE' }
            if ($row.CreationDate.ToUniversalTime() -lt $parent.Created.AddTicks(-9)) { throw 'UPDATE_TREE_GENERATION_MISMATCH' }
            try {
                $prior=@($Identity.Nodes | Where-Object {$_.Pid -eq $row.ProcessId})
                $child=if($prior.Count -eq 1){$prior[0].Process}else{[Diagnostics.Process]::GetProcessById([int]$row.ProcessId)}
                $null = $child.Handle
            }
            catch [ArgumentException] { continue } # Exited before retention; never a kill target.
            if (-not (Test-OmiCutoffCreation $row.CreationDate $child.StartTime)) {
                $child.Dispose(); throw 'UPDATE_TREE_GENERATION_MISMATCH'
            }
            $nodes.Add([pscustomobject]@{ Process=$child; Pid=$child.Id; Created=$child.StartTime.ToUniversalTime(); Parent=$parent.Pid; Role=$role })
        }
    }
    # Keep previously captured descendants even if a graceful parent exited.
    foreach ($prior in @($Identity.Nodes)) {
        if ($seen.Add([int]$prior.Pid)) { $nodes.Add($prior) }
    }
    return $nodes.ToArray()
}

function Stop-OmiCapturedTree {
    param($Identity)
    # Refresh ancestry once before cutting. Retained OS handles remain the only
    # termination targets. No taskkill /T expansion, PID reopen, retry or port kill.
    $nodes = @(Get-OmiCutoffTree -Identity $Identity -Rows @(Get-OmiCutoffSnapshot))
    foreach ($node in $nodes) {
        if ($node.Process.Id -ne $node.Pid -or $node.Process.StartTime.ToUniversalTime() -ne $node.Created -or
            $node.Pid -eq $PID -or $node.Process.Handle -eq [IntPtr]::Zero) { throw 'UPDATE_TREE_GENERATION_MISMATCH' }
    }
    $Identity.Nodes = $nodes
    foreach ($node in $nodes) {
        try { if (-not $node.Process.HasExited) { $node.Process.Kill() } }
        catch { Write-Verbose "Exact target termination observation pending: $($node.Pid)" }
    }
    $observe = [Diagnostics.Stopwatch]::StartNew()
    foreach ($node in $nodes) {
        if (-not $node.Process.WaitForExit([Math]::Max(0, 3000 - [int]$observe.ElapsedMilliseconds))) {
            throw 'UPDATE_FORCED_EXIT_UNCONFIRMED'
        }
    }
    # A child spawned during the snapshot/cut gap prevents successor startup.
    $after = @(Get-OmiCutoffSnapshot)
    foreach ($node in $nodes) {
        foreach($row in @($after | Where-Object { $_.ParentProcessId -eq $node.Pid -and $_.CreationDate.ToUniversalTime() -ge $node.Created })){
            if($null -ne (Get-OmiScopedChildRole $row $node $Identity)){throw 'UPDATE_TREE_EXIT_UNCONFIRMED'}
        }
    }
    return @($nodes | ForEach-Object { @{ pid=$_.Pid; created_at=$_.Created.ToString('o'); parent=$_.Parent; role=$_.Role } })
}

function Write-OmiUpdateReceipt {
    param([string]$LogRoot, $Receipt)
    $directory = Join-Path $LogRoot 'updates'
    $null = New-Item -ItemType Directory -Path $directory -Force
    $path = Join-Path $directory ($Receipt.request_id + '.json')
    $Receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
}

function Read-OmiUpdateOwnerStatus {
    param([string]$PipeName, $Process)
    return ([Omi.RuntimeControl.Controller]::ReadOwnerStatus($PipeName,$Process) | ConvertFrom-Json)
}

function Wait-OmiUpdateSuccessor {
    param([string]$Repo, $OldIdentity, [string]$ExpectedLifecycle, [string]$ExpectedApplication, [int]$ObservationMilliseconds=110000)
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $suffix=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Repo.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24) }
    finally { $sha.Dispose() }
    # Startup has its own finite observation budget; it never extends old-owner grace.
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $lastError='NEW_OWNER_NOT_OBSERVED'
    while($clock.ElapsedMilliseconds -lt $ObservationMilliseconds){
        $next=$null
        try {
            $next=Get-OmiUpdateOwner -Repo $Repo
            if($next.Pid -eq $OldIdentity.Pid -or $next.Created -le $OldIdentity.Created){throw 'UPDATE_OLD_GENERATION'}
            $status=Read-OmiUpdateOwnerStatus "omi-runtime-$suffix" $next.Process
            if($status.loaded_lifecycle_source_id -cne $ExpectedLifecycle -or $status.application_release_id -cne $ExpectedApplication){throw 'UPDATE_SOURCE_NOT_ADOPTED'}
            if($status.backend.identity -cne 'PROCESS_IDENTITY' -or $status.backend.selected_host -cnotin @('127.0.0.1','::1')){throw 'UPDATE_BACKEND_UNATTESTED'}
            $hostName=if($status.backend.selected_host -eq '::1'){'[::1]'}else{'127.0.0.1'}
            $url='http://{0}:{1}/api/system/runtime-control/status' -f $hostName,[int]$status.backend.selected_port
            $http=Invoke-RestMethod -Uri $url -TimeoutSec 2 -MaximumRedirection 0
            $serving=$http.serving_backend.owned_start
            if($http.owner_id -cne $status.owner_id -or -not $http.serving_backend.runtime_started -or
                $serving.release_id -cne $ExpectedApplication -or [int]$serving.child_pid -ne [int]$status.backend.pid -or
                [string]$serving.child_created -cne [string]([DateTime]::Parse($status.backend.created_at).ToUniversalTime().ToFileTimeUtc()) -or
                $serving.host -cne $status.backend.selected_host -or [int]$serving.port -ne [int]$status.backend.selected_port){throw 'UPDATE_HTTP_GENERATION_UNCONFIRMED'}
            $ready=Invoke-WebRequest -Uri ('http://{0}:{1}/api/system/readyz' -f $hostName,[int]$status.backend.selected_port) -UseBasicParsing -TimeoutSec 2 -MaximumRedirection 0
            $final=Read-OmiUpdateOwnerStatus "omi-runtime-$suffix" $next.Process
            if($ready.StatusCode -eq 200 -and -not $next.Process.HasExited -and $final.owner_id -ceq $status.owner_id -and
                $final.backend.pid -eq $status.backend.pid -and $final.backend.created_at -ceq $status.backend.created_at -and
                $final.loaded_lifecycle_source_id -ceq $ExpectedLifecycle -and $final.application_release_id -ceq $ExpectedApplication){
                return @{launcher_pid=$next.Pid; launcher_created=$next.Created.ToString('o'); backend=$status.backend;
                    loaded_lifecycle_source_id=$ExpectedLifecycle; application_release_id=$ExpectedApplication; http_readiness='VERIFIED'}
            }
        } catch {
            $lastError=$_.Exception.Message
            # A wrong route is a contract error, not startup latency.
            if ($null -ne $_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
                throw 'UPDATE_VERIFIER_ROUTE_NOT_FOUND'
            }
        } # Read-only observation, never a second launch/kill.
        finally { if($null -ne $next){foreach($node in $next.Nodes){$node.Process.Dispose()}} }
        Start-Sleep -Milliseconds 500
    }
    Write-Warning "UPDATE_SUCCESSOR_UNVERIFIED: $lastError"
    return $null
}

function Read-OmiUpdateLog {
    param([string]$Path, [long]$Offset)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
        if ($stream.Length -lt $Offset) { throw 'UPDATE_LOG_TRUNCATED' }
        $null = $stream.Seek($Offset, 'Begin')
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8)
        try { return $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Invoke-OmiApplyUpdate {
    # Only internal fixtures may shorten the clock or replace OS observations.
    param([string]$LogRoot, [scriptblock]$Launch, [int]$TimeoutSeconds = 180,
        [string]$MutexName = 'OpenMarketIntelligenceLauncher',
        [string]$ExitEventName = 'OpenMarketIntelligenceLauncherExit',
        [scriptblock]$CaptureOwner, [scriptblock]$VerifySuccessor)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $receipt = [ordered]@{ request_id=[guid]::NewGuid().ToString('D'); action='ApplyUpdate';
        accepted_at=[DateTime]::UtcNow.ToString('o'); status='UNKNOWN'; old_owner_stop='UNCONFIRMED';
        stop_kind=$null; cutoff_at=$null; graceful_deadline_seconds=$TimeoutSeconds; nodes=@();
        recovery_state='UNVERIFIED'; vbs_invocations=0; update_applied='UNVERIFIED'; services_ready='UNAVAILABLE';
        backend_readiness='UNVERIFIED'; frontend_readiness='UNVERIFIED'; error=$null }
    $update=$null; $owner=$null; $exitEvent=$null; $identity=$null
    $ownsUpdate=$false; $ownsOwner=$false; $abandoned=$false
    try {
        $update = [Threading.Mutex]::new($false, "$MutexName.ApplyUpdate")
        try { $ownsUpdate = $update.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsUpdate=$true }
        if (-not $ownsUpdate) { throw 'UPDATE_ALREADY_IN_PROGRESS' }
        try { $owner = [Threading.Mutex]::OpenExisting($MutexName) }
        catch [Threading.WaitHandleCannotBeOpenedException] { throw 'UPDATE_NO_OWNER' }
        try { $ownsOwner = $owner.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $ownsOwner=$true; throw 'UPDATE_NO_LIVE_OWNER' }
        if ($ownsOwner) { throw 'UPDATE_NO_OWNER' }
        # Capture exact handles before signalling even an old loaded Launcher.
        if ($null -eq $CaptureOwner) { throw 'UPDATE_CAPTURE_REQUIRED' }
        $identity = & $CaptureOwner
        $receipt.owner_pid=$identity.Pid; $receipt.owner_created=$identity.Created.ToString('o')
        $receipt.owner_commandline=$identity.CommandLine
        $receipt.nodes=@($identity.Nodes|ForEach-Object{@{pid=$_.Pid;created_at=$_.Created.ToString('o');parent=$_.Parent;role=$_.Role}})
        $exitEvent = [Threading.EventWaitHandle]::OpenExisting($ExitEventName)
        $offsets=@{}; $today=(Get-Date).Date
        foreach ($day in @($today,$today.AddDays(1))) {
            $path=Join-Path $LogRoot ($day.ToString('yyyy-MM-dd')+'\launcher.log')
            $offsets[$path]=if(Test-Path -LiteralPath $path){(Get-Item -LiteralPath $path).Length}else{0L}
        }
        if (-not $exitEvent.Set()) { throw 'UPDATE_EXIT_SIGNAL_FAILED' }
        Write-Host 'EXIT_REQUESTED; graceful deadline shared with exact-owner cutoff'
        while (-not $ownsOwner -and $clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
            try { $ownsOwner=$owner.WaitOne(0) }
            catch [Threading.AbandonedMutexException] { $ownsOwner=$true; $abandoned=$true }
            if (-not $ownsOwner) { Start-Sleep -Milliseconds 50 }
        }
        $normal=$false
        if ($ownsOwner -and -not $abandoned) {
            # Legacy Add-Content has incompatible sharing. Read only after release.
            Start-Sleep -Milliseconds ([Math]::Min(400,[Math]::Max(0,($TimeoutSeconds*1000)-[int]$clock.ElapsedMilliseconds)))
            try { $text=($offsets.Keys | ForEach-Object { Read-OmiUpdateLog $_ $offsets[$_] }) -join "`n" }
            catch { $text=''; $receipt.graceful_observation_error=$_.Exception.Message }
            $normal=$text -match '(?m)^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[INFO\] Launcher stopped\.\r?\n'
            $normal=$normal -and $identity.Process.WaitForExit([Math]::Max(0,[Math]::Min(1000,($TimeoutSeconds*1000)-[int]$clock.ElapsedMilliseconds)))
            foreach($node in $identity.Nodes){ if(-not $node.Process.HasExited){$normal=$false} }
        }
        if ($normal) { $receipt.stop_kind='GRACEFUL'; $receipt.old_owner_stop='CONFIRMED' }
        else {
            # Refusal/rearm/abandonment cannot reset or end the original window.
            while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) { Start-Sleep -Milliseconds 25 }
            $receipt.cutoff_at=[DateTime]::UtcNow.ToString('o'); $receipt.stop_kind='HARD_CUTOFF'
            $receipt.recovery_state='RECONCILIATION_REQUIRED'
            try { $receipt.nodes=@(Stop-OmiCapturedTree -Identity $identity) }
            finally { $receipt.nodes=@($identity.Nodes|ForEach-Object{@{pid=$_.Pid;created_at=$_.Created.ToString('o');parent=$_.Parent;role=$_.Role}}) }
            $receipt.old_owner_stop='FORCED_EXIT_CONFIRMED'
            if(-not $ownsOwner){
                try{$ownsOwner=$owner.WaitOne(0)}catch [Threading.AbandonedMutexException]{$ownsOwner=$true}
            }
            if(-not $ownsOwner){throw 'UPDATE_MUTEX_RELEASE_UNCONFIRMED'}
        }
        $receipt.status='OLD_OWNER_STOPPED'
        Write-OmiUpdateReceipt -LogRoot $LogRoot -Receipt $receipt
        $owner.ReleaseMutex(); $ownsOwner=$false
        $receipt.vbs_invocations=1
        & $Launch
        $receipt.status='NEW_START_UNVERIFIED'
        if ($null -ne $VerifySuccessor) {
            $successor = & $VerifySuccessor $identity
            if ($null -ne $successor) {
                $receipt.successor=$successor; $receipt.update_applied='LAUNCHER_AND_BACKEND_VERIFIED'
                $receipt.backend_readiness='VERIFIED'; $receipt.services_ready='BACKEND_VERIFIED_FRONTEND_UNVERIFIED'
                $receipt.status='UPDATE_BACKEND_READY'
            }
        }
        Write-OmiUpdateReceipt -LogRoot $LogRoot -Receipt $receipt
        return [pscustomobject]$receipt
    }
    catch {
        $receipt.error=$_.Exception.Message
        $receipt.status=if($receipt.old_owner_stop -in @('CONFIRMED','FORCED_EXIT_CONFIRMED')){'UPDATE_START_UNAVAILABLE'}else{'UPDATE_STOP_UNCONFIRMED'}
        try { Write-OmiUpdateReceipt -LogRoot $LogRoot -Receipt $receipt } catch { }
        throw
    }
    finally {
        if($null -ne $exitEvent){$exitEvent.Dispose()}
        if($ownsOwner){$owner.ReleaseMutex()}; if($null -ne $owner){$owner.Dispose()}
        if($ownsUpdate){$update.ReleaseMutex()}; if($null -ne $update){$update.Dispose()}
        if($null -ne $identity){ foreach($node in $identity.Nodes){$node.Process.Dispose()} }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $appData = if (Test-Path -LiteralPath (Join-Path $repo 'release-manifest.json')) {
            Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Open Market Intelligence'
        } else { $repo }
        $vbs = Join-Path $PSScriptRoot 'start-omi-launcher-hidden.vbs'
        $wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
        if (-not (Test-Path -LiteralPath $vbs -PathType Leaf) -or
            -not (Test-Path -LiteralPath $wscript -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'omi-launcher.ps1') -PathType Leaf)) {
            throw 'UPDATE_ENTRY_MISSING; nothing signalled'
        }
        Add-Type -Path @((Join-Path $PSScriptRoot 'OmiRuntimeControl.cs'), (Join-Path $PSScriptRoot 'OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
        . (Join-Path $PSScriptRoot 'omi-runtime-control.ps1')
        $script:RepoRoot=$repo
        $expectedLifecycle=Get-OmiLifecycleSourceId
        $expectedApplication=[Omi.OwnedShutdown.ProductionSession]::ApplicationRelease($repo)
        $result = Invoke-OmiApplyUpdate -LogRoot (Join-Path $appData 'logs\launcher') `
            -TimeoutSeconds 180 -CaptureOwner { Get-OmiUpdateOwner -Repo $repo } -VerifySuccessor {
                param($old)
                Wait-OmiUpdateSuccessor -Repo $repo -OldIdentity $old -ExpectedLifecycle $expectedLifecycle -ExpectedApplication $expectedApplication
            } -Launch {
                Start-Process -FilePath $wscript -ArgumentList ('"{0}"' -f $vbs) -WindowStyle Hidden -ErrorAction Stop
            }
        $result | ConvertTo-Json -Depth 8 -Compress
        if ($result.status -ne 'UPDATE_BACKEND_READY') { exit 2 }
        exit 0
    }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        if ($_.Exception.Message -like 'UPDATE_NO_OWNER*') { exit 3 }
        exit 2
    }
}
