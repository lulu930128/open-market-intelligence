"""Factory-issued synthetic ledgers only; retained ledgers are still LOCAL_MOCK."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import hmac
import secrets
import sqlite3
import sys
from tempfile import TemporaryDirectory, gettempdir, mkdtemp
from weakref import WeakSet

from execution.validation import require


APPLICATION_ID = 0x4F4D5332
SCHEMA_VERSION = 1
_SANDBOXES = WeakSet()

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE previews (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, request_id TEXT NOT NULL,
 draft_digest TEXT NOT NULL, evidence_digest TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(account_id, request_id));
CREATE TABLE confirmations (id TEXT PRIMARY KEY REFERENCES previews(id), payload TEXT NOT NULL);
CREATE TABLE orders (id TEXT PRIMARY KEY REFERENCES previews(id), payload TEXT NOT NULL);
CREATE TABLE budgets (account_id TEXT PRIMARY KEY, binding TEXT NOT NULL, cash TEXT NOT NULL);
CREATE TABLE positions (
 account_id TEXT NOT NULL, instrument TEXT NOT NULL, binding TEXT NOT NULL, quantity INTEGER NOT NULL,
 PRIMARY KEY(account_id, instrument));
CREATE TABLE reservations (
 id TEXT PRIMARY KEY REFERENCES previews(id), account_id TEXT NOT NULL, instrument TEXT NOT NULL,
 cash TEXT NOT NULL, quantity INTEGER NOT NULL);
CREATE TABLE outbox (
 id TEXT PRIMARY KEY, preview_id TEXT NOT NULL REFERENCES previews(id), kind TEXT NOT NULL,
 UNIQUE(preview_id, kind));
CREATE TABLE outbox_events (
 seq INTEGER PRIMARY KEY, command_id TEXT NOT NULL REFERENCES outbox(id), stage TEXT NOT NULL,
 occurred_at TEXT NOT NULL, UNIQUE(command_id, stage));
CREATE TABLE mock_effects (
 command_id TEXT PRIMARY KEY REFERENCES outbox(id), fixture TEXT NOT NULL, receipt TEXT);
CREATE TABLE audit (
 seq INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, operation TEXT NOT NULL, preview_id TEXT,
 payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
"""


@dataclass(frozen=True, eq=False)
class Sandbox:
    """Lifetime capability for one temporary directory, not an arbitrary DB path."""
    directory: Path
    _lease: TemporaryDirectory | None

    @property
    def database(self):
        require(self in _SANDBOXES, "INVALID_SANDBOX")
        require(self.directory.name.startswith("omi-synthetic-m2a-")
                and self.directory.is_dir() and not self.directory.is_symlink()
                and self.directory.resolve() == self.directory, "INVALID_SANDBOX")
        require(self._lease is None or self.directory == Path(self._lease.name).resolve(), "INVALID_SANDBOX")
        path = self.directory / "simulation.sqlite3"
        require(not path.is_symlink() and path.resolve() == path, "INVALID_SANDBOX")
        require(not path.exists() or path.stat().st_nlink == 1, "INVALID_SANDBOX")
        return path

    def ticket(self):
        self.database  # Validate issued lifetime capability before exporting fixture material.
        return SandboxTicket(str(self.directory), (self.directory / 'sandbox.token').read_text(encoding='ascii'))


@dataclass(frozen=True)
class SandboxTicket:
    """Test-process handoff only; not user identity, broker credentials, or production auth."""
    directory: str
    token: str = field(repr=False)


@contextmanager
def reopen_sandbox(ticket):
    """Reopen the factory's existing temp directory across process restarts, never initialize it."""
    require(type(ticket) is SandboxTicket, "INVALID_SANDBOX")
    directory = Path(ticket.directory)
    require(directory.is_absolute() and directory.parent == Path(gettempdir()).resolve()
            and directory.name.startswith('omi-synthetic-m2a-')
            and directory.resolve() == directory and not directory.is_symlink(), "INVALID_SANDBOX")
    marker = directory / 'sandbox.token'
    require(marker.is_file() and not marker.is_symlink() and marker.resolve() == marker
            and marker.stat().st_nlink == 1 and marker.stat().st_size == 64, "INVALID_SANDBOX")
    require(type(ticket.token) is str and len(ticket.token) == 64 and ticket.token.isascii()
            and hmac.compare_digest(marker.read_text(encoding='ascii'), ticket.token), "INVALID_SANDBOX")
    sandbox = Sandbox(directory, None)
    _SANDBOXES.add(sandbox)
    try:
        with connection(sandbox, readonly=True):
            pass
        yield sandbox
    finally:
        _SANDBOXES.discard(sandbox)


@contextmanager
def temporary_sandbox():
    """No path/config/production DB argument. Cleanup only this factory's directory."""
    # tempfile creates mode 0700; Python 3.13+ enforces the private Windows ACL
    # (current user, SYSTEM and administrators), rather than ignoring that mode.
    require(sys.platform != 'win32' or sys.version_info >= (3, 13), 'PRIVATE_TEMP_ACL_REQUIRED')
    lease = TemporaryDirectory(prefix="omi-synthetic-m2a-")
    try:
        sandbox = Sandbox(Path(lease.name).resolve(), lease)
        _SANDBOXES.add(sandbox)
        _initialize(sandbox)
        yield sandbox
    finally:
        if 'sandbox' in locals():
            _SANDBOXES.discard(sandbox)
        lease.cleanup()


