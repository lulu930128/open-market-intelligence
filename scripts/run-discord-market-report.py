"""One report attempt; no retry, scheduler startup, or configuration output."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preopen", "intraday", "postclose"), default="postclose")
    parser.add_argument("--mode", choices=("compact", "audit"), default="compact")
    parser.add_argument("--evidence-time-mode", choices=("live", "replay"), default="live")
    parser.add_argument("--confirm-live-send", action="store_true")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Prepare the fixed selection and print its receipt; never send Discord")
    parser.add_argument("--prepare-history", action="store_true",
                        help="Explicitly backfill selected daily history before the read-only report")
    parser.add_argument("--now", type=datetime.fromisoformat,
                        help="Timezone-aware report timestamp (required for a dated replay)")
    args = parser.parse_args()
    if not args.confirm_live_send and not args.prepare_only:
        parser.error("--confirm-live-send is required")
    if args.prepare_only and args.confirm_live_send:
        parser.error("--prepare-only cannot be combined with --confirm-live-send")
    if args.now is not None and args.now.tzinfo is None:
        parser.error("--now must include a timezone offset")
    try:
        from app.dispatch.discord_market_report import run_discord_market_report
        from app.dispatch.discord_sender import DiscordDeliveryError
    except Exception:
        print(json.dumps({"status": "failed", "reason": "report initialization failed"}))
        return 1
    try:
        kwargs = {"now": args.now} if args.now is not None else {}
        preparation = None
        if args.prepare_history or args.prepare_only:
            from app.db.session import SessionLocal
            from app.dispatch.discord_market_report import TAIPEI
            from app.jobs.market_report_history import prepare_discord_market_report_history
            local_now = args.now or datetime.now(TAIPEI)
            with SessionLocal() as db:
                preparation = prepare_discord_market_report_history(
                    db, args.phase, local_now, evidence_time_mode=args.evidence_time_mode)
            kwargs.update(now=local_now, selection=preparation.pop("selection"))
            print(json.dumps({"history_preparation": preparation}, ensure_ascii=False, default=str))
            if args.prepare_only:
                return 0 if preparation["status"] == "ready" else 2
        result = run_discord_market_report(
            args.phase, mode=args.mode, evidence_time_mode=args.evidence_time_mode, **kwargs)
    except DiscordDeliveryError as error:
        print(json.dumps({
            "status": error.outcome, "reason": error.reason,
            "sent_chunks": error.sent_chunks, "total_chunks": error.total_chunks,
            "status_code": error.status_code,
        }))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "reason": "report preparation failed"}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
