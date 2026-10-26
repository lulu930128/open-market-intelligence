param([Parameter(Mandatory = $true)][string]$FixtureRoot, [switch]$PipeFixture,
    [int]$BackendFixturePid = 0, [switch]$StaleClientIdentity)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Add-Type -Path @((Join-Path $repo 'scripts/OmiRuntimeControl.cs'), (Join-Path $repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions', 'System.Core', 'System.Windows.Forms')
foreach ($name in @('scripts/omi-launcher.ps1', 'scripts/omi-runtime-control.ps1')) {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $name), [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw 'POWERSHELL_SYNTAX_FAILED' }
}
function Assert($condition, $message) { if (-not $condition) { throw $message } }
function Identity([int]$number, [string]$created) {
    $identity = [Omi.RuntimeControl.Identity]::new(); $identity.pid = $number; $identity.created_at = $created; return $identity
}
function Request($controller, $id, $owner, $tokenValue, $action = 'RestartBackend') {
    return ($controller.Dispatch((@{ action = $action; request_id = $id; expected_owner_id = $owner; token = $tokenValue } |
        ConvertTo-Json -Compress)) | ConvertFrom-Json)
}
function Read($controller, $id) { return (Request $controller $id $null $null 'ReadOperation') }
$before = Identity 100 '2026-10-14T00:00:00Z'
$after = Identity 200 '2026-10-14T01:00:00Z'
# Synthetic token only, never printed or stored.
$token = 'a' * 64
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token)))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($PipeFixture) {
    # Only the disposable Python test client is attested here, never an OMI service.
    if ($BackendFixturePid -le 0) { throw 'Fixture Python client required' }
    $client = [Diagnostics.Process]::GetProcessById($BackendFixturePid)
    $before = Identity $client.Id $client.StartTime.ToUniversalTime().ToString('o')
    if ($StaleClientIdentity) { $before.created_at = '2000-01-01T00:00:00Z' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $suffix = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($FixtureRoot.ToLowerInvariant())))).Replace('-', '').ToLowerInvariant().Substring(0, 24) }
    finally { $sha.Dispose() }
    $fixture = [Omi.RuntimeControl.Controller]::new($FixtureRoot, $hash, "omi-runtime-$suffix")
    try {
        $fixture.Publish('{"restart":{"available":true}}', $before, $true)
        $fixture.Start()
        . (Join-Path $repo 'scripts/omi-runtime-control.ps1')
        function Get-OmiOwnedBackendIdentity { return $before }
        function Stop-BackendService { throw 'REAL_STOP_FORBIDDEN' }
        function Start-Backend { throw 'REAL_START_FORBIDDEN' }
        $script:RuntimeController = $fixture
        @{ pid = $PID; created = [string]([Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().ToFileTimeUtc()); owner_id = $fixture.OwnerId } | ConvertTo-Json -Compress
        while (($command = [Console]::ReadLine()) -ne 'done' -and $null -ne $command) {
            if ($command -eq 'tick' -or $command -eq 'tick-stale') {
                $requestId = $fixture.TakePending()
                if ($command -eq 'tick-stale') { $before = Identity $before.pid '2000-01-01T00:00:00Z' }
                if ($null -ne $requestId) { Restart-Backend -RequestId $requestId }
                'TICK_COMPLETE'
            } else { throw 'Unsupported fixture command' }
        }
    } finally { $fixture.Dispose() }
    exit 0
}

