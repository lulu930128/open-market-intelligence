param(
    [switch]$Apply,
    [switch]$Backup,
    [switch]$NoBackup,
    [switch]$Vacuum,
    [int]$MinRawChars = 10000,
    [int]$BatchSize = 500,
    [int]$MaxRows = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing Python executable: $python"
}

$env:PYTHONPATH = Join-Path $repoRoot "backend"
$arguments = @(
    "-m",
    "app.resource_market.maintenance",
    "--min-raw-chars",
    ([string]$MinRawChars),
    "--batch-size",
    ([string]$BatchSize)
)

if ($Apply) {
    $arguments += "--apply"
}
if ($Backup) {
    $arguments += "--backup"
}
if ($NoBackup) {
    $arguments += "--no-backup"
}
if ($Vacuum) {
    $arguments += "--vacuum"
}
if ($MaxRows -gt 0) {
    $arguments += @("--max-rows", ([string]$MaxRows))
}

& $python @arguments
