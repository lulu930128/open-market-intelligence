param([switch]$DisposableRunner, [string]$EvidencePath, [int]$LauncherPid)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if ($DisposableRunner) {
    # This process owns only a finite stdlib child. No backend, port, CIM, or stop.
    $python = Join-Path $repo '.venv\Scripts\python.exe'
    $child = Join-Path $PSScriptRoot 'owned-identity-child.py'
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = Join-Path $env:SystemRoot 'System32\cmd.exe'
    $start.Arguments = "/d /s /c `"`"$python`" -I -S `"$child`" `"$EvidencePath`" $LauncherPid`""
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $cmd = [Diagnostics.Process]::Start($start)
    try { if (-not $cmd.WaitForExit(15000)) { throw 'DISPOSABLE_CHILD_TIMEOUT' }; exit $cmd.ExitCode }
    finally { $cmd.Dispose() }
}

Add-Type -Path @((Join-Path $repo 'scripts/OmiRuntimeControl.cs'), (Join-Path $repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions', 'System.Core', 'System.Windows.Forms')
. (Join-Path $repo 'scripts/omi-runtime-control.ps1')
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/omi-launcher.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'LAUNCHER_PARSE_FAILED' }
# Reuse canonical expected-path owner without invoking the launcher's entrypoint.
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ExpectedBackendPython' }, $true)
Invoke-Expression $definition.Extent.Text

$script:Checks = 0
function Assert($Condition, [string]$Name) {
    if (-not $Condition) { throw "ASSERT_FAILED: $Name (stage=$script:BackendOwnershipReason)" }
    $script:Checks++
}
function Fake-Process($Record) {
    $result = [pscustomobject]@{ Id = [int]$Record.ProcessId; StartTime = $Record.CreationDate; HasExited = $false }
    $result | Add-Member ScriptMethod Refresh { }
    $result | Add-Member ScriptMethod Dispose { }
    return $result
}
# Only OS observation boundaries are substituted. Identity, path/config checks,
# publish logic and expected interpreter selection remain production functions.
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($script:Denied) { throw 'SENSITIVE: provider token secret path command line' }
    $number = [int]($Filter -replace 'ProcessId = ', '')
    $script:Reads[$number]++
    $value = $script:Records[$number]
    if ($script:ChangePid -eq $number -and $script:Reads[$number] -gt 1) {
        $value = $value.PSObject.Copy(); $value.CreationDate = $value.CreationDate.AddSeconds(1)
    }
    return $value
}
function Get-OmiIdentityProcess { param([int]$ProcessId) return $script:Processes[$ProcessId] }
function Get-ListeningProcessIdsOnPort {
    param($Port)
    if ($Port -ne $script:BackendPort -or $Port -eq 8400) { throw 'FIXTURE_PORT_MISMATCH' }
    $script:ListenerReads++
    if ($script:ListenerReads -gt 1 -and $script:LoseMutex) { $script:OwnsMutex = $false }
    if ($script:ListenerReads -gt 1 -and $script:ChangeConfig) { [IO.File]::WriteAllText($config, "executable = $foreign") }
    if ($script:ChangeListener -and $script:ListenerReads -gt 1) { return @(909) }
    return $script:Listeners
}
function Stop-BackendService { throw 'REAL_STOP_FORBIDDEN' }
function Start-Backend { throw 'REAL_START_FORBIDDEN' }

$fixture = Join-Path $repo ('.tmp/owned-identity-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
$venv = Join-Path $fixture '.venv\Scripts\python.exe'
$base = Join-Path $fixture 'base\python.exe'
$packaged = Join-Path $fixture 'runtime\python\python.exe'
$foreign = Join-Path $fixture 'foreign\python.exe'
foreach ($path in @($venv, $base, $packaged, $foreign)) {
    New-Item -ItemType Directory -Force ([IO.Path]::GetDirectoryName($path)) | Out-Null
    [IO.File]::WriteAllText($path, 'fixture path only; never executed')
}
$config = Join-Path $fixture '.venv\pyvenv.cfg'
function Reset-Fixture {
    $script:RepoRoot = $fixture; $script:IsPackagedRelease = $false; $script:PackagedPython = $packaged
    $script:OwnsMutex = $true; $script:BackendReload = $false; $script:BackendPort = 49199
    $script:BackendHost = '127.0.0.1'; $script:FrontendHost = '127.0.0.1'; $script:FrontendPort = 49198
    $script:Denied = $false; $script:ChangePid = 0; $script:ChangeListener = $false
    $script:LoseMutex = $false; $script:ChangeConfig = $false
    $script:ListenerReads = 0; $script:Reads = @{}; $script:Listeners = @(104)
    $script:Records = @{}; $script:Processes = @{}
    [IO.File]::WriteAllText($config, "executable = $base`n")
    $time = [DateTime]::UtcNow
    $specs = @(@(101, $PID, (Join-Path $PSHOME 'powershell.exe')), @(102, 101, (Join-Path $env:SystemRoot 'System32\cmd.exe')), @(103, 102, $venv), @(104, 103, $base))
    foreach ($spec in $specs) {
        $record = [pscustomobject]@{ ProcessId = $spec[0]; ParentProcessId = $spec[1]; ExecutablePath = $spec[2]; CreationDate = $time; CommandLine = "`"$venv`" -m uvicorn app.main:app --host 127.0.0.1 --port 49199" }
        $script:Records[$spec[0]] = $record; $script:Processes[$spec[0]] = Fake-Process $record
    }
    $script:BackendProcess = Fake-Process $script:Records[101]
}
function Expect-Rejected([string]$Name, [string]$Reason) {
    $result = Get-OmiOwnedBackendIdentity
    Assert ($null -eq $result) "$Name rejected"
    Assert ($script:BackendOwnershipReason -eq $Reason) "$Name reason"
}

Reset-Fixture
$identity = Get-OmiOwnedBackendIdentity
Assert ($identity.pid -eq 104 -and $script:BackendOwnershipReason -eq 'ATTESTED') 'redirector accepted'
Assert ($identity.created_at -eq $script:Processes[104].StartTime.ToUniversalTime().ToString('o')) 'listener creation returned'
$precision = [DateTime]::UtcNow
Assert (Test-OmiCreationEvidence $precision $precision.AddTicks(9)) 'submicrosecond WMI truncation accepted'
Assert (-not (Test-OmiCreationEvidence $precision $precision.AddTicks(10))) 'microsecond mismatch rejected'
Assert (-not (Test-OmiCreationEvidence $precision.AddTicks(1) $precision)) 'future CIM rejected'
foreach ($direct in @('venv-cmd', 'venv-direct', 'packaged-cmd', 'packaged-direct', 'redirector-direct')) {
    Reset-Fixture
    if ($direct -like 'packaged*') { $script:IsPackagedRelease = $true; $script:Records[103].ExecutablePath = $packaged; $script:Records[103].CommandLine = "`"$packaged`" -m uvicorn app.main:app --host 127.0.0.1 --port 49199" }
    if ($direct -ne 'redirector-direct') { $script:Listeners = @(103) }
    if ($direct -like '*-direct') { $script:Records[103].ParentProcessId = 101 }
    Assert ($null -ne (Get-OmiOwnedBackendIdentity)) $direct
}

$cases = @(
    @('mutex', 'OWNER_MUTEX_NOT_HELD', { $script:OwnsMutex = $false }),
    @('reload', 'RELOAD_UNSUPPORTED', { $script:BackendReload = $true }),
    @('missing runner', 'RUNNER_UNAVAILABLE', { $script:BackendProcess = $null }),
    @('exited runner', 'RUNNER_UNAVAILABLE', { $script:BackendProcess.HasExited = $true }),
    @('denied CIM', 'RUNNER_UNAVAILABLE', { $script:Denied = $true }),
    @('unknown runner', 'RUNNER_IDENTITY_MISMATCH', { $script:Records.Remove(101) }),
    @('foreign launcher', 'RUNNER_IDENTITY_MISMATCH', { $script:Records[101].ParentProcessId = 999 }),
    @('tracked PID reuse', 'RUNNER_IDENTITY_MISMATCH', { $script:BackendProcess.StartTime = $script:BackendProcess.StartTime.AddSeconds(-1) }),
    @('runner CIM reuse', 'RUNNER_IDENTITY_MISMATCH', { $script:Records[101].CreationDate = $script:Records[101].CreationDate.AddSeconds(-1) }),
    @('runner predates launcher', 'RUNNER_IDENTITY_MISMATCH', { $script:Processes[101].StartTime = [DateTime]::UtcNow.AddDays(-1); $script:BackendProcess.StartTime = $script:Processes[101].StartTime; $script:Records[101].CreationDate = $script:Processes[101].StartTime }),
    @('no listener', 'LISTENER_NOT_UNIQUE', { $script:Listeners = @() }),
    @('duplicate listener', 'LISTENER_NOT_UNIQUE', { $script:Listeners = @(104, 104) }),
    @('foreign listener', 'PROCESS_EVIDENCE_UNAVAILABLE', { $script:Listeners = @(909) }),
    @('unknown parent', 'PROCESS_EVIDENCE_UNAVAILABLE', { $script:Records.Remove(103) }),
    @('unknown creation', 'PROCESS_EVIDENCE_UNAVAILABLE', { $script:Records[103].CreationDate = $null }),
    @('cycle', 'PROCESS_EVIDENCE_UNAVAILABLE', { $script:Records[103].ParentProcessId = 104 }),
    @('stale child', 'PROCESS_IDENTITY_MISMATCH', { $script:Processes[104].StartTime = $script:Processes[104].StartTime.AddSeconds(1) }),
    @('stale redirector', 'PROCESS_IDENTITY_MISMATCH', { $script:Processes[103].StartTime = $script:Processes[103].StartTime.AddSeconds(1) }),
    @('stale cmd', 'PROCESS_IDENTITY_MISMATCH', { $script:Processes[102].StartTime = $script:Processes[102].StartTime.AddSeconds(1) }),
    @('exited intermediate', 'PROCESS_IDENTITY_MISMATCH', { $script:Processes[103].HasExited = $true }),
    @('bad parent order', 'PROCESS_CREATION_ORDER_INVALID', { $script:Processes[103].StartTime = $script:Processes[103].StartTime.AddSeconds(1); $script:Records[103].CreationDate = $script:Processes[103].StartTime }),
    @('child before runner', 'PROCESS_CREATION_ORDER_INVALID', { $script:Processes[104].StartTime = $script:Processes[104].StartTime.AddSeconds(-1); $script:Records[104].CreationDate = $script:Processes[104].StartTime }),
    @('base alone', 'INTERPRETER_PATH_MISMATCH', { $script:Records[104].ParentProcessId = 102 }),
    @('foreign repo', 'INTERPRETER_PATH_MISMATCH', { $script:Records[103].ExecutablePath = $foreign }),
    @('foreign shell', 'ANCESTRY_UNSUPPORTED', { $script:Records[102].ExecutablePath = $foreign }),
    @('missing image', 'INTERPRETER_PATH_MISMATCH', { $script:Records[103].ExecutablePath = $null }),
    @('relative image', 'INTERPRETER_PATH_MISMATCH', { $script:Records[103].ExecutablePath = '.venv\Scripts\python.exe' }),
    @('noncanonical image', 'INTERPRETER_PATH_MISMATCH', { $script:Records[103].ExecutablePath = (Join-Path $fixture '.venv\Scripts\..\Scripts\python.exe') }),
    @('config mismatch', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, "executable = $foreign") }),
    @('config duplicate', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, "executable = $base`nexecutable = $base") }),
    @('config missing key', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, 'home = unused') }),
    @('config missing file', 'VENV_CONFIG_INVALID', { [IO.File]::Delete($config) }),
    @('config relative', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, 'executable = python.exe') }),
    @('config self redirect', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, "executable = $venv"); $script:Records[104].ExecutablePath = $venv }),
    @('config oversized', 'VENV_CONFIG_INVALID', { [IO.File]::WriteAllText($config, ('a' * 16385)) }),
    @('reload command', 'WORKER_MODE_UNSUPPORTED', { $script:Records[104].CommandLine = 'python -m uvicorn --reload' }),
    @('workers command', 'WORKER_MODE_UNSUPPORTED', { $script:Records[103].CommandLine = 'python -m uvicorn --workers=2' }),
    @('unknown command', 'PROCESS_EVIDENCE_UNAVAILABLE', { $script:Records[104].CommandLine = $null }),
    @('packaged delegation', 'INTERPRETER_PATH_MISMATCH', { $script:IsPackagedRelease = $true; $script:Records[103].ExecutablePath = $packaged }),
    @('extra supervisor', 'ANCESTRY_UNSUPPORTED', { $script:Records[102].ParentProcessId = 105; $node = $script:Records[102].PSObject.Copy(); $node.ProcessId = 105; $node.ParentProcessId = 101; $script:Records[105] = $node; $script:Processes[105] = Fake-Process $node }),
    @('ancestry bound', 'ANCESTRY_UNSUPPORTED', { $script:Records[102].ParentProcessId = 105; $node = $script:Records[102].PSObject.Copy(); $node.ProcessId = 105; $node.ParentProcessId = 106; $script:Records[105] = $node; $script:Processes[105] = Fake-Process $node }),
    @('runner changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangePid = 101 }),
    @('child changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangePid = 104 }),
    @('parent changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangePid = 103 }),
    @('cmd changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangePid = 102 }),
    @('listener changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangeListener = $true }),
    @('submillisecond mismatch', 'PROCESS_IDENTITY_MISMATCH', { $script:Processes[104].StartTime = $script:Processes[104].StartTime.AddTicks(100) }),
    @('future CIM', 'PROCESS_IDENTITY_MISMATCH', { $script:Records[104].CreationDate = $script:Records[104].CreationDate.AddTicks(1) }),
    @('wrong entry', 'BACKEND_COMMAND_MISMATCH', { $script:Records[104].CommandLine = $script:Records[104].CommandLine.Replace('app.main:app', 'other:app') }),
    @('wrong port', 'BACKEND_COMMAND_MISMATCH', { $script:Records[104].CommandLine = $script:Records[104].CommandLine.Replace('49199', '49198') }),
    @('extra argv', 'BACKEND_COMMAND_MISMATCH', { $script:Records[104].CommandLine += ' --factory' }),
    @('authority lost', 'PROCESS_EVIDENCE_CHANGED', { $script:LoseMutex = $true }),
    @('config changed', 'PROCESS_EVIDENCE_CHANGED', { $script:ChangeConfig = $true })
)
foreach ($case in $cases) { Reset-Fixture; & $case[2]; Expect-Rejected $case[0] $case[1] }

# Actual directory junction, confined to the disposable fixture; never traverse
# it for cleanup or modify the real repo/venv. No symlink privilege is requested.
Reset-Fixture
$junction = Join-Path $fixture 'linked-base'
New-Item -ItemType Junction -Path $junction -Target (Join-Path $fixture 'base') | Out-Null
try {
    $linked = Join-Path $junction 'python.exe'
    $script:Records[104].ExecutablePath = $linked
    [IO.File]::WriteAllText($config, "executable = $linked")
    Expect-Rejected 'reparse image' 'INTERPRETER_PATH_MISMATCH'
} finally { [IO.Directory]::Delete($junction) } # Nonrecursive: remove only our junction.
Reset-Fixture
$linkedRepo = Join-Path $fixture 'linked-repo'
New-Item -ItemType Junction -Path $linkedRepo -Target $fixture | Out-Null
try {
    $script:RepoRoot = $linkedRepo
    $script:Records[103].ExecutablePath = Join-Path $linkedRepo '.venv\Scripts\python.exe'
    Expect-Rejected 'reparse repo' 'INTERPRETER_PATH_MISMATCH'
} finally { [IO.Directory]::Delete($linkedRepo) }

# Exercise the cfg leaf attribute boundary without requiring symlink privileges.
# The separate real junction checks above cover actual filesystem reparses.
Reset-Fixture
function Get-Item {
    param($LiteralPath, [switch]$Force, $ErrorAction)
    $item = Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    if ($LiteralPath -eq $config) { return [pscustomobject]@{ FullName = $item.FullName; Attributes = [IO.FileAttributes]::ReparsePoint } }
    return $item
}
Expect-Rejected 'reparse config' 'VENV_CONFIG_INVALID'
Remove-Item Function:\Get-Item

# In-memory status sink: no controller store, HTTP or operational reads/writes.
$script:RuntimeController = [pscustomobject]@{}
$script:RuntimeController | Add-Member ScriptMethod Publish { param($json, $identity, $attested) $script:Published = $json | ConvertFrom-Json; $script:Attested = $attested }
Reset-Fixture
Publish-OmiRuntimeControlStatus
$gates = @([Omi.RuntimeControl.Controller]::UnavailableRestartGates())
Assert ($script:Attested -and $script:Published.backend.ownership_reason -eq 'ATTESTED') 'status attested'
Assert (-not $script:Published.restart.available -and $script:Published.backend.readiness -eq 'UNATTESTED') 'readiness and restart unchanged'
Assert (($script:Published.restart.blockers -join ',') -eq 'OWNED_BOOTSTRAP_REQUIRED') 'legacy process cannot hot-adopt owned channel'
$attestedStatus = $script:Published
$script:Denied = $true
Publish-OmiRuntimeControlStatus
Assert ($script:Published.backend.identity -eq 'UNATTESTED' -and $null -eq $script:Published.backend.pid -and -not $script:Attested) 'failure closed'
Assert (($script:Published.restart.blockers -join ',') -eq 'OWNER_NOT_ATTESTED') 'owner failure remains authoritative'
Assert (($script:Published | ConvertTo-Json -Depth 6) -notmatch 'SENSITIVE|token|secret|CommandLine|ExecutablePath|provider') 'diagnostic redaction'
$deniedStatus = $script:Published

# Real Windows redirector observation, then same-function evidence playback.
# Query scope is this test's child ancestry only, never a host CIM query.
$evidence = Join-Path $fixture 'disposable-os-evidence.json'
$arguments = "-NoProfile -File `"$PSCommandPath`" -DisposableRunner -EvidencePath `"$evidence`" -LauncherPid $PID"
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = Join-Path $PSHOME 'powershell.exe'; $start.Arguments = $arguments
$start.UseShellExecute = $false; $start.CreateNoWindow = $true
$start.RedirectStandardError = $true
# Inherit the environment without rebuilding PowerShell 5.1's case-insensitive
# dictionary (some Python parents expose both PATH and Path).
$runner = [Diagnostics.Process]::Start($start)
$null = $runner.Handle
$runnerStarted = $runner.StartTime
try {
    if (-not $runner.WaitForExit(20000)) { throw 'DISPOSABLE_RUNNER_TIMEOUT' }
    if ($runner.ExitCode -ne 0) { throw ('DISPOSABLE_RUNNER_FAILED: ' + $runner.StandardError.ReadToEnd()) }
    Assert ($runner.ExitCode -eq 0) 'disposable runner exited naturally'
    $observations = Get-Content -LiteralPath $evidence -Raw | ConvertFrom-Json
    $realArgv = [Omi.RuntimeControl.ProcessEvidence]::Arguments($observations[0].CommandLine)
    Assert ($realArgv[0] -ieq (Join-Path $repo '.venv\Scripts\python.exe')) 'actual redirector preserves venv argv0'
    Reset-Fixture
    $script:RepoRoot = $repo
    $script:Records = @{}; $script:Processes = @{}
    foreach ($record in $observations) {
        $record.CreationDate = [DateTime]::FromFileTimeUtc([long]$record.CreatedFileTime)
        # Only ancestry is an actual OS observation. Supply the fixed production
        # argv separately; this stdlib child is deliberately not OMI/Uvicorn.
        $record.CommandLine = "`"$(Join-Path $repo '.venv\Scripts\python.exe')`" -m uvicorn app.main:app --host 127.0.0.1 --port 49199"
        $script:Records[[int]$record.ProcessId] = $record
        $script:Processes[[int]$record.ProcessId] = Fake-Process $record
    }
    $script:Listeners = @([int]$observations[0].ProcessId)
    $script:BackendProcess = [pscustomobject]@{ Id = $runner.Id; StartTime = $runnerStarted; HasExited = $false }
    Assert ($observations.Count -eq 4) 'OS runner cmd redirector base shape'
    Assert ($observations[1].ExecutablePath -ieq (Join-Path $repo '.venv\Scripts\python.exe')) 'OS venv redirector image'
    Assert ($observations[0].ExecutablePath -ine $observations[1].ExecutablePath) 'OS base image differs'
    Assert ($null -ne (Get-OmiOwnedBackendIdentity)) 'real ancestry with fixed argv accepted by production function'
} finally { $runner.Dispose() }
'OWNED_IDENTITY_STATUS=' + (ConvertTo-Json -InputObject @($attestedStatus, $deniedStatus) -Depth 8 -Compress)
"OWNED_IDENTITY_FIXTURE_PASS checks=$script:Checks cases=$($cases.Count) real_redirector=PASS"
