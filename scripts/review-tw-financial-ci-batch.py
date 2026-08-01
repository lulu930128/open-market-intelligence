from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
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
from app.market.financial_ci_review import review_ci_parse_run_batch  # noqa: E402


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


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "reviewed timestamp must include timezone evidence"
        )
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or approve one bounded Taiwan CI parser-v4 batch. "
            "Every output is rehashed; dry-run is default."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--stock-id", action="append", required=True)
    parser.add_argument("--period", type=_parse_period, action="append", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", type=_parse_timestamp, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required with --apply when targeting the production database.",
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--integrity-check",
        choices=("deferred", "quick", "full"),
        default="quick",
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
    if args.apply and database_path == PRODUCTION_DATABASE and not args.allow_production:
        parser.error(
            "refusing production review; validate a clone first, then add "
            "--allow-production explicitly"
        )
    output_path = args.output.expanduser().resolve() if args.output else None
    if output_path is not None:
        if output_path.exists():
            parser.error(f"refusing to overwrite existing output: {output_path}")
        if not output_path.parent.is_dir():
            parser.error(f"output directory does not exist: {output_path.parent}")

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
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        if not args.apply:
            db.execute(text("PRAGMA query_only = ON"))
        summary = review_ci_parse_run_batch(
            db,
            stock_ids=args.stock_id,
            periods=args.period,
            reviewer=args.reviewer,
            reviewed_at=args.reviewed_at,
            apply=args.apply,
            fail_fast=args.fail_fast,
        )
        summary["database"] = str(database_path)
        summary["database_revision"] = current_revision
        if args.integrity_check == "deferred":
            summary["integrity_check"] = "deferred_explicitly"
        else:
            pragma = (
                "PRAGMA quick_check"
                if args.integrity_check == "quick"
                else "PRAGMA integrity_check"
            )
            summary["integrity_check"] = db.execute(text(pragma)).scalar_one()
        rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
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
