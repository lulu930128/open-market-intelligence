from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import hashlib
import math
import os
from pathlib import Path
from threading import Lock
import time

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Base


connect_args = {}

if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}


engine_options: dict[str, object] = {"connect_args": connect_args}

# SQLite connections are local file handles, not scarce remote database
# connections.  A bounded QueuePool lets slow provider-facing requests retain
# every slot and turn otherwise cheap cache reads into 30 second pool waits.
# NullPool closes each connection with its Session, so one slow request cannot
# starve unrelated API/health requests.  WAL + busy_timeout below continue to
# provide the SQLite read/write concurrency policy.
if settings.database_url.startswith("sqlite"):
    engine_options["poolclass"] = NullPool

engine = create_engine(settings.database_url, **engine_options)


def _database_target_metadata(url) -> dict[str, object]:
    """Describe only a URL's lexical target; never connect, stat or expose a URL.

    Relative paths, URI options and filesystem aliases require separate evidence.
    A fingerprint is not an OS file identity or proof of an open connection.
    """
    result: dict[str, object] = {"kind": "unsupported", "path_sha256": None}
    if url.get_backend_name() != "sqlite":
        return result
    database = url.database
    if url.query or url.username or url.password or url.host:
        return result
    if not database or database == ":memory:":
        return {"kind": "sqlite_memory", "path_sha256": None}
    if database.startswith("file:") or not Path(database).is_absolute():
        return result
    normalized = os.path.normcase(os.path.normpath(database))
    return {
        "kind": "sqlite_absolute_path",
        "path_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


# Captured alongside the actual engine object, not reconstructed from disk at GET.
_binding_engine = engine
_binding_url = engine.url
_binding_target = _database_target_metadata(engine.url)
_binding_captured_at = datetime.now(timezone.utc).isoformat()


def database_binding_metadata() -> dict[str, object]:
    """Memory-only diagnostic, deliberately weaker than process/file attestation."""
    same_engine = engine is _binding_engine
    same_url = same_engine and engine.url == _binding_url
    try:
        settings_match = make_url(settings.database_url) == _binding_url
    except (ArgumentError, TypeError, ValueError):
        settings_match = False
    return {
        "diagnostic_contract": "omi.engine-binding.v1",
        "pid": os.getpid(),
        "engine_metadata_captured_at": _binding_captured_at,
        "engine_object_unchanged": same_engine,
        "engine_url_unchanged": same_url,
        "settings_match_engine_url": settings_match,
        "target": dict(_binding_target) if same_url else {"kind": "unknown", "path_sha256": None},
        "path_basis": "lexical_normcase_normpath_no_filesystem_resolution",
        "evidence_scope": "loaded_engine_configuration_only",
        "database_handle_binding": "UNVERIFIED",
        "loaded_release_identity": "UNATTESTED",
        "source_hash_basis": None,
    }


if settings.database_url.startswith("sqlite"):
    _sqlite_wal_initialization_lock = Lock()
    _sqlite_wal_initialized = False

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        global _sqlite_wal_initialized
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            # WAL mode is persistent for a SQLite database.  Reissuing the
            # mode-changing pragma for every NullPool connection can wait on
            # an active materializer write transaction and turn a cache-only
            # read into a multi-second cold request.  Establish it once per
            # process; every later connection only needs its own busy timeout.
            if not _sqlite_wal_initialized:
                with _sqlite_wal_initialization_lock:
                    if not _sqlite_wal_initialized:
                        cursor.execute("PRAGMA journal_mode=WAL")
                        _sqlite_wal_initialized = True
        finally:
            cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Explicit owner scopes only. SessionLocal and the default API dependency above
# remain unchanged. No engine/SQLAlchemy-wide hooks, SQL inspection or new IO.
_session_scope_lock = Lock()
_session_scope_closed = False
_session_scopes: dict[object, "_SessionScope"] = {}
_session_scope_last_exit: float | None = None


class SessionAdmissionClosed(RuntimeError):
    """The explicit Session owner has entered terminal drain."""


@dataclass
class _SessionScope:
    owner: str
    session: Session | None = None
    close_failed: bool = False
    ownership_unknown: bool = False


@dataclass(frozen=True)
class SessionDrainResult:
    state: str
    admission_closed: bool
    active_owners: tuple[str, ...]
    pending_constructors: int
    close_failures: int
    uncertain_owners: tuple[str, ...] = ()
    evidence_scope: str = "explicit_session_scopes_only"
    all_writers_drained: bool = False

    @property
    def drained(self) -> bool:
        return self.state == "drained" and self.admission_closed and not self.active_owners


def require_session_scope_admission() -> None:
    with _session_scope_lock:
        if _session_scope_closed:
            raise SessionAdmissionClosed("Explicit Session admission is closed")


def begin_session_scope_drain() -> None:
    global _session_scope_closed
    with _session_scope_lock:
        _session_scope_closed = True


@contextmanager
def owned_session(
    owner: str, *, session_factory: Callable[[], Session] | None = None,
) -> Generator[Session, None, None]:
    """Retain an admitted owner through lazy construction, all work and close.

    This is an upper bound on that owner's active transactions, not a transaction
    counter. The caller still owns commit/rollback; normal close keeps Session
    semantics. Cancellation retains unknown ownership instead of racing close.
    A borrowed Session/Connection must not escape to detached work. Such work and
    arbitrary SessionLocal/SDK/other-process writers are outside this receipt.
    """
    global _session_scope_last_exit
    if owner not in {"api_request", "runtime_startup"}:
        raise ValueError("Unclassified Session owner")
    token = object()
    record = _SessionScope(owner)
    with _session_scope_lock:
        if _session_scope_closed:
            raise SessionAdmissionClosed("Explicit Session admission is closed")
        _session_scopes[token] = record
    # Reservation precedes construction, including a blocked/late constructor.
    # Never execute constructor, SQL, commit, rollback or close under this lock.
    try:
        db = (session_factory or SessionLocal)()
    except BaseException:
        with _session_scope_lock:
            del _session_scopes[token]
            _session_scope_last_exit = time.monotonic()
        raise
    with _session_scope_lock:
        record.session = db
    try:
        yield db
    except (asyncio.CancelledError, GeneratorExit):
        # Cancellation of an awaiting request is not exit proof for its sync
        # worker. Do not race close against that worker, or discard its Session.
        # No automatic rearm/release: a later lifecycle gate must prove ownership.
        with _session_scope_lock:
            record.ownership_unknown = True
        raise
    finally:
        if not record.ownership_unknown:
            try:
                db.close()
            except BaseException:
                with _session_scope_lock:
                    record.close_failed = True
                # Retain the actual Session and owner on unknown close outcome.
                raise
            else:
                with _session_scope_lock:
                    del _session_scopes[token]
                    _session_scope_last_exit = time.monotonic()


def session_scope_drain_status(*, deadline: float) -> SessionDrainResult:
    if not math.isfinite(deadline):
        raise ValueError("Drain deadline must be finite")
    with _session_scope_lock:
        records = tuple(_session_scopes.values())
        failures = sum(record.close_failed for record in records)
        uncertain = tuple(record.owner for record in records if record.ownership_unknown)
        if uncertain:
            state = "unknown"
        elif failures:
            state = "error"
        elif not _session_scope_closed:
            state = "accepting"
        elif records:
            state = "timeout" if time.monotonic() >= deadline else "draining"
        elif _session_scope_last_exit is not None and _session_scope_last_exit > deadline:
            state = "timeout"
        else:
            state = "drained"
        return SessionDrainResult(
            state, _session_scope_closed, tuple(record.owner for record in records),
            sum(record.session is None for record in records), failures, uncertain,
        )


async def drain_session_scopes(*, deadline: float) -> SessionDrainResult:
    if not math.isfinite(deadline):
        raise ValueError("Drain deadline must be finite")
    begin_session_scope_drain()
    while True:
        result = session_scope_drain_status(deadline=deadline)
        if result.state != "draining":
            return result
        await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def get_draining_db() -> Generator[Session, None, None]:
    """Opt-in dependency seam; default app routes still use get_db.

    Adoption must pair dependency_overrides[get_db] with RuntimeCoordinator's
    drain_owned_sessions=True before serving requests. Only disposable fixtures
    exercise that wiring so far; it is not production writer coverage.
    """
    from fastapi import HTTPException

    scope = owned_session("api_request")
    try:
        db = scope.__enter__()
    except SessionAdmissionClosed as exc:
        raise HTTPException(status_code=503, detail="Database owner is draining") from exc
    try:
        yield db
    except BaseException as exc:
        scope.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        scope.__exit__(None, None, None)
