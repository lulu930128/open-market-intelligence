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

    Write-ServiceLog "Starting service. file=$FilePath args=$($arguments -join ' ') cwd=$WorkingDirectory" "SYSTEM"

    Push-Location -LiteralPath $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"

        try {
            & $FilePath @arguments 2>&1 | ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) {
                    Write-ServiceLog $_.ToString() "ERROR"
                }
                else {
                    Write-ServiceLog $_.ToString()
                }
            }
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        $exitCode = if ($null -ne $global:LASTEXITCODE) { $global:LASTEXITCODE } else { 0 }
        Write-ServiceLog "Service exited. exit_code=$exitCode" "SYSTEM"
        exit $exitCode
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-ServiceLog "Service runner failed. error=$($_.Exception.Message)" "ERROR"
    exit 1
}
