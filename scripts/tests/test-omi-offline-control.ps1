param([Parameter(Mandatory=$true)][string]$FixtureRoot)
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot)
Add-Type -Path @((Join-Path $repo 'scripts/OmiRuntimeControl.cs'),(Join-Path $repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
function Assert($condition,$message) {if (-not $condition) {throw $message}}
$token='b'*64 # Synthetic fixture credential; never read real credentials.
$sha=[Security.Cryptography.SHA256]::Create()
try {$hash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token)))).Replace('-','').ToLowerInvariant()}
finally {$sha.Dispose()}
$pipeName='omi-offline-fixture-'+[Guid]::NewGuid().ToString('N')
$controller=[Omi.RuntimeControl.Controller]::new($FixtureRoot,$hash,$pipeName)
$owner=[Diagnostics.Process]::GetCurrentProcess()
function Send($action,$id,$credential=$token,$confirmation='') {
    $request=@{action=$action;request_id=$id;expected_owner_id=$controller.OwnerId;token=$credential}
    if ($action -notin @('Status','ReadOperation')) {$request.confirmation=if ($confirmation) {$confirmation} else {@{StartBackend='start_backend';RecoverFailedStart='recover_failed_start';SchemaUpgrade='upgrade_schema'}[$action]}}
    return ([Omi.RuntimeControl.Controller]::RequestOwner($pipeName,$owner,($request|ConvertTo-Json -Compress))|ConvertFrom-Json)
}
try {
    $controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)
    $controller.Start()
    Assert ((Send 'Status' '').owner_id -eq $controller.OwnerId) 'OFFLINE_STATUS'
    foreach($action in @('StartBackend','RecoverFailedStart','SchemaUpgrade')) {
        $id=[Guid]::NewGuid().ToString('D')
        $accepted=Send $action $id
        Assert ($accepted.state -eq 'accepted' -and $accepted.action -eq $action -and $accepted.actor -eq 'authenticated_pipe_client') 'OFFLINE_ACCEPTANCE'
        # Publication without a Backend must not retire this intent.
        $controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)
        Assert ($controller.TakePending() -eq $id) 'OFFLINE_QUEUE'
        Assert ($controller.BeginRemoteOperation($id)) 'REMOTE_CONSUME'
        Assert (-not $controller.BeginRemoteOperation($id)) 'CONSUMED_TWICE'
        $controller.CompleteRemoteOperation($id,$false,'NOT_ATTEMPTED','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,$null)
        Assert ((Send $action $id).state -eq 'unknown') 'REPLAY_ACCEPTED'
        $next=[Guid]::NewGuid().ToString('D')
        Assert ((Send $action $next).state -eq 'accepted') 'NEW_UUID_POISONED'
        Assert ($controller.TakePending() -eq $next) 'NEW_QUEUE'
        Assert ($controller.BeginRemoteOperation($next)) 'REMOTE_CONSUME'
        Assert (-not $controller.BeginRemoteOperation($next)) 'INTENT_REUSED'
        $controller.CompleteRemoteOperation($next,$false,'UNKNOWN','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,$null)
        $receipt=Send 'ReadOperation' $next
        Assert ($receipt.state -eq 'unknown' -and $receipt.next_action -eq 'ReadOperation_then_reconcile_retained_generation') 'FAILURE_RECEIPT'
        Assert ((Send $action $next).state -eq 'unknown') 'UNKNOWN_REPLAY'
    }
    foreach($bad in @('Shell','ApplyRelease','ChangePassword')) {
        Assert ((Send $bad ([Guid]::NewGuid().ToString('D'))).state -ne 'accepted') 'ARBITRARY_ACTION'
    }
    Assert ((Send 'StartBackend' ([Guid]::NewGuid().ToString('D')) ('c'*64)).error -eq 'RUNTIME_CONTROL_FORBIDDEN') 'TOKEN_BYPASS'
    Assert ((Send 'StartBackend' ([Guid]::NewGuid().ToString('D')) $token 'control_center').state -ne 'accepted') 'WRONG_CONFIRMATION'
    $verifiedId=[Guid]::NewGuid().ToString('D')
    Assert ((Send 'StartBackend' $verifiedId).state -eq 'accepted') 'SUCCESS_ACCEPTANCE'
    Assert ($controller.TakePending() -eq $verifiedId) 'SUCCESS_DEQUEUE'
    Assert ($controller.BeginRemoteOperation($verifiedId)) 'SUCCESS_CONSUME'
    # Publish only this disposable test process, never a real Backend.
    $identity=[Omi.RuntimeControl.Identity]::new();$identity.pid=$owner.Id;$identity.created_at=$owner.StartTime.ToUniversalTime().ToString('o')
    $controller.Publish('{"backend":{"status":"observed"}}',$identity,$true)
    $controller.CompleteRemoteOperation($verifiedId,$true,'stopped','NOT_ATTEMPTED','VERIFIED',$identity,$null)
    Assert ((Send 'ReadOperation' $verifiedId).state -eq 'succeeded') 'VERIFIED_SUCCESS'
    $controller.Publish('{"backend":{"status":"stopped"}}',$null,$false)
    $id=[Guid]::NewGuid().ToString('D')
    Assert ((Send 'StartBackend' $id).state -eq 'accepted') 'ACCEPT_FOR_RECOVERY'
    $controller.Dispose()
    $controller=[Omi.RuntimeControl.Controller]::new($FixtureRoot,$hash,$pipeName)
    $receipt=$controller.Dispatch((@{action='ReadOperation';request_id=$id;expected_owner_id='';token=''}|ConvertTo-Json -Compress))|ConvertFrom-Json
    Assert ($receipt.state -eq 'unknown' -and $receipt.reason -eq 'CONTROLLER_RECOVERED_NO_REPLAY') 'LOST_INTENT_REPLAY'
    'OFFLINE_CONTROL_PASS'
} finally {$controller.Dispose();$owner.Dispose()}
