param([string]$OutputRoot=(Join-Path $env:TEMP ('omi-update-cutoff-'+[guid]::NewGuid().ToString('N'))))
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '..\apply-omi-update.ps1')
$realScope=${function:Get-OmiScopedChildRole}
function Assert($value,$message){if(-not $value){throw $message}}
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python=@(Get-Content -Encoding UTF8 (Join-Path $repo '.venv/pyvenv.cfg') | Where-Object {$_ -like 'executable = *'})[0].Substring(13)
function Get-OmiScopedChildRole { param($Row,$Parent,$Identity)
    if($Row.ProcessId -eq $script:fixtureChild.Id){return 'backend_app'}
    return $null
}
$shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach($case in @('graceful','blocked','owner-mismatch','startup-failure','new-owner-unverified')){
    $root=Join-Path $OutputRoot $case
    $null=New-Item -ItemType Directory -Path (Join-Path $root ('logs\'+(Get-Date -Format 'yyyy-MM-dd'))) -Force
    $name='omi-update-cutoff-'+[guid]::NewGuid().ToString('N')
    $mode=if($case -eq 'graceful'){'graceful'}else{'blocked'}
    $fixtureOwner=Start-Process -FilePath $shell -ArgumentList ('-NoProfile -File "{0}" -Name {1} -Root "{2}" -Mode {3} -Python "{4}"' -f
        (Join-Path $PSScriptRoot 'update-owner-fixture.ps1'),$name,$root,$mode,$python) -WindowStyle Hidden -PassThru
    $null=$fixtureOwner.Handle
    $unrelated=Start-Process -FilePath $python -ArgumentList '-c "import time; time.sleep(30)"' -WindowStyle Hidden -PassThru
    $null=$unrelated.Handle
    $child=$null;$foreign=$null;$captured=$null;$script:launches=0;$errorText=''
    try{
        $clock=[Diagnostics.Stopwatch]::StartNew()
        while(-not(Test-Path -LiteralPath (Join-Path $root 'ready')) -and $clock.ElapsedMilliseconds -lt 5000){Start-Sleep -Milliseconds 30}
        Assert (Test-Path -LiteralPath (Join-Path $root 'ready')) 'FIXTURE_NOT_READY'
        $child=[Diagnostics.Process]::GetProcessById([int](Get-Content -LiteralPath (Join-Path $root 'ready')));$null=$child.Handle
        $script:fixtureChild=$child
        $foreign=[Diagnostics.Process]::GetProcessById([int](Get-Content -LiteralPath (Join-Path $root 'foreign')));$null=$foreign.Handle
        try{
            $result=Invoke-OmiApplyUpdate -LogRoot (Join-Path $root 'logs') -TimeoutSeconds 2 -MutexName $name -ExitEventName "$name.Exit" -CaptureOwner {
                $rows=@(Get-OmiCutoffSnapshot);$row=@($rows|Where-Object{$_.ProcessId -eq $fixtureOwner.Id})[0]
                $script:captured=[pscustomobject]@{Process=$fixtureOwner;Pid=$fixtureOwner.Id;Created=$fixtureOwner.StartTime.ToUniversalTime();CommandLine=$row.CommandLine;ExecutablePath=$row.ExecutablePath;Nodes=@();Repo=$repo;RootRole='launcher'}
                $script:captured.Nodes=@(Get-OmiCutoffTree $script:captured $rows)
                if($case -eq 'owner-mismatch'){$script:captured.CommandLine='different-generation'}
                return $script:captured
            } -Launch {
                $script:launches++
                Assert ($fixtureOwner.HasExited -and $child.HasExited) 'LAUNCHED_BEFORE_OLD_TREE_EXIT'
                if($case -eq 'startup-failure'){throw 'FIXTURE_STARTUP_FAILURE'}
            } -VerifySuccessor {
                if($case -eq 'new-owner-unverified'){return $null}
                return @{fixture='new-generation-and-ready'}
            }
        }catch{$errorText=$_.Exception.Message; if($case -eq 'graceful'){Write-Output $_.ScriptStackTrace}}
        Assert (-not $unrelated.HasExited) 'UNRELATED_PROCESS_KILLED'
        Assert (-not $foreign.HasExited) 'FOREIGN_DESCENDANT_KILLED'
        if($case -eq 'owner-mismatch'){
            Assert ($errorText -like '*GENERATION_MISMATCH*' -and $script:launches -eq 0) 'MISMATCH_ACCEPTED'
            Assert (-not $fixtureOwner.HasExited -and -not $child.HasExited) 'MISMATCH_KILLED'
        }elseif($case -eq 'startup-failure'){
            Assert ($errorText -like '*FIXTURE_STARTUP_FAILURE*' -and $script:launches -eq 1) 'START_FAILURE_HIDDEN'
        }else{
            Assert (-not $errorText) "$case $errorText"
            Assert ($script:launches -eq 1) 'MULTIPLE_STARTS'
            if($case -eq 'new-owner-unverified'){Assert ($result.status -eq 'NEW_START_UNVERIFIED' -and $result.services_ready -eq 'UNAVAILABLE') 'FALSE_READY'}
            else{
                Assert ($result.status -eq 'UPDATE_BACKEND_READY') 'SUCCESS_PATH_NOT_REACHED'
                Assert ($result.frontend_readiness -eq 'UNVERIFIED' -and $result.services_ready -ne 'VERIFIED') 'FALSE_FRONTEND_READY'
            }
            if($case -eq 'graceful'){Assert ($result.stop_kind -eq 'GRACEFUL') 'GRACEFUL_LOST'}
            else{Assert ($result.stop_kind -eq 'HARD_CUTOFF' -and $result.recovery_state -eq 'RECONCILIATION_REQUIRED') 'FORCE_FALSE_GRACEFUL'}
        }
        $files=@(Get-ChildItem -LiteralPath (Join-Path $root 'logs\updates') -Filter '*.json')
        Assert ($files.Count -eq 1) 'MISSING_RECEIPT'
        $saved=Get-Content -Raw -Encoding UTF8 $files[0].FullName|ConvertFrom-Json
        if($case -eq 'startup-failure'){Assert ($saved.old_owner_stop -eq 'FORCED_EXIT_CONFIRMED' -and $saved.services_ready -eq 'UNAVAILABLE') 'LOST_STOP_ON_START_FAILURE'}
        "PASS update-$case"
    }finally{
        foreach($p in @($fixtureOwner,$child,$foreign,$unrelated)){
            if($null -ne $p){try{if(-not $p.HasExited){$p.Kill();$null=$p.WaitForExit(2000)}}catch{};$p.Dispose()}
        }
    }
}

$scopeIdentity=[pscustomobject]@{Repo=$repo;Pid=111}
foreach($foreignExe in @('chrome.exe','msedge.exe','explorer.exe','other-service.exe')){
    $row=[pscustomobject]@{ExecutablePath=('C:\foreign\'+$foreignExe);CommandLine=('"C:\foreign\'+$foreignExe+'" https://example.invalid')}
    Assert ($null -eq (& $realScope $row ([pscustomobject]@{Role='launcher'}) $scopeIdentity)) 'FOREIGN_LAUNCHER_CHILD_SCOPE'
    Assert ($null -eq (& $realScope $row ([pscustomobject]@{Role='frontend_app'}) $scopeIdentity)) 'FOREIGN_APP_CHILD_SCOPE'
}
'PASS foreign-browser-scope'

# Execute the actual production verifier with private observations/HTTP doubles.
# No request reaches a live endpoint. Assert exact URLs and identity after readyz.
$script:httpCalls=0;$script:observations=0;$script:verifierCase='ready'
$created=[DateTime]::UtcNow.AddSeconds(-1)
function Get-OmiUpdateOwner {
    $p=[pscustomobject]@{HasExited=$false};$p|Add-Member ScriptMethod Dispose {}
    return [pscustomobject]@{Pid=222;Created=$created;Process=$p;Nodes=@()}
}
function Read-OmiUpdateOwnerStatus {
    $script:observations++
    $pidValue=if($script:verifierCase -eq 'changed-after-ready' -and $script:observations -gt 1){444}else{333}
    return [pscustomobject]@{owner_id='owner';loaded_lifecycle_source_id='lifecycle';application_release_id='application';
        backend=[pscustomobject]@{pid=$pidValue;created_at=$created.ToString('o');identity='PROCESS_IDENTITY';selected_host='127.0.0.1';selected_port=18400}}
}
function Invoke-RestMethod {
    param($Uri,$TimeoutSec,$MaximumRedirection)
    Assert ($Uri -ceq 'http://127.0.0.1:18400/api/system/runtime-control/status') 'WRONG_STATUS_ROUTE'
    $script:httpCalls++
    if($script:verifierCase -eq '404'){
        $error=[Exception]::new('fixture 404');$error|Add-Member NoteProperty Response ([pscustomobject]@{StatusCode=404});throw $error
    }
    $childId=if($script:verifierCase -eq 'wrong-child'){999}else{333}
    return [pscustomobject]@{owner_id='owner';serving_backend=[pscustomobject]@{runtime_started=$true;
        owned_start=[pscustomobject]@{release_id='application';child_pid=$childId;child_created=[string]$created.ToFileTimeUtc();host='127.0.0.1';port=18400}}}
}
function Invoke-WebRequest {
    param($Uri,$TimeoutSec,$MaximumRedirection,[switch]$UseBasicParsing)
    Assert ($Uri -ceq 'http://127.0.0.1:18400/api/system/readyz') 'WRONG_READYZ_ROUTE'
    return [pscustomobject]@{StatusCode=200}
}
foreach($case in @('ready','wrong-child','changed-after-ready','404')){
    $script:verifierCase=$case;$script:observations=0;$caught='';$result=$null
    try{$result=Wait-OmiUpdateSuccessor -Repo $repo -OldIdentity ([pscustomobject]@{Pid=111;Created=$created.AddSeconds(-5)}) -ExpectedLifecycle lifecycle -ExpectedApplication application -ObservationMilliseconds 100}
    catch{$caught=$_.Exception.Message}
    if($case -eq 'ready'){Assert ($null -ne $result -and $script:observations -eq 2) 'VERIFIER_SUCCESS_FAILED'}
    elseif($case -eq '404'){Assert ($caught -like '*UPDATE_VERIFIER_ROUTE_NOT_FOUND*') '404_SWALLOWED'}
    else{Assert ($null -eq $result -and -not $caught) 'VERIFIER_FALSE_SUCCESS'}
    "PASS verifier-$case"
}
"Evidence: $OutputRoot"
