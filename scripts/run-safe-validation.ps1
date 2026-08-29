<#
.SYNOPSIS
Runs OMI validation steps with bounded timeouts and log capture.

.DESCRIPTION
This script is meant for local agent/developer validation on Windows. It avoids
open-ended command chains by running each step as a child process with a timeout,
capturing stdout/stderr under .tmp/validation/<timestamp>, and warning when common
OMI ports already have listeners.

Profiles:
  quick    architecture guard + backend compileall + frontend tsc
  backend  architecture guard + backend compileall + pytest
  frontend frontend lint + tsc, optional build/e2e
  full     architecture guard + backend compileall + pytest + frontend lint + tsc + build

E2E is opt-in because it starts a Next dev server and a browser. Use a short
timeout first when debugging browser or worker hangs.

.EXAMPLE
.\scripts\run-safe-validation.ps1 -Profile quick

.EXAMPLE
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_crypto_market.py

.EXAMPLE
.\scripts\run-safe-validation.ps1 -Profile full -IncludeE2E -E2ETimeoutSeconds 180

.EXAMPLE
.\scripts\run-safe-validation.ps1 -Profile quick -StopPortOwners -Force
#>

param(
    [ValidateSet("quick", "backend", "frontend", "full")]
    [string]$Profile = "quick",

    [string[]]$BackendPytestArgs = @("backend/tests"),

    [switch]$IncludeBuild,
    [switch]$IncludeE2E,
    [switch]$SkipLint,
    [switch]$SkipBuild,
    [switch]$SkipGitCheck,

    [int]$CompileTimeoutSeconds = 120,
    [int]$ArchitectureTimeoutSeconds = 120,
    [int]$BackendTestTimeoutSeconds = 420,
    [int]$FrontendTimeoutSeconds = 180,
    [int]$BuildTimeoutSeconds = 360,
    [int]$E2ETimeoutSeconds = 240,

    [int[]]$KnownPorts = @(3000, 3100, 8400, 8427),
    [switch]$StopPortOwners,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$frontendDir = Join-Path $repoRoot "frontend"
$backendDir = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runLogDir = Join-Path (Join-Path $repoRoot ".tmp\validation") $runStamp
$pycacheDir = Join-Path ([System.IO.Path]::GetTempPath()) "omi_pycache_safe_validation"
$pytestBaseTemp = Join-Path (Join-Path $repoRoot ".tmp") "pytest-safe-validation-$runStamp"

New-Item -ItemType Directory -Force -Path $runLogDir | Out-Null

function ConvertTo-ProcessArgument {
    param([AllowEmptyString()][string]$Argument)

    if ($null -eq $Argument) {
        return '""'
    }

    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }

    $result = '"'
    $backslashes = 0

    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }

        if ($character -eq '"') {
            $result += ('\' * (($backslashes * 2) + 1))
            $result += '"'
            $backslashes = 0
            continue
        }

        if ($backslashes -gt 0) {
            $result += ('\' * $backslashes)
            $backslashes = 0
        }

        $result += $character
    }

    if ($backslashes -gt 0) {
        $result += ('\' * ($backslashes * 2))
    }

    $result += '"'
    return $result
}

function Resolve-Tool {
    param([Parameter(Mandatory = $true)][string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "None of these tools were found on PATH: $($Candidates -join ', ')"
}

function Get-SafeFileName {
    param([Parameter(Mandatory = $true)][string]$Name)
    return ($Name -replace '[^A-Za-z0-9_.-]', '_')
}

function Stop-ProcessTreeById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    if ($ProcessId -eq $PID) {
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path -LiteralPath $taskkill) {
        & $taskkill /PID $ProcessId /T /F | Out-Null
        return
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-ListeningPortOwners {
    param([Parameter(Mandatory = $true)][int[]]$Ports)

    $owners = @()
    foreach ($port in $Ports) {
        try {
            $connections = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop)
            foreach ($connection in $connections) {
                if ($connection.OwningProcess -gt 0) {
                    $owners += [pscustomobject]@{
                        Port = $port
                        Pid = [int]$connection.OwningProcess
                    }
                }
            }
        }
        catch {
            $netstat = & netstat -ano 2>$null
            foreach ($line in $netstat) {
                if ($line -notmatch "LISTENING") {
                    continue
                }
                $parts = @($line -split "\s+" | Where-Object { $_ })
                if ($parts.Count -lt 5) {
                    continue
                }
                if ($parts[1] -match ":(\d+)$" -and [int]$Matches[1] -eq $port) {
                    $owners += [pscustomobject]@{
                        Port = $port
                        Pid = [int]$parts[-1]
                    }
                }
            }
        }
    }

    return $owners | Sort-Object Port, Pid -Unique
}

function Write-PortOwnerSummary {
    param([Parameter(Mandatory = $true)][int[]]$Ports)

    $owners = @(Get-ListeningPortOwners -Ports $Ports)
    if ($owners.Count -eq 0) {
        Write-Host "No listeners found on validation-sensitive ports: $($Ports -join ', ')"
        return
    }

    Write-Host "Listeners found on validation-sensitive ports:"
    foreach ($owner in $owners) {
        $process = Get-Process -Id $owner.Pid -ErrorAction SilentlyContinue
        $name = if ($process) { $process.ProcessName } else { "unknown" }
        Write-Host ("  port={0} pid={1} process={2}" -f $owner.Port, $owner.Pid, $name)
    }
}

function Stop-KnownPortOwners {
    param([Parameter(Mandatory = $true)][int[]]$Ports)

    if (-not $Force) {
        throw "Refusing to stop port owners without -Force. Re-run with -StopPortOwners -Force after checking the printed listeners."
    }

    $owners = @(Get-ListeningPortOwners -Ports $Ports)
    foreach ($owner in $owners) {
        if ($owner.Pid -eq $PID) {
            Write-Host "Skipping current PowerShell process pid=$PID."
            continue
        }
        Write-Host ("Stopping port owner port={0} pid={1}" -f $owner.Port, $owner.Pid)
        Stop-ProcessTreeById -ProcessId $owner.Pid
    }
}

function Get-EnvFilePortValues {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Names
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    $ports = @()
    $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or
            $trimmed.StartsWith("#") -or
            (-not $trimmed.Contains("="))) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        if ($Names -notcontains $key) {
            continue
        }

        $value = $parts[1].Trim().Trim('"').Trim("'")
        $port = 0
        if ([int]::TryParse($value, [ref]$port) -and
            $port -ge 1 -and
            $port -le 65535) {
            $ports += $port
        }
    }

    return $ports
}

function Get-ValidationSensitivePorts {
    param([Parameter(Mandatory = $true)][int[]]$BasePorts)

    $portNames = @(
        "OMI_BACKEND_PORT",
        "APP_PORT",
        "OMI_FRONTEND_PORT",
        "FRONTEND_PORT",
        "PORT"
    )
    $ports = @($BasePorts)
    foreach ($path in @(
        (Join-Path $repoRoot ".env"),
        (Join-Path $frontendDir ".env.local"),
        (Join-Path $frontendDir ".env")
    )) {
        $ports += @(Get-EnvFilePortValues -Path $path -Names $portNames)
    }

    return @($ports | Where-Object { $_ -ge 1 -and $_ -le 65535 } | Sort-Object -Unique)
}

function Invoke-ValidationStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [hashtable]$Environment = @{}
    )

    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        throw "Missing working directory for $Name`: $WorkingDirectory"
    }
    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Missing executable for $Name`: $FilePath"
    }

    $safeName = Get-SafeFileName -Name $Name
    $stdoutPath = Join-Path $runLogDir "$safeName.out.log"
    $stderrPath = Join-Path $runLogDir "$safeName.err.log"
    $commandLine = "$FilePath $((@($Arguments) | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' ')"

    Write-Host ""
    Write-Host "==> $Name"
    Write-Host "cwd: $WorkingDirectory"
    Write-Host "cmd: $commandLine"
    Write-Host "timeout: ${TimeoutSeconds}s"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($Arguments) | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    $startedAt = Get-Date
    $timedOut = $false
    $previousEnvironment = @{}

    try {
        foreach ($key in $Environment.Keys) {
            $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, [EnvironmentVariableTarget]::Process)
            [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], [EnvironmentVariableTarget]::Process)
        }
        [void]$process.Start()
    }
    catch {
        throw "Failed to start $Name`: $($_.Exception.Message)"
    }
    finally {
        foreach ($key in $previousEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousEnvironment[$key], [EnvironmentVariableTarget]::Process)
        }
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $finished = $process.WaitForExit([Math]::Max(1, $TimeoutSeconds) * 1000)
    if (-not $finished) {
        $timedOut = $true
        Write-Host "Timed out. Stopping process tree pid=$($process.Id)."
        Stop-ProcessTreeById -ProcessId $process.Id
        [void]$process.WaitForExit(10000)
    }

    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    Set-Content -LiteralPath $stdoutPath -Value $stdout -Encoding UTF8
    Set-Content -LiteralPath $stderrPath -Value $stderr -Encoding UTF8

    $duration = [int]((Get-Date) - $startedAt).TotalSeconds
    $exitCode = if ($timedOut) { 124 } else { $process.ExitCode }
    $status = if ($exitCode -eq 0) { "passed" } elseif ($timedOut) { "timeout" } else { "failed" }

    Write-Host ("status: {0}; exit_code={1}; duration={2}s" -f $status, $exitCode, $duration)
    Write-Host "logs: $stdoutPath ; $stderrPath"

    if ($exitCode -ne 0) {
        foreach ($path in @($stderrPath, $stdoutPath)) {
            if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Length -gt 0)) {
                Write-Host "--- tail $path ---"
                Get-Content -LiteralPath $path -Tail 40 | ForEach-Object { Write-Host $_ }
            }
        }
    }

    return [pscustomobject]@{
        Name = $Name
        Status = $status
        ExitCode = $exitCode
        DurationSeconds = $duration
        Stdout = $stdoutPath
        Stderr = $stderrPath
    }
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return [int]$listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "Missing backend directory: $backendDir"
}
if (-not (Test-Path -LiteralPath $frontendDir)) {
    throw "Missing frontend directory: $frontendDir"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Python executable: $python. Rebuild .venv from the repo root before running validation."
}

