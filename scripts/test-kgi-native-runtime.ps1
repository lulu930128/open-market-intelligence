<#
.SYNOPSIS
Offline, read-only .venv-kgi interpreter readiness. Never imports the SDK.
Exit 0 = CPython base readiness ONLY; 2 = BLOCKED. Neither permits REAL_SIM.
No caller-supplied interpreter, proof, credential, output file or repair option.
#>
param([ValidateRange(1, 60)][int]$TimeoutSeconds = 10)

$ErrorActionPreference = 'Stop'

function Assert-KgiLocalPath([string]$Path) {
    # Reject UNC, mapped network drives and reparse points before any file read.
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2).Contains(':')) {
        throw 'LOCAL_PATH_REQUIRED'
    }
    $full = [IO.Path]::GetFullPath($Path)
    if ([IO.DriveInfo]::new($full.Substring(0, 3)).DriveType -ne 'Fixed') {
        throw 'LOCAL_PATH_REQUIRED'
    }
    $cursor = $full
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'REPARSE_POINT_FORBIDDEN' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Read-KgiVenvConfig([string]$Path) {
    $null = Assert-KgiLocalPath $Path
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if (-not $line.Trim()) { continue }
        if ($line -notmatch '^([^=]+?)\s*=\s*(.*?)\s*$') { throw 'VENV_CONFIG_INVALID' }
        $key = $Matches[1].Trim()
        if ($values.ContainsKey($key)) { throw 'VENV_CONFIG_INVALID' }
        $values[$key] = $Matches[2]
    }
    if ($values['version'] -notmatch '^3\.12\.\d+$' -or
        $values['include-system-site-packages'] -cne 'false' -or
        -not $values['home'] -or -not $values['executable']) { throw 'VENV_CONFIG_MISMATCH' }
    # Do not resolve an untrusted network path just to compare it.
    foreach ($key in @('home', 'executable')) {
        if ($values[$key] -notmatch '^[A-Za-z]:\\' -or $values[$key].Substring(2).Contains(':')) {
            throw 'LOCAL_PATH_REQUIRED'
        }
    }
    if ([IO.Path]::GetFullPath($values['executable']) -ine
        [IO.Path]::GetFullPath((Join-Path $values['home'] 'python.exe'))) { throw 'VENV_BASE_MISMATCH' }
    return $values
}

function Assert-KgiPythonImage([string]$Path) {
    $null = Assert-KgiLocalPath $Path
    $stream = [IO.File]::OpenRead($Path)
    $reader = [IO.BinaryReader]::new($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5a4d) { throw 'PYTHON_IMAGE_INVALID' }
        $stream.Position = 60
        $offset = $reader.ReadUInt32()
        if ($offset -gt ($stream.Length - 6)) { throw 'PYTHON_IMAGE_INVALID' }
        $stream.Position = $offset
        if ($reader.ReadUInt32() -ne 0x4550) { throw 'PYTHON_IMAGE_INVALID' }
        if ($reader.ReadUInt16() -ne 0x8664) { throw 'PYTHON_ARCH_MISMATCH' }
    } finally { $reader.Dispose(); $stream.Dispose() }
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    if ($version.FileMajorPart -ne 3 -or $version.FileMinorPart -ne 12) {
        throw 'PYTHON_VERSION_MISMATCH'
    }
}

function New-KgiPythonStartInfo([string]$Python, [string]$WorkingDirectory) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Python
    $info.Arguments = '-I -S -B -'
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    try { $childEnvironment = $info.get_Environment() }
    catch [ArgumentException] { $childEnvironment = $info.get_Environment() }
    $childEnvironment.Clear()
    # No PATH, PYTHON*, TEMP, KGI* or credentials; fixed absolute executable.
    $windows = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $childEnvironment['SystemRoot'] = $windows
    $childEnvironment['WINDIR'] = $windows
    return $info
}

function Get-KgiInterpreterProbe {
    # Literal source only. stdin is closed after writing; caller JSON is not read.
    return @'
import sys
def guard(event, args):
    if (event.startswith(('socket.', 'subprocess.', 'os.spawn', 'os.exec'))
        or event in ('ctypes.dlopen', 'os.system', 'os.mkdir', 'os.remove', 'os.rename')
        or (event == 'import' and str(args[0]).split('.')[0] in ('kgisuperpy', 'site', 'sitecustomize', 'usercustomize'))):
        raise RuntimeError('OFFLINE_INTERPRETER_ONLY')
sys.addaudithook(guard)
import json, struct
print(json.dumps({'schema': 'omi.kgi-interpreter-observation.v1',
    'implementation': sys.implementation.name, 'version': list(sys.version_info[:3]),
    'pointer_bits': struct.calcsize('P') * 8, 'executable': sys.executable,
    'base_executable': sys._base_executable, 'base_prefix': sys.base_prefix,
    'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
    'no_bytecode': sys.flags.dont_write_bytecode, 'ignore_environment': sys.flags.ignore_environment,
    'sys_path': sys.path, 'site_loaded': 'site' in sys.modules,
    'sdk_loaded': any(n == 'kgisuperpy' or n.startswith('kgisuperpy.') for n in sys.modules)}))
'@
}

