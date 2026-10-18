"""Canonical Engine leases and known physical SQLite connection admission.

Reservations include DBAPI construction and checked-out connections, including
direct Session/Engine/raw_connection callers. Detached/invalidated handles remain
unknown until that physical driver's close completes. Pool-record reuse cannot
erase a predecessor or its replacement. Cross-process SQLite authority belongs
to the separate native writer lease retained by RuntimeCoordinator.
"""
from dataclasses import dataclass
from threading import Lock
import asyncio
import math
import time
import sqlite3

from sqlalchemy import event


class EngineAdmissionClosed(RuntimeError):
    pass


class SqliteAdmission:
    """Process-local construction fence, retained until the driver's close returns.

    A returned pool lease is deliberately insufficient. SQLite can also retain
    native statements after close; the lifecycle owner must obtain native SQLite exclusion
    before issuing a global drain certificate.
    """
    def __init__(self):
        self._lock = Lock()
        self._closed = False
        self._connections = {}
        self._pause = None

    def connect(self, *args, **kwargs):
        return self.connect_using(sqlite3.connect, *args, **kwargs)

    def connect_using(self, constructor, *args, **kwargs):
        if "factory" in kwargs:
            raise EngineAdmissionClosed("Untracked SQLite factory refused")
        token = object()
        with self._lock:
            if self._closed or self._pause is not None:
                raise EngineAdmissionClosed("SQLite admission is closed")
            self._connections[token] = "constructing"
        try:
            connection = constructor(*args, factory=AdmittedSqliteConnection, **kwargs)
        except BaseException:
            with self._lock:
                del self._connections[token]
            raise
        connection._admission_owner = self
        connection._admission_token = token
        with self._lock:
            self._connections[token] = "open"
        return connection

    def begin_drain(self):
        with self._lock:
            self._closed = True

    def pause_if_idle(self):
        with self._lock:
            if self._closed or self._pause is not None:
                raise EngineAdmissionClosed("SQLite quiescence unavailable")
            if self._connections:
                return None
            self._pause = object()
            return self._pause

    def resume(self, lease):
        with self._lock:
            if lease is not self._pause or self._closed:
                raise EngineAdmissionClosed("Invalid SQLite quiescence lease")
            self._pause = None

    def observation(self):
        with self._lock:
            return {"admission_closed": self._closed,
                    "active_connections": len(self._connections),
                    "pending_constructors": sum(v == "constructing" for v in self._connections.values()),
                    "close_failures": sum(v == "close_failed" for v in self._connections.values())}


class AdmittedSqliteConnection(sqlite3.Connection):
    def close(self):
        owner = getattr(self, "_admission_owner", None)
        token = getattr(self, "_admission_token", None)
        try:
            super().close()
        except BaseException:
            if owner is not None:
                with owner._lock:
                    owner._connections[token] = "close_failed"
            raise
        else:
            if owner is not None:
                with owner._lock:
                    owner._connections.pop(token, None)
            callback = getattr(self, "_driver_closed", None)
            if callback is not None:
                callback()


sqlite_admission = SqliteAdmission()


def attach_sqlite_admission(engine):
    """Fence known independent migration Engines without changing transactions."""
    if engine.dialect.name == "sqlite" and engine.dialect.driver == "pysqlite":
        @event.listens_for(engine, "do_connect", retval=True)
        def connect(dialect, record, args, kwargs):
            return sqlite_admission.connect(*args, **kwargs)


@dataclass(frozen=True)
class EngineDrainResult:
    state: str
    admission_closed: bool
    active_connections: int
    pending_constructors: int
    unknown_connections: int
    evidence_scope: str = "canonical_engine_construction_and_checkout_leases_only"
    all_writers_drained: bool = False

    @property
    def drained(self):
        return self.state == "drained" and self.admission_closed


