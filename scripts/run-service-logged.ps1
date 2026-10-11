param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$ArgumentsJsonBase64,
    [int]$LauncherPid = 0,
    [ValidateRange(0, 20)][int]$MaxRestartAttempts = 3,
    [string]$RestartBackoffSecondsCsv = "2,10,30",
    [ValidateRange(1, 86400)][int]$StableRunResetSeconds = 600,
    [ValidateRange(1, 255)][int]$BindFailureExitCode = 78,
    [switch]$GracefulStopFixture,
    [switch]$UvicornLifespanFixture,
    [ValidateSet('normal','double-signal','wrong-pid','wrong-start','wrong-instance','wrong-deadline','wrong-request','wrong-runner','missing-ack','timeout','child-crash','runner-crash','parent-disappearance','partial-drain','stuck-worker','cancel-worker','unknown-session','borrowed-escape','fake-ack','ack-without-exit','source-drift','ready-wrong-start','request-wrong-pid','request-wrong-start','request-wrong-token','request-expired','request-wrong-runner','orphan','ack-session-type','ack-publisher-type','ack-unknown-type','ack-pending-constructor','ack-close-failure','ack-uncertain-owner','ack-unknown-publisher','ack-incomplete-jobs','ack-global-drained','ack-null-owners','ack-unknown-scheduler','ack-active-collector')]
    [string]$LifespanScenario = 'normal',
    [ValidateSet('normal', 'wrong-pid', 'wrong-start', 'wrong-instance', 'wrong-deadline', 'missing-ack', 'timeout', 'child-crash', 'runner-crash', 'double-signal', 'incomplete-drain', 'invalid-drain-receipt', 'forced-receipt', 'ready-wrong-start', 'ack-without-exit')]
    [string]$FixtureScenario = 'normal'
)

$ErrorActionPreference = "Stop"

# The B4 seam is a bounded extension of the R1E owner, never production startup.
if ($UvicornLifespanFixture) {
    try {
        if ($GracefulStopFixture -or $ServiceName -cne 'r1-b4-disposable' -or $LauncherPid -ne 0 -or
            [IO.Path]::GetFullPath($WorkingDirectory) -cne [IO.Path]::GetFullPath($RepoRoot)) {
            throw 'Disposable B4 fixture identity required'
        }
        $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgumentsJsonBase64))
        if ($json -cne '[]') { throw 'Only empty JSON argv accepted; fixed fixture child required' }
        $venvConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../.venv/pyvenv.cfg')
        $basePython = @($venvConfig | Where-Object { $_ -match '^executable = ' })
        if ($basePython.Count -ne 1 -or [IO.Path]::GetFullPath($FilePath) -ine $basePython[0].Substring(13)) {
            throw 'Verified base interpreter required; redirectors refused'
        }
        . (Join-Path $PSScriptRoot 'omi-graceful-stop-fixture.ps1')
        $code = Invoke-OmiGracefulStopFixture -OutputRoot $RepoRoot -Python $FilePath -Scenario $LifespanScenario -Uvicorn
        exit $code
    }
    catch {
        Write-Error "B4 BLOCKED: $($_.Exception.Message)" -ErrorAction Continue
        exit 79
    }
}

# Explicit rehearsal only. Never fall through to the legacy force/restart loop,
# and never accept a production command or an existing IPC directory here.
if ($GracefulStopFixture) {
    try {
        if ($ServiceName -ne 'r1e-fixture' -or $LauncherPid -ne 0) {
            throw 'Disposable fixture identity required'
        }
        . (Join-Path $PSScriptRoot 'omi-graceful-stop-fixture.ps1')
        $code = Invoke-OmiGracefulStopFixture -OutputRoot $RepoRoot -Python $FilePath -Scenario $FixtureScenario
        exit $code
    }
    catch {
        Write-Error "R1E BLOCKED: $($_.Exception.Message)" -ErrorAction Continue
        exit 79
    }
}

$logRoot = Join-Path $RepoRoot "logs"

function Get-ServiceLogPath {
    $dateFolder = Get-Date -Format "yyyy-MM-dd"
    $directory = Join-Path (Join-Path $logRoot $ServiceName) $dateFolder
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    return (Join-Path $directory "$ServiceName.log")
}

