"""Bounded, read-only source profiling; never starts the application/runtime."""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import socket
import sqlite3
import sys
from time import perf_counter
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--limits", type=int, nargs="+", default=[1, 20, 100])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.at.utcoffset() is None or not 1 <= args.runs <= 5 or any(not 1 <= n <= 100 for n in args.limits):
        parser.error("Use an aware --at, 1..5 runs and limits of 1..100")

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("profiling forbids network I/O")

    socket.create_connection = forbidden
    socket.socket.connect = forbidden
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from app.market.tw_workspace import build_tw_workspace_watchlist
    from app.market.tw_market_dashboard_schemas import TaiwanWorkspaceWatchlistRead

    deadline = float("inf")

    def connect():
        conn = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: int(perf_counter() >= deadline), 10_000)
        return conn

    engine = create_engine("sqlite://", creator=connect)
    queries = []

    @event.listens_for(engine, "before_cursor_execute")
    def before(_conn, _cursor, statement, parameters, context, _many):
        if not statement.lstrip().upper().startswith(("SELECT", "WITH", "PRAGMA", "BEGIN")):
            raise RuntimeError("profiling forbids SQL writes")
        context.profile_started = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after(_conn, _cursor, statement, parameters, context, _many):
        queries.append({"seconds": perf_counter() - context.profile_started, "sql": statement})

    results = []
    try:
        # One consistent SQLite read snapshot for all limits/runs in this process.
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("BEGIN")
            for limit in args.limits:
                for run in range(args.runs):
                    queries.clear()
                    profile = cProfile.Profile()
                    with Session(connection, autoflush=False) as db:
                        start = perf_counter()
                        deadline = start + 30
                        profile.enable()
                        result = build_tw_workspace_watchlist(db, watchlist_limit=limit, now=args.at)
                        built = perf_counter()
                        payload = TaiwanWorkspaceWatchlistRead.model_validate(result).model_dump_json()
                        end = perf_counter()
                        profile.disable()
                    stats = pstats.Stats(profile)
                    functions = []
                    for (filename, line, name), (primitive, calls, own, cumulative, _callers) in stats.stats.items():
                        if "app" in filename or cumulative > .02:
                            functions.append({"file": filename, "line": line, "function": name,
                                              "calls": calls, "self_seconds": own, "cumulative_seconds": cumulative})
                    sample = {"limit": limit, "run": run, "items": len(result["items"]),
                              "build_seconds": built-start, "serialization_seconds": end-built,
                              "total_seconds": end-start, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                              "queries": list(queries), "functions": sorted(functions, key=lambda f: -f["cumulative_seconds"])[:100]}
                    results.append(sample)
                    print(json.dumps({k: v for k, v in sample.items() if k not in {"queries", "functions"}}), flush=True)
    finally:
        engine.dispose()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"at": args.at.isoformat(), "results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
