from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
PRODUCTION_DATABASE = (PROJECT_ROOT / "data" / "open_market_intelligence.db").resolve()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_filing_ingestion import (  # noqa: E402
    MAX_INGESTION_PERIODS,
    ingest_mops_financial_filings,
)


_PERIOD_RE = re.compile(r"^(?P<year>20\d{2})Q(?P<quarter>[1-4])$", re.I)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _parse_period(value: str) -> tuple[int, int]:
    match = _PERIOD_RE.fullmatch(value.strip())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"invalid period {value!r}; expected YYYYQ1 through YYYYQ4"
        )
    return int(match.group("year")), int(match.group("quarter"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch versioned official MOPS iXBRL financial filings. "
            "Dry-run is the default; targets and database must be explicit."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--stock-id", required=True)
    parser.add_argument(
        "--period",
        type=_parse_period,
        action="append",
        required=True,
        help=(
            "Bounded filing period such as 2025Q1. Repeat up to "
            f"{MAX_INGESTION_PERIODS} times."
        ),
    )
    parser.add_argument("--report-id", default="C", choices=("C", "A", "B"))
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag no database rows are added.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required with --apply when targeting the production database.",
    )
    parser.add_argument(
        "--defer-integrity-check",
        action="store_true",
        help=(
            "Skip the expensive full SQLite integrity scan for this invocation. "
            "Use only inside a bounded batch that runs a final non-deferred check."
        ),
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if len(set(args.period)) > MAX_INGESTION_PERIODS:
        parser.error(f"at most {MAX_INGESTION_PERIODS} unique periods are allowed")
    if args.timeout_seconds < 1 or args.timeout_seconds > 120:
        parser.error("--timeout-seconds must be between 1 and 120")
    if args.apply and database_path == PRODUCTION_DATABASE and not args.allow_production:
        parser.error(
            "refusing production write; use a clone first, then add "
            "--allow-production only after reconciliation"
        )

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"database revision {current_revision!r} is not head {head_revision!r}"
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
        summary = ingest_mops_financial_filings(
            db,
            stock_id=args.stock_id,
            periods=args.period,
            report_id=args.report_id,
            apply=args.apply,
            timeout_seconds=args.timeout_seconds,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
        summary["database"] = str(database_path)
        summary["database_revision"] = current_revision
        summary["integrity_check"] = (
            "deferred_explicitly"
            if args.defer_integrity_check
            else db.execute(text("PRAGMA integrity_check")).scalar_one()
        )
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
