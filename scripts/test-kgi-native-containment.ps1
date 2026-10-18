<#
Read-only host capability inventory, NOT a containment attestation or issuer.
Does not create an AppContainer profile, child, firewall filter, ACL or service.
Never imports SDK/Settings or reads credential, CA, log or environment values.
Exit 2 is expected: no reviewed TEST target and no OMI native enforcer deployed.
#>
param()
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) {
    @{status='BLOCKED';reasonCodes=@('UNEXPECTED_ARGUMENTS');broker_calls=0;orders_sent=0} | ConvertTo-Json -Compress
    exit 2
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$observations = @()
foreach ($name in @('BFE','MpsSvc')) {
    try {
        $service = Get-Service -Name $name -ErrorAction Stop
        $observations += @{name=$name;status=[string]$service.Status;meaning='CAPABILITY_ONLY_NOT_POLICY_PROOF'}
    } catch {
        $observations += @{name=$name;status='UNVERIFIED';reason='SERVICE_QUERY_UNAVAILABLE'}
    }
}
$binaries = @()
foreach ($relative in @('url.cp312-win_amd64.pyd','pushClient/tradecom_windows_bridge64.dll')) {
    try {
        $fixed = Join-Path $repo ('.venv-kgi/Lib/site-packages/kgisuperpy/' + $relative)
        $item = Get-Item -LiteralPath $fixed -Force
        while ($null -ne $item) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'UNSAFE_PATH' }
            if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
        }
        # Hash only. WinVerifyTrust/Authenticode chain checks may fetch revocation
        # material; do not invoke them in an offline inventory.
        $digest = (Get-FileHash -LiteralPath $fixed -Algorithm SHA256).Hash
        $binaries += @{path=$relative;sha256=$digest;authenticode='NOT_QUERIED_OFFLINE';meaning='NOT_TEST_ENDPOINT_PROOF'}
    } catch {
        $binaries += @{path=$relative;status='UNVERIFIED';reason='FILE_HASH_QUERY_UNAVAILABLE'}
    }
}
@{
    schema='omi.kgi-windows-containment-inventory.v1';status='BLOCKED';origin='HOST_READONLY_INVENTORY'
    windows_version=[Environment]::OSVersion.Version.ToString();services=$observations;binaries=$binaries
    enforcement=@{owned_child='NOT_CREATED';job_token='UNVERIFIED';appcontainer='UNVERIFIED';wfp_rules='UNVERIFIED';filesystem='UNVERIFIED';redirect_fallback='UNVERIFIED'}
    reasonCodes=@('OFFICIAL_TEST_DESTINATION_ATTESTATION_MISSING','OWNED_WINDOWS_CONTAINMENT_ENFORCER_NOT_IMPLEMENTED')
    sdk_imported=$false;credential_values_read=$false;broker_calls=0;orders_sent=0
} | ConvertTo-Json -Depth 6 -Compress
exit 2
