param(
    [Parameter(Mandatory = $true)][string]$ServiceName,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$ArgumentsJsonBase64
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

    Write-ServiceLog "Starting service. file=$FilePath args=$($arguments -join ' ') cwd=$WorkingDirectory" "SYSTEM"
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
    $process.WaitForExit()

    $exitCode = $process.ExitCode
    Write-ServiceLog "Service exited. exit_code=$exitCode" "SYSTEM"
    exit $exitCode
}
catch {
    Write-ServiceLog "Service runner failed. error=$($_.Exception.Message)" "ERROR"
    exit 1
}
