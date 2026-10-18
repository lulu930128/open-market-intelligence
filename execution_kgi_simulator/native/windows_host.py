"""Single Windows process/handle owner. Never imports the SDK.

This is a lifecycle building block, not a native network/filesystem sandbox.
No global policy/profile/ACL/registry changes, credential reads or env inheritance.
G1-A keeps the fixed repo interpreter suspended. G1-B/C may resume ONLY the
SHA-pinned synthetic canary after independent AppContainer token/Job checks.
"""

import ctypes as C
from ctypes import wintypes as W
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / '.venv/Scripts/python.exe'
KILL_ON_CLOSE = 0x2000
ACTIVE_PROCESS = 0x8
JOB_FLAGS = KILL_ON_CLOSE | ACTIVE_PROCESS


class HostDenied(RuntimeError):
    def __init__(self, stage, winerror=0):
        self.stage, self.winerror = stage, winerror
        super().__init__(stage)


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [('length', W.DWORD), ('descriptor', C.c_void_p), ('inherit', W.BOOL)]


class STARTUPINFO(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR),
                ('title', W.LPWSTR), ('x', W.DWORD), ('y', W.DWORD),
                ('xsize', W.DWORD), ('ysize', W.DWORD), ('xchars', W.DWORD),
                ('ychars', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved2size', W.WORD), ('reserved2', C.c_void_p),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class STARTUPINFOEX(C.Structure):
    _fields_ = [('startup', STARTUPINFO), ('attributes', C.c_void_p)]


class PROCESS_INFORMATION(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


class BASIC_LIMIT(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                ('flags', W.DWORD), ('min_ws', C.c_size_t), ('max_ws', C.c_size_t),
                ('active', W.DWORD), ('affinity', C.c_size_t), ('priority', W.DWORD),
                ('scheduling', W.DWORD)]


class IO_COUNTERS(C.Structure):
    _fields_ = [(n, C.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops',
                                          'read_bytes', 'write_bytes', 'other_bytes')]


class EXTENDED_LIMIT(C.Structure):
    _fields_ = [('basic', BASIC_LIMIT), ('io', IO_COUNTERS),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process_memory', C.c_size_t), ('peak_job_memory', C.c_size_t)]


class LUID(C.Structure):
    _fields_ = [('low', W.DWORD), ('high', W.LONG)]


class PRIVILEGE(C.Structure):
    _fields_ = [('luid', LUID), ('attributes', W.DWORD)]


class FILE_INFORMATION(C.Structure):
    _fields_ = [('attributes', W.DWORD), ('creation', W.FILETIME),
                ('access', W.FILETIME), ('write', W.FILETIME), ('volume', W.DWORD),
                ('size_high', W.DWORD), ('size_low', W.DWORD), ('links', W.DWORD),
                ('index_high', W.DWORD), ('index_low', W.DWORD)]


class WindowsAPI:
    """Explicit ABI signatures; DLL lookup restricted to Windows System32."""
    def __init__(self):
        if sys.platform != 'win32':
            raise HostDenied('WINDOWS_REQUIRED')
        self.k = C.WinDLL('kernel32.dll', use_last_error=True, winmode=0x800)
        self.a = C.WinDLL('advapi32.dll', use_last_error=True, winmode=0x800)
        signatures = [
            (self.k, 'CloseHandle', W.BOOL, [W.HANDLE]),
            (self.k, 'GetCurrentProcess', W.HANDLE, []),
            (self.k, 'GetProcessId', W.DWORD, [W.HANDLE]),
            (self.k, 'GetHandleInformation', W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
            (self.k, 'SetHandleInformation', W.BOOL, [W.HANDLE, W.DWORD, W.DWORD]),
            (self.k, 'CreateJobObjectW', W.HANDLE, [C.c_void_p, W.LPCWSTR]),
            (self.k, 'SetInformationJobObject', W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]),
            (self.k, 'QueryInformationJobObject', W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p]),
            (self.k, 'IsProcessInJob', W.BOOL, [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]),
            (self.k, 'CreatePipe', W.BOOL, [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.POINTER(SECURITY_ATTRIBUTES), W.DWORD]),
            (self.k, 'InitializeProcThreadAttributeList', W.BOOL, [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]),
            (self.k, 'UpdateProcThreadAttribute', W.BOOL, [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p]),
            (self.k, 'DeleteProcThreadAttributeList', None, [C.c_void_p]),
            (self.k, 'QueryFullProcessImageNameW', W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]),
            (self.k, 'GetProcessTimes', W.BOOL, [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4),
            (self.k, 'WaitForSingleObject', W.DWORD, [W.HANDLE, W.DWORD]),
            (self.k, 'TerminateProcess', W.BOOL, [W.HANDLE, W.UINT]),
            (self.k, 'GetExitCodeProcess', W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
            (self.k, 'CreateFileW', W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]),
            (self.k, 'GetFinalPathNameByHandleW', W.DWORD, [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]),
            (self.k, 'ReadFile', W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]),
            (self.k, 'GetFileInformationByHandle', W.BOOL, [W.HANDLE, C.POINTER(FILE_INFORMATION)]),
            (self.a, 'OpenProcessToken', W.BOOL, [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]),
            (self.a, 'CreateRestrictedToken', W.BOOL, [W.HANDLE, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD, C.c_void_p, C.POINTER(W.HANDLE)]),
            (self.a, 'GetTokenInformation', W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]),
            (self.a, 'LookupPrivilegeValueW', W.BOOL, [W.LPCWSTR, W.LPCWSTR, C.POINTER(LUID)]),
            (self.a, 'CreateProcessAsUserW', W.BOOL, [W.HANDLE, W.LPCWSTR, W.LPWSTR,
                C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR,
                C.POINTER(STARTUPINFOEX), C.POINTER(PROCESS_INFORMATION)]),
        ]
        for dll, name, result, args in signatures:
            function = getattr(dll, name)
            function.restype, function.argtypes = result, args

    def check(self, result, stage):
        if not result:
            raise HostDenied(stage, C.get_last_error())
        return result


