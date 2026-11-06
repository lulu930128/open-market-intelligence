param([ValidateSet('Start','Stop','Status')][string]$Action = 'Status',
    [string]$RequestId = ([Guid]::NewGuid().ToString('D')))
$ErrorActionPreference = 'Stop'
# A fixed semantic client. Never starts a Launcher, supervisor, SDK or Backend.
# The existing desktop owner must already have adopted the deployment source.
try {
    $RequestId = [Guid]::ParseExact($RequestId, 'D').ToString('D')
    $repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    Add-Type -Path @((Join-Path $PSScriptRoot 'OmiRuntimeControl.cs'), (Join-Path $PSScriptRoot 'OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
    . (Join-Path $PSScriptRoot 'apply-omi-update.ps1')
    $identity = Get-OmiUpdateOwner -Repo $repo
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $suffix = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($repo.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24) }
        finally { $sha.Dispose() }
        $pipe = "omi-runtime-$suffix"
        $status = [Omi.RuntimeControl.Controller]::ReadOwnerStatus($pipe, $identity.Process) | ConvertFrom-Json
        if (-not $status.owner_id) { throw 'EXECUTION_OWNER_NOT_CURRENT' }
        $message = @{action="Execution$Action";request_id=$RequestId;expected_owner_id=$status.owner_id;token=''} | ConvertTo-Json -Compress
        $result = [Omi.RuntimeControl.Controller]::RequestOwner($pipe, $identity.Process, $message) | ConvertFrom-Json
        if ($result.schema -cne 'omi.launcher.execution.v1' -or $result.owner_id -cne $status.owner_id -or $result.request_id -cne $RequestId) {
            throw 'EXECUTION_OWNER_NOT_ADOPTED'
        }
        $result | ConvertTo-Json -Depth 6 -Compress
        if ($result.state -in @('UNKNOWN','BLOCKED')) { exit 2 }
    } finally { foreach ($node in $identity.Nodes) { $node.Process.Dispose() } }
} catch {
    # No exception text, config, credentials, alternate launch or implicit retry.
    '{"schema":"omi.launcher.execution.v1","state":"UNKNOWN","reason":"EXECUTION_OWNER_UNAVAILABLE_OR_NOT_ADOPTED"}'
    exit 2
}
