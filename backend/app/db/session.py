from collections.abc import Generator

from sqlalchemy import create_engine, event
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

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
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