class _OwnedHandles:
    """One owner; transfer/close tracked, failed closes retained for retry."""
    def __init__(self, api):
        self.api, self.items = api, []

    def add(self, handle):
        value = handle.value if isinstance(handle, W.HANDLE) else handle
        if not value or value == C.c_void_p(-1).value or value in self.items:
            raise HostDenied('INVALID_OR_DUPLICATE_OWNED_HANDLE')
        self.items.append(value)
        return value

    def close(self, handle):
        if handle not in self.items:
            raise HostDenied('HANDLE_NOT_OWNED')
        self.api.check(self.api.k.CloseHandle(handle), 'HANDLE_CLOSE_FAILED')
        self.items.remove(handle)

    def close_all(self):
        failed = False
        for handle in self.items[:][::-1]:
            try:
                self.close(handle)
            except HostDenied:
                failed = True
        if failed:
            raise HostDenied('HANDLE_CLEANUP_UNVERIFIED')


def _verify_token(api, token):
    size, elevation = W.DWORD(), W.DWORD()
    api.check(api.a.GetTokenInformation(token, 20, C.byref(elevation), C.sizeof(elevation), C.byref(size)), 'TOKEN_ELEVATION_QUERY')
    if elevation.value:
        raise HostDenied('ELEVATED_TOKEN_REJECTED')
    api.a.GetTokenInformation(token, 3, None, 0, C.byref(size))
    if not 4 <= size.value <= 65536:
        raise HostDenied('TOKEN_PRIVILEGE_SIZE')
    buffer = C.create_string_buffer(size.value)
    api.check(api.a.GetTokenInformation(token, 3, buffer, size, C.byref(size)), 'TOKEN_PRIVILEGE_QUERY')
    count = W.DWORD.from_buffer(buffer).value
    if 4 + count * C.sizeof(PRIVILEGE) > len(buffer):
        raise HostDenied('TOKEN_PRIVILEGE_BOUNDS')
    allowed = LUID()
    api.check(api.a.LookupPrivilegeValueW(None, 'SeChangeNotifyPrivilege', C.byref(allowed)), 'TOKEN_PRIVILEGE_ID')
    for index in range(count):
        entry = PRIVILEGE.from_buffer(buffer, 4 + index * C.sizeof(PRIVILEGE))
        if (entry.luid.low, entry.luid.high) != (allowed.low, allowed.high):
            raise HostDenied('TOKEN_EXCESS_PRIVILEGES')


def _verify_identity(api, process, pid, expected_image=IMAGE):
    if api.k.GetProcessId(process) != pid:
        raise HostDenied('PROCESS_ID_MISMATCH')
    path, size = C.create_unicode_buffer(32768), W.DWORD(32768)
    api.check(api.k.QueryFullProcessImageNameW(process, 0, path, C.byref(size)), 'PROCESS_IMAGE_QUERY')
    if Path(path.value) != expected_image:
        raise HostDenied('PROCESS_IMAGE_MISMATCH')
    times = [W.FILETIME() for _ in range(4)]
    api.check(api.k.GetProcessTimes(process, *(C.byref(t) for t in times)), 'PROCESS_CREATION_QUERY')
    created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    if not created or api.k.WaitForSingleObject(process, 0) != 258:
        raise HostDenied('PROCESS_NOT_LIVE_SUSPENDED')
    return created


def _locked_image_digest(api, handle):
    path = C.create_unicode_buffer(32768)
    count = api.k.GetFinalPathNameByHandleW(handle, path, len(path), 0)
    if not 0 < count < len(path) or path.value != '\\\\?\\' + str(IMAGE):
        raise HostDenied('LOCKED_IMAGE_PATH_MISMATCH')
    digest, total = sha256(), 0
    buffer, count = C.create_string_buffer(65536), W.DWORD()
    while True:
        api.check(api.k.ReadFile(handle, buffer, len(buffer), C.byref(count), None), 'LOCKED_IMAGE_READ')
        if not count.value:
            break
        total += count.value
        if total > 64 * 1024 * 1024:
            raise HostDenied('LOCKED_IMAGE_SIZE_REJECTED')
        digest.update(buffer.raw[:count.value])
    if not total:
        raise HostDenied('LOCKED_IMAGE_EMPTY')
    return digest.hexdigest()


def _lock_source_path(api, handles):
    # Lock ancestors top-down before walking deeper. Deny rename/delete/write;
    # OPEN_REPARSE_POINT plus handle metadata rejects a swap at every component.
    for part in reversed(IMAGE.parents):
        handle = api.k.CreateFileW(str(part), 0x80, 1, None, 3, 0x02200000, None)
        if not handle or handle == C.c_void_p(-1).value:
            raise HostDenied('SOURCE_ANCESTOR_LOCK_FAILED', C.get_last_error())
        handles.add(handle)
        info = FILE_INFORMATION()
        api.check(api.k.GetFileInformationByHandle(handle, C.byref(info)), 'SOURCE_ANCESTOR_QUERY')
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise HostDenied('SOURCE_ANCESTOR_REPARSE_OR_NOT_DIRECTORY')
    handle = api.k.CreateFileW(str(IMAGE), 0x80000000, 1, None, 3, 0x00200000, None)
    if not handle or handle == C.c_void_p(-1).value:
        raise HostDenied('IMAGE_LOCK_FAILED', C.get_last_error())
    handles.add(handle)
    info = FILE_INFORMATION()
    api.check(api.k.GetFileInformationByHandle(handle, C.byref(info)), 'LOCKED_IMAGE_QUERY')
    if info.attributes & (0x400 | 0x10) or info.links != 1:
        raise HostDenied('IMAGE_REPARSE_DIRECTORY_OR_HARDLINK_REJECTED')
    return handle


