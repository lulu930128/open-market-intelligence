from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs import us_intraday_materializer_scheduler as us_scheduler
from app.us_market import service as us_market_service
from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    USQuoteSnapshot,
    USStockMaster,
)
from app.jobs.us_intraday_materializer_scheduler import (
    add_us_intraday_materializer_jobs,
    collect_us_active_intraday_bars,
    collect_us_active_quote_snapshots,
    collect_us_index_intraday_bars,
    collect_us_index_quote_snapshots,
    collect_us_intraday_bars,
    collect_us_quote_snapshots,
)
from app.us_market.active_equity_targets import (
    _clear_us_active_equity_viewers_for_tests,
    active_us_equity_viewer_symbols,
    claim_us_active_equity_viewer,
    release_us_active_equity_viewer,
)
from app.market_data.gateway import PostAcquisitionError
from app.market_data.integration_contracts import AcquisitionStatus, AcquisitionSummary
from app.us_market.intraday_maintenance import (
    _survivor_after_values,
    inspect_us_yahoo_intraday_minute_integrity,
    prune_expired_us_quote_snapshots,
    repair_us_yahoo_intraday_minute_integrity,
    rollback_us_yahoo_intraday_minute_repair,
)
from app.us_market.intraday_materializer import (
    US_BOOTSTRAP_MATERIALIZER_PROFILE,
    _materializer_lock_for,
    bootstrap_us_current_market,
    materialize_us_intraday_capability,
    resolve_us_materializer_universe,
    us_intraday_materializer_runtime_summary,
)
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.intraday_profiles import (
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM,
    US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS,
)
from app.us_market.market_data.descriptors import (
    YAHOO_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_RESOURCE_ID,
    YAHOO_QUOTE_DESCRIPTOR,
    YAHOO_QUOTE_RESOURCE_ID,
    TWELVE_INTRADAY_RESOURCE_ID,
    TWELVE_QUOTE_RESOURCE_ID,
)


class _FakeDb:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.closed = False

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, function, **kwargs) -> None:
        self.jobs.append({"function": function, **kwargs})


def _refresh_result(*, postcondition: bool = True):
    return SimpleNamespace(
        postcondition_satisfied=postcondition,
        postcondition_reasons=(
            () if postcondition else ("FRESHNESS_POSTCONDITION_UNSATISFIED",)
        ),
        result=SimpleNamespace(
            resolved=SimpleNamespace(
                health=SimpleNamespace(
                    status=SimpleNamespace(value="selected"),
                    selected_provider="yahoo_chart",
                    fallback_used=False,
                    facts_usable=postcondition,
                    limitations=("DELAYED_VENDOR_EVIDENCE",),
                )
            ),
        )
    )


