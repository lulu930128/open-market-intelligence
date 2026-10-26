# Pure checkpoint model, not an executable lifecycle controller.
# No process lookup, signal, named IPC, restart or force fallback is implemented.
function Get-R1DGracefulStopCheckpoint {
    param([Parameter(Mandatory=$true)]$Evidence)
    $reason = 'OS_TRANSPORT_UNVERIFIED'
    $checkpoint = 'BLOCKED'
    if (-not $Evidence.IdentityKnown -or $Evidence.ChildPid -le 0 -or -not $Evidence.ChildStart) {
        $reason = 'IDENTITY_UNKNOWN'
    } elseif ($Evidence.DeadlineExpired) {
        $reason = 'DEADLINE_EXCEEDED'
    } elseif ($Evidence.Forced -or $Evidence.Crashed) {
        $reason = 'UNCLEAN_EXIT'
    } elseif (-not $Evidence.StopIntentLatched -or -not $Evidence.RespawnInhibited) {
        $reason = 'RUNNER_MAY_RESPAWN'
    } elseif (-not $Evidence.TransportVerified) {
        $reason = 'OS_TRANSPORT_UNVERIFIED'
    } elseif (-not $Evidence.AuthenticatedAck -or
              $Evidence.AckPid -ne $Evidence.ChildPid -or
              $Evidence.AckStart -ne $Evidence.ChildStart -or
              $Evidence.AckInstance -ne $Evidence.Instance) {
        $reason = 'ACK_IDENTITY_MISMATCH'
    } elseif (-not $Evidence.AllWritersCovered -or -not $Evidence.AllWritersDrained) {
        $reason = 'WRITER_COVERAGE_INCOMPLETE'
    } elseif (-not $Evidence.ExactProcessExited) {
        $reason = 'EXIT_UNCONFIRMED'
    } else {
        $checkpoint = 'CONTRACT_SATISFIED_SIMULATION_ONLY'
        $reason = 'SIMULATED_EVIDENCE_ONLY'
    }
    [pscustomobject]@{
        Scope = 'MOCK_ONLY'
        Checkpoint = $checkpoint
        Reason = $reason
        ProductionGate = 'BLOCKED'
        SignalAction = 'NONE'
        ForceFallback = $false
        RestartAuthorized = $false
    }
}
