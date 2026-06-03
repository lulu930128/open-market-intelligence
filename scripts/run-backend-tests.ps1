param(
    [string[]]$UnittestArgs = @("discover", "-s", "tests")
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "Missing backend directory: $backendDir"
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Python executable: $python. Rebuild .venv from the repo root before running backend tests."
}

$previousPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $backendDir
}
else {
    $env:PYTHONPATH = "$backendDir;$previousPythonPath"
}

Push-Location -LiteralPath $backendDir
try {
    & $python -m unittest @UnittestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