def _yahoo_quote_payload(now: datetime, *, symbol: str = "AAPL") -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "currency": "USD",
                        "chartPreviousClose": 198.0,
                    },
                    "timestamp": [int(now.timestamp()) - 30],
                    "indicators": {
                        "quote": [
                            {
                                "open": [200.0],
                                "high": [201.0],
                                "low": [199.5],
                                "close": [200.5],
                                "volume": [1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _twelve_quote_payload(now: datetime, *, symbol: str) -> dict:
    return {
        "symbol": symbol,
        "timestamp": int(now.timestamp()) - 30,
        "close": "202.50",
        "open": "201.00",
        "high": "203.00",
        "low": "200.50",
        "previous_close": "200.00",
        "volume": "3500",
        "currency": "USD",
    }


def _twelve_bars_payload(now: datetime, *, symbol: str) -> dict:
    local = now.astimezone(timezone(timedelta(hours=-4))).replace(
        second=0,
        microsecond=0,
    )
    return {
        "meta": {
            "symbol": symbol,
            "currency": "USD",
            "exchange_timezone": "America/New_York",
        },
        "values": [
            {
                "datetime": (local - timedelta(minutes=1)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "open": "210.0",
                "high": "211.0",
                "low": "209.0",
                "close": "210.5",
                "volume": "2000",
            }
        ],
        "status": "ok",
    }


def test_us_materializer_universe_is_configuration_owned_and_hard_bounded() -> None:
    universe = resolve_us_materializer_universe(
        "aapl, TSM, AAPL, MSFT",
        max_symbols=2,
    )

    assert universe == {
        "contract_version": "omi.us.materializer.universe.v1",
        "owner": "configuration",
        "lane_id": "equity_research",
        "instrument_type": "stock",
        "configured_count": 3,
        "selected_count": 2,
        "skipped_count": 1,
        "rejected_count": 0,
        "symbols": ["AAPL", "TSM"],
        "is_bounded": True,
        "max_symbols": 2,
    }


def test_us_materializer_universe_preserves_explicit_dynamic_owner() -> None:
    universe = resolve_us_materializer_universe(
        "AAPL,TSM,MSFT",
        max_symbols=3,
        owner="configuration+portfolio+watchlist",
    )

    assert universe["owner"] == "configuration+portfolio+watchlist"
    assert universe["symbols"] == ["AAPL", "TSM", "MSFT"]


def test_active_equity_viewer_lease_switches_without_using_canary_quota() -> None:
    _clear_us_active_equity_viewers_for_tests()
    now = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
    try:
        first = claim_us_active_equity_viewer(
            symbol="MU",
            owner_id="test-panel",
            now=now,
        )
        assert active_us_equity_viewer_symbols(now=now) == ("MU",)

        second = claim_us_active_equity_viewer(
            symbol="NVDA",
            owner_id="test-panel",
            now=now + timedelta(seconds=30),
        )
        assert second["lease_id"] == first["lease_id"]
        assert active_us_equity_viewer_symbols(
            now=now + timedelta(seconds=30)
        ) == ("NVDA",)
        assert release_us_active_equity_viewer(owner_id="test-panel") is True
        assert active_us_equity_viewer_symbols(
            now=now + timedelta(seconds=31)
        ) == ()
    finally:
        _clear_us_active_equity_viewers_for_tests()


def test_us_materializer_skips_weekend_before_opening_database() -> None:
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return _FakeDb()

    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols="AAPL,TSM",
        now=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
        session_factory=session_factory,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "outside_us_intraday_acquisition_window"
    assert result["requested_count"] == 0
    assert opened is False


def test_us_materializer_is_partial_when_one_target_fails() -> None:
    db = _FakeDb()
    calls: list[tuple[str, int, bool]] = []

    class _Platform:
        def refresh_quote(
            self,
            *,
            symbol: str,
            max_provider_calls: int,
            require_live: bool,
            **_kwargs,
        ):
            calls.append((symbol, max_provider_calls, require_live))
            if symbol == "TSM":
                raise RuntimeError("fixture provider failure")
            return _refresh_result()

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL,TSM",
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert calls == [("AAPL", 2, False), ("TSM", 2, False)]
    assert result["status"] == "partial"
    assert result["requested_count"] == 2
    assert result["refreshed_count"] == 1
    assert result["failed_count"] == 1
    assert result["results"][1]["error_type"] == "RuntimeError"
    assert db.rollback_count == 1
    assert db.closed is True


def test_us_materializer_fails_visible_when_refresh_postcondition_is_unsatisfied() -> None:
    db = _FakeDb()

    class _Platform:
        def refresh_intraday_bars(self, **_kwargs):
            return _refresh_result(postcondition=False)

    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols="AAPL",
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["refreshed_count"] == 0
    assert result["status"] == "failed"
    assert result["results"][0]["reason"] == "refresh_postcondition_unsatisfied"


def test_recurring_intraday_profile_replaces_unbounded_five_thousand_bar_fetch() -> None:
    db = _FakeDb()
    requested_bars: list[int] = []

    class _Platform:
        def refresh_intraday_bars(self, *, bars: int, **_kwargs):
            requested_bars.append(bars)
            return _refresh_result()

    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols="AAPL",
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["status"] == "success"
    assert requested_bars == [600]


def test_intraday_materializer_preserves_truthful_read_model_until_publish() -> None:
    db = _FakeDb()
    key = (1, "TSM", "regular", "1m", "regular")
    us_market_service._set_us_intraday_cache(
        key,
        {
            "current_observation": {
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            "latest_bar_time": datetime.now(timezone.utc).isoformat(),
        },
    )

    class _Platform:
        def refresh_intraday_bars(self, **_kwargs):
            return _refresh_result()

    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols="TSM",
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["status"] == "success"
    assert us_market_service._get_us_intraday_cache(key) is not None


def test_real_platform_result_integrates_with_materializer_contract() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    with Session(engine) as seed_db:
        seed_db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                is_etf=False,
            )
        )
        seed_db.commit()

    def fetch(_route, _requirement):
        return _yahoo_quote_payload(now), "https://query.example.invalid/AAPL"

    def platform_factory(db):
        return USIntradayMarketPlatform(
            db,
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={
                    YAHOO_QUOTE_RESOURCE_ID: fetch,
                    YAHOO_INTRADAY_RESOURCE_ID: fetch,
                },
                clock=lambda: now,
            ),
            quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
            bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
        )

    quote = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL",
        max_provider_calls=1,
        now=now,
        session_factory=lambda: Session(engine),
        platform_factory=platform_factory,
    )
    intraday = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols="AAPL",
        max_provider_calls=1,
        now=now,
        session_factory=lambda: Session(engine),
        platform_factory=platform_factory,
    )

    for result in (quote, intraday):
        assert result["status"] == "success"
        assert result["results"][0]["postcondition_reasons"] == []
        assert result["external_call_count"] == 1
        assert result["observed_external_call_count"] == 1
    engine.dispose()


def test_pre_acquisition_exception_does_not_consume_external_call_budget() -> None:
    db = _FakeDb()
    calls: list[str] = []

    class _Platform:
        def refresh_quote(self, *, symbol: str, **_kwargs):
            calls.append(symbol)
            raise RuntimeError("identity unavailable before provider call")

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL,TSM",
        max_provider_calls=2,
        max_external_calls=2,
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert calls == ["AAPL", "TSM"]
    assert result["external_call_count"] == 0
    assert result["observed_external_call_count"] == 0
    assert all(
        item["reason"] == "pre_acquisition_exception"
        and item["external_calls"] == 0
        for item in result["results"]
    )


def test_post_acquisition_exception_preserves_known_external_calls() -> None:
    db = _FakeDb()
    calls: list[str] = []

    class _Platform:
        def refresh_quote(self, *, symbol: str, **_kwargs):
            calls.append(symbol)
            raise PostAcquisitionError(
                "persistence failed after provider call",
                acquisition=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.COMPLETED,
                    external_calls=1,
                ),
            )

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL,TSM",
        max_provider_calls=2,
        max_external_calls=2,
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert calls == ["AAPL", "TSM"]
    assert result["external_call_count"] == 2
    assert result["observed_external_call_count"] == 2
    assert all(
        item["reason"] == "post_acquisition_exception"
        and item["external_calls"] == 1
        for item in result["results"]
    )


