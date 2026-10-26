"""Native SQLite writer reservation retained across graceful process shutdown.

BEGIN IMMEDIATE arbitrates with independent SQLite engines/processes, including
WAL writers. It does not assert that arbitrary programs cannot corrupt a file.
The default lease is lock-only. Maintenance may borrow an already initialized
SQLAlchemy connection, reserve it here and use it for Alembic without a second
writer connection. Only the maintenance owner commits; release rolls back leftovers.
"""
import ctypes
import os
from pathlib import Path
import sqlite3


class SQLiteWriterLease:
    def __init__(self, connection, path_handle, borrowed=None):
        self._connection = connection
        self._path_handle = path_handle
        self._borrowed = borrowed

    @classmethod
    def acquire(cls, url, *, connection=None):
        borrowed = connection
        if (url.drivername not in {"sqlite", "sqlite+pysqlite"} or url.query
                or url.username or url.password or url.host or not url.database):
            raise RuntimeError("SQLITE_TARGET_UNSUPPORTED")
        path = Path(url.database)
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError("SQLITE_TARGET_UNSUPPORTED")
        for part in (path, *path.parents):
            stat = part.stat(follow_symlinks=False)
            if part.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("SQLITE_TARGET_ALIAS")
        if path.stat().st_nlink != 1:
            raise RuntimeError("SQLITE_TARGET_ALIAS")
        handle = None
        connection = None
        try:
            if os.name == "nt":
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
                if kernel.GetDriveTypeW(path.anchor) != 3:
                    raise RuntimeError("SQLITE_TARGET_NOT_LOCAL_FIXED_DISK")
                kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                kernel.CreateFileW.restype = wintypes.HANDLE
                handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
                if handle == wintypes.HANDLE(-1).value:
                    handle = None
                    raise ctypes.WinError(ctypes.get_last_error())
            # Untracked intentionally: this is the lifecycle owner's lock-only
            # connection, opened AFTER the application connection fence is held.
            if borrowed is None:
                connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                                             timeout=0, isolation_level=None)
                connection.execute("BEGIN IMMEDIATE").close()
            else:
                connection = borrowed.connection.driver_connection
                actual = connection.execute("PRAGMA database_list").fetchall()
                if (borrowed.in_transaction() or connection.in_transaction or
                        len(actual) != 1 or Path(actual[0][2]) != path):
                    raise RuntimeError("MAINTENANCE_CONNECTION_TARGET_MISMATCH")
                borrowed.exec_driver_sql("BEGIN IMMEDIATE")
            return cls(connection, handle, borrowed)
        except BaseException:
            if connection is not None and borrowed is None:
                connection.close()
            if handle is not None:
                cls._close_handle(handle)
            raise

    @staticmethod
    def _close_handle(handle):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    @property
    def held(self):
        return self._connection is not None and self._connection.in_transaction

    def release(self):
        # On commit this method is deliberately NOT called: the process exit
        # closes the native transaction after lifespan and all writers complete.
        if self._connection is not None:
            if self._borrowed is not None:
                self._borrowed.rollback()
            else:
                self._connection.rollback()
                self._connection.close()
            self._connection = None
        if self._path_handle is not None:
            self._close_handle(self._path_handle)
            self._path_handle = None
