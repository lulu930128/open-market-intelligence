from __future__ import annotations

import argparse
from datetime import date
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
from app.market.monthly_revenue_history_backfill import (  # noqa: E402
    MAX_CACHED_PERIOD_ROWS,
    backfill_monthly_revenue_period_from_cached_raw,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _parse_period(value: str) -> date:
    try:
        year_text, month_text = value.split("-", 1)
        return date(int(year_text), int(month_text), 1)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "period must use YYYY-MM format."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill one Taiwan monthly-revenue period from persisted MOPS HTML. "
            "The command is cache-only and dry-run by default."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Explicit SQLite database path; no production default is assumed.",
    )
    parser.add_argument(
        "--period",
        type=_parse_period,
        required=True,
        help="Target revenue period in YYYY-MM format.",
    )
    parser.add_argument(
        "--market",
        action="append",
        choices=("TWSE", "TPEX"),
        default=[],
        help="Bound the run to a market. Repeat for both; default is both.",
    )
    parser.add_argument(
        "--stock-id",
        action="append",
        default=[],
        help="Bound the run to a stock ID. Repeat for multiple stocks.",
    )
    parser.add_argument(
        "--company-type",
        action="append",
        type=int,
        choices=(0, 1),
        default=[],
        help="MOPS company type: 0 domestic, 1 foreign. Default is both.",
    )
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help=(
            "Fetch a missing official MOPS document. Without this flag the command "
            "is strictly cache-only."
        ),
    )
    parser.add_argument(
        "--refresh-documents",
        action="store_true",
        help=(
            "Re-fetch selected MOPS documents and create a new raw version only "
            "when content changed."
        ),
    )
    parser.add_argument(
        "--max-fetches",
        type=int,
        default=4,
        help="Maximum missing documents fetched in one run (0-4).",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=MAX_CACHED_PERIOD_ROWS,
        help=f"Maximum rows that may be planned (1-{MAX_CACHED_PERIOD_ROWS}).",
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
            "--allow-production after backup and dry-run reconciliation."
        )

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"Database revision {current_revision!r} is not head {head_revision!r}; "
            "migrate the database explicitly before backfill."
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
        summary = backfill_monthly_revenue_period_from_cached_raw(
            db,
            period=args.period,
            markets=tuple(args.market or ("TWSE", "TPEX")),
            company_types=tuple(args.company_type or (0, 1)),
            stock_ids=tuple(args.stock_id),
            apply=args.apply,
            max_candidates=args.max_candidates,
            fetch_missing=args.fetch_missing,
            refresh_documents=args.refresh_documents,
            max_fetches=args.max_fetches,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
        summary["database"] = str(database_path)
        summary["database_revision"] = current_revision
        summary["quick_check"] = db.execute(text("PRAGMA quick_check")).scalar_one()
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
