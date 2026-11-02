param(
    [switch]$Execute, [switch]$Fixture,
    [string]$RequestId, [string]$OwnerId,
    [int]$OwnerPid, [string]$OwnerBirth,
    [int]$WorkerPid, [string]$WorkerBirth
)
$ErrorActionPreference='Stop'

# Manual operator command. Default is read-only; -Execute explicitly stops one worker.
# No retry, launcher stop/start, migration, private receipt access or owner admission.
function Invoke-ExactWorkerStop {
    param($Observed,$Expected,[scriptblock]$Stop,[scriptblock]$WaitExit,[scriptblock]$ReadDatabase,[switch]$InspectOnly)
    foreach($field in @('pid','birth','parent','image','command','owner_birth','owner_image','owner_command','owner_id','request_id')) {
        if ([string]$Observed.$field -cne [string]$Expected.$field) {throw "WORKER_IDENTITY_MISMATCH:$field"}
    }
    if ($InspectOnly) {
        $db=& $ReadDatabase
        return [pscustomobject]@{request_id=$Expected.request_id;worker_pid=$Expected.pid;
            worker_birth=$Expected.birth;identity='MATCHED';worker_exact_exit=$false;
            phase='READ_ONLY_OBSERVATION';migration_outcome='UNKNOWN';database=$db;
            next_action='Wait_or_explicit_operator_Execute';launcher_receipt=$false}
    }
    if ($Observed.operation_status -cne 'running') {throw 'ORIGINAL_OPERATION_NOT_RUNNING'}
    & $Stop
    $exitEvidence=& $WaitExit
    if ($exitEvidence.confirmed -cne $true) {throw 'WORKER_EXACT_EXIT_UNCONFIRMED'}
    # Process exit never implies commit or rollback; the DB is observed separately.
    $database=& $ReadDatabase
    $known=($database.known -ceq $true)
    [pscustomobject]@{request_id=$Expected.request_id;worker_pid=$Expected.pid;worker_birth=$Expected.birth;
        worker_exact_exit=$true;worker_exit_code=$exitEvidence.exit_code;migration_outcome='UNKNOWN';
        schema_revision_observed=$database.current;schema_head=$database.head;
        database_observation=if($known){'KNOWN_REVISION'}else{'UNKNOWN'};
        next_action=if($known){'Read_original_Launcher_Status_then_official_ApplyUpdate'}else{'Read_CheckStart_failure_no_update'};
        authority='user_authorized_os_stop';launcher_receipt=$false}
}

if ($Fixture) {
    $expected=@{pid=42;birth='birth';parent=7;image='python';command='ApplyStopped';
        owner_birth='owner-birth';owner_image='powershell';owner_command='Run';owner_id='owner';request_id='request'}
    $observed=$expected.Clone();$observed.operation_status='running';$cases=0
    foreach($field in $expected.Keys) {
        $bad=$observed.Clone();$bad[$field]='mismatch';$script:stopCalls=0
        try {Invoke-ExactWorkerStop $bad $expected {$script:stopCalls++} {} {};throw 'FIXTURE_UNEXPECTED_ALLOW'}
        catch {if($_.Exception.Message -cne "WORKER_IDENTITY_MISMATCH:$field"){throw}}
        if($script:stopCalls -ne 0){throw 'FIXTURE_STOP_BEFORE_IDENTITY'};$cases++
    }
    foreach($revision in @('20261025_0093','20261030_0095',$null)) {
        $script:stopCalls=0
        $result=Invoke-ExactWorkerStop $observed $expected {$script:stopCalls++} {
            @{confirmed=$true;exit_code=-1}
        } {@{current=$revision;head='20261030_0095';known=[bool]$revision}}
        if($script:stopCalls -ne 1 -or $result.migration_outcome -cne 'UNKNOWN' -or
            $result.worker_exact_exit -cne $true -or
            ($result.database_observation -ceq 'KNOWN_REVISION') -ne [bool]$revision){throw 'FIXTURE_FALSE_DATABASE_RESULT'}
        $cases++
    }
    try {Invoke-ExactWorkerStop $observed $expected {} {@{confirmed=$false}} {throw 'DB_READ_BEFORE_EXIT'};throw 'FIXTURE_EXIT_ALLOWED'}
    catch {if($_.Exception.Message -cne 'WORKER_EXACT_EXIT_UNCONFIRMED'){throw}};$cases++
    try {Invoke-ExactWorkerStop $observed $expected {throw [UnauthorizedAccessException]::new('fixture access denied')} {} {};throw 'FIXTURE_PERMISSION_ALLOWED'}
    catch {if($_.Exception -isnot [UnauthorizedAccessException]){throw}};$cases++
    $done=$observed.Clone();$done.operation_status='failed'
    try {Invoke-ExactWorkerStop $done $expected {throw 'STOPPED_TERMINAL_WORKER'} {} {};throw 'FIXTURE_TERMINAL_ALLOWED'}
    catch {if($_.Exception.Message -cne 'ORIGINAL_OPERATION_NOT_RUNNING'){throw}};$cases++
    $inspect=Invoke-ExactWorkerStop $observed $expected {throw 'INSPECT_STOPPED_PROCESS'} {} {@{current='head';head='head';known=$true}} -InspectOnly
    if($inspect.phase -cne 'READ_ONLY_OBSERVATION' -or $inspect.worker_exact_exit){throw 'FIXTURE_INSPECT_MUTATED'};$cases++
    [pscustomobject]@{fixture='PASS';cases=$cases;real_processes_stopped=0}|ConvertTo-Json -Compress
    exit 0
}

