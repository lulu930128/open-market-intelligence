from __future__ import annotations

import logging
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL, make_url

from app.db.admission import attach_sqlite_admission


logger = logging.getLogger(__name__)

# Source-only inspection must not instantiate Settings (or read dotenv/secrets).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = PROJECT_ROOT / "backend" / "alembic"


def _database_url(database_url: str | None) -> str:
    if database_url:
        return database_url
    from app.config import settings
    return settings.database_url


def _sqlite_connect_args(database_url: str) -> dict[str, bool | int]:
    return {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}


def _ensure_sqlite_parent(database_url: str) -> None:
    try:
        url = make_url(database_url)
    except Exception:
        return

    if not url.drivername.startswith("sqlite"):
        return

    database = url.database
    if not database or database == ":memory:":
        return

    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _safe_database_url(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable database url>"


def create_alembic_config(database_url: str | None = None) -> Config:
    if not ALEMBIC_SCRIPT_LOCATION.exists():
        raise RuntimeError(f"Alembic script directory was not found: {ALEMBIC_SCRIPT_LOCATION}")

    config = Config(str(ALEMBIC_INI_PATH)) if ALEMBIC_INI_PATH.exists() else Config()
    resolved_database_url = _database_url(database_url)

    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("prepend_sys_path", str(PROJECT_ROOT / "backend"))
    config.set_main_option("sqlalchemy.url", resolved_database_url)
    config.attributes["database_url"] = resolved_database_url
    return config


def get_head_revision() -> str:
    config = create_alembic_config("sqlite://")
    return ScriptDirectory.from_config(config).get_current_head()


def inspect_database_schema(path: Path, *, check_integrity: bool = False) -> dict:
    """Read one bounded snapshot; revision equality is not full model validation.

    No settings, database creation, stamp, repair, journal-mode change or retry.
    Unknown revision IDs cannot be ordered lexically: they may be from newer code
    or an unrelated branch. This observation never grants maintenance authority.
    """
    scripts = ScriptDirectory.from_config(create_alembic_config("sqlite://"))
    head = scripts.get_current_head()
    result = {"current": None, "head": head, "state": "DB_UNKNOWN",
              "migration_needed": None, "integrity": "NOT_CHECKED",
              "schema_sha256": None, "schema_validation": "UNVERIFIED"}
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        return dict(result, reason="EXISTING_ABSOLUTE_DATABASE_REQUIRED")
    deadline = time.monotonic() + 10
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        db.execute("BEGIN")
        rows = db.execute("SELECT version_num FROM alembic_version").fetchmany(2)
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            return dict(result, reason="REVISION_NOT_SINGLE")
        current = rows[0][0]
        result["current"] = current
        schema = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        result["schema_sha256"] = hashlib.sha256(
            json.dumps(schema, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        if check_integrity:
            checks = db.execute("PRAGMA quick_check").fetchmany(2)
            result["integrity"] = "ok" if checks == [("ok",)] else "FAILED"
            if result["integrity"] != "ok":
                return dict(result, reason="DATABASE_INTEGRITY_FAILED")
        ancestors = {revision.revision for revision in scripts.walk_revisions()}
        if current == head:
            return dict(result, state="DB_AT_HEAD", migration_needed=False)
        if current in ancestors:
            return dict(result, state="DB_BEHIND", migration_needed=True)
        return dict(result, state="DB_AHEAD_OR_UNKNOWN", reason="REVISION_NOT_IN_SOURCE_GRAPH")
    except sqlite3.Error as exc:
        # Fixed error class only; no SQL data or private configuration in output.
        return dict(result, reason="DATABASE_READ_FAILED", error_type=type(exc).__name__)
    finally:
        if db is not None:
            db.close()


def get_database_revision(database_url: str | None = None, *, existing_only: bool = False) -> str | None:
    resolved_database_url = _database_url(database_url)
    if existing_only:
        target = make_url(resolved_database_url)
        if (target.drivername not in {"sqlite", "sqlite+pysqlite"} or target.query
                or not target.database or not Path(target.database).is_absolute()
                or not Path(target.database).is_file()):
            raise RuntimeError("Owned startup requires an existing local SQLite database")
        resolved_database_url = URL.create("sqlite+pysqlite", database=Path(target.database).as_uri(),
                                          query={"mode": "ro", "uri": "true"})
    else:
        _ensure_sqlite_parent(resolved_database_url)

    engine = create_engine(
        resolved_database_url,
        connect_args=_sqlite_connect_args(str(resolved_database_url)),
    )
    attach_sqlite_admission(engine)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def run_database_migrations(database_url: str | None = None, *, connection=None) -> None:
    if connection is not None:
        if (connection.dialect.name != "sqlite" or not connection.in_transaction()
                or not connection.connection.driver_connection.in_transaction):
            raise RuntimeError("MAINTENANCE_TRANSACTION_REQUIRED")
        config = create_alembic_config("sqlite://")
        config.attributes["connection"] = connection
        head = ScriptDirectory.from_config(config).get_current_head()
        if MigrationContext.configure(connection).get_current_revision() != head:
            command.upgrade(config, "head")
        if (not connection.connection.driver_connection.in_transaction
                or MigrationContext.configure(connection).get_current_revision() != head):
            raise RuntimeError("MIGRATION_TRANSACTION_OR_HEAD_LOST")
        return
    resolved_database_url = _database_url(database_url)
    _ensure_sqlite_parent(resolved_database_url)

    config = create_alembic_config(resolved_database_url)
    head_revision = ScriptDirectory.from_config(config).get_current_head()
    current_revision = get_database_revision(resolved_database_url)

    if current_revision == head_revision:
        logger.info("Database schema is already at Alembic head revision %s.", head_revision)
        return

    logger.info(
        "Applying database migrations. current_revision=%s target_revision=%s database=%s",
        current_revision or "<none>",
        head_revision,
        _safe_database_url(resolved_database_url),
    )
    command.upgrade(config, "head")

    updated_revision = get_database_revision(resolved_database_url)
    logger.info("Database migrations completed. revision=%s", updated_revision)
