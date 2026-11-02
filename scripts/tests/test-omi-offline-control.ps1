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
    # Real durable Controller/pipe roundtrip; diagnostics never alter UNKNOWN or replay policy.
    foreach ($case in @('owner','unsafe','wrong-request')) {
        $id=[Guid]::NewGuid().ToString('D')
        Assert ((Send 'SchemaUpgrade' $id).state -eq 'accepted') 'DIAGNOSTIC_ACCEPTANCE'
        Assert ($controller.TakePending() -eq $id -and $controller.BeginRemoteOperation($id)) 'DIAGNOSTIC_CONSUME'
        $diagnostic=[Omi.RuntimeControl.OperationDiagnostics]::new()
        $diagnostic.request_id=$id;$diagnostic.phase='FAILED';$diagnostic.failed_phase='POST_STOP_OWNER_CHECK'
        $diagnostic.failure_code='BACKEND_START_OWNER_NOT_ATTESTED';$diagnostic.error_type='RuntimeException'
        $diagnostic.worker_outcome='NOT_ATTEMPTED';$diagnostic.schema_revision_observed='20261025_0093'
        $diagnostic.schema_revision_basis='CHECK_START';$diagnostic.observed_at=[DateTime]::UtcNow.ToString('o')
        $diagnostic.recovery_fence.no_effects=$false;$diagnostic.recovery_fence.worker_settled=$false
        $diagnostic.recovery_fence.terminal_receipt='MATCHED';$diagnostic.recovery_fence.admission='RECONCILIATION_REQUIRED'
        if ($case -eq 'unsafe') {
            foreach ($name in @('phase','failed_phase','failure_code','error_type','worker_phase','worker_failure_code',
                'worker_error_type','schema_revision_observed','schema_revision_basis','next_action','observed_at')) {$diagnostic.$name='PRIVATE_SENTINEL'}
            $diagnostic.recovery_fence.terminal_receipt='PRIVATE_SENTINEL';$diagnostic.recovery_fence.admission='PRIVATE_SENTINEL'
        }
        if ($case -eq 'wrong-request') {$diagnostic.request_id=[Guid]::NewGuid().ToString('D')}
        $payload=$diagnostic|ConvertTo-Json -Depth 6 -Compress
        $controller.Publish((@{backend=@{status='stopped'};last_operation=$diagnostic}|ConvertTo-Json -Depth 6 -Compress),$null,$false)
        $status=Send 'Status' ''
        Assert (($status|ConvertTo-Json -Depth 8 -Compress) -notmatch 'PRIVATE_SENTINEL') 'STATUS_SECRET_LEAK'
        $controller.CompleteRemoteOperation($id,$false,'stopped','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,'BACKEND_START_OWNER_NOT_ATTESTED',$payload)
        $receipt=Send 'ReadOperation' $id
        Assert ($receipt.state -eq 'unknown' -and $receipt.reason -eq 'LIFECYCLE_FAILED') 'DIAGNOSTICS_CHANGED_AUTHORITY'
        Assert (($receipt|ConvertTo-Json -Depth 8 -Compress) -notmatch 'PRIVATE_SENTINEL') 'RECEIPT_SECRET_LEAK'
        if ($case -eq 'owner') {
            Assert ($receipt.diagnostics.failed_phase -eq 'POST_STOP_OWNER_CHECK' -and
                $receipt.diagnostics.failure_code -eq 'BACKEND_START_OWNER_NOT_ATTESTED' -and
                $receipt.diagnostics.worker_outcome -eq 'NOT_ATTEMPTED' -and
                $receipt.diagnostics.recovery_fence.admission -eq 'RECONCILIATION_REQUIRED' -and
                $receipt.diagnostics.schema_revision_observed -eq '20261025_0093') 'DIAGNOSTIC_FIELDS_LOST'
            Assert ($status.last_operation.failure_code -eq $receipt.diagnostics.failure_code) 'STATUS_RECEIPT_DIVERGED'
        } elseif ($case -eq 'unsafe') {
            Assert ($receipt.diagnostics.failure_code -eq 'UNCLASSIFIED_FAILURE' -and
                $null -eq $receipt.diagnostics.schema_revision_observed) 'UNSAFE_VALUE_NOT_UNKNOWN'
        } else {Assert ($null -eq $receipt.diagnostics) 'OTHER_REQUEST_DIAGNOSTIC_BORROWED'}
        Assert ((Send 'SchemaUpgrade' $id).state -eq 'unknown') 'DIAGNOSTIC_REPLAY'
    }
    $inner=[IO.IOException]::new('SCHEMA_SOURCE_CHANGED')
    $reconcileId=[Guid]::NewGuid().ToString('D')
    Assert ((Send 'SchemaUpgrade' $reconcileId).state -eq 'accepted') 'RECONCILE_ACCEPTANCE'
    Assert ($controller.TakePending() -eq $reconcileId -and $controller.BeginRemoteOperation($reconcileId)) 'RECONCILE_CONSUME'
    $controller.CompleteRemoteOperation($reconcileId,$false,'stopped','NOT_ATTEMPTED','NOT_ATTEMPTED',$null,$null)
    $receiptPath=Join-Path $FixtureRoot ($reconcileId+'.json')
    $original=[Convert]::ToBase64String([IO.File]::ReadAllBytes($receiptPath))
    $proof=[Omi.RuntimeControl.OperationDiagnostics]::new();$proof.request_id=$reconcileId
    $proof.observed_at=[DateTime]::UtcNow.ToString('o');$proof.phase='FAILED'
    $proof.recovery_fence.terminal_receipt='MATCHED';$proof.recovery_fence.admission='RECHECK_REQUIRED'
    $proof.recovery_fence.worker_not_dispatched=$true;$proof.recovery_fence.worker_settled=$false
    $proof.recovery_fence.no_effects=$false;$proof.recovery_fence.owner_attested=$true
    $proof.recovery_fence.retained_generation='EXACT_EXIT'
    foreach ($case in @('fresh','stale','wrong-request')) {
        $proof.observed_at=[DateTime]::UtcNow.AddSeconds($(if ($case -eq 'stale') {-60} else {0})).ToString('o')
        $proof.request_id=if ($case -eq 'wrong-request') {[Guid]::NewGuid().ToString('D')} else {$reconcileId}
        $controller.Publish((@{schema_reconciliation=$proof}|ConvertTo-Json -Depth 6 -Compress),$null,$false)
        $receipt=Send 'ReadOperation' $reconcileId
        Assert ($receipt.state -eq 'unknown' -and $receipt.reason -eq 'LIFECYCLE_FAILED') 'RECONCILIATION_REWROTE_OUTCOME'
        Assert (($null -ne $receipt.reconciliation) -eq ($case -eq 'fresh')) 'STALE_OR_WRONG_RECOVERY_PROOF'
        if ($case -eq 'fresh') {Assert ($receipt.reconciliation.recovery_fence.worker_not_dispatched -and
            -not $receipt.reconciliation.recovery_fence.worker_settled) 'WORKER_UNATTEMPTED_IS_NOT_SETTLED'}
        Assert ($original -ceq [Convert]::ToBase64String([IO.File]::ReadAllBytes($receiptPath))) 'READ_OPERATION_WROTE_HISTORY'
        Assert ((Send 'SchemaUpgrade' $reconcileId).state -eq 'unknown') 'RECONCILIATION_REPLAYED'
    }
    Assert ([Omi.RuntimeControl.OperationDiagnostics]::FailureCode([Exception]::new('PRIVATE_SENTINEL',$inner)) -eq 'SCHEMA_SOURCE_CHANGED') 'INNER_GATE_LOST'
    Assert ([Omi.RuntimeControl.OperationDiagnostics]::FailureCode([Exception]::new('PRIVATE_SENTINEL')) -eq 'UNCLASSIFIED_FAILURE') 'UNKNOWN_EXCEPTION_LEAK'
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
    $proof.request_id=$reconcileId;$proof.observed_at=[DateTime]::UtcNow.ToString('o')
    $controller.Publish((@{schema_reconciliation=$proof}|ConvertTo-Json -Depth 6 -Compress),$null,$false)
    $other=$controller.Dispatch((@{action='ReadOperation';request_id=$reconcileId;expected_owner_id='';token=''}|ConvertTo-Json -Compress))|ConvertFrom-Json
    Assert ($null -eq $other.reconciliation) 'OTHER_OWNER_BORROWED_RECOVERY'
    $receipt=$controller.Dispatch((@{action='ReadOperation';request_id=$id;expected_owner_id='';token=''}|ConvertTo-Json -Compress))|ConvertFrom-Json
    Assert ($receipt.state -eq 'unknown' -and $receipt.reason -eq 'CONTROLLER_RECOVERED_NO_REPLAY') 'LOST_INTENT_REPLAY'
    'OFFLINE_CONTROL_PASS'
} finally {$controller.Dispose();$owner.Dispose()}
