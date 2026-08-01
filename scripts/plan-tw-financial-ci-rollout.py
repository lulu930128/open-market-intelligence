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
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_ci_rollout import (  # noqa: E402
    MAX_CI_PLAN_PAGE_SIZE,
    MAX_CI_PLAN_PERIODS,
    build_ci_rollout_plan,
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
            "Build a query-only coverage and next-action plan for Taiwan "
            "general-industry (ci) financial normalization."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
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
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON audit output. Existing files are never overwritten.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if len(set(args.period)) > MAX_CI_PLAN_PERIODS:
        parser.error(f"at most {MAX_CI_PLAN_PERIODS} unique periods are allowed")
    if args.offset < 0:
        parser.error("--offset must be non-negative")
    if args.limit < 1 or args.limit > MAX_CI_PLAN_PAGE_SIZE:
        parser.error(f"--limit must be between 1 and {MAX_CI_PLAN_PAGE_SIZE}")
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
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    db = session_factory()
    try:
        db.execute(text("PRAGMA query_only = ON"))
        query_only = bool(db.execute(text("PRAGMA query_only")).scalar_one())
        if not query_only:
            raise RuntimeError("SQLite query_only guard could not be enabled")
        result = build_ci_rollout_plan(
            db,
            periods=args.period,
            offset=args.offset,
            limit=args.limit,
        )
        db.rollback()
        result["database"] = str(database_path)
        result["database_revision"] = current_revision
        result["query_only"] = query_only
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
