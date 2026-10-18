param([Parameter(Mandatory = $true)][string]$OutputRoot, [string]$Scenario = 'normal', [string]$Fault = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../omi-runtime-control.ps1')
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python = @(Get-Content (Join-Path $repo '.venv/pyvenv.cfg') | Where-Object { $_ -match '^executable = ' })[0].Substring(13)
$session = New-OmiDisposableOwnedBackend -OutputRoot $OutputRoot -Python $python -Scenario $Scenario
try {
    # Persist public identity for the outer test's independent retained child handle.
    $identity = $session.Identity
    $public = @{}
    foreach ($key in $identity.Keys) { if ($key -ne 'nonce') { $public[$key] = $identity[$key] } }
    $public | ConvertTo-Json -Compress | Set-Content (Join-Path $OutputRoot 'public-identity.tmp') -Encoding UTF8
    [IO.File]::Move((Join-Path $OutputRoot 'public-identity.tmp'), (Join-Path $OutputRoot 'public-identity.json'))
    if ($Fault -eq 'owner-crash') { Start-Sleep -Milliseconds 150; [Environment]::Exit(77) }
    if ($Fault -eq 'owner-absence') {
        $session.Disconnect()
    } else {
        $id = [Guid]::NewGuid().ToString()
        $approvalId = if ($Fault -eq 'approval-missing') { [Guid]::NewGuid().ToString() } else { $id }
        $result = $session.StopDisposable($id, $approvalId, $Fault)
        $replay = $session.StopDisposable($id, $approvalId, $Fault)
        if ($Fault -eq 'approval-missing') {
            $lateApproval = $session.StopDisposable($id, $id, '')
            if ($lateApproval['reason'] -ne 'INDEPENDENT_APPROVAL_MISSING') { throw 'REJECTED_UUID_REPLAYED_WITH_NEW_AUTHORITY' }
        }
        if ($result['state'] -eq 'SUCCEEDED_DISPOSABLE') {
            $nextId = [Guid]::NewGuid().ToString()
            $next = $session.StopDisposable($nextId, $nextId, '')
            if ($next['reason'] -ne 'TERMINAL_NO_REPLAY') { throw 'NEW_UUID_REARMED_TERMINAL_RUNNER' }
        }
        $result.Remove('nonce') | Out-Null
        $replay.Remove('nonce') | Out-Null
        @{ result = $result; replay = $replay } | ConvertTo-Json -Depth 5 -Compress |
            Set-Content (Join-Path $OutputRoot 'launcher-receipt.json') -Encoding UTF8
        if ($Fault -eq 'approval-missing') { $session.Disconnect() }
    }
    if (-not $session.WaitForExit(15000)) { throw 'RUNNER_EXIT_UNPROVEN_NO_FORCE_CLEANUP' }
} finally { $session.Dispose() }
