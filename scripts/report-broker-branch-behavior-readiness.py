from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.market.broker_branch_behavior import (  # noqa: E402
    BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS,
    BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
)
from app.market.broker_branch_calibration import (  # noqa: E402
    build_broker_branch_readiness_report,
    render_broker_branch_readiness_markdown,
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必須使用 YYYY-MM-DD。") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "唯讀檢查 materialized 分點行為 evidence；不呼叫 provider、不寫 DB。"
        )
    )
    parser.add_argument("--as-of", type=_iso_date)
    parser.add_argument(
        "--lookback-sessions",
        type=int,
        default=BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS,
    )
    parser.add_argument(
        "--methodology-version",
        default=BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    db = SessionLocal()
    try:
        report = build_broker_branch_readiness_report(
            db,
            as_of_trade_date=args.as_of,
            lookback_sessions=args.lookback_sessions,
            methodology_version=args.methodology_version,
        )
        if args.format == "markdown":
            print(render_broker_branch_readiness_markdown(report), end="")
        else:
            print(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2 if args.pretty else None,
                    separators=None if args.pretty else (",", ":"),
                )
            )
        return 0
    finally:
        # SELECTs may have opened a transaction. Roll it back explicitly so the
        # operator contract remains visibly read-only even if future code drifts.
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