# All positive intents use the real OS-authenticated pipe, pinned to this fixture.
$process = [Diagnostics.Process]::GetCurrentProcess()
$before = Identity $process.Id $process.StartTime.ToUniversalTime().ToString('o')
$pipeName = 'omi-fixture-' + [Guid]::NewGuid().ToString('N')
$controller = [Omi.RuntimeControl.Controller]::new($FixtureRoot, $hash, $pipeName)
$report = @{schema='omi.restart-preflight.v1';runtime_started=$true;registered_drain_state='NOT_REQUESTED';all_writers_drained=$false;unknown_writer_count=3} | ConvertTo-Json -Compress
function Submit($id, $owner = $controller.OwnerId, $credential = $token, $preflight = $report) {
    $message = @{action='RestartBackend';request_id=$id;expected_owner_id=$owner;token=$credential}
    if ($null -ne $preflight) { $message.backend_preflight = $preflight }
    $client = [IO.Pipes.NamedPipeClientStream]::new('.', $pipeName, [IO.Pipes.PipeDirection]::InOut)
    try {
        $client.Connect(1500)
        $writer = [IO.StreamWriter]::new($client); $writer.AutoFlush=$true
        $reader = [IO.StreamReader]::new($client)
        $writer.WriteLine(($message | ConvertTo-Json -Compress))
        return ($reader.ReadLine() | ConvertFrom-Json)
    } finally { $client.Dispose() }
}
function Fresh { $controller.Publish('{"restart":{"available":true}}', $before, $true) }
function NewId { return [Guid]::NewGuid().ToString('D') }
try {
    $controller.Start(); Fresh
    $id=NewId
    Assert ((Submit $id $controller.OwnerId ('b'*64)).error -eq 'RUNTIME_CONTROL_FORBIDDEN') 'forged credential'
    Assert ((Read $controller $id).reason -eq 'NOT_FOUND') 'forbidden persisted'
    Assert ((Submit $id (NewId)).reason -eq 'OWNER_MISMATCH') 'forged owner'
    foreach ($bad in @($null, '{}', ($report.Replace('true','"true"')))) {
        $id=NewId; $receipt=Submit $id $controller.OwnerId $token $bad
        Assert ($receipt.state -eq 'accepted') 'optional preflight blocked intent'
        Assert ($controller.TakePending() -eq $id) 'optional preflight not queued'
        Assert ($controller.BeginAuthenticatedOwnedRestart($id,$before)) 'optional preflight blocked begin'
        $controller.CompleteOwnedRestart($id,$null,$null,$null)
    }
    $id=NewId
    Assert ((Request $controller $id $controller.OwnerId $token).state -eq 'blocked') 'public Dispatch bypass'
    Assert (-not $controller.BeginAuthenticatedOwnedRestart($id,$before)) 'unbound begin'
    foreach ($extra in @('local_approval','owner_approval','all_writers_drained')) {
        $id=NewId
        $request=@{action='RestartBackend';request_id=$id;expected_owner_id=$controller.OwnerId;token=$token}
        $request[$extra]=$true
        $null=$controller.Dispatch(($request|ConvertTo-Json -Compress))
        Assert ((Read $controller $id).reason -eq 'NOT_FOUND') 'extra authority persisted'
    }
    foreach ($scenario in @('success','wrong-pid','wrong-created','expired','stale-status','owner-lost','generation','unavailable','historical','save-failure')) {
        Fresh; $id=NewId; $accepted=Submit $id
        Assert ($accepted.state -eq 'accepted' -and $null -eq $accepted.local_approval) 'authenticated accept'
        Assert (-not $controller.BeginAuthenticatedOwnedRestart($id,$before)) 'must TakePending first'
        Assert ((Submit (NewId)).reason -eq 'BUSY') 'singleton busy'
        Assert ((Submit $id).updated_at -eq $accepted.updated_at) 'accepted replay'
        Assert ($controller.TakePending() -eq $id -and $null -eq $controller.TakePending()) 'single handoff'
        $current=Identity $before.pid $before.created_at
        if ($scenario -eq 'wrong-pid') {$current.pid=1}
        if ($scenario -eq 'wrong-created') {$current.created_at='2000-01-01T00:00:00Z'}
        if ($scenario -eq 'expired') {
            $clock=[Omi.OwnedShutdown.LifecycleDeadline].GetConstructor('NonPublic,Instance',$null,[type[]]@([int]),$null).Invoke(@(0))
            [Omi.RuntimeControl.Controller].GetField('operationDeadline','NonPublic,Instance').SetValue($controller,$clock)
        }
        if ($scenario -eq 'stale-status') {[Omi.RuntimeControl.Controller].GetField('published','NonPublic,Instance').SetValue($controller,[DateTime]::UtcNow.AddSeconds(-16))}
        if ($scenario -eq 'owner-lost') {$controller.Publish('{"restart":{"available":true}}',$before,$false)}
        if ($scenario -eq 'generation') {$controller.Publish('{"restart":{"available":true}}',(Identity $before.pid '2000-01-01T00:00:00Z'),$true)}
        if ($scenario -eq 'unavailable') {$controller.Publish('{"restart":{"available":false}}',$before,$true)}
        $file=Join-Path $FixtureRoot "$id.json"
        if ($scenario -eq 'historical') {
            $old=Read $controller $id
            $old.local_approval=@{issuer='launcher_local_ui';decision='approved';expires_at=[DateTime]::UtcNow.AddMinutes(1).ToString('o');consumed_at=$null}
            [IO.File]::WriteAllText($file,($old|ConvertTo-Json -Depth 8 -Compress))
        }
        if ($scenario -eq 'save-failure') {
            # Reads succeed, atomic Replace fails; consumed memory authority cannot retry.
            $locked=[IO.File]::Open($file,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            try { $threw=$false; try {$null=$controller.BeginAuthenticatedOwnedRestart($id,$current)} catch {$threw=$true}; Assert $threw 'write failure not raised' }
            finally {$locked.Dispose()}
            Assert (-not $controller.BeginAuthenticatedOwnedRestart($id,$current)) 'ambiguous save replay'
            $controller.BlockOwnedRestart($id,'STORE_UNAVAILABLE')
        } else {
            $begun=$controller.BeginAuthenticatedOwnedRestart($id,$current)
            Assert ($begun -eq ($scenario -in @('success','expired','stale-status','unavailable'))) $scenario
        }
        if ($scenario -in @('success','expired','stale-status','unavailable')) {
            $running=Read $controller $id
            Assert ($running.state -eq 'running' -and $null -eq $running.local_approval) 'running durable without fake approval'
            Assert (-not $controller.BeginAuthenticatedOwnedRestart($id,$current)) 'running replay'
            $controller.CompleteOwnedRestart($id,$null,$null,$null)
            Assert ((Read $controller $id).state -eq 'unknown') 'missing lifecycle evidence'
        }
        $terminal=Read $controller $id
        Assert ($terminal.state -in @('blocked','unknown')) 'fail closed'
        Assert ((Submit $id).updated_at -eq $terminal.updated_at) 'terminal replay'
        Assert ($null -eq $controller.TakePending()) 'terminal queue'
    }
    # Old terminal approval receipts remain readable and cannot be revived.
    $historicalId=$id
    $old=Read $controller $historicalId
    $old.reason='OWNER_APPROVAL_REQUIRED';$old.state='blocked'
    $old.local_approval=@{issuer='launcher_local_ui';decision='denied';expires_at='2026-10-14T00:00:00Z';consumed_at=$null}
    [IO.File]::WriteAllText((Join-Path $FixtureRoot "$historicalId.json"),($old|ConvertTo-Json -Depth 8 -Compress))
    Assert ((Submit $historicalId).local_approval.decision -eq 'denied') 'historical denied receipt'
    Fresh; $id=NewId; $null=Submit $id; $oldOwner=$controller.OwnerId
} finally {$controller.Dispose()}
$recovered=[Omi.RuntimeControl.Controller]::new($FixtureRoot,$hash,('omi-recovered-'+(NewId)))
try {
    Assert ((Read $recovered $id).reason -eq 'CONTROLLER_RECOVERED_NO_REPLAY') 'recover accepted'
    Assert ($null -eq $recovered.TakePending()) 'recover cannot queue'
    Assert (-not $recovered.BeginAuthenticatedOwnedRestart($id,$before)) 'recover cannot begin'
    Assert ((Request $recovered $id $oldOwner $token).state -eq 'unknown') 'recover replay'
    Assert ((Read $recovered $historicalId).local_approval.decision -eq 'denied') 'historical compatibility'
    Assert ((Get-ChildItem -LiteralPath $FixtureRoot -Filter '*.tmp').Count -eq 0) 'atomic leftovers'
} finally {$recovered.Dispose()}
'CONTROLLER_FIXTURE_PASS'
