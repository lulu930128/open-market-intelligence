param([string]$OutputRoot = (Join-Path $env:TEMP ('omi-cutoff-fixture-'+[guid]::NewGuid().ToString('N'))))
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$null=New-Item -ItemType Directory -Path $OutputRoot -Force
Add-Type -Path @((Join-Path $repo 'scripts/OmiOwnedShutdown.cs'),(Join-Path $repo 'scripts/OmiRuntimeControl.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
function Assert($value,$message){if(-not $value){throw $message}}
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
$type=[Omi.OwnedShutdown.ProductionSession]
$deadlineType=[Omi.OwnedShutdown.LifecycleDeadline]
$ctor=$deadlineType.GetConstructor($flags,$null,[type[]]@([int]),$null)
$python=@(Get-Content -Encoding UTF8 (Join-Path $repo '.venv/pyvenv.cfg') | Where-Object {$_ -like 'executable = *'})[0].Substring(13)
foreach($mode in @('graceful','rearmed','hang','child-exited','runner-exited','owner-mismatch','expired')){
    $root=Join-Path $OutputRoot $mode; $null=New-Item -ItemType Directory -Path $root
    $info=[Diagnostics.ProcessStartInfo]::new($python,('"{0}" {1}' -f (Join-Path $PSScriptRoot 'cutoff-fixture.py'),$mode))
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true
    $runner=[Diagnostics.Process]::Start($info); $null=$runner.Handle
    $read=$runner.StandardOutput.ReadLineAsync()
    Assert ($read.Wait(3000)) 'FIXTURE_CHILD_BOOT_TIMEOUT'
    $child=[Diagnostics.Process]::GetProcessById([int]$read.Result); $null=$child.Handle
    try {
        $owner=[Diagnostics.Process]::GetCurrentProcess()
        $identity=[Collections.Generic.Dictionary[string,string]]::new()
        foreach($pair in @(@('launcher',$owner),@('runner',$runner),@('child',$child))){
            $identity[$pair[0]+'_pid']=[string]$pair[1].Id
            $identity[$pair[0]+'_created']=[string]$pair[1].StartTime.ToUniversalTime().ToFileTimeUtc()
        }
        $identity['instance']=[guid]::NewGuid().ToString(); $identity['nonce']='fixture-only'
        $identity['journal']=$root; $identity['restart_abort_protocol']='1'
        if($mode -eq 'owner-mismatch'){$identity['launcher_created']='1'}
        $session=[Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
        foreach($pair in @(@('runner',$runner),@('child',$child),@('identity',$identity),@('stopGate',[object]::new()),
            @('stops',[Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new()))){
            $type.GetField($pair[0],$flags).SetValue($session,$pair[1])
        }
        $deadline=$ctor.Invoke(@(800))
        if($mode -eq 'expired'){Start-Sleep -Milliseconds 850}
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $id=[guid]::NewGuid().ToString('D')
        $task=$session.StopWithinDeadlineAsync($id,$null,$deadline)
        Assert ($task.Wait(6000)) 'CUTOFF_TASK_UNBOUNDED'
        $result=$task.Result
        $result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $root 'result.json')
        if($mode -eq 'graceful'){
            Assert ($result.ExactExit -and -not $result.Forced -and $result.Reason -eq 'LIFESPAN_AND_EXACT_EXIT') 'GRACEFUL_REGRESSION'
            Assert $session.CanStartAfterStop 'GRACEFUL_START_REJECTED'
        } elseif($mode -eq 'owner-mismatch'){
            Assert ($result.Reason -eq 'FORCE_OWNER_NOT_ATTESTED' -and -not $result.ForcedExitConfirmed) 'MISMATCH_FALSE_SUCCESS'
            Assert (-not $child.HasExited -and -not $runner.HasExited) 'MISMATCH_KILLED_PROCESS'
            Assert (-not $session.CanStartAfterStop) 'MISMATCH_ALLOWED_START'
        } else {
            Assert ($result.ForcedExitConfirmed -and -not $result.ExactExit -and $result.RecoveryState -eq 'RECONCILIATION_REQUIRED') 'FORCE_FALSE_GRACEFUL'
            Assert ($result.ElapsedMilliseconds -ge 800) 'EARLY_CUTOFF'
            Assert ($child.HasExited -and $runner.HasExited -and $session.CanStartAfterStop) 'RETAINED_EXIT_UNPROVEN'
            $saved=Get-Content -Raw -Encoding UTF8 (Join-Path $root "hard-cutoff-$id.json") | ConvertFrom-Json
            Assert ($saved.ProcessGeneration -eq $identity['instance'] -and $saved.BeforePid -eq $child.Id -and -not $saved.ExactExit) 'DURABLE_RECEIPT_MISMATCH'
            if($mode -eq 'expired'){Assert ($watch.ElapsedMilliseconds -lt 2000) 'NESTED_DEADLINE_RESET'}
            if($mode -eq 'rearmed'){Assert ($result.GracefulReason -eq 'PREFLIGHT_REARMED') 'REARM_DIAGNOSTIC_LOST'}
        }
        Assert ([object]::ReferenceEquals($task,$session.StopWithinDeadlineAsync($id,$null,$deadline))) 'REPLAYED_STOP'
        $result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $root 'result.json')
        "PASS $mode"
    } finally {
        # Only the exact fixture handles born above, never production PIDs.
        foreach($process in @($runner,$child)){if(-not $process.HasExited){$process.Kill();$null=$process.WaitForExit(3000)};$process.Dispose()}
    }
}

# Real private named pipe: writer unavailable/unknown cannot veto authenticated intent.
$token='a'*64; $sha=[Security.Cryptography.SHA256]::Create()
try{$hash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token)))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
$pipeName='omi-cutoff-fixture-'+[guid]::NewGuid().ToString('N')
$controller=[Omi.RuntimeControl.Controller]::new((Join-Path $OutputRoot 'controller'),$hash,$pipeName)
$me=[Diagnostics.Process]::GetCurrentProcess()
$identity=[Omi.RuntimeControl.Identity]::new();$identity.pid=$PID;$identity.created_at=$me.StartTime.ToUniversalTime().ToString('o')
function Submit($id,$credential,$ownerId){
    $client=[IO.Pipes.NamedPipeClientStream]::new('.',$pipeName,[IO.Pipes.PipeDirection]::InOut)
    try{
        $client.Connect(1000);$writer=[IO.StreamWriter]::new($client);$writer.AutoFlush=$true;$reader=[IO.StreamReader]::new($client)
        $writer.WriteLine((@{action='RestartBackend';request_id=$id;expected_owner_id=$ownerId;token=$credential;
            backend_preflight='{"schema":"omi.restart-preflight.v1","runtime_started":false,"registered_drain_state":"UNKNOWN","all_writers_drained":false,"unknown_writer_count":10}'}|ConvertTo-Json -Compress))
        $read=$reader.ReadLineAsync();Assert ($read.Wait(2000)) 'PIPE_TIMEOUT';return ($read.Result|ConvertFrom-Json)
    }finally{$client.Dispose()}
}
try{
    $controller.Start();$controller.Publish('{"restart":{"available":false,"reason":"ALL_WRITERS_DRAIN_UNAVAILABLE"}}',$identity,$true)
    $id=[guid]::NewGuid().ToString('D')
    Assert ((Submit $id ('b'*64) $controller.OwnerId).error -eq 'RUNTIME_CONTROL_FORBIDDEN') 'BAD_TOKEN_ACCEPTED'
    Assert ((Submit $id $token ([guid]::NewGuid().ToString('D'))).reason -eq 'OWNER_MISMATCH') 'BAD_OWNER_ACCEPTED'
    Assert ((Submit $id $token $controller.OwnerId).state -eq 'accepted') 'WRITER_GATE_REJECTED_INTENT'
    $deadline=$controller.OwnedRestartDeadline($id);Start-Sleep -Milliseconds 100
    $controller.Publish('{"restart":{"available":false}}',$identity,$true)
    Assert ($controller.TakePending() -eq $id) 'WRITER_GATE_BLOCKED_QUEUE'
    Assert ($controller.BeginAuthenticatedOwnedRestart($id,$identity)) 'WRITER_GATE_BLOCKED_BEGIN'
    Assert ([object]::ReferenceEquals($deadline,$controller.OwnedRestartDeadline($id))) 'REMOTE_DEADLINE_RESET'
    Assert ($deadline.ElapsedMilliseconds -ge 100) 'ACCEPTANCE_TIME_LOST'
    Assert (-not $controller.BeginAuthenticatedOwnedRestart($id,$identity)) 'REMOTE_REPLAY'
    $controller.CompleteOwnedRestart($id,$result,$null,$null)
    $readRequest=@{action='ReadOperation';request_id=$id;expected_owner_id=$controller.OwnerId;token=''}|ConvertTo-Json -Compress
    $readback=$controller.Dispatch($readRequest)|ConvertFrom-Json
    Assert ($null -ne $readback.stop_evidence -and $readback.reason -ne 'STORE_UNAVAILABLE') 'COMPLETED_RECEIPT_UNREADABLE'
    $controller.Dispose()
    $controller=[Omi.RuntimeControl.Controller]::new((Join-Path $OutputRoot 'controller'),$hash,$pipeName)
    $readback=$controller.Dispatch($readRequest)|ConvertFrom-Json
    Assert ($null -ne $readback.stop_evidence -and $readback.reason -ne 'STORE_UNAVAILABLE') 'RECOVERED_RECEIPT_UNREADABLE'
    'PASS forced-receipt-read-and-recover'
    'PASS remote-unavailable-preflight-intent'
}finally{$controller.Dispose()}
"Evidence: $OutputRoot"