$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
foreach($required in @($RequestId,$OwnerId,$OwnerPid,$OwnerBirth,$WorkerPid,$WorkerBirth)) {
    if(-not $required){throw 'REQUEST_OWNER_AND_WORKER_IDENTITY_REQUIRED'}
}
$request=[Guid]::ParseExact($RequestId,'D').ToString('D')
$OwnerId=[Guid]::ParseExact($OwnerId,'D').ToString('D')
$null=[DateTime]::Parse($OwnerBirth);$null=[DateTime]::Parse($WorkerBirth)
$python=@(Get-Content (Join-Path $repo '.venv\pyvenv.cfg')|Where-Object {$_ -like 'executable = *'})[0].Substring(13)
$receiptDirectory=Join-Path $repo ('logs\launcher\'+(Get-Date -Format 'yyyy-MM-dd'))
$receiptPath=Join-Path $receiptDirectory ('schema-worker-exit-'+$request+'-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')+'.json')
function Read-OmiSchemaExitDatabase {
    $entry=Join-Path $repo 'scripts\omi-schema-maintenance.py'
    $proof=(& $python -I -S -B $entry CheckStart | Out-String)|ConvertFrom-Json
    $known=$proof.compatible -ceq $true
    if(-not $known){
        $behind=(& $python -I -S -B $entry CheckStart --upgrade | Out-String)|ConvertFrom-Json
        $known=$behind.compatible -ceq $true -and
            $behind.schema_generation.current -ceq $proof.schema_generation.current -and
            $behind.schema_generation.head -ceq $proof.schema_generation.head
    }
    @{current=$proof.schema_generation.current;head=$proof.schema_generation.head;known=[bool]$known}
}
$process=$null;$owner=$null
try {
    . (Join-Path $repo 'scripts\apply-omi-update.ps1')
    Add-Type -Path @((Join-Path $repo 'scripts\OmiRuntimeControl.cs'),(Join-Path $repo 'scripts\OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
    $owner=Get-OmiUpdateOwner -Repo $repo
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$suffix=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($repo.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24)}
    finally {$sha.Dispose()}
    $status=Read-OmiUpdateOwnerStatus ('omi-runtime-'+$suffix) $owner.Process
    $expected=@{pid=$WorkerPid;birth=$WorkerBirth;parent=$OwnerPid;image=$python;
        command=('"{0}" -I -S -B "{1}" ApplyStopped' -f $python,(Join-Path $repo 'scripts\omi-schema-maintenance.py'));
        owner_birth=$OwnerBirth;owner_image=(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe');
        owner_command=$owner.CommandLine;owner_id=$OwnerId;request_id=$request}
    $row=Get-CimInstance Win32_Process -Filter ("ProcessId="+$WorkerPid) -ErrorAction Stop
    if($null -eq $row){[pscustomobject]@{request_id=$request;worker_pid=$WorkerPid;action='NOT_STOPPED_ALREADY_ABSENT';worker_exact_exit=$false;migration_outcome='UNKNOWN';database=(Read-OmiSchemaExitDatabase);next_action='Read_original_Launcher_Status_then_official_ApplyUpdate';launcher_receipt=$false}|ConvertTo-Json -Depth 5 -Compress;exit 0}
    $process=[Diagnostics.Process]::GetProcessById($WorkerPid)
    $null=$process.Handle # Retain this exact process instance before any mutation.
    $ownerRow=Get-CimInstance Win32_Process -Filter ("ProcessId="+$OwnerPid) -ErrorAction Stop
    $observed=@{pid=$process.Id;birth=$process.StartTime.ToUniversalTime().ToString('o');parent=$row.ParentProcessId;
        image=$row.ExecutablePath;command=$row.CommandLine;owner_birth=$owner.Process.StartTime.ToUniversalTime().ToString('o');
        owner_image=$ownerRow.ExecutablePath;owner_command=$ownerRow.CommandLine;owner_id=$status.owner_id;
        request_id=$status.update_operation.request_id;operation_status=$status.update_operation.status}
    $result=Invoke-ExactWorkerStop $observed $expected {
        if($process.HasExited){return}
        $null=[IO.Directory]::CreateDirectory($receiptDirectory)
        [IO.File]::WriteAllText($receiptPath,(@{request_id=$request;worker_pid=$process.Id;worker_birth=$observed.birth;
            phase='AUTHORIZED_STOP_INTENT';migration_outcome='UNKNOWN';launcher_receipt=$false}|ConvertTo-Json))
        $process.Kill() # Only this retained Python process; never a tree or Launcher.
    } {
        $confirmed=$process.WaitForExit(15000) -and $process.HasExited
        @{confirmed=$confirmed;exit_code=$(if($confirmed){$process.ExitCode}else{$null})}
    } {Read-OmiSchemaExitDatabase} -InspectOnly:(-not $Execute)
    $result|Add-Member NoteProperty observed_at ([DateTime]::UtcNow.ToString('o'))
    if($Execute){[IO.File]::WriteAllText($receiptPath,($result|ConvertTo-Json -Depth 5))}
    $result|ConvertTo-Json -Depth 5 -Compress
} catch {
    $failure=[ordered]@{request_id=$request;phase='STOP_OR_READBACK_FAILED';error_type=$_.Exception.GetType().Name;
        error=$_.Exception.Message;migration_outcome='UNKNOWN';launcher_receipt=$false;
        worker_exact_exit=($null -ne $process -and $process.HasExited)}
    if($Execute){$null=[IO.Directory]::CreateDirectory($receiptDirectory);[IO.File]::WriteAllText($receiptPath,($failure|ConvertTo-Json -Depth 4))}
    $failure|ConvertTo-Json -Depth 4 -Compress
    exit 1
} finally {
    if($null -ne $process){$process.Dispose()}
    if($null -ne $owner){foreach($node in $owner.Nodes){$node.Process.Dispose()}}
}
