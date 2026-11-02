"""Dedicated journal schema/codec and OS lifetime lock; no business reducer."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys

from execution.contracts import EventKind
from execution.order_reducer import OrderFact, OrderProgress, OrderStatus
from execution.validation import require
from .contracts import encoded


APPLICATION_ID = 0x4F4D4558
SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE intents (
 execution_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, request_id TEXT NOT NULL,
 intent_id TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(account_id, request_id), UNIQUE(account_id, intent_id));
CREATE TABLE orders (
 execution_id TEXT PRIMARY KEY REFERENCES intents(execution_id),
 account_id TEXT NOT NULL, trade_date TEXT NOT NULL, broker_id TEXT,
 state TEXT NOT NULL, submit_stage TEXT NOT NULL, cancel_stage TEXT,
 reconcile_required INTEGER NOT NULL DEFAULT 1,
 UNIQUE(account_id, trade_date, broker_id));
CREATE TABLE journal (
 seq INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
 execution_id TEXT, kind TEXT NOT NULL, occurred_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE observations (
 event_id TEXT PRIMARY KEY, broker_key TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE applied (event_id TEXT PRIMARY KEY REFERENCES observations(event_id),
 execution_id TEXT NOT NULL REFERENCES intents(execution_id));
CREATE TABLE fills (
 broker_key TEXT NOT NULL, fill_id TEXT NOT NULL,
 execution_id TEXT NOT NULL REFERENCES intents(execution_id),
 quantity INTEGER NOT NULL, price TEXT NOT NULL, source_time TEXT NOT NULL,
 PRIMARY KEY(broker_key, fill_id));
CREATE TABLE external_orders (
 broker_key TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
"""
IMMUTABLE = ("intents", "journal", "observations", "applied", "fills", "external_orders")


def state_payload(state: OrderProgress) -> str:
    result = asdict(state)
    result["state"] = state.state.value
    for key in ("admitted_at", "last_report_at"):
        result[key] = result[key].isoformat() if result[key] else None
    for event in result["events"]:
        event["kind"] = event["kind"].value
        event["occurred_at"] = event["occurred_at"].isoformat()
        event["fill_price"] = str(event["fill_price"]) if event["fill_price"] is not None else None
    return encoded(result)


def state_from(value: dict) -> OrderProgress:
    value = dict(value)
    value["state"] = OrderStatus(value["state"])
    for key in ("admitted_at", "last_report_at"):
        value[key] = datetime.fromisoformat(value[key]) if value[key] else None
    value["events"] = tuple(OrderFact(**{**e, "kind": EventKind(e["kind"]),
        "occurred_at": datetime.fromisoformat(e["occurred_at"]),
        "fill_price": Decimal(e["fill_price"]) if e["fill_price"] is not None else None}) for e in value["events"])
    return OrderProgress(**value)


class OwnerLease:
    """Kernel-held, per canonical journal path lease. No PID guessing or lock deletion."""

    def __init__(self, path: Path):
        self.path = path.with_suffix(path.suffix + ".owner")
        self._file = None

    def acquire(self):
        require(self._file is None, "EXECUTION_OWNER_LEASE_ALREADY_HELD")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            raise RuntimeError("EXECUTION_OWNER_ALREADY_ACTIVE") from None
        self._file = handle

    @property
    def held(self):
        return self._file is not None and not self._file.closed

    def release(self):
        if self._file is not None:
            self._file.close()  # OS also releases this on abrupt process exit.
            self._file = None


class Journal:
    def __init__(self, path: Path, account_id: str):
        self.path = path
        # Never apply this schema to an existing foreign/production database.
        if path.exists():
            with self.connection(readonly=True) as con:
                require(con.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
                        "FOREIGN_JOURNAL")
                require(con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
                        "UNSUPPORTED_JOURNAL_VERSION")
                row = con.execute("SELECT value FROM metadata WHERE key='account_id'").fetchone()
                require(row is not None and row[0] == account_id, "JOURNAL_ACCOUNT_MISMATCH")
        else:
            with self.connection() as con:
                con.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
                for table in IMMUTABLE:
                    for action in ("UPDATE", "DELETE"):
                        con.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} "
                                    "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_EXECUTION_FACT'); END")
                con.execute("INSERT INTO metadata VALUES ('account_id', ?)", (account_id,))
                con.execute(f"PRAGMA application_id={APPLICATION_ID}")
                con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                con.commit()

    @contextmanager
    def connection(self, *, readonly=False):
        uri = self.path.as_uri() + ("?mode=ro" if readonly else "?mode=rwc")
        con = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            if readonly:
                con.execute("PRAGMA query_only=ON")
            else:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=FULL")
            yield con
        finally:
            con.close()