def suspended_denial_probe() -> dict:
    """Actual OS calls, fixed no-secret image, atomic Job admission, no resume.

    A suspended child cannot exercise Winsock; this is NOT a network denial test.
    No caller command, endpoint, proof, token, handle or environment accepted.
    """
    report = {'schema': 'omi.kgi-host-lifecycle.v1', 'status': 'BLOCKED',
              'evidence': 'OS_PROBE_ATTEMPTED', 'lifecycle': 'UNVERIFIED',
              'network': 'NOT_INSTALLED', 'filesystem': 'NOT_INSTALLED',
              'child_resumed': False, 'credential_values_read': False,
              'sdk_imported': False, 'broker_calls': 0, 'orders_sent': 0,
              'activation_authority': False}
    api = None
    handles = None
    attributes = None
    child = None
    try:
        api = WindowsAPI()
        handles = _OwnedHandles(api)
        image = _lock_source_path(api, handles)
        report['locked_image_sha256'] = _locked_image_digest(api, image)
        parent_token, restricted = W.HANDLE(), W.HANDLE()
        api.check(api.a.OpenProcessToken(api.k.GetCurrentProcess(), 0xB, C.byref(parent_token)), 'PARENT_TOKEN_OPEN')
        handles.add(parent_token)
        api.check(api.a.CreateRestrictedToken(parent_token, 1, 0, None, 0, None, 0, None, C.byref(restricted)), 'RESTRICTED_TOKEN_CREATE')
        handles.add(restricted)
        _verify_token(api, restricted)
        job = handles.add(api.check(api.k.CreateJobObjectW(None, None), 'JOB_CREATE'))
        limits = EXTENDED_LIMIT()
        limits.basic.flags, limits.basic.active = JOB_FLAGS, 1
        api.check(api.k.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)), 'JOB_LIMITS_SET')
        observed = EXTENDED_LIMIT()
        api.check(api.k.QueryInformationJobObject(job, 9, C.byref(observed), C.sizeof(observed), None), 'JOB_LIMITS_QUERY')
        if observed.basic.flags != JOB_FLAGS or observed.basic.active != 1:
            raise HostDenied('JOB_LIMITS_MISMATCH')
        sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), None, True)
        pipes = []
        for _ in range(2):
            read, write = W.HANDLE(), W.HANDLE()
            api.check(api.k.CreatePipe(C.byref(read), C.byref(write), C.byref(sa), 4096), 'PRIVATE_PIPE_CREATE')
            pipes.append((handles.add(read), handles.add(write)))
        child_read, parent_write = pipes[0]
        parent_read, child_write = pipes[1]
        for h in (parent_read, parent_write):
            api.check(api.k.SetHandleInformation(h, 1, 0), 'PARENT_HANDLE_NO_INHERIT')
        for h in handles.items:
            flags = W.DWORD()
            api.check(api.k.GetHandleInformation(h, C.byref(flags)), 'HANDLE_FLAGS_QUERY')
            if bool(flags.value & 1) != (h in (child_read, child_write)):
                raise HostDenied('HANDLE_INHERITANCE_MISMATCH')
        size = C.c_size_t()
        api.k.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
        if not 0 < size.value <= 65536:
            raise HostDenied('ATTRIBUTE_LIST_SIZE')
        buffer = C.create_string_buffer(size.value)
        api.check(api.k.InitializeProcThreadAttributeList(buffer, 2, 0, C.byref(size)), 'ATTRIBUTE_LIST_INIT')
        attributes = buffer
        inherited = (W.HANDLE * 2)(child_read, child_write)
        jobs = (W.HANDLE * 1)(job)
        api.check(api.k.UpdateProcThreadAttribute(buffer, 0, 0x20002, inherited, C.sizeof(inherited), None, None), 'HANDLE_LIST_BIND')
        api.check(api.k.UpdateProcThreadAttribute(buffer, 0, 0x2000D, jobs, C.sizeof(jobs), None, None), 'ATOMIC_JOB_LIST_BIND')
        startup = STARTUPINFOEX()
        startup.startup.cb, startup.startup.flags = C.sizeof(startup), 0x100
        startup.startup.stdin = child_read
        startup.startup.stdout = startup.startup.stderr = child_write
        startup.attributes = C.cast(buffer, C.c_void_p)
        info = PROCESS_INFORMATION()
        command = C.create_unicode_buffer('"' + str(IMAGE) + '" -I -S -B -c "raise SystemExit(97)"')
        environment = C.create_unicode_buffer('\0\0')
        # CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
        api.check(api.a.CreateProcessAsUserW(restricted, str(IMAGE), command, None, None,
            True, 0x08080404, environment, str(ROOT), C.byref(startup), C.byref(info)), 'RESTRICTED_SUSPENDED_CREATE')
        child = handles.add(info.process)
        handles.add(info.thread)
        for h in (child_read, child_write):
            handles.close(h)
        identity = _verify_identity(api, child, info.pid)
        in_job = W.BOOL()
        api.check(api.k.IsProcessInJob(child, job, C.byref(in_job)), 'CHILD_JOB_QUERY')
        if not in_job.value:
            raise HostDenied('CHILD_JOB_MISMATCH')
        child_token = W.HANDLE()
        api.check(api.a.OpenProcessToken(child, 8, C.byref(child_token)), 'CHILD_TOKEN_OPEN')
        handles.add(child_token)
        _verify_token(api, child_token)
        if _verify_identity(api, child, info.pid) != identity:
            raise HostDenied('CHILD_CREATION_IDENTITY_CHANGED')
        handles.close(job)
        if api.k.WaitForSingleObject(child, 5000) != 0:
            raise HostDenied('JOB_CLOSE_TERMINATION_UNVERIFIED')
        exit_code = W.DWORD()
        api.check(api.k.GetExitCodeProcess(child, C.byref(exit_code)), 'CHILD_EXIT_QUERY')
        report.update(lifecycle='OS_VERIFIED_SUSPENDED_CHILD_JOB_CLOSE',
                      child_exit_code=exit_code.value, pid=info.pid,
                      creation_time=identity, token='OS_VERIFIED_PRIVILEGES_STRIPPED_NON_ELEVATED',
                      handles='EXPLICIT_TWO_PIPE_ENDS', job='KILL_ON_CLOSE_NO_BREAKAWAY_ACTIVE_LIMIT_1')
    except HostDenied as error:
        report.update(reasonCodes=[error.stage], winerror=error.winerror)
    except OSError as error:
        report.update(reasonCodes=['HOST_OS_ACCESS_UNVERIFIED'], winerror=error.winerror or 0)
    finally:
        if api is not None:
            try:
                if child and api.k.WaitForSingleObject(child, 0) != 0:
                    api.check(api.k.TerminateProcess(child, 2), 'OWNED_CHILD_TERMINATE_FAILED')
                    if api.k.WaitForSingleObject(child, 5000) != 0:
                        raise HostDenied('OWNED_CHILD_TEARDOWN_UNVERIFIED')
                report['teardown'] = 'NO_LIVE_OWNED_CHILD'
            except HostDenied as error:
                report.update(lifecycle='UNVERIFIED', teardown=error.stage)
            finally:
                if attributes is not None:
                    api.k.DeleteProcThreadAttributeList(attributes)
                if handles is not None:
                    try:
                        handles.close_all()
                        report['owned_handles_remaining'] = 0
                    except HostDenied:
                        report.update(lifecycle='UNVERIFIED', teardown='HANDLE_CLEANUP_UNVERIFIED')
    return report


