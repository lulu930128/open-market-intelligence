"""One report attempt; no retry, scheduler startup, or configuration output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preopen", "intraday", "postclose"), default="postclose")
    parser.add_argument("--confirm-live-send", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_send:
        parser.error("--confirm-live-send is required")
    try:
        from app.dispatch.discord_market_report import run_discord_market_report
        from app.dispatch.discord_sender import DiscordDeliveryError
    except Exception:
        print(json.dumps({"status": "failed", "reason": "report initialization failed"}))
        return 1
    try:
        result = run_discord_market_report(args.phase)
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
