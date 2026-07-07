param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$ArgumentsJsonBase64,
    [int]$LauncherPid = 0
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

    $serviceLogPath = Get-ServiceLogPath
    $processFilePath = Join-Path $env:SystemRoot "System32\cmd.exe"
    $innerCommand = ((@($FilePath) + $arguments) | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
    $innerCommand = "$innerCommand >> $(ConvertTo-ProcessArgument $serviceLogPath) 2>&1"
    $processArguments = "/d /s /c `"$innerCommand`""

    Write-ServiceLog "Starting service. file=$FilePath args=$($arguments -join ' ') cwd=$WorkingDirectory launcher_pid=$LauncherPid" "SYSTEM"
    Write-ServiceLog "Process runner. file=$processFilePath args=$processArguments" "SYSTEM"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $processFilePath
    $startInfo.Arguments = $processArguments
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    [void]$process.Start()
    while (-not $process.HasExited) {
        if (-not (Test-LauncherAlive)) {
            Stop-ServiceProcessTree -ProcessId $process.Id -Reason "launcher process exited"
            Write-ServiceLog "Service runner exiting because launcher process is gone. launcher_pid=$LauncherPid" "WARN"
            exit 0
        }

        Start-Sleep -Seconds 2
        $process.Refresh()
    }

    $exitCode = $process.ExitCode
    Write-ServiceLog "Service exited. exit_code=$exitCode" "SYSTEM"
    exit $exitCode
}
catch {
    Write-ServiceLog "Service runner failed. error=$($_.Exception.Message)" "ERROR"
    exit 1
}
