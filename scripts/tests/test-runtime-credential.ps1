param([Parameter(Mandatory = $true)][string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
$FixtureRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($FixtureRoot)
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
function Assert($condition, $message) { if (-not $condition) { throw $message } }
function Parse([string]$path) {
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    Assert ($errors.Count -eq 0) 'CREDENTIAL_FIXTURE_SYNTAX'
    return $ast
}
$source = Parse (Join-Path $repo 'scripts/omi-runtime-control.ps1')
$launcher = Parse (Join-Path $repo 'scripts/omi-launcher.ps1')
$null = Parse (Join-Path $repo 'scripts/run-service-logged.ps1')
$null = Parse $PSCommandPath
function Definition($ast, $name) {
    return $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true).Extent.Text
}
# No Launcher entry point is executed. Only the real initializer's Controller
# constructor is replaced: no persistent user directory or listener is opened.
. (Join-Path $repo 'scripts/omi-runtime-control.ps1')
Add-Type -TypeDefinition @'
public sealed class CredentialControllerFixture {
    public static string SeenHash;
    public static bool Started;
    public CredentialControllerFixture(string root, string hash, string name) {
        SeenHash = hash; Started = false;
    }
    public void Start() { Started = true; }
    public void Dispose() {}
}
'@
$initializer = Definition $source 'Initialize-OmiRuntimeControl'
Assert ($initializer.Contains('[Omi.RuntimeControl.Controller]::new')) 'CONSTRUCTOR_SEAM_MISSING'
$script:RuntimeSourceRoot = Join-Path $repo 'scripts'
Invoke-Expression ($initializer.Replace('[Omi.RuntimeControl.Controller]::new', '[CredentialControllerFixture]::new').Replace('$PSScriptRoot', '$script:RuntimeSourceRoot'))
function Get-OmiRuntimeControlUserHash {
    $script:UserReads++
    if ($script:UserThrows) { throw 'SYNTHETIC_USER_ACCESS_DENIED' }
    return $script:UserHash
}
function Publish-OmiRuntimeControlStatus { }
function Write-LauncherLog { param($Message, $Level) $script:CredentialLogs += $Message }
$script:RepoRoot = $repo
$script:UserReads = 0
$script:CredentialLogs = @()
# Synthetic material only; never emitted, persisted, or passed as arguments.
$token = [string]::new([char]97, 64)
$sha = [Security.Cryptography.SHA256]::Create()
try { $valid = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($token)))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
$stale = [string]::new([char]98, 64)
$cases = @(
    @{ user = $valid; parent = $stale; state = 'valid'; relation = 'stale'; enabled = $true },
    @{ user = $valid; parent = $valid; state = 'valid'; relation = 'matches'; enabled = $true },
    @{ user = $valid; parent = $null; state = 'valid'; relation = 'absent'; enabled = $true },
    @{ user = $null; parent = $valid; state = 'missing'; relation = 'stale' },
    @{ user = ''; parent = $valid; state = 'missing'; relation = 'stale' },
    @{ user = $valid.ToUpperInvariant(); parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = $valid.Substring(1); parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = $valid + '0'; parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = $valid + "`n"; parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = ' ' + $valid; parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = [string]::new([char]0xff41, 64); parent = $valid; state = 'invalid'; relation = 'stale' },
    @{ user = $null; parent = $valid; state = 'unavailable'; relation = 'stale'; denied = $true }
)
$index = 0
foreach ($case in $cases) {
    $script:UserHash = $case.user
    $script:UserThrows = [bool]$case.denied
    # Overwrite, never read or restore any host credential in this disposable process.
    [Environment]::SetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', $case.parent, 'Process')
    $output = @(Initialize-OmiRuntimeControl *>&1)
    Assert ($output.Count -eq 0) 'INITIALIZER_OUTPUT_LEAK'
    Assert ([CredentialControllerFixture]::Started) 'NORMAL_STARTUP_BLOCKED'
    $adopted = [Environment]::GetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', 'Process')
    if ($case.enabled) { Assert ($adopted -ceq $valid) 'CANONICAL_USER_NOT_ADOPTED' }
    else { Assert ([string]::IsNullOrEmpty($adopted)) 'STALE_PARENT_NOT_CLEARED' }
    Assert ([string][CredentialControllerFixture]::SeenHash -ceq [string]$adopted) 'CONTROLLER_CHILD_MISMATCH'
    $log = $script:CredentialLogs[-1]
    Assert ($log.Contains("state=source_user_$($case.state) parent=parent_$($case.relation)")) 'DIAGNOSTIC_STATE'
    Assert ($log.Contains('account_scope=launcher_process_user source=hkcu_user')) 'DIAGNOSTIC_SCOPE'
    Assert ($log.EndsWith($(if ($case.enabled) { 'authorization=configured' } else { 'authorization=disabled' }))) 'DIAGNOSTIC_AUTH'

    # Real C# independent verifier; durable receipts live only under FixtureRoot.
    $controller = [Omi.RuntimeControl.Controller]::new((Join-Path $FixtureRoot "controller-$index"), $adopted, ('credential-fixture-' + [Guid]::NewGuid().ToString('N')))
    try {
        $request = @{ action = 'RestartBackend'; request_id = [Guid]::NewGuid().ToString('D'); expected_owner_id = $controller.OwnerId; token = $token }
        $reply = $controller.Dispatch(($request | ConvertTo-Json -Compress)) | ConvertFrom-Json
        if ($case.enabled) { Assert ($reply.reason -eq 'OWNER_NOT_ATTESTED') 'VALID_CREDENTIAL_BYPASSED_OWNER' }
        else { Assert ($reply.error -eq 'RUNTIME_CONTROL_FORBIDDEN') 'DISABLED_CREDENTIAL_ACCEPTED' }
        Assert ($null -eq $controller.TakePending()) 'CREDENTIAL_GRANTED_LIFECYCLE'
    } finally { $controller.Dispose() }

    # Exercise the existing Launcher -> runner -> cmd -> Python inheritance with
    # a finite, listener-free child, once enabled and once disabled. Never start
    # app.main, read HKCU, bind a port, or operate any existing OMI process.
    if ($index -in @(0, 3)) {
        Invoke-Expression (Definition $launcher 'Start-LoggedService')
        $script:ServiceRunner = Join-Path $repo 'scripts/run-service-logged.ps1'
        $script:RepoRoot = Join-Path $FixtureRoot "child-$index"
        $null = New-Item -ItemType Directory -Path $script:RepoRoot -Force
        $mode = if ($case.enabled) { 'enabled' } else { 'disabled' }
        $child = Start-LoggedService -ServiceName 'backend' -FilePath (Join-Path $repo '.venv/Scripts/python.exe') -Arguments @('-B', (Join-Path $repo 'backend/tests/fixtures/runtime_credential_child.py'), $mode) -WorkingDirectory $script:RepoRoot
        Assert ($child.WaitForExit(15000)) 'FINITE_CHILD_TIMEOUT_NO_KILL'
        $child.Refresh()
        Assert ($child.ExitCode -eq 0) 'FINITE_CHILD_FAILED'
        $child.Dispose()
        $childLogs = @(Get-ChildItem -LiteralPath (Join-Path $script:RepoRoot 'logs') -Recurse -File | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n"
        Assert ($childLogs.Contains('CREDENTIAL_CHILD_PASS')) 'CHILD_VERIFIER_FAILED'
        $script:CredentialLogs += $childLogs
        $script:RepoRoot = $repo
    }
    $index++
}
Assert ($script:UserReads -eq $cases.Count) 'USER_SOURCE_NOT_SINGLE_READ'
$allOutput = ($script:CredentialLogs -join "`n") + (@(Get-ChildItem -LiteralPath $FixtureRoot -Recurse -File | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n")
foreach ($secret in @($token, $valid, $stale)) {
    Assert (-not $allOutput.Contains($secret)) 'CREDENTIAL_PERSISTENCE_LEAK'
}
Assert (-not ($script:CredentialLogs -join "`n").Contains('SYNTHETIC_USER_ACCESS_DENIED')) 'EXCEPTION_REFLECTION'
# Startup wiring is checked on source AST, never by running the Launcher.
$topCommands = @($launcher.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.PipelineAst] } | ForEach-Object { $_.Extent.Text })
$initIndex = [Array]::IndexOf($topCommands, 'Initialize-OmiRuntimeControl')
$startIndex = [Array]::IndexOf($topCommands, 'Start-Services')
Assert ($initIndex -ge 0 -and $startIndex -gt $initIndex) 'INITIALIZATION_ORDER'
Assert ($initializer.IndexOf('Initialize-OmiRuntimeControlCredential') -lt $initializer.IndexOf('[Omi.RuntimeControl.Controller]::new')) 'CONSTRUCTOR_ORDER'
[Environment]::SetEnvironmentVariable('OMI_RUNTIME_CONTROL_TOKEN_SHA256', $null, 'Process')
'RUNTIME_CREDENTIAL_FIXTURE_PASS'