# G1-B/C private synthetic seam. No profile registration or existing ACL edits.
class SECURITY_CAPABILITIES(C.Structure):
    _fields_ = [('sid', C.c_void_p), ('capabilities', C.c_void_p),
                ('count', W.DWORD), ('reserved', W.DWORD)]


class STREAM_DATA(C.Structure):
    _fields_ = [('size', C.c_longlong), ('name', W.WCHAR * 296)]


class SandboxAPI(WindowsAPI):
    def __init__(self):
        super().__init__()
        self.u = C.WinDLL('userenv.dll', use_last_error=True, winmode=0x800)
        self.ole = C.WinDLL('ole32.dll', use_last_error=True, winmode=0x800)
        self.firewall = C.WinDLL('firewallapi.dll', use_last_error=True, winmode=0x800)
        signatures = [
            (self.u, 'DeriveAppContainerSidFromAppContainerName', W.LONG, [W.LPCWSTR, C.POINTER(C.c_void_p)]),
            (self.u, 'GetAppContainerFolderPath', W.LONG, [W.LPCWSTR, C.POINTER(W.LPWSTR)]),
            (self.ole, 'CoTaskMemFree', None, [C.c_void_p]),
            (self.firewall, 'NetworkIsolationGetAppContainerConfig', W.DWORD, [C.POINTER(W.DWORD), C.POINTER(C.c_void_p)]),
            (self.a, 'FreeSid', C.c_void_p, [C.c_void_p]),
            (self.a, 'EqualSid', W.BOOL, [C.c_void_p, C.c_void_p]),
            (self.a, 'ConvertSidToStringSidW', W.BOOL, [C.c_void_p, C.POINTER(W.LPWSTR)]),
            (self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', W.BOOL,
                [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)]),
            (self.k, 'LocalFree', C.c_void_p, [C.c_void_p]),
            (self.k, 'GetProcessHeap', W.HANDLE, []),
            (self.k, 'HeapFree', W.BOOL, [W.HANDLE, W.DWORD, C.c_void_p]),
            (self.k, 'CreateMutexW', W.HANDLE, [C.c_void_p, W.BOOL, W.LPCWSTR]),
            (self.k, 'CreateDirectoryW', W.BOOL, [W.LPCWSTR, C.POINTER(SECURITY_ATTRIBUTES)]),
            (self.k, 'WriteFile', W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]),
            (self.k, 'PeekNamedPipe', W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.c_void_p, C.POINTER(W.DWORD), C.c_void_p]),
            (self.k, 'ResumeThread', W.DWORD, [W.HANDLE]),
            (self.k, 'FindFirstStreamW', W.HANDLE, [W.LPCWSTR, C.c_int, C.POINTER(STREAM_DATA), W.DWORD]),
            (self.k, 'FindNextStreamW', W.BOOL, [W.HANDLE, C.POINTER(STREAM_DATA)]),
            (self.k, 'FindClose', W.BOOL, [W.HANDLE]),
        ]
        for dll, name, result, args in signatures:
            function = getattr(dll, name)
            function.restype, function.argtypes = result, args


def sandbox_capabilities() -> dict:
    """Pure export checks; no profile, token, workspace, policy or child creation."""
    report = {'schema': 'omi.kgi-sandbox-capability.v1', 'status': 'BLOCKED',
              'network': 'UNVERIFIED', 'filesystem': 'UNVERIFIED',
              'profile_registration': 'NOT_ATTEMPTED', 'activation_default': 'DISABLED',
              'activation_authority': False, 'experimental_used': False}
    from execution_kgi_simulator.native.host_policy import APPROVED_APPCONTAINER_PROFILE
    report['approved_profile'] = 'NOT_ENROLLED' if APPROVED_APPCONTAINER_PROFILE is None else 'ENROLLED_REQUIRES_OS_CHECK'
    try:
        api = SandboxAPI()
        report['documented_apis'] = 'AVAILABLE_NOT_OS_ACCEPTANCE'
        # System32-only optional detection. Never call experimental exports.
        try:
            experimental = C.WinDLL('processmodel.dll', use_last_error=True, winmode=0x800)
            report['experimental_exports'] = {name: hasattr(experimental, name) for name in (
                'Experimental_CreateProcessInSandbox', 'Experimental_CreateProcessAsUserInSandbox')}
        except OSError as error:
            report['experimental_exports'] = 'UNAVAILABLE'
            report['experimental_winerror'] = error.winerror or 0
        report['profile_api_available'] = all(hasattr(api.u, name) for name in
            ('CreateAppContainerProfile', 'DeleteAppContainerProfile'))
    except (HostDenied, OSError) as error:
        report['stage'] = getattr(error, 'stage', 'CAPABILITY_API_LOAD')
        report['winerror'] = getattr(error, 'winerror', 0) or 0
    return report


class SID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [('sid', C.c_void_p), ('attributes', W.DWORD)]


