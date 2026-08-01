from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import get_database_revision, get_head_revision  # noqa: E402
from app.market.financial_ci_rollout import (  # noqa: E402
    select_ci_acceptance_sample,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Select a query-only, deterministic, source-stratified acceptance "
            "sample from the current Taiwan general-industry (ci) universe."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", default="omi-ci-acceptance-v1")
    parser.add_argument(
        "--exclude-stock-id",
        action="append",
        default=[],
        help="Exclude a previously reviewed pilot or production symbol.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    if args.sample_size < 1 or args.sample_size > 100:
        parser.error("--sample-size must be between 1 and 100")

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
        result = select_ci_acceptance_sample(
            db,
            sample_size=args.sample_size,
            seed=args.seed,
            exclude_stock_ids=args.exclude_stock_id,
        )
        db.rollback()
        result["database"] = str(database_path)
        result["database_revision"] = current_revision
        result["query_only"] = query_only
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
