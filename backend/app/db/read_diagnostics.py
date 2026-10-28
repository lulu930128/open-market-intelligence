"""Numeric, connection/session-local read diagnostics; no payload or SQL capture."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from time import monotonic, thread_time
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


PHASE_TRACE_KEY = "omi_read_phase_trace"
_TECHNICAL_PHASES = frozenset({
    "parameters", "daily_bars", "weekly_bars", "monthly_bars", "current_bars",
    "indicators", "benchmark", "sector", "advanced", "assemble",
})


@contextmanager
def technical_read_phase(db: Session, label: str, *, active: bool = True) -> Iterator[None]:
    """Only an explicitly instrumented Session records the fixed phase labels."""
    info = getattr(db, "info", None)
    records = info.get(PHASE_TRACE_KEY) if isinstance(info, dict) else None
    if not isinstance(records, list):
        yield
        return
    if label not in _TECHNICAL_PHASES:
        raise ValueError("Unknown technical read phase")
    wall, cpu = monotonic(), thread_time()
    row = {"phase": label, "status": "completed" if active else "skipped"}
    try:
        yield
    except BaseException:
        row["status"] = "error"
        raise
    finally:
        row.update(wall_ms=round((monotonic() - wall) * 1000, 3),
                   thread_cpu_ms=round((thread_time() - cpu) * 1000, 3))
        records.append(row)


@contextmanager
def connection_execute_trace(connection: Connection, deadline: float, output: dict[str, Any]) -> Iterator[None]:
    """Time cursor execute only, including its failure at the execute boundary.

    SQLAlchemy 2 does not support a Connection-local handle_error event. Wrap
    this Connection's public execute entrypoints to finish pending cursor spans
    before errors reach the caller, even if the caller catches and continues.
    No Engine/Dialect listener, SQL text, arguments, rows or exception is kept.
    Failure timing includes exception unwind to the public execute entrypoint;
    neither successful nor failed spans include subsequent result fetching.
    """
    output["sql_execute_scope"] = "node_read_connection_only"
    output["sql_execute_excludes"] = ["fetch", "orm_materialization", "other_connections", "raw_dbapi_setup_cleanup"]
    stats: dict[str, Any] = dict(count=0, completed_count=0, error_count=0,
                                wall_ms=0.0, thread_cpu_ms=0.0,
                                max_wall_ms=0.0, max_thread_cpu_ms=0.0,
                                last_failed_execute=None)
    output["sql_execute"] = stats
    pending: dict[Any, tuple[float, float, float]] = {}

    def before(conn, cursor, statement, parameters, context, executemany):
        wall = monotonic()
        pending[context] = (wall, thread_time(), max(0.0, (deadline - wall) * 1000))
        stats["count"] += 1

    def finish(context, *, failed):
        start = pending.pop(context, None)
        if start is None:
            return
        wall_ms = (monotonic() - start[0]) * 1000
        cpu_ms = (thread_time() - start[1]) * 1000
        stats["error_count" if failed else "completed_count"] += 1
        stats["wall_ms"] += wall_ms
        stats["thread_cpu_ms"] += cpu_ms
        stats["max_wall_ms"] = max(stats["max_wall_ms"], wall_ms)
        stats["max_thread_cpu_ms"] = max(stats["max_thread_cpu_ms"], cpu_ms)
        if failed:
            stats["last_failed_execute"] = {
                "wall_ms": round(wall_ms, 3), "thread_cpu_ms": round(cpu_ms, 3),
                "deadline_remaining_ms_at_sql_start": round(start[2], 3),
            }

    def after(conn, cursor, statement, parameters, context, executemany):
        finish(context, failed=False)

    def guarded(method):
        @wraps(method)
        def execute(*args, **kwargs):
            prior = set(pending)
            try:
                return method(*args, **kwargs)
            except BaseException:
                for context in list(pending):
                    if context not in prior:
                        finish(context, failed=True)
                raise
        return execute

    originals = {}
    listeners = []
    try:
        for name in ("execute", "exec_driver_sql"):
            originals[name] = (name in vars(connection), getattr(connection, name))
            setattr(connection, name, guarded(getattr(connection, name)))
        for name, listener in (("before_cursor_execute", before), ("after_cursor_execute", after)):
            event.listen(connection, name, listener)
            listeners.append((name, listener))
        yield
    finally:
        for name, listener in reversed(listeners):
            event.remove(connection, name, listener)
        for name, (had_override, original) in originals.items():
            if had_override:
                setattr(connection, name, original)
            else:
                delattr(connection, name)
        pending.clear()
        for name in ("wall_ms", "thread_cpu_ms", "max_wall_ms", "max_thread_cpu_ms"):
            stats[name] = round(stats[name], 3)
