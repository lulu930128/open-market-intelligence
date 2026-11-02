"""Bounded OMI scheduler work; no KGI lifecycle and no automatic Entry consent."""
from datetime import datetime, timezone
import logging

from sqlalchemy.exc import OperationalError

from app.research.candidate_service import CandidateService


logger = logging.getLogger(__name__)
_cursor = ""
_status = {"state": "NOT_STARTED", "last_cycle": None}


def monitor_status():
    return dict(_status)


def run_cycle(session_factory=None, service_factory=CandidateService, *, limit=50):
    global _cursor, _status
    if session_factory is None:
        from app.db.session import SessionLocal
        session_factory = SessionLocal
    summary = {"state": "RUNNING", "last_cycle": datetime.now(timezone.utc).isoformat(),
               "observed": 0, "created": 0, "errors": 0}
    try:
        with session_factory() as db:
            rows = service_factory(db).list(after=_cursor, limit=limit)
        _cursor = rows[-1]["id"] if len(rows) == limit else ""
        for row in rows:
            try:
                with session_factory() as db:
                    service_factory(db).drain_invalidations(row["id"])
                with session_factory() as db:
                    result = service_factory(db).observe(row["id"])
                summary["observed"] += 1
                summary["created"] += int(result.get("created", False))
                pending = result.get("pending")
                if pending and pending["state"] in {"PENDING_APPROVAL", "PREPARING"}:
                    with session_factory() as db:
                        service_factory(db).prepare(pending["id"])
            except (ValueError, LookupError):
                summary["errors"] += 1
    except OperationalError:
        summary["state"] = "SCHEMA_OR_DATABASE_UNAVAILABLE"
    except Exception as exc:
        summary["state"] = "ERROR"
        summary["error_type"] = type(exc).__name__
        logger.error("Candidate monitor failed: %s", type(exc).__name__)
    _status = summary
    return dict(summary)


def add_candidate_monitor_job(scheduler):
    scheduler.add_job(run_cycle, trigger="interval", seconds=15, id="conditional_candidate_monitor",
                      replace_existing=True, coalesce=True, max_instances=1)


def main():
    import argparse
    import json
    from threading import Event
    parser = argparse.ArgumentParser(description="OMI cache-only Candidate Monitor; never confirms Entry")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    stop = Event()
    try:
        while True:
            print(json.dumps(run_cycle()), flush=True)
            if args.once or stop.wait(15):
                return
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