function Write-ServiceLog {
    param(
        [AllowEmptyString()][string]$Message,
        [string]$Level = "INFO"
    )

    if ($null -eq $Message) {
        $Message = ""
    }

    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    $logPath = Get-ServiceLogPath
    $maxWriteAttempts = 20

    for ($attempt = 1; $attempt -le $maxWriteAttempts; $attempt += 1) {
        try {
            Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
            return
        }
        catch [System.IO.IOException] {
            if ($attempt -ge $maxWriteAttempts) {
                throw
            }

            # The child process appends to the same log through cmd.exe. On
            # Windows, opening that redirect and Add-Content can briefly race.
            Start-Sleep -Milliseconds 50
        }
    }
}

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

function Stop-ServiceProcessTree {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path -LiteralPath $taskkill) {
        Write-ServiceLog "Stopping service process tree. pid=$ProcessId reason=$Reason" "SYSTEM"
        Start-Process -FilePath $taskkill -ArgumentList @("/PID", "$ProcessId", "/T", "/F") -Wait -WindowStyle Hidden | Out-Null
        return
    }

    Write-ServiceLog "taskkill.exe was not found; stopping only root process. pid=$ProcessId reason=$Reason" "WARN"
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Test-LauncherAlive {
    if ($LauncherPid -le 0) {
        return $true
    }

    return $null -ne (Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue)
}

function ConvertTo-RestartBackoffSeconds {
    param([Parameter(Mandatory = $true)][string]$Value)

    $seconds = @()
    foreach ($rawSegment in $Value.Split(",")) {
        $segment = $rawSegment.Trim()
        $parsed = 0
        if ((-not [int]::TryParse($segment, [ref]$parsed)) -or $parsed -lt 0) {
            throw "Invalid restart backoff '$segment'. Expected comma-separated non-negative seconds."
        }
        $seconds += $parsed
    }

    if ($seconds.Count -eq 0) {
        throw "At least one restart backoff value is required."
    }

    return $seconds
}

function Wait-RestartBackoff {
    param([ValidateRange(0, 86400)][int]$Seconds)

    for ($elapsed = 0; $elapsed -lt $Seconds; $elapsed += 1) {
        if (-not (Test-LauncherAlive)) {
            Write-ServiceLog "Service restart cancelled because launcher process is gone. launcher_pid=$LauncherPid" "WARN"
            return $false
        }
        Start-Sleep -Seconds 1
    }

    return (Test-LauncherAlive)
}

function Test-ServiceBindFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$OutputLines = @()
    )

    if ($Name -ne "backend") {
        return $false
    }

    foreach ($line in $OutputLines) {
        if ($line -match "(?i)error while attempting to bind on address" -or
            $line -match "(?i)winerror\s+(?:10013|10048)" -or
            $line -match "(?i)address already in use") {
            return $true
        }
    }

    return $false
}

function Get-ServiceOutputSinceLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(0, 2147483647)][int]$StartLine
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    return @(Get-Content -LiteralPath $Path | Select-Object -Skip $StartLine)
}

