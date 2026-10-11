[CmdletBinding()]
param(
    [switch]$Smoke,
    [ValidatePattern('^[0-9]{4,6}[A-Z]?$')][string]$Symbol = '2330',
    [ValidateSet('BUY','SELL')][string]$Side = 'BUY',
    [int]$Shares = 1000,
    [ValidateSet('BOARD','ODD')][string]$Lot = 'BOARD',
    [ValidateSet('LIMIT','MARKET')][string]$OrderKind = 'LIMIT',
    [string]$LimitPrice = '25.50',
    [ValidateSet('CASH','MARGIN','SHORT_SELLING','LEND_SELLING')][string]$Funding = 'CASH',
    [ValidateSet('OPEN','CLOSE')][string]$PositionAction = 'OPEN'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Repository Python is required; no install attempted.' }
$process = New-Object System.Diagnostics.Process
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = $python
$symbols = @('2330','2317','2454','2303','2882','9998','9997','9996','9995', $Symbol) | Select-Object -Unique
$info.Arguments = '-B -m execution_manual_mock.runtime --symbols ' + ($symbols -join ',')
$info.WorkingDirectory = $repo
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
# Child-local TEMP only. Never modifies production or the user's environment.
$tempRoot = Join-Path $repo '.tmp'
[void][IO.Directory]::CreateDirectory($tempRoot)
$process.StartInfo = $info
$script:checks = 0
$started = $false

function Assert-Value($Condition, [string]$Code) {
    if (-not $Condition) { throw "SMOKE_ASSERTION_FAILED: $Code" }
    $script:checks++
}
function Invoke-Mock([string]$Method, [string]$Path, $Body = $null, $Preview = $null) {
    $headers = @{
        Authorization = 'Bearer ' + $script:bootstrap.session
        Origin = $script:bootstrap.origin
        'X-CSRF-Token' = $script:bootstrap.csrf
    }
    if ($null -ne $Preview) { $headers['X-Order-Access'] = $Preview.order_access }
    $parameters = @{
        Uri = $script:baseUri + $Path; Method = $Method; Headers = $headers
        ContentType = 'application/json'; UseBasicParsing = $true; TimeoutSec = 25
    }
    if ($null -ne $Body) { $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 12 -Compress }
    try { $raw = (Invoke-WebRequest @parameters).Content }
    catch {
        if ($null -eq $_.Exception.Response) { throw 'MOCK_TRANSPORT_FAILED; outcome unknown, never auto retry.' }
        $raw = $_.ErrorDetails.Message
        if ([string]::IsNullOrWhiteSpace($raw)) {
            $reader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
            try { $raw = $reader.ReadToEnd() } finally { $reader.Dispose() }
        }
    }
    $result = $raw | ConvertFrom-Json
    Assert-Value ($result.simulated -eq $true -and $result.broker_connected -eq $false) 'SYNTHETIC_ENVELOPE'
    return $result
}
function New-Draft([string]$Code, [string]$Request, [hashtable]$Changes = @{}) {
    $body = @{client_request_id=$Request; symbol=$Code; side='BUY'; quantity=1000; lot='BOARD'
        limit_price='25.50'; currency='TWD'; order_kind='LIMIT'; funding='CASH'
        contract_version=2; position_action='OPEN'}
    foreach ($key in $Changes.Keys) { $body[$key] = $Changes[$key] }
    return $body
}
function Show-Result([string]$Phase, [string]$Code, $Result) {
    $broker = $Result.data.broker
    [ordered]@{phase=$Phase; symbol=$Code; status=$Result.status; simulated=$true
        reasonCodes=@($Result.reasonCodes); order_id=$broker.order_id
        filled_shares=$broker.filled_shares; errcode=$broker.errcode; msg=$broker.msg} |
        ConvertTo-Json -Depth 8 -Compress | Write-Output
}
function Confirm-Mock($Preview) {
    $body = @{preview_id=$Preview.preview_id; token=$Preview.confirmation.token
        digest=$Preview.confirmation.digest; user_confirmed=$true}
    return Invoke-Mock 'POST' '/confirm' $body $Preview
}
function Act-Mock($Preview, [string]$Action) {
    return Invoke-Mock 'POST' ('/orders/' + $Preview.preview_id + '/' + $Action) @{user_confirmed=$true} $Preview
}

try {
    $started = $process.Start()
    $stderr = $process.StandardError.ReadToEndAsync()
    $ready = $process.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(15000)) { throw 'MOCK_START_TIMEOUT' }
    $script:bootstrap = $ready.Result | ConvertFrom-Json
    if ($null -eq $script:bootstrap -or $script:bootstrap.simulated -ne $true) { throw 'MOCK_START_FAILED' }
    $script:baseUri = 'http://127.0.0.1:' + $script:bootstrap.port + '/test-execution/v1'
    if ($Smoke) {
        foreach ($case in @(
            @{symbol='2330'; expected='BROKER_ACCEPTED'},
            @{symbol='2317'; expected='PENDING'},
            @{symbol='2454'; expected='BROKER_REJECTED'},
            @{symbol='2303'; expected='UNKNOWN'},
            @{symbol='2882'; expected='UNKNOWN'})) {
            $code = $case.symbol
            $result = Invoke-Mock 'POST' '/preview' (New-Draft $code ('smoke-' + $code))
            Assert-Value ($result.status -eq 'PREVIEWED' -and $result.data.status -eq 'READY') 'PREVIEW_READY'
            Show-Result 'PREVIEWED' $code $result
            $preview = $result.data
            $result = Confirm-Mock $preview
            Assert-Value ($result.data.phase -eq 'CONFIRMED' -and $result.status -eq 'PENDING') 'CONFIRMED_NOT_SENT'
            Show-Result 'CONFIRMED' $code $result
            $result = Act-Mock $preview 'submit'
            Assert-Value ($result.status -eq $case.expected) ('SUBMIT_' + $code)
            Show-Result 'SENT' $code $result
            if ($result.status -eq 'BROKER_ACCEPTED') {
                Assert-Value ($result.data.broker.order_id_verified -and $result.data.broker.filled_shares -eq 0) 'ACCEPT_IS_NOT_FILL'
            }
            if ($code -eq '2454') {
                Assert-Value ($result.data.broker.errcode -eq 'FAKE_REJECT' -and $result.data.broker.msg) 'REJECTION_DETAIL'
                continue
            }
            $query = Act-Mock $preview 'query'
            Show-Result 'QUERY' $code $query
            if ($code -ne '2330') {
                $result = Act-Mock $preview 'reconcile'
                Assert-Value ($result.status -eq $(if ($code -eq '2882') {'RECONCILING'} else {'BROKER_ACCEPTED'})) 'RECONCILE'
                Show-Result 'RECONCILE' $code $result
            }
            $read = Invoke-Mock 'GET' ('/orders/' + $preview.preview_id) $null $preview
            Show-Result 'STATUS' $code $read
            $repeat = Act-Mock $preview 'submit'
            Assert-Value ($repeat.data.broker.commands[0].mock_effects -eq 1) 'NO_RESEND'
            if ($code -eq '2882') { continue }
            $result = Act-Mock $preview 'cancel'
            Assert-Value ($result.status -eq 'CANCEL_PENDING') 'CANCEL_ACK_NOT_FINAL'
            Show-Result 'CANCEL_ACK' $code $result
            $result = Act-Mock $preview 'reconcile'
            Assert-Value ($result.status -eq 'CANCELLED') 'CANCEL_QUERY_FINAL'
            Show-Result 'CANCELLED' $code $result
        }
        foreach ($case in @(
            @{symbol='0000'; changes=@{}; reason='INSTRUMENT_UNVERIFIED'},
            @{symbol='9998'; changes=@{}; reason='NOT_TRADABLE'},
            @{symbol='9997'; changes=@{}; reason='EVIDENCE_EXPIRED_OR_NOT_YET_VALID'},
            @{symbol='9996'; changes=@{}; reason='PERMISSION_DENIED'},
            @{symbol='9995'; changes=@{}; reason='SESSION_NOT_OPEN'},
            @{symbol='2330'; changes=@{lot='ODD';quantity=17}; reason='LOT_UNVERIFIED'},
            @{symbol='2330'; changes=@{funding='MARGIN'}; reason='CREDIT_UNVERIFIED'})) {
            $result = Invoke-Mock 'POST' '/preview' (New-Draft $case.symbol ('deny-' + [guid]::NewGuid().ToString('N')) $case.changes)
            Assert-Value ($result.status -eq 'VALIDATION_BLOCKED' -and $result.reasonCodes -contains $case.reason) $case.reason
            Show-Result 'DENIED' $case.symbol $result
        }
        $result = Invoke-Mock 'POST' '/preview' (New-Draft '2330' 'market' @{order_kind='MARKET';limit_price=$null})
        Assert-Value ($result.status -eq 'PREVIEWED') 'MARKET_PREVIEW'
        $preview = $result.data
        [void](Confirm-Mock $preview)
        $result = Act-Mock $preview 'submit'
        Assert-Value ($result.status -eq 'BROKER_ACCEPTED') 'MARKET_ACCEPT'
        Show-Result 'MARKET_SENT' '2330' $result
        [void](Invoke-Mock 'POST' '/kill-switch' @{enabled=$false;user_confirmed=$true})
        $result = Invoke-Mock 'POST' '/preview' (New-Draft '2330' 'kill-test')
        Assert-Value ($result.reasonCodes -contains 'KILL_SWITCH_ACTIVE') 'KILL_SWITCH'
        [ordered]@{result='PASS'; assertions=$script:checks; source='isolated loopback HTTP + fake SDK'
            simulated=$true; runtime=$script:bootstrap.runtime; live_gate='BLOCKED'; frontend_gate='BLOCKED'} | ConvertTo-Json -Depth 6 -Compress
    } else {
        $price = if ($OrderKind -eq 'MARKET') { $null } else { $LimitPrice }
        $request = New-Draft $Symbol ([guid]::NewGuid().ToString('N')) @{
            side=$Side;quantity=$Shares;lot=$Lot;order_kind=$OrderKind;limit_price=$price
            funding=$Funding;position_action=$PositionAction}
        $result = Invoke-Mock 'POST' '/preview' $request
        if ($result.status -ne 'PREVIEWED') { Show-Result 'DENIED' $Symbol $result; return }
        $preview = $result.data
        # Display order, cost and constraints, never capability/token or account ID.
        [ordered]@{phase='PREVIEWED';status='READY';simulated=$true;draft=$preview.draft
            expense=$preview.expense;assessment=$preview.assessment;constraints=$preview.constraints
            warnings=$preview.warnings} | ConvertTo-Json -Depth 12 | Write-Output
        $answer = Read-Host 'SYNTHETIC ONLY. Type CONFIRM to confirm and send this exact fake order'
        if ($answer -cne 'CONFIRM') { Write-Output '{"status":"NOT_CONFIRMED","simulated":true}'; return }
        $result = Confirm-Mock $preview
        Show-Result 'CONFIRMED' $Symbol $result
        if ($result.status -ne 'PENDING') { return }
        $result = Act-Mock $preview 'submit'
        Show-Result 'SENT' $Symbol $result
        while ($true) {
            $action = Read-Host 'status / query / reconcile / CANCEL / exit (all SYNTHETIC)'
            if ($action -ceq 'exit') { break }
            if ($action -ceq 'status') {
                $result = Invoke-Mock 'GET' ('/orders/' + $preview.preview_id) $null $preview
            } elseif ($action -cin @('query','reconcile','CANCEL')) {
                $result = Act-Mock $preview $action.ToLowerInvariant()
            } else { continue }
            Show-Result $action $Symbol $result
        }
    }
} finally {
    if ($started -and -not $process.HasExited) {
        $process.StandardInput.WriteLine('STOP')
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(15000)) {
            # Only the exact test child we created; never port-owner cleanup.
            $process.Kill()
            $process.WaitForExit()
            throw 'MOCK_CHILD_STOP_TIMEOUT'
        }
    }
    if ($started -and $process.ExitCode -ne 0) { throw 'MOCK_CHILD_FAILED; inspect isolated test source.' }
    $process.Dispose()
}
