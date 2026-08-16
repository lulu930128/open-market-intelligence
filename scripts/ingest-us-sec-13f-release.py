from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import run_database_migrations  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.us_market.ownership_13f_service import ingest_13f_release  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest one downloaded official SEC Form 13F data-set release."
    )
    parser.add_argument("--period", required=True, help="Release partition key, for example 2026Q1.")
    parser.add_argument("--source-url", required=True, help="Official www.sec.gov ZIP URL.")
    parser.add_argument("--archive", required=True, type=Path, help="Local official ZIP archive.")
    parser.add_argument("--force", action="store_true", help="Rebuild an already completed release.")
    return parser


def main() -> int:
    args = _parser().parse_args()
    archive = args.archive.expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"SEC Form 13F archive was not found: {archive}")
    run_database_migrations()
    db = SessionLocal()
    try:
        result = ingest_13f_release(
            db,
            period_key=args.period,
            source_url=args.source_url,
            archive_path=archive,
            force=args.force,
            progress_callback=lambda current, total, message: print(
                json.dumps(
                    {"current": current, "total": total, "message": message},
                    ensure_ascii=False,
                ),
                flush=True,
            ),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