try {
    $argumentsJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgumentsJsonBase64))
    $parsedArguments = ConvertFrom-Json -InputObject $argumentsJson
    $arguments = @()

    foreach ($argument in $parsedArguments) {
        if ($argument -is [System.Array]) {
            foreach ($innerArgument in $argument) {
                $arguments += [string]$innerArgument
            }
        }
        else {
            $arguments += [string]$argument
        }
    }

    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        throw "Working directory does not exist: $WorkingDirectory"
    }

    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Executable does not exist: $FilePath"
    }

    $restartBackoffSeconds = @(ConvertTo-RestartBackoffSeconds -Value $RestartBackoffSecondsCsv)
    $processFilePath = Join-Path $env:SystemRoot "System32\cmd.exe"
    $restartAttempt = 0
    $instanceId = [Guid]::NewGuid().ToString("N")

    while ($true) {
        if (-not (Test-LauncherAlive)) {
            Write-ServiceLog "Service runner exiting before child start because launcher process is gone. launcher_pid=$LauncherPid instance_id=$instanceId" "WARN"
            exit 0
        }

        $serviceLogPath = Get-ServiceLogPath
        $innerCommand = ((@($FilePath) + $arguments) | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
        $innerCommand = "$innerCommand >> $(ConvertTo-ProcessArgument $serviceLogPath) 2>&1"
        $processArguments = "/d /s /c `"$innerCommand`""

        Write-ServiceLog "Starting service. file=$FilePath args=$($arguments -join ' ') cwd=$WorkingDirectory launcher_pid=$LauncherPid instance_id=$instanceId restart_attempt=$restartAttempt" "SYSTEM"
        Write-ServiceLog "Process runner. file=$processFilePath args=$processArguments" "SYSTEM"
        $serviceOutputStartLine = @(Get-Content -LiteralPath $serviceLogPath).Count

        # Windows PowerShell can expose the lazily initialized environment
        # dictionaries as null to the indexer. Reading Count materializes the
        # collection before backend-specific values are assigned.
        $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $processFilePath
        $startInfo.Arguments = $processArguments
        $startInfo.WorkingDirectory = $WorkingDirectory
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        if ($ServiceName -eq "backend") {
            $null = $startInfo.EnvironmentVariables.Count
            $startInfo.EnvironmentVariables["PYTHONFAULTHANDLER"] = "1"
            $startInfo.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"
        }

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        $startedAt = Get-Date

        [void]$process.Start()
        Write-ServiceLog "Service child started. child_pid=$($process.Id) instance_id=$instanceId restart_attempt=$restartAttempt" "SYSTEM"
        while (-not $process.HasExited) {
            if (-not (Test-LauncherAlive)) {
                Stop-ServiceProcessTree -ProcessId $process.Id -Reason "launcher process exited"
                Write-ServiceLog "Service runner exiting because launcher process is gone. launcher_pid=$LauncherPid instance_id=$instanceId" "WARN"
                exit 0
            }

            Start-Sleep -Seconds 2
            $process.Refresh()
        }

        $exitCode = $process.ExitCode
        $runtimeSeconds = [int][Math]::Max(0, ((Get-Date) - $startedAt).TotalSeconds)
        $process.Dispose()
        Write-ServiceLog "Service exited. exit_code=$exitCode runtime_seconds=$runtimeSeconds instance_id=$instanceId restart_attempt=$restartAttempt" "SYSTEM"

        $serviceOutput = @(
            Get-ServiceOutputSinceLine `
                -Path $serviceLogPath `
                -StartLine $serviceOutputStartLine
        )
        if ($exitCode -ne 0 -and
            (Test-ServiceBindFailure -Name $ServiceName -OutputLines $serviceOutput)) {
            Write-ServiceLog "Service bind failure classified for launcher port recovery. child_exit_code=$exitCode launcher_exit_code=$BindFailureExitCode instance_id=$instanceId" "ERROR"
            exit $BindFailureExitCode
        }

        if ($exitCode -eq 0) {
            exit 0
        }

        if ($runtimeSeconds -ge $StableRunResetSeconds) {
            Write-ServiceLog "Service ran past the stable reset threshold; clearing prior restart count. runtime_seconds=$runtimeSeconds threshold_seconds=$StableRunResetSeconds instance_id=$instanceId" "SYSTEM"
            $restartAttempt = 0
        }

        if ($restartAttempt -ge $MaxRestartAttempts) {
            Write-ServiceLog "Service crash-loop protection stopped recovery. exit_code=$exitCode max_restart_attempts=$MaxRestartAttempts instance_id=$instanceId" "ERROR"
            exit $exitCode
        }

        $backoffIndex = [Math]::Min($restartAttempt, $restartBackoffSeconds.Count - 1)
        $backoffSeconds = [int]$restartBackoffSeconds[$backoffIndex]
        $restartAttempt += 1
        Write-ServiceLog "Service restart scheduled. attempt=$restartAttempt/$MaxRestartAttempts backoff_seconds=$backoffSeconds exit_code=$exitCode instance_id=$instanceId" "WARN"

        if (-not (Wait-RestartBackoff -Seconds $backoffSeconds)) {
            exit 0
        }
    }
}
catch {
    Write-ServiceLog "Service runner failed. error=$($_.Exception.Message)" "ERROR"
    exit 1
}
