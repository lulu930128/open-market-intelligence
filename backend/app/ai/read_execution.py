from __future__ import annotations

from contextlib import contextmanager
from time import monotonic
from typing import Any, Callable, Iterator

from sqlalchemy.orm import Session

from app.ai.capability_resolution_registry import CapabilityReadNode


@contextmanager
def _bounded_read_session(db: Session, deadline: float) -> Iterator[Session]:
    """Same-thread, separately owned read transaction with a SQLite deadline.

    Busy waits and VM execution are bounded. Pure Python readers must also keep
    their canonical row/iteration bounds; no abandoned worker shares a Session.
    Connection-local settings are restored before returning it to the pool.
    """
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as reader:
        connection = reader.connection()
        raw = connection.connection.driver_connection
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            query_only = raw.execute("PRAGMA query_only").fetchone()[0]
            busy_timeout = raw.execute("PRAGMA busy_timeout").fetchone()[0]
            raw.execute("PRAGMA query_only=ON")
            raw.execute(f"PRAGMA busy_timeout={max(1, int((deadline - monotonic()) * 1000))}")
            raw.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
        try:
            yield reader
        finally:
            if sqlite:
                raw.set_progress_handler(None, 0)
                raw.execute(f"PRAGMA busy_timeout={busy_timeout}")
                raw.execute(f"PRAGMA query_only={query_only}")


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
        deadline = min(self.deadline, started + spec.timeout_seconds)
        record: dict[str, Any] = {"node": node_id, "status": "completed", "timeout_seconds": spec.timeout_seconds}
        value = default
        try:
            if started >= deadline:
                raise TimeoutError("Request read budget exhausted")
            with _bounded_read_session(self.db, deadline) as reader:
                value = read(reader)
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
        record["duration_ms"] = round((monotonic() - started) * 1000, 3)
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
