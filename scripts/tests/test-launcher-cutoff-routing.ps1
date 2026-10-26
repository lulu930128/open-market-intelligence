$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Add-Type -Path (Join-Path $repo 'scripts/OmiOwnedShutdown.cs') -ReferencedAssemblies @('System.Web.Extensions','System.Core')
Add-Type 'namespace System.Windows.Forms { public static class Application { public static int Exits; public static void Exit(){Exits++;} public static void DoEvents(){} } }'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/omi-launcher.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'LAUNCHER_PARSE_FAILED'}
foreach($name in @('Stop-Services','Exit-Launcher','Invoke-OwnedBackendRestart','Restart-Services')){
    $node=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$false)
    . ([scriptblock]::Create($node.Extent.Text))
}
function Assert($value,$message){if(-not $value){throw $message}}
function Write-LauncherLog {}
function Publish-OmiRuntimeControlStatus {}
function Show-Message {throw 'UNEXPECTED_MODAL'}
function Restore-TrayIcon {}
function Assert-FrontendSafeStopAvailable {throw 'PREMATURE_FRONTEND_GATE'}
function Stop-BackendService {param($Deadline)$script:seenDeadline=$Deadline;$script:calls.Add('backend-stop')}
function Stop-FrontendService {param([switch]$RequireSafeStop)$script:calls.Add('frontend-stop')}
function Get-OmiOwnedBackendIdentity {return [pscustomobject]@{pid=123;created_at='old'}}
function Get-OmiBackendApplicationRelease {return 'fixture-release'}
function Assert-OmiSchemaRecoveryAdmission {}
function Assert-OmiManualBackendStartOwner {}
function Assert-OmiBackendApplicationRelease {param($ExpectedRelease) Assert ($ExpectedRelease -eq 'fixture-release') 'TARGET_RELEASE_LOST'}
function Assert-OmiSchemaCompatibility {param($ExpectedRelease) Assert ($ExpectedRelease -eq 'fixture-release') 'SCHEMA_RELEASE_LOST'}
function Start-OmiBackendAfterExactStop {
    param($ExpectedRelease)
    $script:calls.Add('backend-start')
    if($script:failStart){throw 'FIXTURE_STARTUP_FAILURE'}
    $script:OwnedBackendSession.Terminal=$false;$script:OwnedBackendSession.Alive=$true
    return [pscustomobject]@{pid=456;created_at='new'}
}
function Test-OmiRemoteRestartGeneration {throw 'WRITER_GATE_CALLED'}
$script:OwnsMutex=$true;$script:OwnedBackendStartAttempted=$true
$script:OwnedBackendRestartRequests=[Collections.Generic.HashSet[string]]::new()
$script:OwnedBackendSession=[pscustomobject]@{RunnerProcess=[object]::new();HasRetainedIdentity=$true;ChildPid=123;ChildCreated='old';
    Terminal=$true;Alive=$false;RestartBlocker='ALL_WRITERS_DRAIN_UNAVAILABLE';CanStartAfterStop=$true;StartupExitConfirmed=$false}
$script:BackendProcess=$script:OwnedBackendSession.RunnerProcess
$script:OwnedBackendSession | Add-Member ScriptMethod StopWithinDeadlineAsync {
    param($id,$release,$deadline)
    $script:seenDeadline=$deadline;$script:calls.Add('backend-stop')
    $this.Terminal=$true;$this.Alive=$false
    $evidence=[pscustomobject]@{RequestId=$id;BeforePid=123;BeforeCreated='old';State='forced_stopped';Reason='HARD_CUTOFF_EXACT_OWNED_EXIT';
        Forced=$true;ForcedExitConfirmed=$true;ExactExit=$false;Rearmed=$false;StopNotSent=$false;PreflightStage='JOB_QUIESCENCE'}
    $t=[Threading.Tasks.TaskCompletionSource[object]]::new();$t.SetResult($evidence);return $t.Task
}
foreach($case in @('stop-services','exit','backend-restart','startup-failure','remote-restart','full-restart')){
    $script:OwnedBackendSession.Terminal=$false;$script:OwnedBackendSession.Alive=$true
    $script:calls=[Collections.Generic.List[string]]::new();$script:failStart=$case -eq 'startup-failure'
    $script:IsShuttingDown=$false;$script:ServiceStopInProgress=$false;$script:ServiceStartRequestInProgress=$false
    $script:RuntimeControlInProgress=$false;$script:SafeStopAttempted=$false;$script:LauncherExitReady=$false
    $deadline=[Omi.OwnedShutdown.LifecycleDeadline]::new();$script:seenDeadline=$null
    if($case -eq 'stop-services'){Stop-Services -Deadline $deadline;Assert ([object]::ReferenceEquals($deadline,$script:seenDeadline)) 'STOP_DEADLINE_RESET'}
    elseif($case -eq 'exit'){Exit-Launcher -Reason fixture;Assert $script:LauncherExitReady 'EXIT_DID_NOT_CLOSE'}
    elseif($case -eq 'full-restart'){
        function Restart-Frontend {$script:calls.Add('frontend-restart')}
        function Test-HttpOk {return $true}
        function Test-FrontendOk {return $true}
        function Assert-FrontendRunnerIdentity {}
        $script:OwnedBackendSession|Add-Member ScriptMethod VerifyReadiness {return $true} -Force
        Restart-Services
        Assert ($script:LastFullServiceRestart.State -eq 'succeeded') 'FULL_RESTART_FAILED'
    }else{
        $id=[guid]::NewGuid().ToString('D');$caught=''
        $script:RuntimeController=[pscustomobject]@{Deadline=$deadline;Completed=$false}
        $script:RuntimeController|Add-Member ScriptMethod OwnedRestartDeadline {param($id)return $this.Deadline}
        $script:RuntimeController|Add-Member ScriptMethod BeginAuthenticatedOwnedRestart {param($id,$identity)return $true}
        $script:RuntimeController|Add-Member ScriptMethod CompleteOwnedRestart {param($id,$stop,$next,$verified)$this.Completed=$true}
        try{Invoke-OwnedBackendRestart -RequestId $id -Deadline $deadline -RemoteRequest:($case -eq 'remote-restart')}catch{$caught=$_.Exception.Message}
        Assert ([object]::ReferenceEquals($deadline,$script:seenDeadline)) 'RESTART_DEADLINE_RESET'
        if($case -eq 'startup-failure'){Assert ($caught -eq 'FIXTURE_STARTUP_FAILURE' -and $script:LastBackendRestart.State -ne 'succeeded') 'START_FAILURE_FALSE_SUCCESS'}
        else{Assert (-not $caught -and $script:LastBackendRestart.State -eq 'succeeded') "RESTART_FAILED $caught"}
    }
    $expected=switch($case){'stop-services'{'backend-stop,frontend-stop'} 'exit'{'backend-stop,frontend-stop'} 'full-restart'{'backend-stop,backend-start,frontend-restart'} default{'backend-stop,backend-start'}}
    Assert (($script:calls -join ',') -ceq $expected) "WRONG_ACTION_SCOPE $case $($script:calls -join ',')"
    "PASS routing-$case"
}
