from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
PRODUCTION_DATABASE = (
    PROJECT_ROOT / "data" / "open_market_intelligence.db"
).resolve()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_filing_ingestion import (  # noqa: E402
    MAX_REPLAY_FILINGS,
    replay_stored_mops_financial_filings,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically replay stored MOPS raw filings into an immutable "
            "parse run. Dry-run is the default and no network request is made."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--filing-id",
        type=int,
        action="append",
        required=True,
        help=(
            "Explicit filing id. Repeat up to "
            f"{MAX_REPLAY_FILINGS} unique filings."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist a pending parse run; otherwise roll back.",
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
            "Skip the full SQLite integrity scan inside a bounded batch that "
            "will run one final non-deferred check."
        ),
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    filing_ids = sorted(set(args.filing_id))
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if any(item < 1 for item in filing_ids):
        parser.error("--filing-id must be a positive integer")
    if len(filing_ids) > MAX_REPLAY_FILINGS:
        parser.error(f"at most {MAX_REPLAY_FILINGS} unique filings are allowed")
    if (
        args.apply
        and database_path == PRODUCTION_DATABASE
        and not args.allow_production
    ):
        parser.error(
            "refusing production replay; validate a clone first, then add "
            "--allow-production explicitly"
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
    db = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )()
    try:
        summary = replay_stored_mops_financial_filings(
            db,
            filing_ids=filing_ids,
            apply=args.apply,
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
