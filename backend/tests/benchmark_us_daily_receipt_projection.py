"""Offline G3 before/after evidence, using actual repository SQL and consumers.

Run from repo root with PYTHONPATH=backend. JSON goes to stdout.
No latency assertions: fixture timings are not production SLOs.
"""

from g3_offline_guard import install

install()

import argparse
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter
import tracemalloc
from unittest.mock import patch

from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from app.db.models import Base, RawFetchResult
from app.market_data import gateway
from app.us_market import daily_ohlcv_platform, daily_price_repository, market_truth
from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
from app.us_market.research_service import build_us_market_research
from us_daily_receipt_fixture import NOW, RECEIPT_CHARS, seed_daily_receipts


def encode(value):
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":")).encode()


def summarize(values):
    return {"n": len(values), "p50_ms": median(values),
            "p95_ms": sorted(values)[ceil(len(values) * .95) - 1]}


def measured(engine, operation):
    spans = Counter()
    calls = Counter()
    statements = []

    def capture(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append((sql, params))

    def timed(owner, name, label, stack):
        original = getattr(owner, name)

        def wrapper(*args, **kwargs):
            start = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                spans[label] += (perf_counter() - start) * 1000
                calls[label] += 1

        stack.enter_context(patch.object(owner, name, wrapper))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with ExitStack() as stack, Session(engine) as db:
            timed(daily_price_repository, "_load_bounded_candidate_rows", "daily_query_fetch_orm", stack)
            timed(daily_price_repository.USDailyBarRepository, "load_daily_bars", "daily_repository_inclusive", stack)
            timed(gateway.MarketDataGateway, "resolve_bars", "gateway_bars_inclusive", stack)
            timed(daily_ohlcv_platform, "project_resolved_us_daily_bars", "daily_projection", stack)
            timed(market_truth, "_read_components", "truth_components_inclusive", stack)
            timed(market_truth, "_compose_us_market_truth_snapshot", "truth_projection", stack)
            start = perf_counter()
            result = operation(db)
            read_ms = (perf_counter() - start) * 1000
            start = perf_counter()
            payload = encode(result)
            serialization_ms = (perf_counter() - start) * 1000
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return {"read_ms": read_ms, "serialization_ms": serialization_ms,
            "spans_ms": dict(spans), "calls": dict(calls),
            "selects": len(statements), "payload_bytes": len(payload),
            "payload_sha256": sha256(payload).hexdigest()}, statements


def sql_and_orm_bytes(engine, operation, statements):
    # Replay exact captured SELECTs outside timed samples. Sum UTF-8 values;
    # this is a result-value estimate, not SQLite disk IO or network bytes.
    rows = total_bytes = raw_bytes = 0
    with engine.connect() as conn:
        for sql, params in statements:
            result = conn.exec_driver_sql(sql, params)
            keys = list(result.keys())
            for row in result:
                rows += 1
                for key, value in zip(keys, row):
                    size = 0 if value is None else len(str(value).encode())
                    total_bytes += size
                    if key == "raw_fetch_result_raw_text":
                        raw_bytes += size
    loads = Counter()
    retained_text = 0

    def loaded(db, obj):
        nonlocal retained_text
        loads[type(obj).__name__] += 1
        if isinstance(obj, RawFetchResult):
            retained_text += len(inspect(obj).dict.get("raw_text", "").encode())

    with Session(engine) as db:
        event.listen(db, "loaded_as_persistent", loaded)
        tracemalloc.start()
        operation(db)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return {"sql_returned_rows_including_fairness_probe": rows,
            "sql_result_value_utf8_bytes": total_bytes, "sql_raw_text_utf8_bytes": raw_bytes,
            "orm_load_events": dict(loads), "orm_raw_text_bytes_at_load": retained_text,
            "tracemalloc_peak_bytes_separate_run": peak}


def run(samples):
    report = {"scope": "SYNTHETIC SQLite only; no runtime/provider/browser acceptance",
              "receipt_chars": RECEIPT_CHARS, "days": 180, "providers": 2,
              "cold_definition": "fresh connection/session, cleared compiled cache; OS cache uncontrolled",
              "warm_definition": "same engine/connection pool, fresh Session each sample",
              "stage_note": "inclusive spans overlap; Query includes execute/fetch/ORM; resolver span below excludes repository",
              "source_sha256": sha256(Path(daily_price_repository.__file__).read_bytes()).hexdigest(),
              "cases": {}}
    fixture_root = Path(".tmp/g3-receipt-benchmark")
    fixture_root.mkdir(parents=True, exist_ok=True)
    for shared in (True, False):
        with tempfile.TemporaryDirectory(dir=fixture_root) as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'fixture.db'}")
            try:
                Base.metadata.create_all(engine)
                with Session(engine) as db:
                    query = seed_daily_receipts(db, shared=shared)
                operation = lambda db: daily_price_repository.USDailyBarRepository(db).load_daily_bars(query)
                cold, warm = [], []
                hashes = set()
                for index in range(samples):
                    engine.dispose()
                    engine.clear_compiled_cache()
                    sample, statements = measured(engine, operation)
                    cold.append(sample)
                    hashes.add(sample["payload_sha256"])
                    sample, statements = measured(engine, operation)
                    warm.append(sample)
                    hashes.add(sample["payload_sha256"])
                assert len(hashes) == 1
                case = {"cold": summarize([s["read_ms"] for s in cold]),
                        "warm": summarize([s["read_ms"] for s in warm]),
                        "cold_samples": cold, "warm_samples": warm,
                        **sql_and_orm_bytes(engine, operation, statements)}
                report["cases"]["shared_receipt" if shared else "receipt_per_day"] = case
                if shared:
                    consumers = {
                        "daily180": lambda db: daily_ohlcv_platform.USDailyOhlcvPlatform(db).read(symbol="AAPL", bars=180, now=NOW).projection,
                        "truth": lambda db: market_truth.read_us_market_truth_snapshot(db, symbol="AAPL", evaluated_at=NOW),
                        "intraday_bundle": lambda db: market_truth.read_us_market_truth_bundle(db, symbol="AAPL", evaluated_at=NOW, include_session_summary=True),
                        "chart180_overlay": lambda db: read_us_daily_ohlcv_chart(db, symbol="AAPL", bars=180, now=NOW, include_intraday_overlay=True),
                        "research260": lambda db: build_us_market_research(db, symbol="AAPL", bars=260, now=NOW),
                    }
                    report["consumers"] = {}
                    for name, consumer in consumers.items():
                        measured(engine, consumer)  # explicit warmup
                        observations = [measured(engine, consumer)[0] for _ in range(samples)]
                        spans = observations[-1]["spans_ms"]
                        observations[-1]["gateway_excluding_daily_repository_ms"] = spans.get("gateway_bars_inclusive", 0) - spans.get("daily_repository_inclusive", 0)
                        report["consumers"][name] = {
                            "read": summarize([s["read_ms"] for s in observations]),
                            "serialization": summarize([s["serialization_ms"] for s in observations]),
                            "samples": observations,
                        }
            finally:
                engine.dispose()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("at least two samples required")
    print(json.dumps(run(args.samples), indent=2))