$npm = Resolve-Tool -Candidates @("npm.cmd", "npm")
$git = Resolve-Tool -Candidates @("git.exe", "git")

$pythonEnv = @{
    PYTHONPATH = $backendDir
    PYTHONPYCACHEPREFIX = $pycacheDir
}

$frontendEnv = @{
    NEXT_TELEMETRY_DISABLED = "1"
}

Write-Host "Safe validation profile: $Profile"
Write-Host "Log directory: $runLogDir"
$validationPorts = Get-ValidationSensitivePorts -BasePorts $KnownPorts
Write-PortOwnerSummary -Ports $validationPorts

if ($StopPortOwners) {
    Stop-KnownPortOwners -Ports $validationPorts
}

$steps = @()

if ($Profile -in @("quick", "backend", "full")) {
    $steps += @{
        Name = "architecture checker"
        WorkingDirectory = $repoRoot
        FilePath = $python
        Arguments = @("scripts\check-architecture.py")
        TimeoutSeconds = $ArchitectureTimeoutSeconds
        Environment = $pythonEnv
    }

    $steps += @{
        Name = "architecture pytest"
        WorkingDirectory = $repoRoot
        FilePath = $python
        Arguments = @(
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "backend\tests\architecture"
        )
        TimeoutSeconds = $ArchitectureTimeoutSeconds
        Environment = $pythonEnv
    }

    $steps += @{
        Name = "backend compileall"
        WorkingDirectory = $repoRoot
        FilePath = $python
        Arguments = @("-m", "compileall", "backend\app")
        TimeoutSeconds = $CompileTimeoutSeconds
        Environment = $pythonEnv
    }
}