def _approved_profile_sid(api):
    from execution_kgi_simulator.native.host_policy import APPROVED_APPCONTAINER_PROFILE
    approved = APPROVED_APPCONTAINER_PROFILE
    if approved is None: raise HostDenied('APPROVED_PREEXISTING_PROFILE_NOT_ENROLLED')
    if (type(approved) is not tuple or len(approved) != 2
            or any(type(v) is not str for v in approved)
            or not approved[0].startswith('OMI.KGI.Canary.')
            or not approved[1].startswith('S-1-15-2-')):
        raise HostDenied('APPROVED_PROFILE_SOURCE_RECORD_INVALID')
    sid, folder, exemptions = C.c_void_p(), W.LPWSTR(), C.c_void_p()
    count = W.DWORD()
    exemptions_validated = False
    try:
        hr = api.u.DeriveAppContainerSidFromAppContainerName(approved[0], C.byref(sid))
        if hr != 0: raise HostDenied('APPROVED_PROFILE_SID_DERIVE', hr & 0xffffffff)
        if _sid_text(api, sid) != approved[1]: raise HostDenied('APPROVED_PROFILE_SID_MISMATCH')
        hr = api.u.GetAppContainerFolderPath(approved[1], C.byref(folder))
        if hr != 0: raise HostDenied('APPROVED_PROFILE_FOLDER_QUERY', hr & 0xffffffff)
        # Metadata only. Never inspect contents, registry, user CA or credentials.
        profile = Path(folder.value)
        from execution_kgi_simulator.native.host_policy import local_path
        local_path(profile)
        for path in (profile, *profile.parents):
            info = path.lstat()
            if not path.is_dir() or info.st_file_attributes & 0x400:
                raise HostDenied('APPROVED_PROFILE_MISSING_OR_REPARSE')
        code = api.firewall.NetworkIsolationGetAppContainerConfig(C.byref(count), C.byref(exemptions))
        if code: raise HostDenied('LOOPBACK_EXEMPTION_QUERY', code)
        if count.value > 4096 or (count.value and not exemptions): raise HostDenied('LOOPBACK_EXEMPTION_BOUNDS')
        exemptions_validated = True
        values = C.cast(exemptions, C.POINTER(SID_AND_ATTRIBUTES))
        if any(api.a.EqualSid(values[i].sid, sid) for i in range(count.value)):
            raise HostDenied('APPROVED_PROFILE_HAS_LOOPBACK_EXEMPTION')
        result, sid = sid, C.c_void_p()
        return result
    finally:
        if sid: api.a.FreeSid(sid)
        if folder: api.ole.CoTaskMemFree(C.cast(folder, C.c_void_p))
        # Microsoft documents separate process-heap allocations for each SID.
        if exemptions:
            heap = api.k.GetProcessHeap()
            freed = True
            if exemptions_validated:
                values = C.cast(exemptions, C.POINTER(SID_AND_ATTRIBUTES))
                for i in range(count.value):
                    if not api.k.HeapFree(heap, 0, values[i].sid): freed = False
            # An invalid OS count is never traversed during cleanup. Only the
            # known array pointer is freed; any untraversed SID allocations are
            # unverified and die with this bounded parent, never an OOB walk.
            if not api.k.HeapFree(heap, 0, exemptions): freed = False
            if not freed: raise HostDenied('EXEMPTION_HEAP_CLEANUP_UNVERIFIED')


def _token_buffer(api, token, kind):
    size = W.DWORD()
    api.a.GetTokenInformation(token, kind, None, 0, C.byref(size))
    if not 4 <= size.value <= 65536: raise HostDenied('SANDBOX_TOKEN_BUFFER_SIZE')
    buffer = C.create_string_buffer(size.value)
    api.check(api.a.GetTokenInformation(token, kind, buffer, size, C.byref(size)), 'SANDBOX_TOKEN_QUERY')
    return buffer


def _sid_text(api, sid):
    text = W.LPWSTR()
    api.check(api.a.ConvertSidToStringSidW(sid, C.byref(text)), 'SID_STRING')
    try: return text.value
    finally: api.k.LocalFree(C.cast(text, C.c_void_p))


def _verify_appcontainer(api, token, sid):
    _verify_token(api, token)
    ac = _token_buffer(api, token, 29)  # TokenIsAppContainer
    actual = _token_buffer(api, token, 31)  # TokenAppContainerSid
    caps = _token_buffer(api, token, 30)  # TokenCapabilities (TOKEN_GROUPS)
    if W.DWORD.from_buffer(ac).value != 1:
        raise HostDenied('CHILD_NOT_APPCONTAINER')
    if len(actual) < C.sizeof(C.c_void_p) or not api.a.EqualSid(C.c_void_p.from_buffer(actual), sid):
        raise HostDenied('CHILD_APPCONTAINER_SID_MISMATCH')
    if W.DWORD.from_buffer(caps).value != 0:
        raise HostDenied('CHILD_CAPABILITIES_NOT_EMPTY')


def _no_streams(api, path):
    data = STREAM_DATA()
    find = api.k.FindFirstStreamW(str(path), 0, C.byref(data), 0)
    if not find or find == C.c_void_p(-1).value:
        raise HostDenied('STREAM_ENUMERATION_UNVERIFIED', C.get_last_error())
    try:
        if data.name != '::$DATA': raise HostDenied('ALTERNATE_DATA_STREAM_REJECTED')
        if api.k.FindNextStreamW(find, C.byref(data)):
            raise HostDenied('ALTERNATE_DATA_STREAM_REJECTED')
        if C.get_last_error() != 38: raise HostDenied('STREAM_ENUMERATION_INCOMPLETE', C.get_last_error())
    finally:
        api.check(api.k.FindClose(find), 'STREAM_ENUMERATION_CLOSE')


def _lock_path(api, owned, path, directory=False):
    from execution_kgi_simulator.native.host_policy import local_path
    local_path(path)
    # Hold every ancestor against rename/delete, checking reparse by handle.
    for parent in reversed(path.parents):
        h = api.k.CreateFileW(str(parent), 0x80, 1, None, 3, 0x02200000, None)
        if not h or h == C.c_void_p(-1).value: raise HostDenied('PATH_ANCESTOR_LOCK', C.get_last_error())
        owned.add(h)
        info = FILE_INFORMATION()
        api.check(api.k.GetFileInformationByHandle(h, C.byref(info)), 'PATH_ANCESTOR_INFO')
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise HostDenied('PATH_ANCESTOR_REPARSE_REJECTED')
    h = api.k.CreateFileW(str(path), 0x80 if directory else 0x80000000, 1, None, 3,
                         0x02200000 if directory else 0x00200000, None)
    if not h or h == C.c_void_p(-1).value: raise HostDenied('PATH_FILE_LOCK', C.get_last_error())
    owned.add(h)
    info = FILE_INFORMATION()
    api.check(api.k.GetFileInformationByHandle(h, C.byref(info)), 'PATH_FILE_INFO')
    if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory or (not directory and info.links != 1):
        raise HostDenied('REPARSE_HARDLINK_OR_FILE_TYPE_REJECTED')
    final = C.create_unicode_buffer(32768)
    size = api.k.GetFinalPathNameByHandleW(h, final, len(final), 0)
    if not 0 < size < len(final) or final.value.casefold() != ('\\\\?\\' + str(path)).casefold():
        raise HostDenied('FINAL_PATH_ESCAPE_REJECTED')
    if not directory: _no_streams(api, path)
    return h


