from __future__ import annotations

import argparse
from datetime import datetime
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
from app.market.financial_ci_fast_lane import (  # noqa: E402
    build_ci_fast_lane_package,
)


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid ISO-8601 datetime: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone offset")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic clone-only M8 fast-lane evidence packages from "
            "approved parser v4 facts. The database remains query-only."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--stock-id", action="append", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", type=_datetime, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Existing directory for package JSON files; omitted means audit-only.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Report ineligible symbols instead of stopping at the first one.",
    )
    args = parser.parse_args()

    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        parser.error(f"database does not exist: {database_path}")
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
    if output_dir is not None and not output_dir.is_dir():
        parser.error(f"output directory does not exist: {output_dir}")

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
    results: list[dict[str, object]] = []
    try:
        db.execute(text("PRAGMA query_only = ON"))
        for stock_id in dict.fromkeys(args.stock_id):
            try:
                package, audit = build_ci_fast_lane_package(
                    db,
                    stock_id=stock_id,
                    reviewer=args.reviewer,
                    reviewed_at=args.reviewed_at,
                )
                output_path = None
                if output_dir is not None:
                    output_path = output_dir / f"{stock_id}-ci-fast-lane-v1-clone.json"
                    if output_path.exists():
                        raise ValueError(f"refusing to overwrite {output_path}")
                    output_path.write_text(
                        json.dumps(
                            package.model_dump(mode="json"),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                audit["output"] = str(output_path) if output_path else None
                results.append(audit)
            except Exception as exc:
                failure = {
                    "stock_id": stock_id,
                    "status": "ineligible",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                results.append(failure)
                if not args.continue_on_error:
                    raise
        db.rollback()
        payload = {
            "database": str(database_path),
            "database_revision": current_revision,
            "mode": "query_only_build" if output_dir else "query_only_audit",
            "eligible_count": sum(item["status"] == "eligible" for item in results),
            "ineligible_count": sum(
                item["status"] == "ineligible" for item in results
            ),
            "results": results,
        }
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
