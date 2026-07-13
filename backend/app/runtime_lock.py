from __future__ import annotations

import os
from pathlib import Path
import time
from typing import BinaryIO


class ProcessFileLock:
    """Small cross-process lock backed by an OS-released file handle."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(
        self,
        *,
        timeout_seconds: float = 0,
        poll_interval_seconds: float = 0.05,
    ) -> bool:
        if self._handle is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        timeout_seconds = max(float(timeout_seconds), 0.0)
        poll_interval_seconds = max(float(poll_interval_seconds), 0.001)
        deadline = time.monotonic() + timeout_seconds

        while True:
            try:
                self._lock_handle(handle)
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    return False
                time.sleep(min(poll_interval_seconds, max(deadline - time.monotonic(), 0)))
                continue

            self._handle = handle
            return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return

        self._handle = None
        try:
            self._unlock_handle(handle)
        finally:
            handle.close()

    @staticmethod
    def _lock_handle(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_handle(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self) -> ProcessFileLock:
        if not self.acquire():
            raise RuntimeError(f"Could not acquire process lock: {self.path}")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()


__all__ = ["ProcessFileLock"]