def _locked_bytes(api, handle, limit=32 * 1024 * 1024):
    chunks, total = [], 0
    buffer, count = C.create_string_buffer(65536), W.DWORD()
    while True:
        api.check(api.k.ReadFile(handle, buffer, len(buffer), C.byref(count), None), 'PINNED_FILE_READ')
        if not count.value: break
        total += count.value
        if total > limit: raise HostDenied('PINNED_FILE_SIZE')
        chunks.append(buffer.raw[:count.value])
    if not total: raise HostDenied('PINNED_FILE_EMPTY')
    return b''.join(chunks)


class _SandboxWorkspace:
    """New objects only: DACL at creation, never an ACL edit on an existing path.

    Files are a five-file quarantine, not an executable SDK installation.
    Cleanup walks only recorded paths, rejects substitutions and never rmtree's.
    """
    def __init__(self, api, user_sid, app_sid, name):
        self.api, self.user_sid, self.app_sid = api, user_sid, app_sid
        self.root = ROOT / '.tmp' / name
        self.created = []
        self.locks = _OwnedHandles(api)

    def create(self, relative, rights='', data=None):
        path = self.root / relative if relative else self.root
        if path != self.root and self.root not in path.parents: raise HostDenied('WORKSPACE_ESCAPE')
        sd = C.c_void_p()
        # Owner/SYSTEM only unless this exact new object needs child access.
        # Low mandatory label permits logs writes by the lowbox token.
        sddl = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;' + self.user_sid + ')'
        if rights: sddl += '(A;OICI;' + rights + ';;;' + self.app_sid + ')'
        sddl += 'S:(ML;;NW;;;LW)'
        self.api.check(self.api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, C.byref(sd), None), 'NEW_OBJECT_SECURITY_DESCRIPTOR')
        sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), sd, False)
        try:
            if data is None:
                self.api.check(self.api.k.CreateDirectoryW(str(path), C.byref(sa)), 'OWNED_DIRECTORY_CREATE')
                self.created.append((path, True))
            else:
                h = self.api.k.CreateFileW(str(path), 0x40000000, 0, C.byref(sa), 1, 0x00200000, None)
                if not h or h == C.c_void_p(-1).value: raise HostDenied('OWNED_NEW_FILE_CREATE', C.get_last_error())
                self.created.append((path, False))
                owned = _OwnedHandles(self.api)
                owned.add(h)
                try:
                    written = W.DWORD()
                    self.api.check(self.api.k.WriteFile(h, data, len(data), C.byref(written), None), 'OWNED_FILE_WRITE')
                    if written.value != len(data): raise HostDenied('OWNED_FILE_SHORT_WRITE')
                finally: owned.close_all()
        finally: self.api.k.LocalFree(sd)
        _lock_path(self.api, self.locks, path, data is None)
        return path

    def cleanup(self):
        self.locks.close_all()
        # Known canary output only; unknown additions make rmdir fail visibly.
        for relative in ('scratch/logs/control.txt', 'scratch/sdk/native-log.txt'):
            path = self.root / relative
            if path.exists() and all(p != path for p, _ in self.created):
                self.created.append((path, False))
        for path, directory in reversed(self.created):
            if path != self.root and self.root not in path.parents: raise HostDenied('CLEANUP_ESCAPE')
            for part in (path, *path.parents):
                info = part.lstat()
                if getattr(info, 'st_file_attributes', 0) & 0x400 or part.is_symlink():
                    raise HostDenied('CLEANUP_REPARSE_REJECTED')
            info = path.lstat()
            if not directory and info.st_nlink != 1: raise HostDenied('CLEANUP_HARDLINK_REJECTED')
            if directory: path.rmdir()
            else: path.unlink()
        if self.root.exists(): raise HostDenied('WORKSPACE_CLEANUP_UNVERIFIED')


def _stage_reviewed_sdk(api, owned, workspace):
    from execution_kgi_simulator.native.readiness import REVIEWED_SHA256, SDK_PREFIX
    from execution_kgi_simulator.native.host_policy import pe_imports
    rows = []
    workspace.create('scratch', 'FRFX')
    workspace.create('scratch/sdk', 'FRFX')
    workspace.create('scratch/sdk/pushClient', 'FRFX')
    workspace.create('scratch/ca')
    workspace.create('scratch/logs', 'FA')
    for relative, expected in REVIEWED_SHA256:
        source = ROOT / SDK_PREFIX / relative
        data = _locked_bytes(api, _lock_path(api, owned, source))
        if sha256(data).hexdigest() != expected: raise HostDenied('SDK_SOURCE_SHA256_DRIFT')
        imports = pe_imports(data) if source.suffix in ('.dll', '.pyd') else ()
        dest = workspace.create('scratch/sdk/' + relative, 'FR', data)
        copied = _locked_bytes(api, _lock_path(api, owned, dest))
        if sha256(copied).hexdigest() != expected: raise HostDenied('SDK_COPY_SHA256_DRIFT')
        rows.append({'path': relative, 'source_sha256': expected, 'copy_sha256': sha256(copied).hexdigest(),
                     'pe_imports': list(imports),
                     'dependency_audit': [{'name': name, 'resolution': 'REJECTED_NOT_IN_FIVE_FILE_PIN_SET',
                                           'search_attempted': False} for name in imports]})
    return {'status': 'SOURCE_COPY_PASS', 'files': rows, 'ca': 'EMPTY_NO_ACCESS',
            'logs': 'EMPTY_OWNED_DIRECTORY', 'sdk_execution': 'REJECTED',
            'dependency_closure': 'REJECTED_MISSING_PINNED_TRANSITIVE_DEPENDENCIES',
            'missing_vendor_dependency': 'PushClient_Win.dll',
            'loader_search': 'FORBIDDEN_NO_SDK_LOAD_OR_ORIGINAL_PATH_FALLBACK',
            'os_isolation': 'UNVERIFIED'}