if ($Profile -in @("backend", "full")) {
    $steps += @{
        Name = "backend pytest"
        WorkingDirectory = $repoRoot
        FilePath = $python
        Arguments = @(
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            $pytestBaseTemp
        ) + $BackendPytestArgs
        TimeoutSeconds = $BackendTestTimeoutSeconds
        Environment = $pythonEnv
    }
}

if ($Profile -in @("quick", "frontend", "full")) {
    if (-not $SkipLint -and $Profile -ne "quick") {
        $steps += @{
            Name = "frontend lint"
            WorkingDirectory = $frontendDir
            FilePath = $npm
            Arguments = @("run", "lint")
            TimeoutSeconds = $FrontendTimeoutSeconds
            Environment = $frontendEnv
        }
    }

    $steps += @{
        Name = "frontend tsc"
        WorkingDirectory = $frontendDir
        FilePath = $npm
        Arguments = @("exec", "tsc", "--", "--noEmit", "--incremental", "false", "--pretty", "false")
        TimeoutSeconds = $FrontendTimeoutSeconds
        Environment = $frontendEnv
    }

    $shouldBuild = ($Profile -eq "full") -or $IncludeBuild
    if ($shouldBuild -and -not $SkipBuild) {
        $steps += @{
            Name = "frontend build"
            WorkingDirectory = $frontendDir
            FilePath = $npm
            Arguments = @("run", "build")
            TimeoutSeconds = $BuildTimeoutSeconds
            Environment = $frontendEnv
        }
    }

    if ($IncludeE2E) {
        $playwrightPort = Get-FreeTcpPort
        $e2eEnv = @{
            NEXT_TELEMETRY_DISABLED = "1"
            PLAYWRIGHT_HOST = "127.0.0.1"
            PLAYWRIGHT_PORT = [string]$playwrightPort
        }
        $steps += @{
            Name = "frontend e2e"
            WorkingDirectory = $frontendDir
            FilePath = $npm
            Arguments = @("run", "test:e2e")
            TimeoutSeconds = $E2ETimeoutSeconds
            Environment = $e2eEnv
        }
        Write-Host "Playwright will use temporary port $playwrightPort."
    }
}

if (-not $SkipGitCheck) {
    $steps += @{
        Name = "git diff check"
        WorkingDirectory = $repoRoot
        FilePath = $git
        Arguments = @("diff", "--check")
        TimeoutSeconds = 60
        Environment = @{}
    }
}

$results = @()
foreach ($step in $steps) {
    $result = Invoke-ValidationStep @step
    $results += $result
    if ($result.ExitCode -ne 0) {
        break
    }
}

Write-Host ""
Write-Host "Validation summary:"
foreach ($result in $results) {
    Write-Host ("  {0}: {1} ({2}s)" -f $result.Name, $result.Status, $result.DurationSeconds)
}

$failed = @($results | Where-Object { $_.ExitCode -ne 0 })
if ($failed.Count -gt 0) {
    Write-Host "Validation failed. Logs are in $runLogDir"
    exit 1
}

if (($Profile -ne "full") -and (-not $IncludeBuild)) {
    Write-Host "Build was not run. Add -IncludeBuild or use -Profile full when needed."
}
if (-not $IncludeE2E) {
    Write-Host "E2E was not run. Add -IncludeE2E when browser validation is required."
}

Write-Host "Validation passed. Logs are in $runLogDir"
exit 0
