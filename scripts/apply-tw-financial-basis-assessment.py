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
from app.market.financial_basis_assessment import (  # noqa: E402
    TaiwanFinancialBasisAssessmentPackage,
    apply_financial_basis_assessment,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and apply a reviewed Taiwan financial basis assessment. "
            "Dry-run is the default; database and package must be explicit."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the assessment; otherwise roll back.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help=(
            "Required with --apply for the production database. The package "
            "must also declare approval_scope=production."
        ),
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
    package_path = args.package.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if not package_path.is_file():
        parser.error(f"package does not exist: {package_path}")
    try:
        package = TaiwanFinancialBasisAssessmentPackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        parser.error(f"invalid basis-assessment package: {exc}")

    is_production = database_path == PRODUCTION_DATABASE
    if args.apply and is_production and not args.allow_production:
        parser.error(
            "refusing production write; validate a clone first, then add "
            "--allow-production explicitly"
        )
    if args.apply and is_production and package.approval_scope != "production":
        parser.error(
            "refusing production write because package approval_scope is not "
            "'production'"
        )

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"database revision {current_revision!r} is not head "
            f"{head_revision!r}"
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
        summary = apply_financial_basis_assessment(
            db,
            package=package,
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
        print(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