def _canary_run(api, owned, workspace, restricted, sid, report):
    """Only caller is sandbox_probe; no arbitrary image/command/receipt ingress."""
    from execution_kgi_simulator.native.host_policy import CANARY_IMAGE_SHA256, CANARY_IMPORTS, pe_imports
    image = workspace.root / 'canary.exe'
    data = _locked_bytes(api, _lock_path(api, owned, image))
    if sha256(data).hexdigest() != CANARY_IMAGE_SHA256 or frozenset(pe_imports(data)) != CANARY_IMPORTS:
        raise HostDenied('CANARY_IMAGE_OR_DEPENDENCY_DRIFT')
    job = owned.add(api.check(api.k.CreateJobObjectW(None, None), 'SANDBOX_JOB_CREATE'))
    limits = EXTENDED_LIMIT()
    limits.basic.flags, limits.basic.active = JOB_FLAGS, 1
    api.check(api.k.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)), 'SANDBOX_JOB_LIMITS')
    observed = EXTENDED_LIMIT()
    api.check(api.k.QueryInformationJobObject(job, 9, C.byref(observed), C.sizeof(observed), None), 'SANDBOX_JOB_QUERY')
    if observed.basic.flags != JOB_FLAGS or observed.basic.active != 1: raise HostDenied('SANDBOX_JOB_MISMATCH')
    sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), None, True)
    read, write = W.HANDLE(), W.HANDLE()
    api.check(api.k.CreatePipe(C.byref(read), C.byref(write), C.byref(sa), 16384), 'CANARY_PIPE_CREATE')
    read_h, write_h = owned.add(read), owned.add(write)
    api.check(api.k.SetHandleInformation(read_h, 1, 0), 'CANARY_PARENT_PIPE_PRIVATE')
    size = C.c_size_t()
    api.k.InitializeProcThreadAttributeList(None, 4, 0, C.byref(size))
    if not 0 < size.value <= 65536: raise HostDenied('SANDBOX_ATTRIBUTE_SIZE')
    attributes = C.create_string_buffer(size.value)
    api.check(api.k.InitializeProcThreadAttributeList(attributes, 4, 0, C.byref(size)), 'SANDBOX_ATTRIBUTE_INIT')
    child = None
    try:
        inherited, jobs = (W.HANDLE * 1)(write_h), (W.HANDLE * 1)(job)
        capabilities = SECURITY_CAPABILITIES(sid, None, 0, 0)
        no_children = W.DWORD(1)
        for key, value, stage in ((0x20002, inherited, 'CANARY_HANDLES_BIND'),
                (0x2000D, jobs, 'CANARY_ATOMIC_JOB_BIND'),
                (0x20009, capabilities, 'APPCONTAINER_NO_CAPABILITIES_BIND'),
                (0x2000E, no_children, 'CANARY_DESCENDANTS_DENY')):
            api.check(api.k.UpdateProcThreadAttribute(attributes, 0, key, C.byref(value), C.sizeof(value), None, None), stage)
        for h in owned.items:
            flags = W.DWORD()
            api.check(api.k.GetHandleInformation(h, C.byref(flags)), 'CANARY_HANDLE_FLAGS')
            if bool(flags.value & 1) != (h == write_h): raise HostDenied('CANARY_HANDLE_LEAK')
        startup = STARTUPINFOEX()
        startup.startup.cb, startup.startup.flags = C.sizeof(startup), 0x100
        startup.startup.stdout = startup.startup.stderr = write_h
        startup.attributes = C.cast(attributes, C.c_void_p)
        info = PROCESS_INFORMATION()
        # Both paths are minted locally with UUID hex; never user command text.
        command = C.create_unicode_buffer('"' + str(image) + '" "' + str(workspace.root) + '"')
        environment = C.create_unicode_buffer('\0\0')
        api.check(api.a.CreateProcessAsUserW(restricted, str(image), command, None, None,
            True, 0x08080404, environment, str(workspace.root / 'scratch'), C.byref(startup), C.byref(info)),
            'APPROVED_APPCONTAINER_SUSPENDED_CREATE')
        child, thread = owned.add(info.process), owned.add(info.thread)
        report['child_created'] = True
        owned.close(write_h)
        identity = _verify_identity(api, child, info.pid, image)
        in_job, token = W.BOOL(), W.HANDLE()
        api.check(api.k.IsProcessInJob(child, job, C.byref(in_job)), 'CANARY_JOB_MEMBERSHIP')
        if not in_job.value: raise HostDenied('CANARY_NOT_IN_JOB')
        api.check(api.a.OpenProcessToken(child, 8, C.byref(token)), 'CANARY_TOKEN_OPEN')
        owned.add(token)
        _verify_appcontainer(api, token, sid)
        if _verify_identity(api, child, info.pid, image) != identity: raise HostDenied('CANARY_IDENTITY_CHANGED')
        report.update(pid=info.pid, creation_time=identity,
                      token='OS_QUERIED_APPCONTAINER_EXACT_SID_ZERO_CAPABILITIES',
                      job='OS_QUERIED_ATOMIC_JOB_KILL_ON_CLOSE_LIMIT_ONE',
                      canary_sha256=CANARY_IMAGE_SHA256)
        # Sole resume site: a fixed native canary, never the G1-A/SDK worker.
        if api.k.ResumeThread(thread) != 1: raise HostDenied('CANARY_RESUME_FAILED', C.get_last_error())
        report['child_resumed'] = True
        # <4KB output by construction; hard 16KB pipe/reader cap, 10s wall bound.
        if api.k.WaitForSingleObject(child, 10000) != 0: raise HostDenied('CANARY_TIMEOUT_OR_WAIT_FAILED')
        exit_code, available = W.DWORD(), W.DWORD()
        api.check(api.k.GetExitCodeProcess(child, C.byref(exit_code)), 'CANARY_EXIT_QUERY')
        report['child_actual_exit'] = exit_code.value
        api.check(api.k.PeekNamedPipe(read_h, None, 0, None, C.byref(available), None), 'CANARY_OUTPUT_SIZE')
        if not 0 < available.value <= 16384: raise HostDenied('CANARY_OUTPUT_MISSING_OR_OVERSIZE')
        data, got = C.create_string_buffer(available.value), W.DWORD()
        api.check(api.k.ReadFile(read_h, data, len(data), C.byref(got), None), 'CANARY_OUTPUT_READ')
        if got.value != len(data): raise HostDenied('CANARY_OUTPUT_INCOMPLETE')
        import json
        from execution_kgi_simulator.native.host_policy import classify_canary
        try: payload = json.loads(data.raw.decode('ascii'))
        except (ValueError, UnicodeError): raise HostDenied('CANARY_OUTPUT_MALFORMED') from None
        report.update(classify_canary(payload, info.pid, exit_code.value))
    finally:
        # Close Job first, including on cancellation and failed token validation.
        try:
            _stop_canary(api, owned, job, child, report)
        finally: api.k.DeleteProcThreadAttributeList(attributes)


