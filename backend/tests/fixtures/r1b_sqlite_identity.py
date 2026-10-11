"""Windows x64 disposable-only B1 evidence. Never imports the OMI application.

No PID, database path or engine supplied by callers. A fresh child owns one
fresh directory and one NullPool connection; PSS observes only this process.
The open/close differential is fixture evidence, not general process attestation.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


class EvidenceUnavailable(RuntimeError):
    pass


class HandleEntry(ctypes.Structure):
    # PSS_HANDLE_ENTRY, Windows x64 ABI. Largest type-specific union is Thread.
    _fields_ = [
        ('handle', w.HANDLE), ('flags', w.DWORD), ('object_type', w.DWORD),
        ('capture_time', w.FILETIME), ('attributes', w.DWORD),
        ('granted_access', w.DWORD), ('handle_count', w.DWORD),
        ('pointer_count', w.DWORD), ('paged_pool', w.DWORD),
        ('nonpaged_pool', w.DWORD), ('creation_time', w.FILETIME),
        ('type_name_length', w.WORD), ('type_name', ctypes.c_void_p),
        ('object_name_length', w.WORD), ('object_name', ctypes.c_void_p),
        ('type_specific', ctypes.c_uint64 * 6),
    ]


class FileInfo(ctypes.Structure):
    _fields_ = [
        ('attributes', w.DWORD), ('creation', w.FILETIME),
        ('access', w.FILETIME), ('write', w.FILETIME), ('volume', w.DWORD),
        ('size_high', w.DWORD), ('size_low', w.DWORD), ('links', w.DWORD),
        ('index_high', w.DWORD), ('index_low', w.DWORD),
    ]


class FileIdInfo(ctypes.Structure):
    _fields_ = [('volume', ctypes.c_uint64), ('identifier', ctypes.c_ubyte * 16)]


def checked(code):
    if code:
        raise EvidenceUnavailable(f'Windows snapshot error {code}')


class OwnHandles:
    def __init__(self):
        if sys.platform != 'win32' or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise EvidenceUnavailable('Windows x64 required')
        if ctypes.sizeof(HandleEntry) != 136:
            raise EvidenceUnavailable('Unsupported PSS_HANDLE_ENTRY ABI')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'GetCurrentProcess': ([], w.HANDLE),
            'PssCaptureSnapshot': ([w.HANDLE, w.DWORD, w.DWORD, ctypes.POINTER(w.HANDLE)], w.DWORD),
            'PssWalkMarkerCreate': ([ctypes.c_void_p, ctypes.POINTER(w.HANDLE)], w.DWORD),
            'PssWalkSnapshot': ([w.HANDLE, w.DWORD, w.HANDLE, ctypes.c_void_p, w.DWORD], w.DWORD),
            'PssWalkMarkerFree': ([w.HANDLE], w.DWORD),
            'PssFreeSnapshot': ([w.HANDLE, w.HANDLE], w.DWORD),
            'GetFileType': ([w.HANDLE], w.DWORD),
            'GetFileInformationByHandle': ([w.HANDLE, ctypes.POINTER(FileInfo)], w.BOOL),
            'GetFileInformationByHandleEx': ([w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD], w.BOOL),
            'GetProcessTimes': ([w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = args, result
        self.process = self.k.GetCurrentProcess()

    def process_start(self):
        times = [w.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(self.process, *(ctypes.byref(t) for t in times)):
            raise EvidenceUnavailable('GetProcessTimes failed')
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def snapshot(self):
        snapshot, marker = w.HANDLE(), w.HANDLE()
        checked(self.k.PssCaptureSnapshot(self.process, 0x04, 0, ctypes.byref(snapshot)))
        try:
            checked(self.k.PssWalkMarkerCreate(None, ctypes.byref(marker)))
            try:
                handles = set()
                for _ in range(4096):
                    entry = HandleEntry()
                    code = self.k.PssWalkSnapshot(snapshot, 2, marker, ctypes.byref(entry), ctypes.sizeof(entry))
                    if code == 259:  # ERROR_NO_MORE_ITEMS; no other error means complete.
                        return handles
                    checked(code)
                    handles.add(entry.handle)
                raise EvidenceUnavailable('Handle enumeration bound exceeded')
            finally:
                checked(self.k.PssWalkMarkerFree(marker))
        finally:
            checked(self.k.PssFreeSnapshot(self.process, snapshot))

    def disk_identity(self, handle):
        if self.k.GetFileType(handle) != 1:  # FILE_TYPE_DISK
            return None
        info = FileInfo()
        if not self.k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise EvidenceUnavailable('Disk handle identity unavailable')
        if info.links != 1 or info.attributes & 0x400:
            raise EvidenceUnavailable('Alias/reparse handle rejected')
        identity = FileIdInfo()
        if not self.k.GetFileInformationByHandleEx(handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)):
            raise EvidenceUnavailable('128-bit file identity unavailable')
        return [identity.volume, int.from_bytes(identity.identifier, 'little')]


def guarded_identity(path, root):
    # Lexical containment before any filesystem query; never accepts other DBs.
    if not path.is_absolute() or not path.is_relative_to(root) or '..' in path.parts:
        raise EvidenceUnavailable('Outside disposable scope')
    for part in [root, *reversed(path.parents[:len(path.parts)-len(root.parts)-1]), path]:
        info = part.lstat()
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise EvidenceUnavailable('Reparse path rejected')
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise EvidenceUnavailable('Not a single-link fixture file')
    return [info.st_dev, info.st_ino]


def verdict(evidence):
    required = ('engine_connection_match', 'file_identity_stable', 'connection_file_match',
                'complete_handle_snapshots', 'one_new_matching_handle', 'handle_closed')
    reasons = [key for key in required if evidence.get(key) is not True]
    return dict(verdict='BLOCKED' if reasons else 'DISPOSABLE_BINDING_PASS',
                reasons=reasons, database_handle_binding='UNKNOWN',
                loaded_release_identity='UNKNOWN', production_gate='BLOCKED')


def run(case='success'):
    if case not in {'success', 'creator_redirect', 'memory', 'retained_connection'}:
        raise ValueError('Unknown fixture case')
    # Fixed task-private parent; no production target/port/PID input surface.
    parent = Path(__file__).absolute().parents[3] / '.tmp/us-g0-b1-20261011'
    for component in [*reversed(parent.parents), parent]:
        if component.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise EvidenceUnavailable('Private parent is reparse')
    root = Path(tempfile.mkdtemp(prefix='sqlite-fixture-', dir=parent))
    expected, alternate = root / 'expected.sqlite', root / 'alternate.sqlite'
    for path in (expected, alternate):
        # Exclusive creation, real SQLite header; fully closed before baseline.
        with path.open('xb'):
            pass
        connection = sqlite3.connect(str(path))
        try:
            connection.execute('CREATE TABLE fixture_only (value INTEGER)')
            connection.commit()
        finally:
            connection.close()
    initial = guarded_identity(expected, root)
    observer = OwnHandles()
    evidence = dict(case=case, pid=os.getpid(), process_start_filetime=observer.process_start(),
                    captured_at=datetime.now(timezone.utc).isoformat(), scope='disposable_child_only',
                    expected_identity=initial, engine_connection_match=False,
                    connection_file_match=False, complete_handle_snapshots=False,
                    one_new_matching_handle=False, handle_closed=False)
    target = ':memory:' if case == 'memory' else str(expected)
    kwargs = {'poolclass': NullPool}
    if case == 'creator_redirect':
        kwargs['creator'] = lambda: sqlite3.connect(str(alternate))
    engine = create_engine('sqlite:///' + target, **kwargs)
    connection = None
    try:
        before = observer.snapshot()
        connection = engine.connect()
        rows = connection.exec_driver_sql('PRAGMA database_list').all()
        main = [row[2] for row in rows if row[1] == 'main']
        effective = Path(main[0]) if len(main) == 1 and main[0] else None
        evidence['engine_connection_match'] = effective == expected and engine.url.database == str(expected)
        if effective is not None:
            evidence['connection_identity'] = guarded_identity(effective, root)
            evidence['connection_file_match'] = evidence['connection_identity'] == initial
        during = observer.snapshot()
        disk_handles = {h: identity for h in during - before
                        if (identity := observer.disk_identity(h)) is not None}
        matching = [h for h, identity in disk_handles.items() if identity == initial]
        evidence['new_disk_handle_identities'] = disk_handles
        evidence['matching_handles'] = matching
        evidence['one_new_matching_handle'] = len(matching) == 1
        if case != 'retained_connection':
            connection.close()
            connection = None
        after = observer.snapshot()
        evidence['handle_snapshot_counts'] = dict(before=len(before), during=len(during), after=len(after))
        evidence['handle_closed'] = bool(matching) and all(h not in after for h in matching)
        evidence['complete_handle_snapshots'] = True
        evidence['file_identity_stable'] = guarded_identity(expected, root) == initial
    except (EvidenceUnavailable, OSError) as exc:
        evidence['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()
    return dict(**verdict(evidence), evidence=evidence)


if __name__ == '__main__':
    try:
        result = run(sys.argv[1] if len(sys.argv) == 2 else 'success')
    except (EvidenceUnavailable, OSError) as exc:
        result = dict(verdict='BLOCKED', database_handle_binding='UNKNOWN',
                      loaded_release_identity='UNKNOWN', production_gate='BLOCKED', error=str(exc))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['verdict'] == 'DISPOSABLE_BINDING_PASS' else 2)
