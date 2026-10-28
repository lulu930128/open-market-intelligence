from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from time import monotonic, thread_time
from typing import Any, Callable, Iterator

from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.ai.capability_resolution_registry import CapabilityReadNode
from app.db.read_diagnostics import PHASE_TRACE_KEY, connection_execute_trace


@contextmanager
def _bounded_read_session(db: Session, deadline: float, timings: dict[str, Any]) -> Iterator[Session]:
    """Same-thread, separately owned read transaction with a SQLite deadline.

    Busy waits and VM execution are bounded. Pure Python readers must also keep
    their canonical row/iteration bounds; no abandoned worker shares a Session.
    Connection-local settings are restored before returning it to the pool.
    """
    setup_started = monotonic()
    timings["deadline_interrupt_observed"] = False
    try:
        with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as reader:
            raw = None
            query_only = busy_timeout = None
            try:
                connection = reader.connection()
                if connection.dialect.name == "sqlite":
                    raw = connection.connection.driver_connection
                    query_only = raw.execute("PRAGMA query_only").fetchone()[0]
                    busy_timeout = raw.execute("PRAGMA busy_timeout").fetchone()[0]
                    raw.execute("PRAGMA query_only=ON")
                    raw.execute(f"PRAGMA busy_timeout={max(1, int((deadline - monotonic()) * 1000))}")
                    def progress():
                        expired = monotonic() >= deadline
                        if expired:
                            timings["deadline_interrupt_observed"] = True
                        return int(expired)
                    raw.set_progress_handler(progress, 1000)
                timings["connection_setup_ms"] = round((monotonic() - setup_started) * 1000, 3)
                reader.info[PHASE_TRACE_KEY] = timings.setdefault("phases", [])
                with connection_execute_trace(connection, deadline, timings):
                    yield reader
            finally:
                reader.info.pop(PHASE_TRACE_KEY, None)
                if raw is not None:
                    raw.set_progress_handler(None, 0)
                    if busy_timeout is not None:
                        raw.execute(f"PRAGMA busy_timeout={busy_timeout}")
                    if query_only is not None:
                        raw.execute(f"PRAGMA query_only={query_only}")
    finally:
        if timings["connection_setup_ms"] is None:
            timings["connection_setup_ms"] = round((monotonic() - setup_started) * 1000, 3)


class ReadExecution:
    """Request-local sequential execution state, never a cache/fill owner."""

    def __init__(self, db: Session, nodes: tuple[CapabilityReadNode, ...], *, total_seconds: float = 45.0):
        self.db = db
        self.nodes = {node.node_id: node for node in nodes}
        self.started = monotonic()
        self.deadline = self.started + total_seconds
        self.values: dict[str, Any] = {}
        self.runs: list[dict[str, Any]] = []

    def run(self, node_id: str, read: Callable[[Session], Any], default: Any = None) -> Any:
        if node_id not in self.nodes:
            return default
        if node_id in self.values:
            return self.values[node_id]
        spec = self.nodes[node_id]
        started = monotonic()
        cpu_started = thread_time()
        deadline = min(self.deadline, started + spec.timeout_seconds)
        record: dict[str, Any] = {"node": node_id, "status": "completed", "timeout_seconds": spec.timeout_seconds}
        record.update(connection_setup_ms=None, reader_ms=None)
        value = default
        try:
            if started >= deadline:
                raise TimeoutError("Request read budget exhausted")
            with _bounded_read_session(self.db, deadline, record) as reader:
                reader_started = monotonic()
                try:
                    value = read(reader)
                finally:
                    record["reader_ms"] = round((monotonic() - reader_started) * 1000, 3)
            if monotonic() >= deadline:
                raise TimeoutError("Read node deadline exceeded")
        except Exception as exc:
            value = default
            record.update(
                status="timeout" if isinstance(exc, TimeoutError) or monotonic() >= deadline else "error",
                error_type=type(exc).__name__,
                # Keep driver/SQL arguments out of the outward diagnostic.
                reason_code="READ_NODE_UNAVAILABLE",
            )
            driver_error = exc.orig if isinstance(exc, DBAPIError) else exc
            if isinstance(driver_error, sqlite3.Error):
                code = getattr(driver_error, "sqlite_errorcode", None)
                name = getattr(driver_error, "sqlite_errorname", None)
                if type(code) is int:
                    record["sqlite_errorcode"] = code
                    # Only publish a known SQLite constant matching this code.
                    if isinstance(name, str) and name.startswith("SQLITE_") and vars(sqlite3).get(name) == code:
                        record["sqlite_errorname"] = name
        record["duration_ms"] = round((monotonic() - started) * 1000, 3)
        record["wall_ms"] = record["duration_ms"]
        record["thread_cpu_ms"] = round((thread_time() - cpu_started) * 1000, 3)
        self.runs.append(record)
        self.values[node_id] = value
        return value

    def diagnostics(self) -> dict[str, Any]:
        return {
            "version": "omi.read.execution.v1",
            "execution_order": "sequential",
            "planned_nodes": list(self.nodes),
            "nodes": list(self.runs),
            "duration_ms": round((monotonic() - self.started) * 1000, 3),
            "provider_fetch_attempted": False,
        }
