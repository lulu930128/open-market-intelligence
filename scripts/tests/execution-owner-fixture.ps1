param([Parameter(Mandatory=$true)][string]$FixtureRoot,
    [Parameter(Mandatory=$true)][string]$PipeName,
    [ValidateSet('normal','backoff','missing','bad-preference')][string]$Scenario = 'normal')
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Add-Type -Path @((Join-Path $repo 'scripts/OmiRuntimeControl.cs'),(Join-Path $repo 'scripts/OmiOwnedShutdown.cs')) -ReferencedAssemblies @('System.Web.Extensions','System.Core','System.Windows.Forms')
if (-not (Test-Path (Join-Path $FixtureRoot 'SYNTHETIC_ONLY'))) {throw 'SYNTHETIC_MARKER_REQUIRED'}
$controller=[Omi.RuntimeControl.Controller]::new((Join-Path $FixtureRoot 'controller'),$null,$PipeName)
$flags=[Reflection.BindingFlags]'Instance,NonPublic'
$state=Join-Path $FixtureRoot 'state'
[void][IO.Directory]::CreateDirectory($state)
[IO.File]::WriteAllText((Join-Path $state 'SYNTHETIC_ONLY'),'')
$preference=Join-Path $FixtureRoot 'controller/settings/execution-preference.json'
$python=Join-Path $repo '.venv/Scripts/python.exe'
if($Scenario -eq 'missing') {$python=Join-Path $FixtureRoot 'missing-python.exe'}
$arguments='-B -m execution_runtime.tests.deployment_worker --directory "'+$state+'" --address "\\.\pipe\'+$PipeName+'-native" --native-python "'+(Join-Path $repo '.venv-kgi/Scripts/python.exe')+'" --scenario '+$(if($Scenario -eq 'backoff'){'backoff'}else{'normal'})
try {
    if($Scenario -eq 'bad-preference') {
        # Real constructor failure before any process is created.
        $hash=[Security.Cryptography.SHA256]::Create()
        try {$suffix=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($FixtureRoot.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24)}finally{$hash.Dispose()}
        $bad=$preference
        [void][IO.Directory]::CreateDirectory((Split-Path $bad))
        [IO.File]::WriteAllText($bad,'{"keep_online":"bad"}')
        try {$controller.EnableExecution($FixtureRoot);throw 'EXPECTED_INIT_FAILURE'}
        catch {if($_.Exception.Message -eq 'EXPECTED_INIT_FAILURE'){throw}}
    } else {
        $type=[Omi.RuntimeControl.Controller].Assembly.GetType('Omi.RuntimeControl.ExecutionComponent')
        $constructor=$type.GetConstructor($flags,$null,[type[]]@([string],[string],[string],[string],[string]),$null)
        $component=$constructor.Invoke([object[]]@([string]$repo,[string]$state,[string]$python,[string]$arguments,[string]$preference))
        [Omi.RuntimeControl.Controller].GetField('execution',$flags).SetValue($controller,$component)
        [Omi.RuntimeControl.Controller].GetField('executionState',$flags).SetValue($controller,$state)
        $null=$type.GetMethod('Start',$flags).Invoke($component,[object[]]@($false))
    }
    $controller.Publish('{}',$null,$false)
    $controller.Start()
    @{pid=$PID;owner_id=$controller.OwnerId;pipe=$PipeName} | ConvertTo-Json -Compress
    while(($command=[Console]::ReadLine()) -ne $null) {
        if($command -eq 'exit') {
            $ready=$controller.PrepareExecutionExit(10000)
            @{exit_ready=$ready}|ConvertTo-Json -Compress
            if($ready){break}
        } elseif($command -eq 'owner-loss') {
            # Normal process exit without execution cleanup exercises the
            # retained owner handle in the real supervisor. No kill/escape.
            break
        } elseif($command -eq 'research-cycle') {
            # Controller publication/backend identity changes cannot dispose or
            # start execution; real Backend is never started by this fixture.
            $controller.Publish('{"backend":"stopped"}',$null,$false)
            'RESEARCH_PUBLICATION_COMPLETE'
        } else {throw 'UNSUPPORTED_FIXTURE_COMMAND'}
    }
} finally {$controller.Dispose()}
