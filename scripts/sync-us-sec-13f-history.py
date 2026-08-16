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
from app.us_market.ownership_13f_service import sync_13f_history  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize a bounded set of official SEC Form 13F history releases."
    )
    parser.add_argument("--max-releases", type=int, default=4)
    parser.add_argument("--cached-manifest", action="store_true")
    parser.add_argument("--include-completed", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--skip-projections", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    run_database_migrations()
    db = SessionLocal()
    try:
        result = sync_13f_history(
            db,
            max_releases=args.max_releases,
            refresh_manifest=not args.cached_manifest,
            include_completed=args.include_completed,
            force_download=args.force_download,
            force_rebuild=args.force_rebuild,
            stop_on_error=args.stop_on_error,
            rebuild_projections=not args.skip_projections,
            progress_callback=lambda current, total, message: print(
                json.dumps(
                    {"current": current, "total": total, "message": message},
                    ensure_ascii=False,
                ),
                flush=True,
            ),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if result["failed_count"] == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
