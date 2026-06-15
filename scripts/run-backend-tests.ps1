param(
    [string[]]$PytestArgs = @("backend/tests")
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $repoRoot "backend"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pycacheDir = Join-Path ([System.IO.Path]::GetTempPath()) "omi_pycache_pytest"

if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "Missing backend directory: $backendDir"
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Python executable: $python. Rebuild .venv from the repo root before running backend tests."
}

$previousPythonPath = $env:PYTHONPATH
$previousPycachePrefix = $env:PYTHONPYCACHEPREFIX
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $backendDir
}
else {
    $env:PYTHONPATH = "$backendDir;$previousPythonPath"
}
$env:PYTHONPYCACHEPREFIX = $pycacheDir

Push-Location -LiteralPath $repoRoot
try {
    & $python -m pytest -p no:cacheprovider @PytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONPYCACHEPREFIX = $previousPycachePrefix
}