def _stop_canary(api, owned, job, child, report):
    close_error = None
    try:
        owned.close(job)
    except HostDenied as error:
        close_error = error
    # Failed Job close never bypasses the owned process termination fallback.
    if child and api.k.WaitForSingleObject(child, 5000) != 0:
        api.check(api.k.TerminateProcess(child, 2), 'CANARY_TERMINATE')
        if api.k.WaitForSingleObject(child, 5000) != 0:
            raise HostDenied('CANARY_TEARDOWN_UNVERIFIED')
    report['teardown'] = 'NO_LIVE_OWNED_CHILD'
    if close_error: raise close_error


def sandbox_probe(*, stage_only=False) -> dict:
    """Explicit no-secret probe; default parent CLI is capability-only.

    Requires a source-enrolled, preexisting approved profile before launching.
    Stage-only may derive an unused SID for new-object DACLs; no child/profile.
    """
    import uuid
    from execution_kgi_simulator.native.host_policy import (
        CANARY_SOURCE_SHA256, CANARY_IMAGE_SHA256, CANARY_IMPORTS, pe_imports, PolicyRejected)
    if type(stage_only) is not bool: raise HostDenied('STAGE_MODE_TYPE')
    report = {'schema': 'omi.kgi-sandbox-probe.v1', 'status': 'BLOCKED',
              'network': 'UNVERIFIED', 'filesystem': 'UNVERIFIED', 'child_resumed': False,
              'activation_authority': False, 'gates': dict(G1='BLOCKED', G2='BLOCKED', G3='BLOCKED'),
              'profile_registration': 'NOT_ATTEMPTED', 'existing_acl_changes': 0,
              'credential_values_read': False, 'sdk_imported': False, 'broker_calls': 0, 'orders_sent': 0}
    api = owned = workspace = None
    sid = C.c_void_p()
    try:
        api = SandboxAPI()
        owned = _OwnedHandles(api)
        if not stage_only:
            sid = _approved_profile_sid(api)
            mutex = api.k.CreateMutexW(None, False, 'Local\\OMI.KGI.Canary.' + sha256(_sid_text(api, sid).encode()).hexdigest())
            error = C.get_last_error()
            owned.add(api.check(mutex, 'PROFILE_EXCLUSIVE_OWNER_MUTEX'))
            if error == 183: raise HostDenied('PROFILE_ALREADY_OWNED')
        parent, restricted = W.HANDLE(), W.HANDLE()
        api.check(api.a.OpenProcessToken(api.k.GetCurrentProcess(), 0xB, C.byref(parent)), 'SANDBOX_PARENT_TOKEN')
        owned.add(parent)
        # Stage-only needs no restricted token and creates no child.
        user = _token_buffer(api, parent, 1)
        user_sid = _sid_text(api, C.c_void_p.from_buffer(user))
        name = 'omi-kgi-canary-' + uuid.uuid4().hex
        if stage_only:
            hr = api.u.DeriveAppContainerSidFromAppContainerName(name, C.byref(sid))
            if hr != 0: raise HostDenied('STAGING_ONLY_SID_DERIVE', hr & 0xffffffff)
        app_sid = _sid_text(api, sid)
        report['sid_mode'] = 'STAGING_ONLY_NO_CHILD' if stage_only else 'APPROVED_PREEXISTING_NO_NETWORK_CAPABILITIES'
        report['instance'] = name
        _lock_path(api, owned, ROOT / '.tmp', True)
        workspace = _SandboxWorkspace(api, user_sid, app_sid, name)
        workspace.create('', 'FRFX')
        report['staging'] = _stage_reviewed_sdk(api, owned, workspace)
        if stage_only: return report
        source = _locked_bytes(api, _lock_path(api, owned, ROOT / 'execution_kgi_simulator/native/sandbox_probe.c'))
        image = _locked_bytes(api, _lock_path(api, owned, ROOT / '.tmp/kgi-g1bc-build/sandbox_probe.exe'))
        if sha256(source).hexdigest() != CANARY_SOURCE_SHA256: raise HostDenied('CANARY_SOURCE_SHA256_DRIFT')
        if sha256(image).hexdigest() != CANARY_IMAGE_SHA256 or frozenset(pe_imports(image)) != CANARY_IMPORTS:
            raise HostDenied('CANARY_BUILD_SHA256_OR_IMPORTS_DRIFT')
        workspace.create('canary.exe', 'FRFX', image)
        workspace.create('outside')
        workspace.create('outside/sentinel.txt', '', b'INVENTED_OUTSIDE_SENTINEL')
        workspace.create('scratch/sdk/cwd-sentinel.txt', 'FR', b'INVENTED_SDK_SENTINEL')
        api.check(api.a.CreateRestrictedToken(parent, 1, 0, None, 0, None, 0, None, C.byref(restricted)), 'SANDBOX_RESTRICTED_TOKEN_CREATE')
        owned.add(restricted)
        _verify_token(api, restricted)
        _canary_run(api, owned, workspace, restricted, sid, report)
    except (HostDenied, PolicyRejected, OSError) as error:
        report.update(network='UNVERIFIED', filesystem='UNVERIFIED',
                      reasonCodes=[getattr(error, 'stage', str(error) if isinstance(error, PolicyRejected) else 'SANDBOX_OS_ACCESS')],
                      winerror=getattr(error, 'winerror', 0) or 0)
    finally:
        try:
            if owned: owned.close_all()
            if workspace:
                if report.get('child_created') and report.get('teardown') != 'NO_LIVE_OWNED_CHILD':
                    workspace.locks.close_all()
                    raise HostDenied('LIVE_CHILD_CLEANUP_NOT_AUTHORIZED')
                workspace.cleanup()
                report['workspace_cleanup'] = 'VERIFIED_REMOVED'
            if owned: report['owned_handles_remaining'] = len(owned.items) + (len(workspace.locks.items) if workspace else 0)
        except (HostDenied, OSError) as error:
            report.update(network='UNVERIFIED', filesystem='UNVERIFIED',
                          cleanup_stage=getattr(error, 'stage', 'WORKSPACE_CLEANUP_OS_FAILURE'),
                          cleanup_winerror=getattr(error, 'winerror', 0) or 0,
                          workspace_cleanup='UNVERIFIED_RETAINED_FOR_SCOPED_REVIEW')
        finally:
            if api and sid: api.a.FreeSid(sid)
    return report