def test_bootstrap_cannot_succeed_when_budget_skips_required_plans() -> None:
    db = _FakeDb()

    class _Platform:
        def read_quote(self, **_kwargs):
            raise LookupError("empty cache")

        def refresh_quote(self, **_kwargs):
            refreshed = _refresh_result()
            refreshed.result.acquisition = SimpleNamespace(external_calls=2)
            return refreshed

    result = bootstrap_us_current_market(
        equity_symbols="AAPL",
        index_symbols="^GSPC",
        max_external_calls=2,
        now=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["status"] == "partial"
    assert result["external_call_count"] == 2
    assert len(result["runs"]) == 1


def test_runtime_summary_retains_equity_and_index_quote_lanes() -> None:
    db = _FakeDb()

    class _Platform:
        def refresh_quote(self, **_kwargs):
            return _refresh_result()

    for lane_id, instrument_type, symbols in (
        ("equity_research", "stock", "AAPL"),
        ("index_current", "index", "^GSPC"),
    ):
        materialize_us_intraday_capability(
            "quote.snapshot",
            configured_symbols=symbols,
            lane_id=lane_id,
            instrument_type=instrument_type,
            now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
            session_factory=lambda: db,
            platform_factory=lambda _db: _Platform(),
        )

    summary = us_intraday_materializer_runtime_summary()

    assert set(summary["runs_by_lane"]) >= {"equity_research", "index_current"}
    assert summary["runs_by_lane"]["equity_research"]["quote.snapshot"][
        "lane_id"
    ] == "equity_research"
    assert summary["runs_by_lane"]["index_current"]["quote.snapshot"][
        "lane_id"
    ] == "index_current"


def test_us_materializer_rejects_duplicate_concurrent_run() -> None:
    run_lock = Lock()
    run_lock.acquire()
    try:
        result = materialize_us_intraday_capability(
            "quote.snapshot",
            configured_symbols="AAPL",
            now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
            run_lock=run_lock,
        )
    finally:
        run_lock.release()

    assert result["status"] == "skipped"
    assert result["reason"] == "materializer_run_in_flight"
    assert result["duration_ms"] >= 0


def test_default_materializer_lock_is_keyed_by_lane_and_capability() -> None:
    equity_quote_lock = _materializer_lock_for(
        "equity_research",
        "quote.snapshot",
    )
    equity_quote_lock.acquire()
    try:
        same_key = materialize_us_intraday_capability(
            "quote.snapshot",
            configured_symbols="AAPL",
            lane_id="equity_research",
            now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        )
        different_key = materialize_us_intraday_capability(
            "quote.snapshot",
            configured_symbols="",
            lane_id="index_current",
            instrument_type="index",
            now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        )
    finally:
        equity_quote_lock.release()

    assert same_key["reason"] == "materializer_run_in_flight"
    assert different_key["reason"] == "no_configured_symbols"


def test_cache_satisfaction_is_not_reported_as_provider_refresh() -> None:
    db = _FakeDb()

    class _Platform:
        def refresh_quote(self, **_kwargs):
            result = _refresh_result()
            result.result.acquisition = SimpleNamespace(
                attempted=False,
                external_calls=0,
            )
            result.result.persistence = SimpleNamespace(committed=False)
            return result

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL",
        now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["status"] == "success"
    assert result["succeeded_count"] == 1
    assert result["cache_satisfied_count"] == 1
    assert result["acquired_count"] == 0
    assert result["persisted_count"] == 0
    assert result["refreshed_count"] == 0


def test_runtime_summary_counts_repeated_lane_lock_contention() -> None:
    before = us_intraday_materializer_runtime_summary().get(
        "counters_by_lane",
        {},
    ).get("index_current", {}).get("quote.snapshot", {})
    before_runs = int(before.get("run_count") or 0)
    before_skips = int(before.get("materializer_run_in_flight_count") or 0)
    run_lock = Lock()
    run_lock.acquire()
    try:
        for _ in range(2):
            materialize_us_intraday_capability(
                "quote.snapshot",
                configured_symbols="^GSPC",
                lane_id="index_current",
                instrument_type="index",
                now=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
                run_lock=run_lock,
            )
    finally:
        run_lock.release()

    after = us_intraday_materializer_runtime_summary()["counters_by_lane"][
        "index_current"
    ]["quote.snapshot"]

    assert after["run_count"] - before_runs == 2
    assert after["skipped_count"] >= 2
    assert after["materializer_run_in_flight_count"] - before_skips == 2
    assert after["last_duration_ms"] >= 0


def test_quote_retention_deletes_only_rows_before_cutoff() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    try:
        source = SourceRegistry(
            source_name="fixture_us_quote",
            source_type="api",
            category="market_intraday_quote",
        )
        db.add(source)
        db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            method="GET",
            content_hash="fixture-hash",
            parser_version="fixture.v1",
            fetched_at=now,
        )
        db.add(raw)
        db.flush()
        common = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "provider": "fixture",
            "source": "fixture.quote",
            "symbol": "AAPL",
            "venue": "NASDAQ",
            "instrument_type": "stock",
            "received_at": now,
            "fetched_at": now,
            "observation_state": "observed",
            "trade_state": "traded",
            "authority": "vendor",
            "raw_contract_version": "fixture.v1",
            "raw_payload_hash": "fixture-hash",
        }
        db.add_all(
            [
                USQuoteSnapshot(event_at=now - timedelta(days=31), **common),
                USQuoteSnapshot(event_at=now - timedelta(days=30), **common),
                USQuoteSnapshot(event_at=now - timedelta(days=1), **common),
            ]
        )
        db.commit()

        result = prune_expired_us_quote_snapshots(db, now=now, retention_days=30)

        remaining = db.query(USQuoteSnapshot).order_by(USQuoteSnapshot.event_at).all()
        assert result["status"] == "complete"
        assert result["deleted_count"] == 1
        assert [row.event_at for row in remaining] == [
            (now - timedelta(days=30)).replace(tzinfo=None),
            (now - timedelta(days=1)).replace(tzinfo=None),
        ]
        assert db.query(RawFetchResult).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_us_intraday_minute_integrity_inspection_is_bounded_and_read_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    observed_at = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)
    try:
        source = SourceRegistry(
            source_name="yahoo.chart.1m",
            source_type="api",
            category="market_data",
        )
        db.add(source)
        db.flush()
        raw_results = []
        for offset in (20, 55):
            raw = RawFetchResult(
                source_id=source.id,
                method="GET",
                content_hash=(f"fixture-{offset}".ljust(64, "a"))[:64],
                parser_version="yahoo.chart.v8",
                fetched_at=observed_at + timedelta(seconds=offset),
            )
            db.add(raw)
            db.flush()
            raw_results.append(raw)

        bars = []
        for second in (15, 52, 0):
            bar = MarketIntradayBar(
                provider="yahoo_chart",
                stock_id="AAPL",
                market="NASDAQ",
                symbol="AAPL",
                interval="1m",
                bar_time=(
                    observed_at.replace(second=second)
                    if second
                    else observed_at + timedelta(minutes=1)
                ),
                open_price=200.0,
                high_price=201.0,
                low_price=199.0,
                close_price=200.5,
                trade_volume=100,
                source="yahoo.chart.1m",
            )
            db.add(bar)
            db.flush()
            bars.append(bar)
        for bar, raw in zip(bars[:2], raw_results, strict=True):
            db.add(
                MarketIntradayBarLineage(
                    bar_id=bar.id,
                    source_id=source.id,
                    raw_result_id=raw.id,
                    provider="yahoo_chart",
                    source="yahoo.chart.1m",
                    authority="vendor",
                    raw_contract_version="yahoo.chart.v8",
                    event_at=bar.bar_time,
                    received_at=raw.fetched_at,
                    fetched_at=raw.fetched_at,
                    finalization="final",
                    source_interval="1m",
                )
            )
        db.commit()
        before = [row.bar_time for row in db.query(MarketIntradayBar).all()]

        report = inspect_us_yahoo_intraday_minute_integrity(db, max_rows=10)

        assert report["dry_run"] is True
        assert report["status"] == "complete"
        assert report["inspected_row_count"] == 3
        assert report["non_minute_row_count"] == 2
        assert report["duplicate_minute_bucket_count"] == 1
        assert report["rows_in_duplicate_minute_buckets"] == 2
        assert report["missing_lineage_count"] == 1
        assert report["writes_performed"] == 0
        assert report["conflicts"][0]["recommended_survivor_id"] == bars[1].id
        assert [row.bar_time for row in db.query(MarketIntradayBar).all()] == before
    finally:
        db.close()
        engine.dispose()


