from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from time import perf_counter
import uuid


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.migrations import run_database_migrations  # noqa: E402


TAIPEI = timezone(timedelta(hours=8))
MINUTES_PER_SESSION = 271


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an isolated SQLite capacity proof for TW Base-1m retention.",
    )
    parser.add_argument("--sessions", type=int, default=72)
    parser.add_argument("--providers", type=int, default=3)
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _query_ms(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> tuple[float, int]:
    started = perf_counter()
    rows = connection.execute(sql, params).fetchall()
    return (perf_counter() - started) * 1000, len(rows)


def main() -> int:
    args = _arguments()
    if args.sessions < 1 or args.providers < 1:
        raise SystemExit("sessions and providers must be positive")

    capacity_root = ROOT / ".tmp" / "tw-unified-bar-capacity"
    capacity_root.mkdir(parents=True, exist_ok=True)
    owned_directory = capacity_root / uuid.uuid4().hex
    owned_directory.mkdir()
    database_path = owned_directory / "capacity.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    started = perf_counter()
    try:
        run_database_migrations(database_url)
        migration_seconds = perf_counter() - started

        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        now = _iso(datetime.now(timezone.utc))

        source_ids: list[int] = []
        for provider_index in range(args.providers):
            cursor = connection.execute(
                "INSERT INTO source_registry "
                "(source_name, source_type, category, endpoint_url, enabled, "
                "fetch_interval_minutes, priority, parser_type, auth_type, "
                "reliability_level, created_at, updated_at) "
                "VALUES (?, 'api', 'market', NULL, 1, 1, ?, 'json', 'none', "
                "'test', ?, ?)",
                (f"capacity-provider-{provider_index}", provider_index, now, now),
            )
            source_ids.append(int(cursor.lastrowid))

        raw_ids: dict[tuple[int, int], int] = {}
        for provider_index, source_id in enumerate(source_ids):
            for session_index in range(args.sessions):
                cursor = connection.execute(
                    "INSERT INTO raw_fetch_result "
                    "(source_id, fetched_at, url, method, status_code, content_type, "
                    "content_hash, raw_text, raw_file_path, parser_version, error_message) "
                    "VALUES (?, ?, NULL, 'GET', 200, 'application/json', ?, NULL, "
                    "NULL, 'capacity.v1', NULL)",
                    (
                        source_id,
                        now,
                        f"capacity-{provider_index}-{session_index}",
                    ),
                )
                raw_ids[(provider_index, session_index)] = int(cursor.lastrowid)
        connection.commit()

        first_date = date(2026, 5, 20)
        bar_rows: list[tuple[object, ...]] = []
        for provider_index, source_id in enumerate(source_ids):
            provider = f"capacity-provider-{provider_index}"
            for session_index in range(args.sessions):
                session_date = first_date + timedelta(days=session_index)
                session_start = datetime.combine(session_date, time(9, 0), TAIPEI)
                for minute_index in range(MINUTES_PER_SESSION):
                    bar_at = session_start + timedelta(minutes=minute_index)
                    price = 100 + provider_index + minute_index / 1000
                    bar_rows.append(
                        (
                            source_id,
                            provider,
                            "2330",
                            "TWSE",
                            "TW",
                            "TWSE",
                            "stock",
                            "2330",
                            "1m",
                            _iso(bar_at),
                            price,
                            price + 0.1,
                            price - 0.1,
                            price,
                            100,
                            10000,
                            provider,
                            now,
                            now,
                        )
                    )

        insert_started = perf_counter()
        connection.executemany(
            "INSERT INTO market_intraday_bar "
            "(source_id, provider, stock_id, market, canonical_market, venue, "
            "instrument_type, symbol, interval, bar_time, open_price, high_price, "
            "low_price, close_price, trade_volume, trade_value, source, source_url, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, NULL, ?, ?)",
            bar_rows,
        )
        connection.commit()
        bar_insert_seconds = perf_counter() - insert_started

        lineage_rows: list[tuple[object, ...]] = []
        candidates = connection.execute(
            "SELECT id, source_id, provider, bar_time FROM market_intraday_bar "
            "WHERE canonical_market='TW' ORDER BY id"
        ).fetchall()
        source_to_provider = {source_id: index for index, source_id in enumerate(source_ids)}
        for bar_id, source_id, provider, bar_time in candidates:
            session_index = (datetime.fromisoformat(bar_time).date() - first_date).days
            raw_result_id = raw_ids[(source_to_provider[source_id], session_index)]
            lineage_rows.append(
                (
                    bar_id,
                    source_id,
                    raw_result_id,
                    provider,
                    provider,
                    "vendor",
                    "capacity.raw.v1",
                    bar_time,
                    bar_time,
                    now,
                    "final",
                    "1m",
                    None,
                    None,
                    now,
                    now,
                )
            )
        lineage_started = perf_counter()
        connection.executemany(
            "INSERT INTO market_intraday_bar_lineage "
            "(bar_id, source_id, raw_result_id, provider, source, authority, "
            "raw_contract_version, event_at, received_at, fetched_at, finalization, "
            "source_interval, calculation_version, component_raw_result_ids_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            lineage_rows,
        )
        connection.commit()
        lineage_insert_seconds = perf_counter() - lineage_started

        latest_start = datetime.combine(
            first_date + timedelta(days=args.sessions - 1), time(9, 0), TAIPEI
        )
        query_sql = (
            "SELECT bar_time, open_price, high_price, low_price, close_price, "
            "trade_volume FROM market_intraday_bar WHERE source_id=? "
            "AND canonical_market='TW' AND stock_id='2330' AND interval='1m' "
            "AND bar_time>=? AND bar_time<? ORDER BY bar_time"
        )
        one_session_ms, one_session_rows = _query_ms(
            connection,
            query_sql,
            (
                source_ids[0],
                _iso(latest_start),
                _iso(latest_start + timedelta(days=1)),
            ),
        )
        range_31_ms, range_31_rows = _query_ms(
            connection,
            query_sql,
            (
                source_ids[0],
                _iso(latest_start - timedelta(days=31)),
                _iso(latest_start + timedelta(days=1)),
            ),
        )
        range_93_ms, range_93_rows = _query_ms(
            connection,
            query_sql,
            (
                source_ids[0],
                _iso(latest_start - timedelta(days=93)),
                _iso(latest_start + timedelta(days=1)),
            ),
        )

        prune_before = _iso(latest_start - timedelta(days=100))
        prune_select_ms, prune_candidate_rows = _query_ms(
            connection,
            "SELECT id FROM market_intraday_bar WHERE canonical_market='TW' "
            "AND bar_time<? ORDER BY id LIMIT 5000",
            (prune_before,),
        )
        connection.execute("BEGIN IMMEDIATE")
        prune_started = perf_counter()
        connection.execute(
            "DELETE FROM market_intraday_bar WHERE id IN "
            "(SELECT id FROM market_intraday_bar WHERE canonical_market='TW' "
            "AND bar_time<? ORDER BY id LIMIT 5000)",
            (prune_before,),
        )
        prune_delete_ms = (perf_counter() - prune_started) * 1000
        connection.rollback()

        writer = sqlite3.connect(database_path, timeout=2)
        reader = sqlite3.connect(database_path, timeout=2)
        writer.execute("PRAGMA journal_mode=WAL")
        reader.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        wal_read_started = perf_counter()
        wal_read_count = reader.execute(
            "SELECT COUNT(*) FROM market_intraday_bar WHERE canonical_market='TW'"
        ).fetchone()[0]
        wal_read_ms = (perf_counter() - wal_read_started) * 1000
        writer.rollback()
        writer.close()
        reader.close()

        total_rows = connection.execute(
            "SELECT COUNT(*) FROM market_intraday_bar WHERE canonical_market='TW'"
        ).fetchone()[0]
        lineage_count = connection.execute(
            "SELECT COUNT(*) FROM market_intraday_bar_lineage"
        ).fetchone()[0]
        connection.close()

        reopened = sqlite3.connect(database_path)
        restart_readback_count = reopened.execute(
            "SELECT COUNT(*) FROM market_intraday_bar WHERE canonical_market='TW'"
        ).fetchone()[0]
        journal_mode = reopened.execute("PRAGMA journal_mode").fetchone()[0]
        reopened.close()

        result = {
            "contract": "tw.canonical_1m.capacity_proof.v1",
            "isolated": True,
            "database_path": str(database_path) if args.keep_db else "ephemeral",
            "sessions": args.sessions,
            "providers": args.providers,
            "rows_per_provider": args.sessions * MINUTES_PER_SESSION,
            "candidate_rows": total_rows,
            "lineage_rows": lineage_count,
            "raw_receipts": len(raw_ids),
            "database_bytes": database_path.stat().st_size,
            "wal_bytes": Path(f"{database_path}-wal").stat().st_size
            if Path(f"{database_path}-wal").exists()
            else 0,
            "migration_seconds": round(migration_seconds, 3),
            "bar_insert_seconds": round(bar_insert_seconds, 3),
            "lineage_insert_seconds": round(lineage_insert_seconds, 3),
            "query": {
                "one_session": {"rows": one_session_rows, "ms": round(one_session_ms, 3)},
                "31_days": {"rows": range_31_rows, "ms": round(range_31_ms, 3)},
                "93_days": {"rows": range_93_rows, "ms": round(range_93_ms, 3)},
            },
            "pruning": {
                "candidate_rows": prune_candidate_rows,
                "candidate_query_ms": round(prune_select_ms, 3),
                "rollback_delete_ms": round(prune_delete_ms, 3),
                "enabled": False,
            },
            "wal": {
                "mode": journal_mode,
                "read_while_write_transaction_rows": wal_read_count,
                "read_while_write_transaction_ms": round(wal_read_ms, 3),
            },
            "restart_readback_rows": restart_readback_count,
            "passed": (
                total_rows == len(bar_rows)
                and lineage_count == len(bar_rows)
                and wal_read_count == total_rows
                and restart_readback_count == total_rows
            ),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    finally:
        if not args.keep_db:
            shutil.rmtree(owned_directory, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
