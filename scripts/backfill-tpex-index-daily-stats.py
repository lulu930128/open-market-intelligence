from __future__ import annotations

import argparse
from datetime import date
import json
import logging
from pathlib import Path
import sys

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
PRODUCTION_DATABASE = (
    PROJECT_ROOT / "data" / "open_market_intelligence.db"
).resolve()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import MarketIndexDailyStat  # noqa: E402
from app.market.indices import refresh_market_index_daily_stats  # noqa: E402


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid ISO date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill missing TPEX daily market statistics from the official "
            "TPEx Market Highlight endpoint."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Explicit SQLite database path.",
    )
    parser.add_argument("--from-date", type=_parse_date, required=True)
    parser.add_argument("--to-date", type=_parse_date, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required to fetch and persist the missing rows.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required in addition to --apply for the production database.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"Database does not exist: {database_path}")
    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date.")
    if not args.apply:
        parser.error("Refusing to fetch or write without explicit --apply.")
    if database_path == PRODUCTION_DATABASE and not args.allow_production:
        parser.error(
            "Refusing production write without explicit --allow-production."
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        json.dumps(
            {
                "event": "tpex_daily_stat_backfill_started",
                "database": str(database_path),
                "from_date": args.from_date.isoformat(),
                "to_date": args.to_date.isoformat(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    engine = create_engine(
        _database_url(database_path),
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    db = session_factory()
    try:
        result = refresh_market_index_daily_stats(
            db,
            index_id="TPEX",
            from_date=args.from_date,
            to_date=args.to_date,
        )
        stored_count, first_date, last_date = (
            db.query(
                func.count(MarketIndexDailyStat.id),
                func.min(MarketIndexDailyStat.trade_date),
                func.max(MarketIndexDailyStat.trade_date),
            )
            .filter(MarketIndexDailyStat.index_id == "TPEX")
            .one()
        )
        output = {
            **result,
            "database": str(database_path),
            "stored_row_count": stored_count,
            "stored_first_date": (
                first_date.isoformat() if isinstance(first_date, date) else None
            ),
            "stored_last_date": (
                last_date.isoformat() if isinstance(last_date, date) else None
            ),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
