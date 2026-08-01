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
from app.market.financial_evidence_package import (  # noqa: E402
    TaiwanFinancialEvidencePackage,
    apply_financial_evidence_package,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and apply a reviewed Taiwan financial evidence package. "
            "Dry-run is the default; both package and database must be explicit."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Explicit SQLite database path; no production default is assumed.",
    )
    parser.add_argument(
        "--package",
        type=Path,
        required=True,
        help="Reviewed omi.tw-financial-evidence.v1 JSON package.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the transaction is rolled back.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help=(
            "Required in addition to --apply for the production database. "
            "The package must also declare approval_scope=production."
        ),
    )
    parser.add_argument(
        "--defer-integrity-check",
        action="store_true",
        help=(
            "Skip the expensive full SQLite integrity scan for this invocation. "
            "Use only inside a bounded batch that runs a final non-deferred check."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON audit output. Existing files are never overwritten.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    package_path = args.package.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"Database does not exist: {database_path}")
    if not package_path.is_file():
        parser.error(f"Evidence package does not exist: {package_path}")
    output_path = args.output.expanduser().resolve() if args.output else None
    if output_path is not None:
        if output_path.exists():
            parser.error(f"Refusing to overwrite existing output: {output_path}")
        if not output_path.parent.is_dir():
            parser.error(f"Output directory does not exist: {output_path.parent}")
    try:
        package = TaiwanFinancialEvidencePackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        parser.error(f"Invalid evidence package: {exc}")

    is_production = database_path == PRODUCTION_DATABASE
    if args.apply and is_production and not args.allow_production:
        parser.error(
            "Refusing production write. Complete clone reconciliation and add "
            "--allow-production explicitly."
        )
    if args.apply and is_production and package.approval_scope != "production":
        parser.error(
            "Refusing production write because package approval_scope is not "
            "'production'."
        )

    database_url = _database_url(database_path)
    current_revision = get_database_revision(database_url)
    head_revision = get_head_revision()
    if current_revision != head_revision:
        parser.error(
            f"Database revision {current_revision!r} is not head {head_revision!r}; "
            "migrate the clone explicitly before applying evidence."
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
        summary = apply_financial_evidence_package(
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
        rendered = json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if output_path is not None:
            output_path.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