class EngineAdmission:
    def __init__(self, engine):
        self._lock = Lock()
        self._closed = False
        self._records = {}
        self._physical_tokens = {}
        self._last_exit = None
        # Engine-specific listeners survive pool replacement. Never instrument
        # every SQLAlchemy engine or change transaction ownership.
        event.listen(engine, "do_connect", self._connect, retval=True)
        event.listen(engine, "checkout", self._checkout)
        event.listen(engine, "checkin", self._checkin)
        event.listen(engine, "detach", self._uncertain)
        event.listen(engine, "invalidate", self._uncertain)

    def _connect(self, dialect, record, args, kwargs):
        with self._lock:
            if self._closed:
                raise EngineAdmissionClosed("Canonical Engine admission is closed")
            if record in self._records:
                # Normal pool reconnect remains available while admission is
                # open. Preserve the old unknown handle under a distinct token.
                if self._records[record] != "unknown":
                    raise EngineAdmissionClosed("Canonical Engine ownership is unknown")
                old_token = self._physical_tokens.pop(record, object())
                self._records[old_token] = self._records.pop(record)
            physical_token = object()
            self._physical_tokens[record] = physical_token
            self._records[record] = "constructing"
        try:
            connection = (sqlite_admission.connect_using(dialect.connect, *args, **kwargs)
                          if dialect.name == "sqlite" and dialect.driver == "pysqlite"
                          else dialect.connect(*args, **kwargs))
        except BaseException:
            with self._lock:
                del self._records[record]
                self._physical_tokens.pop(record, None)
                self._last_exit = time.monotonic()
            raise
        with self._lock:
            self._records[record] = "connected"
        if isinstance(connection, AdmittedSqliteConnection):
            # Actual driver completion resolves invalidate/detach uncertainty.
            # The callback is bound to this physical handle, never a pool event.
            def closed():
                with self._lock:
                    # A pool record can already refer to a replacement driver.
                    # Close releases only the token for this physical handle.
                    if self._physical_tokens.get(record) is physical_token:
                        self._records.pop(record, None)
                        self._physical_tokens.pop(record, None)
                    else:
                        self._records.pop(physical_token, None)
                    self._last_exit = time.monotonic()
            connection._driver_closed = closed
        return connection

    def _checkout(self, connection, record, proxy):
        with self._lock:
            # A construction admitted before closure can finish; its reservation
            # never disappeared. An idle pooled connection needs new admission.
            if record not in self._records:
                if self._closed:
                    raise EngineAdmissionClosed("Canonical Engine admission is closed")
                self._records[record] = "connected"
            elif self._records[record] != "connected":
                raise EngineAdmissionClosed("Canonical Engine ownership is unknown")

    def _checkin(self, connection, record):
        # Pool checkin proves lease return after reset, not completion of a
        # subsequent driver close. Escaped DBAPI references remain outside this
        # bounded certificate and therefore outside global restart authority.
        with self._lock:
            if record in self._records and self._records[record] != "unknown":
                if connection is None:
                    self._records[record] = "unknown"
                else:
                    del self._records[record]
                    self._last_exit = time.monotonic()

    def _uncertain(self, connection, record, *error):
        with self._lock:
            self._records[record] = "unknown"

    def begin_drain(self):
        with self._lock:
            self._closed = True

    def status(self, *, deadline):
        if not math.isfinite(deadline):
            raise ValueError("Drain deadline must be finite")
        with self._lock:
            pending = sum(value == "constructing" for value in self._records.values())
            unknown = sum(value == "unknown" for value in self._records.values())
            state = "accepting"
            if unknown:
                state = "unknown"
            elif self._closed:
                if self._records:
                    state = "timeout" if time.monotonic() >= deadline else "draining"
                else:
                    state = "timeout" if self._last_exit is not None and self._last_exit > deadline else "drained"
            return EngineDrainResult(state, self._closed, len(self._records), pending, unknown)

    async def drain(self, *, deadline):
        if not math.isfinite(deadline):
            raise ValueError("Drain deadline must be finite")
        self.begin_drain()
        while True:
            result = self.status(deadline=deadline)
            if result.state != "draining":
                return result
            await asyncio.sleep(min(.01, max(0, deadline - time.monotonic())))