def test_us_intraday_minute_repair_is_audited_and_reversible(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    canonical_minute = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)
    manifest_path = tmp_path / "us-minute-repair.json"
    try:
        source = SourceRegistry(
            source_name="yahoo.chart.1m",
            source_type="api",
            category="market_data",
        )
        db.add(source)
        db.flush()
        raws = []
        for index, fetched_at in enumerate(
            (
                canonical_minute + timedelta(seconds=20),
                canonical_minute + timedelta(hours=1),
            ),
            start=1,
        ):
            raw = RawFetchResult(
                source_id=source.id,
                method="GET",
                content_hash=(f"repair-{index}".ljust(64, "a"))[:64],
                parser_version="yahoo.chart.v8",
                fetched_at=fetched_at,
            )
            db.add(raw)
            db.flush()
            raws.append(raw)
        legacy = MarketIntradayBar(
            provider="yahoo_chart",
            stock_id="AAPL",
            market="NASDAQ",
            symbol="AAPL",
            interval="1m",
            bar_time=canonical_minute.replace(second=20),
            open_price=200.0,
            high_price=200.0,
            low_price=200.0,
            close_price=200.0,
            trade_volume=0,
            source="yahoo.chart.1m",
        )
        canonical = MarketIntradayBar(
            provider="yahoo_chart",
            stock_id="AAPL",
            market="NASDAQ",
            symbol="AAPL",
            interval="1m",
            bar_time=canonical_minute,
            open_price=199.0,
            high_price=202.0,
            low_price=198.0,
            close_price=201.0,
            trade_volume=1000,
            source="yahoo.chart.1m",
        )
        db.add_all((legacy, canonical))
        db.flush()
        for bar, raw in zip((legacy, canonical), raws, strict=True):
            db.add(
                MarketIntradayBarLineage(
                    bar_id=bar.id,
                    source_id=source.id,
                    raw_result_id=raw.id,
                    provider="yahoo_chart",
                    source="yahoo.chart.1m",
                    authority="vendor",
                    raw_contract_version="yahoo.chart.v8",
                    event_at=bar.bar_time,
                    received_at=raw.fetched_at,
                    fetched_at=raw.fetched_at,
                    finalization="final",
                    source_interval="1m",
                )
            )
        db.commit()
        original_times = {
            row.id: row.bar_time
            for row in db.query(MarketIntradayBar).order_by(MarketIntradayBar.id)
        }

        dry_run = repair_us_yahoo_intraday_minute_integrity(
            db,
            max_groups=1,
        )

        assert dry_run["dry_run"] is True
        assert dry_run["planned_group_count"] == 1
        assert dry_run["planned_delete_count"] == 1
        assert dry_run["groups"][0]["survivor_id"] == canonical.id
        assert dry_run["writes_performed"] == 0
        assert db.query(MarketIntradayBar).count() == 2

        row_bounded = repair_us_yahoo_intraday_minute_integrity(
            db,
            max_groups=1,
            max_candidate_rows=1,
        )
        assert row_bounded["planned_group_count"] == 0
        assert row_bounded["row_budget_exhausted"] is True
        assert row_bounded["has_more_groups"] is True
        assert row_bounded["writes_performed"] == 0
        assert db.query(MarketIntradayBar).count() == 2

        applied = repair_us_yahoo_intraday_minute_integrity(
            db,
            apply=True,
            max_groups=1,
            audit_manifest_path=manifest_path,
        )

        assert applied["status"] == "complete"
        assert applied["bar_rows_deleted"] == 1
        assert applied["lineage_rows_deleted"] == 1
        assert applied["bar_rows_updated"] == 1
        assert db.query(MarketIntradayBar).count() == 1
        remaining = db.query(MarketIntradayBar).one()
        assert remaining.id == canonical.id
        assert remaining.bar_time.second == 0
        assert remaining.high_price == 202.0
        assert manifest_path.is_file()

        rollback_dry_run = rollback_us_yahoo_intraday_minute_repair(
            db,
            audit_manifest_path=manifest_path,
        )
        assert rollback_dry_run["status"] == "ready"
        assert rollback_dry_run["writes_performed"] == 0

        rolled_back = rollback_us_yahoo_intraday_minute_repair(
            db,
            audit_manifest_path=manifest_path,
            apply=True,
        )
        assert rolled_back["status"] == "completed"
        assert db.query(MarketIntradayBar).count() == 2
        restored_times = {
            row.id: row.bar_time
            for row in db.query(MarketIntradayBar).order_by(MarketIntradayBar.id)
        }
        assert restored_times == original_times
    finally:
        db.close()
        engine.dispose()


