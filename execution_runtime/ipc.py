"""Windows local, same-user named pipe identity; bytes/JSON only, never pickle."""

import ctypes
from ctypes import wintypes as W
import hashlib
from pathlib import Path
import os

from execution.validation import require


ROOT = Path(__file__).resolve().parents[1]
ADDRESS = r"\\.\pipe\omi-execution-" + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]


def authenticate(connection, *, server):
    """Check OS process token on both ends before accepting any command bytes."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    peer = W.ULONG()
    get_pid = getattr(kernel, "GetNamedPipeClientProcessId" if server else "GetNamedPipeServerProcessId")
    get_pid.argtypes = [W.HANDLE, ctypes.POINTER(W.ULONG)]
    get_pid.restype = W.BOOL
    require(bool(get_pid(connection.fileno(), ctypes.byref(peer))), "PIPE_PEER_UNVERIFIED")
    if server:
        # Reject remote pipe clients before treating their PID as a local PID.
        computer = ctypes.create_unicode_buffer(256)
        kernel.GetNamedPipeClientComputerNameW.argtypes = [W.HANDLE, W.LPWSTR, W.ULONG]
        local_result = kernel.GetNamedPipeClientComputerNameW(connection.fileno(), computer, ctypes.sizeof(computer))
        # Win32 reports ERROR_PIPE_LOCAL (229) for a local pipe. A successful
        # computer-name lookup is remote; other failures remain unverified.
        require(not local_result and ctypes.get_last_error() == 229, "PIPE_NOT_LOCAL")
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD)]
    advapi.EqualSid.argtypes = [W.LPVOID, W.LPVOID]
    advapi.EqualSid.restype = W.BOOL
    buffers = []
    for pid in (os.getpid(), peer.value):
        process = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        require(bool(process), "PIPE_PROCESS_UNVERIFIED")
        token = W.HANDLE()
        try:
            require(bool(advapi.OpenProcessToken(process, 0x0008, ctypes.byref(token))), "PIPE_TOKEN_UNVERIFIED")
            needed = W.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))  # TokenUser
            require(0 < needed.value <= 65536, "PIPE_TOKEN_UNVERIFIED")
            buffer = ctypes.create_string_buffer(needed.value)
            require(bool(advapi.GetTokenInformation(token, 1, buffer, needed.value, ctypes.byref(needed))),
                    "PIPE_TOKEN_UNVERIFIED")
            buffers.append(buffer)
        finally:
            if token:
                kernel.CloseHandle(token)
            kernel.CloseHandle(process)
    # TOKEN_USER starts with SID_AND_ATTRIBUTES; its first member is a PSID.
    require(bool(advapi.EqualSid(ctypes.cast(buffers[0], ctypes.POINTER(W.LPVOID))[0],
                                ctypes.cast(buffers[1], ctypes.POINTER(W.LPVOID))[0])), "PIPE_USER_MISMATCH")
    return peer.value