def _initialize(sandbox):
    """Initialize only a newly issued factory directory, never an existing DB."""
    path = sandbox.database
    require(not path.exists(), 'LEDGER_ALREADY_EXISTS')
    with (sandbox.directory / 'sandbox.token').open('x', encoding='ascii') as marker:
        marker.write(secrets.token_hex(32))
    db = sqlite3.connect(path)
    try:
        db.executescript(SCHEMA)
        db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        for table in ('previews', 'confirmations', 'budgets', 'positions', 'reservations',
                      'outbox', 'outbox_events', 'mock_effects', 'audit'):
            for action in ('UPDATE', 'DELETE'):
                db.execute(f'CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} '
                           "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
        db.commit()
    finally:
        db.close()


@contextmanager
def retained_mock_sandbox():
    """Explicit opt-in retention across worker exit; no caller-supplied DB path.

    Retains even on failure for inspection. No finalizer, automatic recovery or
    cleanup. Reopen requires the issued ticket and the SAME configured temp root.
    This is synthetic evidence retention, NOT a real simulator ledger release.
    """
    require(sys.platform != 'win32' or sys.version_info >= (3, 13), 'PRIVATE_TEMP_ACL_REQUIRED')
    sandbox = Sandbox(Path(mkdtemp(prefix='omi-synthetic-m2a-')).resolve(), None)
    _SANDBOXES.add(sandbox)
    try:
        _initialize(sandbox)
        (sandbox.directory / 'lifecycle.txt').write_text(
            'LOCAL_MOCK\nRETAINED\nSYNTHETIC_ONLY\nNO_BROKER\n', encoding='ascii')
        yield sandbox
    finally:
        _SANDBOXES.discard(sandbox)


@contextmanager
def connection(sandbox, *, readonly=False):
    require(type(sandbox) is Sandbox, "INVALID_SANDBOX")
    # mode=rw/ro cannot create a missing database, and never performs migrations.
    uri = sandbox.database.as_uri() + ("?mode=ro" if readonly else "?mode=rw")
    db = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        require(db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
                and db.execute("PRAGMA user_version").fetchone()[0] in (SCHEMA_VERSION, 2),
                "NOT_SIMULATION_DATABASE")
        if db.execute('PRAGMA user_version').fetchone()[0] == 2:
            from .codec import loads
            from execution.validation import digest_of
            root = db.execute('SELECT payload FROM settlement_root WHERE id=1').fetchone()
            require(root is not None and loads(root[0])['sandbox_binding'] == digest_of(sandbox.ticket().token),
                    'SANDBOX_ROOT_MISMATCH')
        db.execute("PRAGMA foreign_keys=ON")
        if readonly:
            db.execute("PRAGMA query_only=ON")
        else:
            db.execute("PRAGMA synchronous=FULL")
        yield db
    finally:
        db.close()


@contextmanager
def settlement_sandbox_clone(source, *, crash_at=None):
    """Upgrade only a new factory clone, never the source or an arbitrary path.

    Old payloads and audit hashes are copied byte-for-byte. Migration DDL and
    its prefix anchor commit together. The normal reader never runs migration.
    """
    from .application import SimulationApplication
    from .codec import dumps
    from .mock import SimulatedCrash
    from execution.validation import digest_of

    with temporary_sandbox() as clone:
        with connection(source, readonly=True) as src, connection(clone) as dst:
            src.execute('BEGIN')
            require(src.execute('PRAGMA user_version').fetchone()[0] == 1, 'MIGRATION_SOURCE_VERSION')
            SimulationApplication._verify(src)
            src.backup(dst)
        with connection(clone) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                head = db.execute('SELECT seq,hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
                root = dict(version=2, codec_version=1, policy_version='synthetic-settlement-v2',
                            seq=head[0] if head else 0, head=head[1] if head else '0' * 64,
                            sandbox_binding=digest_of(clone.ticket().token))
                db.execute('CREATE TABLE settlement_root (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                db.execute('INSERT INTO settlement_root VALUES(1,?)', (dumps(root),))
                db.execute('CREATE TABLE settlement_events (id TEXT PRIMARY KEY, operation TEXT NOT NULL, '
                           'preview_id TEXT NOT NULL, payload TEXT NOT NULL)')
                db.execute('CREATE TABLE releases (preview_id TEXT PRIMARY KEY REFERENCES reservations(id), '
                           'receipt_id TEXT NOT NULL UNIQUE)')
                db.execute('CREATE TABLE settlement_projection (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                from .settlement import empty_projection
                db.execute('INSERT INTO settlement_projection VALUES(1,?)', (dumps(empty_projection()),))
                for table in ('settlement_root', 'settlement_events', 'releases'):
                    for action in ('UPDATE', 'DELETE'):
                        db.execute(f'CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} '
                                   "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
                db.execute('PRAGMA user_version=2')
                if crash_at == 'before_commit':
                    raise SimulatedCrash('before_commit')
                db.commit()
            except BaseException:
                db.rollback()
                require(db.execute('PRAGMA user_version').fetchone()[0] == 1, 'MIGRATION_ROLLBACK_FAILED')
                require(db.execute("SELECT 1 FROM sqlite_master WHERE name='settlement_root'").fetchone() is None,
                        'MIGRATION_ROLLBACK_FAILED')
                raise
        if crash_at == 'after_commit':
            # Reopen/verify a committed clone before exposing the simulated crash.
            SimulationApplication(clone).verify()
            raise SimulatedCrash('after_commit')
        yield clone