def test_us_intraday_minute_repair_aggregates_provisional_ohlc() -> None:
    canonical_minute = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)
    candidates = []
    for row_id, second, price, volume in (
        (1, 5, 100.0, 0),
        (2, 30, 103.0, 4),
        (3, 55, 99.0, 2),
    ):
        candidates.append(
            (
                MarketIntradayBar(
                    id=row_id,
                    provider="yahoo_chart",
                    stock_id="AAPL",
                    market="NASDAQ",
                    symbol="AAPL",
                    interval="1m",
                    bar_time=canonical_minute.replace(second=second),
                    open_price=price,
                    high_price=price,
                    low_price=price,
                    close_price=price,
                    trade_volume=volume,
                    source="yahoo.chart.1m",
                ),
                None,
            )
        )

    policy, survivor_after = _survivor_after_values(
        candidates,
        canonical_minute=canonical_minute,
    )

    assert policy == "aggregate_provisional"
    assert survivor_after == {
        "bar_time": canonical_minute.isoformat(),
        "open_price": 100.0,
        "high_price": 103.0,
        "low_price": 99.0,
        "close_price": 99.0,
        "trade_volume": 4,
        "volume_status": "observed",
        "trade_value": None,
    }


def test_us_materializer_scheduler_registers_three_non_overlapping_owner_jobs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "enable_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_intraday_materializer", True)
    monkeypatch.setattr(settings, "enable_us_index_quote_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_quote_retention_scheduler", True)
    monkeypatch.setattr(settings, "enable_us_source_health_snapshot_scheduler", False)
    scheduler = _FakeScheduler()

    assert add_us_intraday_materializer_jobs(scheduler) is True
    assert [job["id"] for job in scheduler.jobs] == [
        "us_active_quote_snapshot_materialization",
        "us_quote_snapshot_materialization",
        "us_active_intraday_bar_materialization",
        "us_intraday_bar_materialization",
        "us_quote_snapshot_retention",
    ]
    assert all(job["max_instances"] == 1 for job in scheduler.jobs)
    assert all(job["coalesce"] is True for job in scheduler.jobs)
    assert scheduler.jobs[0]["seconds"] == 60
    assert scheduler.jobs[0]["seconds"] > 45
    assert scheduler.jobs[1]["seconds"] >= 60


def test_active_lane_uses_independent_symbols_and_quota(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _materialize(capability, **kwargs):
        captured["capability"] = capability
        captured.update(kwargs)
        return {
            "status": "success",
            "requested_count": 1,
            "refreshed_count": 1,
            "failed_count": 0,
            "external_call_count": 1,
            "duration_ms": 1,
            "reason": None,
        }

    _clear_us_active_equity_viewers_for_tests()
    now = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
    try:
        claim_us_active_equity_viewer(symbol="MU", owner_id="test-panel", now=now)
        monkeypatch.setattr(
            "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
            _materialize,
        )
        monkeypatch.setattr(
            settings,
            "scheduler_us_active_equity_materializer_max_symbols",
            2,
        )

        collect_us_active_intraday_bars(now=now)

        assert captured["configured_symbols"].split(",")[0] == "MU"
        assert captured["max_symbols"] == 2
        assert captured["lane_id"] == "equity_active"
        assert captured["universe_owner"].startswith("active_viewer")
        assert captured["run_lock"] is not None
    finally:
        _clear_us_active_equity_viewers_for_tests()


def test_canary_lane_defers_symbols_owned_by_active_viewer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _materialize(capability, **kwargs):
        captured["capability"] = capability
        captured.update(kwargs)
        return {
            "status": "success",
            "requested_count": 1,
            "refreshed_count": 1,
            "failed_count": 0,
            "external_call_count": 1,
            "duration_ms": 1,
            "reason": None,
        }

    _clear_us_active_equity_viewers_for_tests()
    now = datetime.now(timezone.utc)
    try:
        claim_us_active_equity_viewer(symbol="TSM", owner_id="test-panel", now=now)
        monkeypatch.setattr(
            "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
            _materialize,
        )
        monkeypatch.setattr(
            settings,
            "scheduler_us_intraday_materializer_symbols",
            "AAPL,TSM",
        )

        collect_us_intraday_bars(now=now)

        assert captured["configured_symbols"] == "AAPL"
        assert captured["universe_owner"] == "configuration_canary_minus_active_viewers"
    finally:
        _clear_us_active_equity_viewers_for_tests()


def test_active_intraday_lane_publishes_cache_only_read_model_after_run(
    monkeypatch,
) -> None:
    scheduled: list[str] = []

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        lambda *_args, **_kwargs: {
            "status": "success",
            "results": [{"symbol": "MU", "status": "success"}],
        },
    )
    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler._schedule_intraday_consumer_read_model",
        lambda symbol: scheduled.append(symbol) is None,
    )
    monkeypatch.setattr(
        settings,
        "enable_us_dynamic_equity_materializer_universe",
        False,
    )

    result = collect_us_active_intraday_bars(
        now=datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
    )

    assert scheduled == ["MU"]
    assert result["consumer_cache_publish_scheduled_count"] == 1
    assert result["consumer_cache_publish_deferred_symbols"] == []


def test_index_intraday_lane_publishes_cache_only_read_model_after_run(
    monkeypatch,
) -> None:
    scheduled: list[str] = []

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        lambda *_args, **_kwargs: {
            "status": "success",
            "results": [{"symbol": "^GSPC", "status": "success"}],
            "requested_count": 1,
            "refreshed_count": 1,
            "failed_count": 0,
            "external_call_count": 1,
            "duration_ms": 1,
            "reason": None,
        },
    )
    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler._schedule_intraday_consumer_read_model",
        lambda symbol: scheduled.append(symbol) is None,
    )
    monkeypatch.setattr(settings, "scheduler_us_index_quote_symbols", "^GSPC")
    monkeypatch.setattr(settings, "scheduler_us_index_quote_max_symbols", 1)
    monkeypatch.setattr(settings, "scheduler_us_index_intraday_batch_size", 1)
    with us_scheduler._INDEX_BATCH_STATE_LOCK:
        us_scheduler._INDEX_BATCH_OFFSETS["intraday.bars"] = 0

    result = collect_us_index_intraday_bars(
        now=datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
    )

    assert scheduled == ["^GSPC"]
    assert result["consumer_cache_publish_scheduled_count"] == 1
    assert result["consumer_cache_publish_deferred_symbols"] == []


