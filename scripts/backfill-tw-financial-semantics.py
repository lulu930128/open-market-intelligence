from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
PRODUCTION_DATABASE = (PROJECT_ROOT / "data" / "open_market_intelligence.db").resolve()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_semantic_backfill import (  # noqa: E402
    MAX_BACKFILL_ROWS,
    backfill_legacy_financial_semantics,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill versioned Taiwan financial raw facts. "
            "Dry-run is the default and a database path is always required."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Explicit SQLite database path; no production default is assumed.",
    )
    parser.add_argument(
        "--stock-id",
        action="append",
        default=[],
        help="Bound the run to a stock ID. Repeat for multiple stocks.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1_000,
        help=f"Maximum legacy rows to inspect (1-{MAX_BACKFILL_ROWS}).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the transaction is rolled back.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required in addition to --apply when the target is the production DB.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"Database does not exist: {database_path}")
    if args.apply and database_path == PRODUCTION_DATABASE and not args.allow_production:
        parser.error(
            "Refusing production write. Use a clone or explicitly add "
            "--allow-production after completing clone reconciliation."
        )

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"Database revision {current_revision!r} is not head {head_revision!r}; "
            "migrate the clone explicitly before backfill."
        )

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    db = session_factory()
    try:
        summary = backfill_legacy_financial_semantics(
            db,
            stock_ids=args.stock_id,
            limit=args.limit,
            apply=args.apply,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
        integrity_check = db.execute(text("PRAGMA integrity_check")).scalar_one()
        summary["database"] = str(database_path)
        summary["database_revision"] = current_revision
        summary["integrity_check"] = integrity_check
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
