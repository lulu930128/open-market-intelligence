from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url

from app.config import PROJECT_ROOT, settings


logger = logging.getLogger(__name__)

ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = PROJECT_ROOT / "backend" / "alembic"


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
    resolved_database_url = database_url or settings.database_url

    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("prepend_sys_path", str(PROJECT_ROOT / "backend"))
    config.set_main_option("sqlalchemy.url", resolved_database_url)
    config.attributes["database_url"] = resolved_database_url
    return config


def get_head_revision() -> str:
    config = create_alembic_config()
    return ScriptDirectory.from_config(config).get_current_head()


def get_database_revision(database_url: str | None = None) -> str | None:
    resolved_database_url = database_url or settings.database_url
    _ensure_sqlite_parent(resolved_database_url)

    engine = create_engine(
        resolved_database_url,
        connect_args=_sqlite_connect_args(resolved_database_url),
    )
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def run_database_migrations(database_url: str | None = None) -> None:
    resolved_database_url = database_url or settings.database_url
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
