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
from app.market.financial_ci_rollout import (  # noqa: E402
    MAX_CI_INGESTION_BATCH_SYMBOLS,
    MAX_CI_PLAN_PERIODS,
    run_ci_filing_ingestion_batch,
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
            "Fetch a bounded, explicit batch of general-industry MOPS filings. "
            "Dry-run is default; each symbol is transaction-isolated."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--stock-id",
        action="append",
        required=True,
        help=(
            "Explicit ci stock id. Repeat up to "
            f"{MAX_CI_INGESTION_BATCH_SYMBOLS} times."
        ),
    )
    parser.add_argument(
        "--period",
        type=_parse_period,
        action="append",
        required=True,
        help=(
            "Target filing period such as 2025Q1. Repeat up to "
            f"{MAX_CI_PLAN_PERIODS} times."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--inter-symbol-delay-seconds",
        type=float,
        default=5,
        help=(
            "Bounded cooldown between symbols. Default 5 seconds protects "
            "the MOPS document index from burst traffic."
        ),
    )
    parser.add_argument(
        "--max-provider-requests",
        type=int,
        required=True,
        help="Explicit hard ceiling for the complete batch.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist each successful symbol. Dry-run still performs bounded HTTP.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required with --apply when targeting the production database.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first symbol failure instead of recording a partial batch.",
    )
    parser.add_argument(
        "--integrity-check",
        choices=("deferred", "quick", "full"),
        default="quick",
        help="Post-run SQLite check. Use full at the final clone/production gate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON audit output. Existing files are never overwritten.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if len(set(args.stock_id)) > MAX_CI_INGESTION_BATCH_SYMBOLS:
        parser.error(
            f"at most {MAX_CI_INGESTION_BATCH_SYMBOLS} unique symbols are allowed"
        )
    if len(set(args.period)) > MAX_CI_PLAN_PERIODS:
        parser.error(f"at most {MAX_CI_PLAN_PERIODS} unique periods are allowed")
    if args.timeout_seconds < 1 or args.timeout_seconds > 120:
        parser.error("--timeout-seconds must be between 1 and 120")
    if args.inter_symbol_delay_seconds < 0 or args.inter_symbol_delay_seconds > 60:
        parser.error("--inter-symbol-delay-seconds must be between 0 and 60")
    if args.max_provider_requests < 1:
        parser.error("--max-provider-requests must be positive")
    output_path = args.output.expanduser().resolve() if args.output else None
    if output_path is not None:
        if output_path.exists():
            parser.error(f"refusing to overwrite existing output: {output_path}")
        if not output_path.parent.is_dir():
            parser.error(f"output directory does not exist: {output_path.parent}")
    if args.apply and database_path == PRODUCTION_DATABASE and not args.allow_production:
        parser.error(
            "refusing production write; validate on a clone first, then add "
            "--allow-production after backup and reconciliation"
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
        if not args.apply:
            db.execute(text("PRAGMA query_only = ON"))
        result = run_ci_filing_ingestion_batch(
            db,
            stock_ids=args.stock_id,
            periods=args.period,
            max_provider_requests=args.max_provider_requests,
            timeout_seconds=args.timeout_seconds,
            inter_symbol_delay_seconds=args.inter_symbol_delay_seconds,
            apply=args.apply,
            fail_fast=args.fail_fast,
        )
        result["database"] = str(database_path)
        result["database_revision"] = current_revision
        if args.integrity_check == "deferred":
            result["integrity_check"] = "deferred_explicitly"
        else:
            pragma = (
                "PRAGMA quick_check"
                if args.integrity_check == "quick"
                else "PRAGMA integrity_check"
            )
            result["integrity_check"] = db.execute(text(pragma)).scalar_one()
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if output_path is not None:
            output_path.write_text(rendered + "\n", encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(rendered)
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
