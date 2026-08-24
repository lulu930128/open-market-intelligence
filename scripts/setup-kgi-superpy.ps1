param(
    [string]$PythonPath = "",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"

$requiredPythonMajor = 3
$requiredPythonMinor = 12

function Get-PythonRuntimeInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    $raw = & $Executable -c "import json, struct, sys; print(json.dumps({'executable': sys.executable, 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'patch': sys.version_info.micro, 'bits': struct.calcsize('P') * 8}))"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect Python runtime: $Executable"
    }
    try {
        return $raw | ConvertFrom-Json
    }
    catch {
        throw "Python runtime returned an invalid version response: $Executable"
    }
}

function Find-Python312 {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $resolved = & $launcher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($resolved)) {
            return [string]($resolved | Select-Object -Last 1)
        }
    }

    $python312 = Get-Command "python3.12.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python312) {
        return $python312.Source
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $info = Get-PythonRuntimeInfo -Executable $python.Source
        if ($info.major -eq $requiredPythonMajor -and $info.minor -eq $requiredPythonMinor) {
            return $python.Source
        }
    }

    throw "64-bit Python 3.12 was not found. Install Python 3.12 or pass -PythonPath with its python.exe."
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$targetDir = Join-Path $repoRoot ".venv-kgi"
$targetPython = Join-Path $targetDir "Scripts\python.exe"
$requirements = Join-Path $repoRoot "backend\requirements-kgi-superpy.txt"

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Find-Python312
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable does not exist: $PythonPath"
}

$sourceInfo = Get-PythonRuntimeInfo -Executable $PythonPath
if ($sourceInfo.major -ne $requiredPythonMajor -or $sourceInfo.minor -ne $requiredPythonMinor) {
    throw "KGI quote runtime requires Python 3.12; selected Python is $($sourceInfo.major).$($sourceInfo.minor).$($sourceInfo.patch)."
}
if ($sourceInfo.bits -ne 64) {
    throw "KGI quote runtime requires 64-bit Python; selected Python is $($sourceInfo.bits)-bit."
}

if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Missing KGI requirements file: $requirements"
}

if (Test-Path -LiteralPath $targetDir) {
    $mustRecreate = $Recreate.IsPresent -or -not (Test-Path -LiteralPath $targetPython)
    if (-not $mustRecreate) {
        $targetInfo = Get-PythonRuntimeInfo -Executable $targetPython
        $mustRecreate = (
            $targetInfo.major -ne $requiredPythonMajor -or
            $targetInfo.minor -ne $requiredPythonMinor -or
            $targetInfo.bits -ne 64
        )
    }
    if ($mustRecreate) {
        if (-not $Recreate.IsPresent) {
            throw "Existing .venv-kgi is not a usable 64-bit Python 3.12 runtime. Rerun with -Recreate."
        }
        $expectedTarget = [System.IO.Path]::GetFullPath(
            (Join-Path $repoRoot ".venv-kgi")
        )
        $resolvedTarget = [System.IO.Path]::GetFullPath($targetDir)
        if (-not [string]::Equals(
            $expectedTarget,
            $resolvedTarget,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to recreate an unexpected KGI runtime path: $resolvedTarget"
        }
        $targetItem = Get-Item -LiteralPath $resolvedTarget -Force
        if (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to recreate a KGI runtime through a reparse point: $resolvedTarget"
        }
        Write-Host "Recreating isolated KGI runtime at $resolvedTarget"
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $targetPython)) {
    Write-Host "Creating isolated KGI runtime at $targetDir"
    & $PythonPath -m venv $targetDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the isolated KGI runtime."
    }
}

Write-Host "Installing KGI SuperPy into the isolated runtime"
& $targetPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update pip in the isolated KGI runtime."
}

& $targetPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install KGI SuperPy."
}

& $targetPython -c "import importlib.metadata, struct, sys; assert sys.version_info[:2] == (3, 12); assert struct.calcsize('P') * 8 == 64; print('python=' + sys.version.split()[0] + ' bits=64 kgisuperpy=' + importlib.metadata.version('kgisuperpy'))"
if ($LASTEXITCODE -ne 0) {
    throw "KGI SuperPy Python 3.12 runtime verification failed."
}

Write-Host "KGI quote runtime is ready. Fill KGI_SUPERPY_PERSON_ID and KGI_SUPERPY_PASSWORD in .env, then enable ENABLE_KGI_SUPERPY_QUOTE."