def test_read_model_publishers_are_deduplicated_and_bounded(monkeypatch) -> None:
    started: list[tuple[str, tuple[str, ...]]] = []

    class _DeferredThread:
        def __init__(self, *, target, args, name, daemon):
            assert daemon is True
            started.append((name, args))

        def start(self) -> None:
            return None

    monkeypatch.setattr(us_scheduler, "Thread", _DeferredThread)
    with us_scheduler._READ_MODEL_PUBLISH_LOCK:
        us_scheduler._READ_MODEL_PUBLISH_IN_FLIGHT.clear()
    try:
        assert us_scheduler._schedule_intraday_consumer_read_model("TSM") is True
        assert us_scheduler._schedule_intraday_consumer_read_model("TSM") is False
        assert us_scheduler._schedule_intraday_consumer_read_model("MU") is True
        assert us_scheduler._schedule_intraday_consumer_read_model("^GSPC") is True
        assert us_scheduler._schedule_intraday_consumer_read_model("^SOX") is True
        assert us_scheduler._schedule_intraday_consumer_read_model("AAPL") is False
        assert started == [
            ("us-intraday-read-model-TSM", ("TSM",)),
            ("us-intraday-read-model-MU", ("MU",)),
            ("us-intraday-read-model-^GSPC", ("^GSPC",)),
            ("us-intraday-read-model-^SOX", ("^SOX",)),
        ]
    finally:
        with us_scheduler._READ_MODEL_PUBLISH_LOCK:
            us_scheduler._READ_MODEL_PUBLISH_IN_FLIGHT.clear()


def test_read_model_publisher_bypasses_old_projection_without_provider_io(
    monkeypatch,
) -> None:
    db = _FakeDb()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(us_scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.us_market.service.get_us_intraday_trend",
        lambda **kwargs: calls.append(kwargs),
    )
    with us_scheduler._READ_MODEL_PUBLISH_LOCK:
        us_scheduler._READ_MODEL_PUBLISH_IN_FLIGHT.add("TSM")

    us_scheduler._publish_intraday_consumer_read_model("TSM")

    assert calls == [
        {
            "symbol": "TSM",
            "session_scope": "regular",
            "interval": "1m",
            "db": db,
            "bypass_read_cache": True,
        }
    ]
    assert db.closed is True
    with us_scheduler._READ_MODEL_PUBLISH_LOCK:
        assert "TSM" not in us_scheduler._READ_MODEL_PUBLISH_IN_FLIGHT


def test_intraday_scheduler_reuses_complete_recurring_profile(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _materialize(capability, **kwargs):
        captured["capability"] = capability
        captured.update(kwargs)
        return {
            "status": "success",
            "requested_count": 0,
            "refreshed_count": 0,
            "failed_count": 0,
            "external_call_count": 0,
            "duration_ms": 0,
            "reason": None,
        }

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        _materialize,
    )
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_bars", 720)

    result = collect_us_intraday_bars()

    profile = captured["profile"]
    assert result["status"] == "success"
    assert captured["capability"] == "intraday.bars"
    assert profile.profile_id == "recurring_current"
    assert profile.intraday_bars == 720
    assert profile.acquisition_history_days == 1
    assert profile.producer_refresh_due_seconds == 45
    assert profile.consumer_stale_after_seconds == 180


def test_scheduler_serializes_within_owner_lane_not_across_owner_lanes(
    monkeypatch,
) -> None:
    locks: dict[str, list[object]] = {}

    def _materialize(capability, **kwargs):
        locks.setdefault(kwargs["lane_id"], []).append(kwargs["run_lock"])
        return {
            "status": "success",
            "requested_count": 0,
            "refreshed_count": 0,
            "failed_count": 0,
            "external_call_count": 0,
            "duration_ms": 0,
            "reason": None,
        }

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        _materialize,
    )

    collect_us_active_quote_snapshots()
    collect_us_quote_snapshots()
    collect_us_active_intraday_bars()
    collect_us_intraday_bars()
    collect_us_index_quote_snapshots()
    collect_us_index_intraday_bars()

    assert locks["equity_active"][0] is locks["equity_active"][1]
    assert locks["equity_canary"][0] is locks["equity_canary"][1]
    assert locks["index_current"][0] is locks["index_current"][1]
    assert locks["equity_active"][0] is not locks["equity_canary"][0]
    assert locks["equity_active"][0] is not locks["index_current"][0]
    assert locks["equity_canary"][0] is not locks["index_current"][0]


def test_index_scheduler_rotates_bounded_batches_across_full_universe(
    monkeypatch,
) -> None:
    batches: list[tuple[str, int, int]] = []

    def _materialize(_capability, **kwargs):
        batches.append(
            (
                kwargs["configured_symbols"],
                kwargs["max_symbols"],
                kwargs["max_external_calls"],
            )
        )
        return {
            "status": "success",
            "requested_count": kwargs["max_symbols"],
            "refreshed_count": kwargs["max_symbols"],
            "failed_count": 0,
            "external_call_count": kwargs["max_symbols"],
            "duration_ms": 1,
            "reason": None,
        }

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        _materialize,
    )
    monkeypatch.setattr(
        settings,
        "scheduler_us_index_quote_symbols",
        "^GSPC,^SOX,^DJI,^IXIC,^NDX,^VIX",
    )
    monkeypatch.setattr(settings, "scheduler_us_index_quote_max_symbols", 6)
    monkeypatch.setattr(settings, "scheduler_us_index_intraday_batch_size", 2)
    with us_scheduler._INDEX_BATCH_STATE_LOCK:
        us_scheduler._INDEX_BATCH_OFFSETS["intraday.bars"] = 0

    collect_us_index_intraday_bars()
    collect_us_index_intraday_bars()
    collect_us_index_intraday_bars()

    assert batches == [
        ("^GSPC,^SOX", 2, 4),
        ("^DJI,^IXIC", 2, 4),
        ("^NDX,^VIX", 2, 4),
    ]


