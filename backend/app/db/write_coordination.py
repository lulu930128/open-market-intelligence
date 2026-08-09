from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import RLock
import time
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


SQLITE_WRITE_RETRY_DELAYS_SECONDS = (0.15, 0.35, 0.75)

_SQLITE_WRITE_LOCK = RLock()
_T = TypeVar("_T")


class SqliteWriteBusyError(RuntimeError):
    """Raised when a bounded SQLite write retry budget is exhausted."""


def is_sqlite_locked_error(error: BaseException) -> bool:
    normalized = str(error).lower()
    return (
        "database is locked" in normalized
        or "database table is locked" in normalized
    )


def _uses_sqlite(db: Session) -> bool:
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        # Lightweight test/session adapters do not always expose a bind. They
        # still benefit from the in-process coordinator.
        return True
    bind = get_bind()
    dialect = getattr(bind, "dialect", None)
    return getattr(dialect, "name", None) == "sqlite"


def run_with_sqlite_write_retry(
    db: Session,
    action: Callable[[], _T],
    *,
    retry_delays_seconds: Sequence[float] = SQLITE_WRITE_RETRY_DELAYS_SECONDS,
    reset_session_before_attempt: bool = False,
) -> _T:
    """Coordinate and retry one complete SQLite-owned write operation.

    ``action`` remains the transaction owner and must commit on success. When
    retrying a read-then-write operation, ``reset_session_before_attempt``
    clears the stale read snapshot before the action rebuilds its inputs.
    """

    if not _uses_sqlite(db):
        return action()

    delays = tuple(max(float(value), 0.0) for value in retry_delays_seconds)
    for attempt in range(len(delays) + 1):
        try:
            with _SQLITE_WRITE_LOCK:
                if reset_session_before_attempt:
                    db.rollback()
                return action()
        except OperationalError as exc:
            db.rollback()
            if not is_sqlite_locked_error(exc):
                raise
            if attempt >= len(delays):
                raise SqliteWriteBusyError(
                    "SQLite write remained busy after bounded retries."
                ) from exc
            time.sleep(delays[attempt])

    raise AssertionError("unreachable SQLite retry state")
