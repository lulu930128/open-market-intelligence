param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$ArgumentsJsonBase64,
    [int]$LauncherPid = 0,
    [ValidateRange(0, 20)][int]$MaxRestartAttempts = 3,
    [string]$RestartBackoffSecondsCsv = "2,10,30",
    [ValidateRange(1, 86400)][int]$StableRunResetSeconds = 600
)

$ErrorActionPreference = "Stop"

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
    Add-Content -LiteralPath (Get-ServiceLogPath) -Value $line -Encoding UTF8
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