def test_index_scheduler_does_not_advance_a_batch_skipped_by_lane_lock(
    monkeypatch,
) -> None:
    batches: list[str] = []

    def _materialize(_capability, **kwargs):
        batches.append(kwargs["configured_symbols"])
        skipped = len(batches) == 1
        return {
            "status": "skipped" if skipped else "success",
            "requested_count": 0 if skipped else kwargs["max_symbols"],
            "refreshed_count": 0 if skipped else kwargs["max_symbols"],
            "failed_count": 0,
            "external_call_count": 0 if skipped else kwargs["max_symbols"],
            "duration_ms": 1,
            "reason": "materializer_run_in_flight" if skipped else None,
        }

    monkeypatch.setattr(
        "app.jobs.us_intraday_materializer_scheduler.materialize_us_intraday_capability",
        _materialize,
    )
    monkeypatch.setattr(
        settings,
        "scheduler_us_index_quote_symbols",
        "^GSPC,^SOX,^DJI,^IXIC,^NDX,^VIX",
    )
    monkeypatch.setattr(settings, "scheduler_us_index_quote_max_symbols", 6)
    monkeypatch.setattr(settings, "scheduler_us_index_intraday_batch_size", 2)
    with us_scheduler._INDEX_BATCH_STATE_LOCK:
        us_scheduler._INDEX_BATCH_OFFSETS["intraday.bars"] = 0

    collect_us_index_intraday_bars()
    collect_us_index_intraday_bars()

    assert batches == ["^GSPC,^SOX", "^GSPC,^SOX"]


def test_quote_retention_registration_is_independent_of_materializer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_quote_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_quote_retention_scheduler", True)
    monkeypatch.setattr(settings, "enable_us_source_health_snapshot_scheduler", False)
    scheduler = _FakeScheduler()

    assert add_us_intraday_materializer_jobs(scheduler) is True
    assert [job["id"] for job in scheduler.jobs] == ["us_quote_snapshot_retention"]


