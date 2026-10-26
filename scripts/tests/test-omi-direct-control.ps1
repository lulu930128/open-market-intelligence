param([Parameter(Mandatory=$true)][string]$FixtureRoot)
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot)
Add-Type -Path @((Join-Path $repo 'scripts/OmiRuntimeControl.cs'),(Join-Path $repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
$token='d'*64 # Disposable capability only.
$sha=[Security.Cryptography.SHA256]::Create()
try {$hash=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token))).Replace('-','').ToLowerInvariant()}
finally {$sha.Dispose()}
$pipeName='omi-direct-fixture-'+[Guid]::NewGuid().ToString('N')
$controller=[Omi.RuntimeControl.Controller]::new($FixtureRoot,$hash,$pipeName)
$process=[Diagnostics.Process]::GetCurrentProcess()
$backend=[Omi.RuntimeControl.Identity]::new()
$backend.pid=$process.Id;$backend.created_at=$process.StartTime.ToUniversalTime().ToString('o')
try {
    $controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)
    $controller.Start()
    @{pipe=$pipeName;owner=$controller.OwnerId;pid=$PID}|ConvertTo-Json -Compress
    while ($null -ne ($line=[Console]::ReadLine()) -and $line -ne 'done') {
        $command=$line|ConvertFrom-Json
        $result=@{}
        switch ($command.action) {
            'offline' {$controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)}
            'running' {$controller.Publish('{"backend":{"status":"fixture"}}',$backend,$true)}
            'owned-running' {
                # Birth only disposable runner/child; never discover a production PID.
                $python=@(Get-Content (Join-Path $repo '.venv/pyvenv.cfg') | Where-Object {$_ -like 'executable = *'})[0].Substring(13)
                $info=[Diagnostics.ProcessStartInfo]::new($python,('"{0}" graceful' -f (Join-Path $PSScriptRoot 'cutoff-fixture.py')))
                $info.UseShellExecute=$false;$info.CreateNoWindow=$true
                $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true
                $runner=[Diagnostics.Process]::Start($info);$null=$runner.Handle
                $read=$runner.StandardOutput.ReadLineAsync()
                if (-not $read.Wait(3000)) {throw 'FIXTURE_BOOT_TIMEOUT'}
                $child=[Diagnostics.Process]::GetProcessById([int]$read.Result);$null=$child.Handle
                $identity=[Collections.Generic.Dictionary[string,string]]::new()
                foreach ($pair in @(@('launcher',$process),@('runner',$runner),@('child',$child))) {
                    $identity[$pair[0]+'_pid']=[string]$pair[1].Id
                    $identity[$pair[0]+'_created']=[string]$pair[1].StartTime.ToUniversalTime().ToFileTimeUtc()
                }
                $identity['instance']=[guid]::NewGuid().ToString('D');$identity['nonce']='fixture-only'
                $identity['journal']=$FixtureRoot;$identity['restart_abort_protocol']='1'
                $type=[Omi.OwnedShutdown.ProductionSession]
                $session=[Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
                foreach ($pair in @(@('runner',$runner),@('child',$child),@('identity',$identity),@('stopGate',[object]::new()),
                    @('stops',[Collections.Generic.Dictionary[string,Omi.OwnedShutdown.ProductionSession+StopEvidence]]::new()))) {
                    $type.GetField($pair[0],'Instance,NonPublic').SetValue($session,$pair[1])
                }
                $backend.pid=$session.ChildPid;$backend.created_at=$session.ChildCreated
                $controller.Publish('{"backend":{"status":"disposable"}}',$backend,$true)
                $result.backend_pid=$backend.pid
            }
            'wrong-generation' {
                $backend.created_at='2000-01-01T00:00:00Z'
                $controller.Publish('{"backend":{"status":"fixture"}}',$backend,$true)
            }
            'caller-reused' {
                $identity=[Omi.RuntimeControl.Controller].GetField('authenticatedCallerIdentity','NonPublic,Instance').GetValue($controller)
                $identity.created_at='2000-01-01T00:00:00Z'
            }
            'consume' {
                $id=$controller.TakePending()
                $result.id=$id
                if ($null -ne $id) {
                    $action=$controller.PendingAction($id)
                    $result.begun=if ($action -eq 'RestartBackend') {$controller.BeginAuthenticatedOwnedRestart($id,$backend)} else {$controller.BeginRemoteOperation($id)}
                    $result.action=$action
                    $result.deadline=$controller.OwnedRestartDeadline($id).RemainingMilliseconds
                }
            }
            'dequeue' {$result.id=$controller.TakePending()}
            'begin' {$result.begun=$controller.BeginRemoteOperation($command.id)}
            'owned-stop' {
                $task=$session.StopWithinDeadlineAsync($command.id,$null,$controller.OwnedRestartDeadline($command.id))
                if (-not $task.Wait(5000)) {throw 'FIXTURE_STOP_TIMEOUT'}
                $stop=$task.Result
                $result.exact=$stop.ExactExit;$result.forced=$stop.Forced;$result.can_start=$session.CanStartAfterStop
                $controller.CompleteOwnedRestart($command.id,$stop,$null,$null)
                $controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)
            }
            'finish' {
                if ($command.kind -eq 'RestartBackend') {$controller.CompleteOwnedRestart($command.id,$null,$null,$null)}
                else {$controller.CompleteRemoteOperation($command.id,$false,'NOT_ATTEMPTED','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,$command.failure)}
            }
            'locked-consume' {
                $id=$controller.TakePending()
                $file=[IO.File]::Open((Join-Path $FixtureRoot "$id.json"),'Open','Read','Read')
                try {try {$null=$controller.BeginRemoteOperation($id);throw 'SAVE_MUST_FAIL'} catch {$result.failed=$true}}
                finally {$file.Dispose()}
                $result.reused=$controller.BeginRemoteOperation($id)
            }
            default {throw 'FIXTURE_COMMAND_INVALID'}
        }
        $result|ConvertTo-Json -Compress
    }
} finally {
    $controller.Dispose();$process.Dispose()
    if ($null -ne $runner) {
        $runner.StandardInput.Close()
        if (-not $runner.WaitForExit(3000) -or -not $child.WaitForExit(3000)) {throw 'FIXTURE_EXIT_UNCONFIRMED'}
        $runner.Dispose();$child.Dispose()
    }
}
