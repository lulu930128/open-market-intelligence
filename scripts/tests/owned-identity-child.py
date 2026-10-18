"""Capture only this disposable child's ancestry; no CIM, sockets or OMI imports.

The parent test replays the bounded OS snapshot through the production identity
function. This is evidence playback, not attestation of an exited fixture.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys


class BasicInfo(ctypes.Structure):
    _fields_ = [("reserved1", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                ("reserved2", ctypes.c_void_p * 2), ("pid", ctypes.c_size_t),
                ("parent", ctypes.c_size_t)]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetCommandLineW.restype = wintypes.LPWSTR
ntdll = ctypes.WinDLL("ntdll")
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG,
                                          ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p]
ntdll.NtQueryInformationProcess.restype = wintypes.LONG


def observe(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)  # query limited; no privileges enabled
    if not handle:
        raise OSError("DISPOSABLE_PROCESS_QUERY_FAILED")
    try:
        info = BasicInfo()
        if ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None):
            raise OSError("DISPOSABLE_PARENT_QUERY_FAILED")
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise OSError("DISPOSABLE_IMAGE_QUERY_FAILED")
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            raise OSError("DISPOSABLE_TIME_QUERY_FAILED")
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        created = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
        return {"ProcessId": pid, "ParentProcessId": int(info.parent),
                "ExecutablePath": image.value, "CreationDate": created.isoformat(), "CreatedFileTime": str(ticks),
                "CommandLine": kernel.GetCommandLineW() if pid == os.getpid() else "disposable ancestor; argv not observed"}
    finally:
        kernel.CloseHandle(handle)


output, launcher = Path(sys.argv[1]), int(sys.argv[2])
records = []
cursor = os.getpid()
for _ in range(4):
    record = observe(cursor)
    records.append(record)
    if record["ParentProcessId"] == launcher:
        break
    cursor = record["ParentProcessId"]
else:
    raise RuntimeError("DISPOSABLE_ANCESTRY_BOUND_EXCEEDED")
output.write_text(json.dumps(records), encoding="utf-8")