def test_index_quote_lane_registers_without_equity_intraday_lane(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_quote_materializer", True)
    monkeypatch.setattr(settings, "enable_us_index_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_quote_retention_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_source_health_snapshot_scheduler", False)
    scheduler = _FakeScheduler()

    assert add_us_intraday_materializer_jobs(scheduler) is True
    assert [job["id"] for job in scheduler.jobs] == [
        "us_index_quote_snapshot_materialization"
    ]


def test_index_intraday_lane_registers_without_index_quote_lane(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_us_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_quote_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_intraday_materializer", True)
    monkeypatch.setattr(settings, "enable_us_quote_retention_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_source_health_snapshot_scheduler", False)
    scheduler = _FakeScheduler()

    assert add_us_intraday_materializer_jobs(scheduler) is True
    assert [job["id"] for job in scheduler.jobs] == [
        "us_index_intraday_bar_materialization"
    ]
    cycle_count = (
        settings.scheduler_us_index_quote_max_symbols
        + settings.scheduler_us_index_intraday_batch_size
        - 1
    ) // settings.scheduler_us_index_intraday_batch_size
    assert scheduler.jobs[0]["seconds"] == (
        settings.scheduler_us_index_intraday_materializer_interval_seconds
        // cycle_count
    )


def test_us_materializer_scheduler_noops_when_all_owned_flags_are_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(settings, "enable_us_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_quote_materializer", False)
    monkeypatch.setattr(settings, "enable_us_index_intraday_materializer", False)
    monkeypatch.setattr(settings, "enable_us_quote_retention_scheduler", False)
    monkeypatch.setattr(settings, "enable_us_source_health_snapshot_scheduler", False)
    scheduler = _FakeScheduler()

    assert add_us_intraday_materializer_jobs(scheduler) is False
    assert scheduler.jobs == []


def test_index_lane_accepts_only_configured_index_targets() -> None:
    universe = resolve_us_materializer_universe(
        "^GSPC,AAPL,^DJI",
        max_symbols=6,
        lane_id="index_current",
        instrument_type="index",
    )

    assert universe["symbols"] == ["^GSPC", "^DJI"]
    assert universe["rejected_count"] == 1
    assert universe["instrument_type"] == "index"


def test_bootstrap_is_explicit_bounded_and_noops_when_cache_is_satisfied() -> None:
    db = _FakeDb()

    class _Platform:
        def read_quote(self, **_kwargs):
            return _refresh_result()

        def read_intraday_bars(self, **_kwargs):
            return _refresh_result()

    result = bootstrap_us_current_market(
        equity_symbols="AAPL",
        index_symbols="^GSPC",
        max_external_calls=3,
        now=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
        session_factory=lambda: db,
        platform_factory=lambda _db: _Platform(),
    )

    assert result["status"] == "success"
    assert result["external_call_count"] == 0
    assert len(result["runs"]) == 4
    assert all(
        item["reason"] == "canonical_cache_already_satisfied"
        for run in result["runs"]
        for item in run["results"]
    )


def test_sunday_default_cold_bootstrap_completes_with_eighteen_call_budget() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    friday = datetime(2026, 8, 28, 19, 59, tzinfo=timezone.utc)
    sunday = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    with Session(engine) as seed_db:
        seed_db.add_all(
            [
                USStockMaster(
                    symbol="AAPL",
                    security_name="Apple Inc.",
                    exchange="NASDAQ",
                    asset_type="stock",
                    is_etf=False,
                ),
                USStockMaster(
                    symbol="TSM",
                    security_name="TSMC ADR",
                    exchange="NYSE",
                    asset_type="stock",
                    is_etf=False,
                ),
            ]
        )
        seed_db.commit()

    calls: list[tuple[str, str, str]] = []

    def yahoo(route, requirement):
        symbol = requirement.target.instrument.symbol
        capability = requirement.request.capability_id
        calls.append((capability, symbol, route.provider_key))
        return (
            _yahoo_quote_payload(friday, symbol=symbol),
            f"https://fixture.invalid/yahoo/{symbol}",
        )

    def twelve_quote(route, requirement):
        symbol = requirement.target.instrument.symbol
        calls.append((requirement.request.capability_id, symbol, route.provider_key))
        return (
            _twelve_quote_payload(friday, symbol=symbol),
            f"https://fixture.invalid/twelve-quote/{symbol}",
        )

    def twelve_bars(route, requirement):
        symbol = requirement.target.instrument.symbol
        calls.append((requirement.request.capability_id, symbol, route.provider_key))
        return (
            _twelve_bars_payload(friday, symbol=symbol),
            f"https://fixture.invalid/twelve-bars/{symbol}",
        )

    acquisition = USIntradayAcquisitionExecutor(
        fetchers={
            YAHOO_QUOTE_RESOURCE_ID: yahoo,
            YAHOO_INTRADAY_RESOURCE_ID: yahoo,
            TWELVE_QUOTE_RESOURCE_ID: twelve_quote,
            TWELVE_INTRADAY_RESOURCE_ID: twelve_bars,
        },
        clock=lambda: sunday,
    )
    result = bootstrap_us_current_market(
        equity_symbols="AAPL,TSM",
        index_symbols="^GSPC,^DJI,^IXIC,^SOX,^NDX,^VIX",
        max_external_calls=US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
        now=sunday,
        session_factory=lambda: Session(engine),
        platform_factory=lambda db: USIntradayMarketPlatform(
            db,
            acquisition=acquisition,
        ),
    )

    assert result["status"] == "success"
    assert result["external_call_count"] == 16
    assert result["remaining_external_calls"] == 2
    assert US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS == (
        US_CURRENT_MARKET_BOOTSTRAP_NORMAL_PATH_CALLS
        + US_CURRENT_MARKET_BOOTSTRAP_FALLBACK_HEADROOM
    )
    assert len(result["runs"]) == 4
    assert [run["external_call_count"] for run in result["runs"]] == [6, 6, 2, 2]
    assert all(run["status"] == "success" for run in result["runs"])
    assert all(
        (
            item["resolved_status"] == "selected"
            and "LATEST_AVAILABLE_STALE_ACCEPTED"
            not in item["postcondition_reasons"]
        )
        if run["capability"] == "quote.snapshot"
        else (
            item["resolved_status"] == "stale"
            and "LATEST_AVAILABLE_STALE_ACCEPTED"
            in item["postcondition_reasons"]
        )
        for run in result["runs"]
        for item in run["results"]
    )
    assert len(calls) == 16
    assert {provider for _capability, _symbol, provider in calls} == {
        "yahoo_chart"
    }
    engine.dispose()


def test_bootstrap_falls_back_after_first_provider_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    friday = datetime(2026, 8, 28, 19, 59, tzinfo=timezone.utc)
    sunday = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    with Session(engine) as seed_db:
        seed_db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                is_etf=False,
            )
        )
        seed_db.commit()
    calls: list[str] = []

    def yahoo(route, _requirement):
        calls.append(route.provider_key)
        raise RuntimeError("Yahoo unavailable")

    def twelve(route, requirement):
        calls.append(route.provider_key)
        symbol = requirement.target.instrument.symbol
        return (
            _twelve_quote_payload(friday, symbol=symbol),
            f"https://fixture.invalid/twelve/{symbol}",
        )

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL",
        max_provider_calls=2,
        max_external_calls=2,
        profile=US_BOOTSTRAP_MATERIALIZER_PROFILE,
        now=sunday,
        session_factory=lambda: Session(engine),
        platform_factory=lambda db: USIntradayMarketPlatform(
            db,
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={
                    YAHOO_QUOTE_RESOURCE_ID: yahoo,
                    TWELVE_QUOTE_RESOURCE_ID: twelve,
                },
                clock=lambda: sunday,
            ),
        ),
    )

    assert calls == ["yahoo_chart", "twelve_data"]
    assert result["status"] == "success"
    assert result["external_call_count"] == 2
    assert result["results"][0]["selected_provider"] == "twelve_data"
    assert result["results"][0]["resolved_status"] == "fallback"
    assert result["results"][0]["fallback_used"] is True
    assert "LATEST_AVAILABLE_STALE_ACCEPTED" not in result["results"][0][
        "postcondition_reasons"
    ]
    engine.dispose()


def test_bootstrap_fails_visible_when_all_providers_are_unusable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sunday = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    with Session(engine) as seed_db:
        seed_db.add(
            USStockMaster(
                symbol="AAPL",
                security_name="Apple Inc.",
                exchange="NASDAQ",
                asset_type="stock",
                is_etf=False,
            )
        )
        seed_db.commit()
    calls: list[str] = []

    def unavailable(route, _requirement):
        calls.append(route.provider_key)
        raise RuntimeError(f"{route.provider_key} unavailable")

    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols="AAPL",
        max_provider_calls=2,
        max_external_calls=2,
        profile=US_BOOTSTRAP_MATERIALIZER_PROFILE,
        now=sunday,
        session_factory=lambda: Session(engine),
        platform_factory=lambda db: USIntradayMarketPlatform(
            db,
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={
                    YAHOO_QUOTE_RESOURCE_ID: unavailable,
                    TWELVE_QUOTE_RESOURCE_ID: unavailable,
                },
                clock=lambda: sunday,
            ),
        ),
    )

    assert calls == ["yahoo_chart", "twelve_data"]
    assert result["status"] == "failed"
    assert result["external_call_count"] == 2
    assert result["results"][0]["reason"] == "refresh_postcondition_unsatisfied"
    assert result["results"][0]["facts_usable"] is False
    assert result["results"][0]["limitations"]
    engine.dispose()