function Read-KgiInterpreterObservation([string]$Output, [int]$ChildExit, [string]$Diagnostic,
                                        [hashtable]$Config, [string]$Python) {
    if ($ChildExit -ne 0) { throw 'INTERPRETER_EXIT_NONZERO' }
    if ($Diagnostic -or $Output.Length -gt 16384) { throw 'INTERPRETER_RESPONSE_INVALID' }
    $value = $Output | ConvertFrom-Json
    $keys = @('schema','implementation','version','pointer_bits','executable','base_executable',
              'base_prefix','isolated','no_site','no_bytecode','ignore_environment','sys_path',
              'site_loaded','sdk_loaded')
    foreach ($key in $keys) {
        if ([regex]::Matches($Output, ('"' + $key + '"\s*:')).Count -ne 1) {
            throw 'INTERPRETER_RESPONSE_INVALID'
        }
    }
    if ($null -eq $value -or $value -is [array] -or
        @(Compare-Object @($value.PSObject.Properties.Name | Sort-Object) @($keys | Sort-Object)).Count) {
        throw 'INTERPRETER_RESPONSE_INVALID'
    }
    if ($value.schema -cne 'omi.kgi-interpreter-observation.v1' -or
        $value.implementation -cne 'cpython' -or $value.version -isnot [array] -or
        $value.version.Count -ne 3) { throw 'INTERPRETER_RESPONSE_INVALID' }
    foreach ($n in $value.version) {
        if ($n -isnot [int] -and $n -isnot [long]) { throw 'INTERPRETER_RESPONSE_INVALID' }
    }
    if ($value.version[0] -ne 3 -or $value.version[1] -ne 12 -or $value.version[2] -lt 0) {
        throw 'PYTHON_VERSION_MISMATCH'
    }
    if (($value.pointer_bits -isnot [int] -and $value.pointer_bits -isnot [long]) -or
        $value.pointer_bits -ne 64) { throw 'PYTHON_ARCH_MISMATCH' }
    foreach ($key in @('isolated','no_site','no_bytecode','ignore_environment')) {
        if (($value.$key -isnot [int] -and $value.$key -isnot [long]) -or $value.$key -ne 1) {
            throw 'INTERPRETER_ISOLATION_MISMATCH'
        }
    }
    foreach ($key in @('site_loaded','sdk_loaded')) {
        if ($value.$key -isnot [bool] -or $value.$key) { throw 'INTERPRETER_ISOLATION_MISMATCH' }
    }
    foreach ($pair in @(@('executable',$Python), @('base_executable',$Config['executable']),
                       @('base_prefix',$Config['home']))) {
        $actual = $value.($pair[0])
        if ($actual -isnot [string] -or $actual -notmatch '^[A-Za-z]:\\' -or
            [IO.Path]::GetFullPath($actual) -ine [IO.Path]::GetFullPath($pair[1])) {
            throw 'VENV_BASE_MISMATCH'
        }
    }
    # CPython 3.12 -S reports base prefix, not venv prefix. Only base stdlib paths
    # are permitted; site-packages, current directory and script paths are absent.
    $base = [IO.Path]::GetFullPath($Config['home']).TrimEnd('\')
    $allowed = @($base, "$base\python312.zip", "$base\DLLs", "$base\Lib")
    if ($value.sys_path -isnot [array] -or -not $value.sys_path.Count) { throw 'INTERPRETER_PATH_MISMATCH' }
    foreach ($path in $value.sys_path) {
        if ($path -isnot [string] -or $path -notmatch '^[A-Za-z]:\\' -or
            [IO.Path]::GetFullPath($path).TrimEnd('\') -notin $allowed) { throw 'INTERPRETER_PATH_MISMATCH' }
    }
    # Paths are used only for internal equality checks; never publish local user
    # paths from sys.executable/sys.path. Patch drift is visible, not an ABI claim.
    return [ordered]@{
        implementation='cpython'; version=($value.version -join '.'); pointer_bits=64
        isolated=$true; no_site=$true; no_bytecode=$true; ignore_environment=$true
        executable_match=$true; base_match=$true; stdlib_path_match=$true
        configured_version=$Config['version']
        patch_drift=(($value.version -join '.') -cne $Config['version'])
    }
}

function Invoke-KgiNativeReadiness([string]$Repo, [int]$Timeout) {
    $report = [ordered]@{
        schema='omi.kgi-native-runtime-readiness.v1'; mode='NativeRuntimeReadiness'
        scope='INTERPRETER_BASE_ONLY'; status='BLOCKED'; reasonCodes=@(); exit_code=2
        observed_at=[DateTimeOffset]::UtcNow.ToString('o'); origin='LOCAL_INTERPRETER_CHECK'
        interpreter=$null; child_exit_code=$null; stage='VENV_CONFIG'
        sdk_imported=$false; native_abi_verified=$false; endpoint_attested=$false
        credential_verified=$false; login_attempts=0; broker_calls=0; orders_sent=0
        real_sim='BLOCKED'; real_production='FORBIDDEN'; session_reuse='FORBIDDEN'
    }
    $child = $null
    $started = $false
    try {
        $config = Read-KgiVenvConfig (Join-Path $Repo '.venv-kgi\pyvenv.cfg')
        $report.stage = 'BASE_IMAGE'
        Assert-KgiPythonImage $config['executable']
        $report.stage = 'VENV_IMAGE'
        $python = Join-Path $Repo '.venv-kgi\Scripts\python.exe'
        Assert-KgiPythonImage $python
        $report.stage = 'INTERPRETER_START'
        $child = [Diagnostics.Process]::new()
        $child.StartInfo = New-KgiPythonStartInfo $python $config['home']
        if (-not $child.Start()) { throw 'INTERPRETER_START_FAILED' }
        $started = $true
        $stdout = $child.StandardOutput.ReadToEndAsync()
        $stderr = $child.StandardError.ReadToEndAsync()
        $child.StandardInput.Write((Get-KgiInterpreterProbe))
        $child.StandardInput.Close()
        $report.stage = 'INTERPRETER_WAIT'
        if (-not $child.WaitForExit($Timeout * 1000)) { throw 'INTERPRETER_TIMEOUT' }
        $report.child_exit_code = $child.ExitCode
        $report.stage = 'INTERPRETER_RESPONSE'
        $report.interpreter = Read-KgiInterpreterObservation $stdout.GetAwaiter().GetResult() `
            $child.ExitCode $stderr.GetAwaiter().GetResult() $config $python
        $report.status = 'PASS'
        $report.exit_code = 0
        if ($report.interpreter.patch_drift) { $report.reasonCodes = @('PYTHON_PATCH_DRIFT') }
        $report.stage = 'COMPLETE'
    } catch {
        # Never echo exception text, child stdout/stderr, config or environment.
        $known = @('LOCAL_PATH_REQUIRED','REPARSE_POINT_FORBIDDEN','VENV_CONFIG_INVALID',
            'VENV_CONFIG_MISMATCH','VENV_BASE_MISMATCH','PYTHON_IMAGE_INVALID','PYTHON_ARCH_MISMATCH',
            'PYTHON_VERSION_MISMATCH','INTERPRETER_EXIT_NONZERO','INTERPRETER_RESPONSE_INVALID',
            'INTERPRETER_ISOLATION_MISMATCH','INTERPRETER_PATH_MISMATCH','INTERPRETER_START_FAILED',
            'INTERPRETER_TIMEOUT')
        $reason = 'READINESS_FAILED_CLOSED'
        if ($_.Exception.Message -cin $known) { $reason = $_.Exception.Message }
        elseif ($_.CategoryInfo.Category -eq 'PermissionDenied' -or
                $_.Exception.GetBaseException() -is [UnauthorizedAccessException]) {
            $reason = if ($report.stage -eq 'BASE_IMAGE') { 'BASE_PATH_ACCESS_DENIED' } else { 'PATH_ACCESS_DENIED' }
        }
        elseif ($_.CategoryInfo.Category -eq 'ObjectNotFound' -or
                $_.Exception.GetBaseException() -is [IO.FileNotFoundException] -or
                $_.Exception.GetBaseException() -is [IO.DirectoryNotFoundException]) { $reason = 'PATH_NOT_FOUND' }
        $report.reasonCodes = @($reason)
    } finally {
        if ($null -ne $child) {
            try {
                if ($started -and -not $child.HasExited) {
                    $child.Kill()
                    if (-not $child.WaitForExit(5000)) { throw 'STOP_TIMEOUT' }
                }
            } catch {
                $report.status = 'BLOCKED'; $report.exit_code = 2
                $report.reasonCodes += 'OWNED_INTERPRETER_TEARDOWN_UNVERIFIED'
            }
            $child.Dispose()
        }
    }
    return $report
}

# Dot-source exposes pure validation helpers for offline tests, never a CLI proof
# ingress. The executable entrypoint always derives the one project-owned path.
if ($MyInvocation.InvocationName -ne '.') {
    $repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $result = Invoke-KgiNativeReadiness $repo $TimeoutSeconds
    $result | ConvertTo-Json -Depth 6 -Compress
    exit $result.exit_code
}
