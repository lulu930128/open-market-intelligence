from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    StockMaster,
)
from app.market import intraday
from app.market.schemas import IntradayTrendRead, MarketIntradayChartRead
from app.market.providers.tw_intraday_bars import (
    IntradayProviderPayload,
    NStockIntradayAdapter,
    YahooIntradayAdapter,
)
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_capabilities import (
    NSTOCK_INTRADAY_DESCRIPTOR,
    TW_INTRADAY_DESCRIPTORS,
    YAHOO_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_PARSER_VERSION,
)
from app.market.tw_intraday_platform import (
    bootstrap_taiwan_intraday_bars,
    build_taiwan_intraday_requirement,
    project_taiwan_intraday_bars,
    read_taiwan_intraday_bars,
    refresh_taiwan_intraday_bars,
)
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.market_data.contracts import (
    DatasetHealthStatus,
    InstrumentKey,
    InstrumentType,
    Market,
    ResolvedEvidenceStatus,
)


TAIPEI = timezone(timedelta(hours=8))


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="3711",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def test_one_day_window_uses_canonical_presentation_session_before_rollover() -> None:
    requested_at = datetime(2026, 8, 28, 0, 53, tzinfo=TAIPEI)

    requirement = build_taiwan_intraday_requirement(
        instrument=_instrument(),
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=requested_at,
        acquiring=False,
    )

    assert requirement.request.start_at == datetime(
        2026, 8, 27, 0, 0, tzinfo=TAIPEI
    )
    assert requirement.request.end_at == requested_at


def test_one_day_window_rolls_to_current_trade_date_at_presentation_boundary() -> None:
    requested_at = datetime(2026, 8, 28, 8, 0, tzinfo=TAIPEI)

    requirement = build_taiwan_intraday_requirement(
        instrument=_instrument(),
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=requested_at,
        acquiring=False,
    )

    assert requirement.request.start_at == datetime(
        2026, 8, 28, 0, 0, tzinfo=TAIPEI
    )
    assert requirement.request.end_at == requested_at


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()
    return db, engine


def _nstock_payload() -> str:
    return json.dumps(
        {
            "data": [
                {
                    "參考價": "1170",
                    "總成交量": "3",
                    "分K": [
                        {
                            "交易日": "20260826",
                            "交易時間": "100000",
                            "開盤價": "1170",
                            "最高價": "1180",
                            "最低價": "1168",
                            "收盤價": "1178",
                            "成交量": "1",
                        },
                        {
                            "交易日": "20260826",
                            "交易時間": "100100",
                            "開盤價": "1178",
                            "最高價": "1182",
                            "最低價": "1176",
                            "收盤價": "1180",
                            "成交量": "1",
                        },
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )


def _yahoo_payload(now: datetime, *, seconds_offset: int = 0) -> str:
    current_minute = now.replace(second=seconds_offset, microsecond=0)
    timestamps = [
        int((current_minute - timedelta(minutes=1)).timestamp()),
        int(current_minute.timestamp()),
    ]
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"gmtoffset": 28800},
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [1160, 1165],
                                    "high": [1170, 1175],
                                    "low": [1158, 1163],
                                    "close": [1168, 1172],
                                    "volume": [1000, 2000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    )


def test_yahoo_seconds_offset_is_normalized_to_minute_grid_with_raw_lineage() -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    requirement = build_taiwan_intraday_requirement(
        instrument=_instrument(),
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=now,
        acquiring=True,
    )
    adapter = YahooIntradayAdapter(
        lambda *_args: IntradayProviderPayload(
            raw_text=_yahoo_payload(now, seconds_offset=10),
            status="available",
            url="https://example.test/yahoo",
            status_code=200,
            content_type="application/json",
        ),
        clock=lambda: now,
    )
    plan = plan_data_acquisition_v2(requirement, (YAHOO_INTRADAY_DESCRIPTOR,))

    acquired = adapter.acquire_route(requirement, plan.routes[0])

    assert acquired.observations, acquired.receipts[0].error_message
    assert all(
        bar.start_at.second == 0 and bar.start_at.microsecond == 0
        for bar in acquired.observations
    )
    assert all(
        bar.end_at - bar.start_at == timedelta(minutes=1)
        for bar in acquired.observations
    )
    assert acquired.observations[0].lineage.event_at is not None
    assert acquired.observations[0].lineage.event_at.second == 10
    assert (
        acquired.observations[0].lineage.raw_contract_version
        == YAHOO_INTRADAY_PARSER_VERSION
    )


def _executor(
    now: datetime,
    *,
    nstock_status: str = "available",
) -> tuple[TaiwanIntradayAcquisitionExecutor, list[str]]:
    calls: list[str] = []

    def read_nstock(_symbol: str, _timeout: int) -> IntradayProviderPayload:
        calls.append("nstock")
        if nstock_status != "available":
            return IntradayProviderPayload(
                raw_text=None,
                status="failed",
                url="https://example.test/nstock",
                error="nstock unavailable",
            )
        return IntradayProviderPayload(
            raw_text=_nstock_payload(),
            status="available",
            url="https://example.test/nstock",
            status_code=200,
            content_type="application/json",
        )

    def read_yahoo(
        _symbol: str,
        _venue: str | None,
        _range: str,
        _interval: str,
        _timeout: int,
    ) -> IntradayProviderPayload:
        calls.append("yahoo_finance_chart")
        return IntradayProviderPayload(
            raw_text=_yahoo_payload(now),
            status="available",
            url="https://example.test/yahoo",
            status_code=200,
            content_type="application/json",
        )

    return (
        TaiwanIntradayAcquisitionExecutor(
            nstock=NStockIntradayAdapter(read_nstock, clock=lambda: now),
            yahoo=YahooIntradayAdapter(read_yahoo, clock=lambda: now),
            clock=lambda: now,
        ),
        calls,
    )


def test_nstock_refresh_persists_actual_provider_lineage_then_rereads() -> None:
    now = datetime(2026, 8, 26, 10, 1, tzinfo=TAIPEI)
    executor, calls = _executor(now)
    db, engine = _db()
    try:
        result = refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
            acquisition=executor,
        )

        assert calls == ["nstock"]
        assert result.persistence.committed is True
        assert result.resolved.bars
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
        assert result.resolved.health.fallback_used is False
        assert result.resolved.bars[-1].lineage.provider == "nstock"
        assert [int(bar.volume.value) for bar in result.resolved.bars] == [1000, 1000]
        assert [bar.finalization.value for bar in result.resolved.bars] == [
            "final",
            "provisional",
        ]
        assert (
            "PROVIDER_SESSION_TOTAL_VOLUME_NOT_ALLOCATED_TO_BARS"
            in result.acquisition.limitations
        )
        assert db.query(MarketIntradayBar).count() == 2
        assert {row.provider for row in db.query(MarketIntradayBar).all()} == {"nstock"}
        assert db.query(MarketIntradayBarLineage).count() == 2
        assert db.query(RawFetchResult).count() == 1
        assert all(
            bar.lineage.raw_receipt_id is not None
            for bar in result.resolved.bars
        )
    finally:
        db.close()
        engine.dispose()


def test_stale_primary_observations_do_not_stop_the_gateway_route_gate() -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    executor, calls = _executor(now)
    db, engine = _db()
    try:
        result = refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
            acquisition=executor,
        )

        assert calls == ["nstock", "yahoo_finance_chart"]
        assert result.acquisition.external_calls == 2
        assert result.persistence.receipts_written == 2
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.STALE
        assert result.resolved.health.status is ResolvedEvidenceStatus.STALE
        assert result.resolved.health.fallback_used is False
        assert any(
            item.startswith("ROUTE_REQUIREMENT_UNSATISFIED:nstock:")
            for item in result.acquisition.limitations
        )
        assert db.query(RawFetchResult).count() == 2
        assert {row.provider for row in db.query(MarketIntradayBar).all()} == {
            "nstock",
            "yahoo_finance_chart",
        }
    finally:
        db.close()
        engine.dispose()


def test_explicit_intraday_bootstrap_is_bounded_and_idempotent() -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    executor, _calls = _executor(now)
    db, engine = _db()

    def refresher(session, **kwargs):
        return refresh_taiwan_intraday_bars(
            session,
            **kwargs,
            acquisition=executor,
        )

    try:
        first = bootstrap_taiwan_intraday_bars(
            db,
            symbols=["2330"],
            max_symbols=1,
            requested_at=now,
            refresher=refresher,
        )
        second = bootstrap_taiwan_intraday_bars(
            db,
            symbols=["2330"],
            max_symbols=1,
            requested_at=now,
            refresher=refresher,
        )

        assert first.status == "success"
        assert first.planned_symbols == ("2330",)
        assert first.receipts_written == first.per_symbol[0].receipts_written == 1
        assert first.bars_written > 0
        assert second.bars_written == 0
        assert second.bars_unchanged > 0
        assert db.query(MarketIntradayBar).filter_by(interval="5m").count() == 0
    finally:
        db.close()
        engine.dispose()


def test_nstock_trailing_window_projects_incomplete_session_coverage() -> None:
    now = datetime(2026, 8, 26, 14, 0, tzinfo=TAIPEI)
    payload = json.dumps(
        {
            "data": [
                {
                    "參考價": "1170",
                    "總成交量": "30000",
                    "分K": [
                        {
                            "交易日": "20260826",
                            "交易時間": "112500",
                            "開盤價": "1170",
                            "最高價": "1172",
                            "最低價": "1168",
                            "收盤價": "1171",
                            "成交量": "1",
                        },
                        {
                            "交易日": "20260826",
                            "交易時間": "132400",
                            "開盤價": "1178",
                            "最高價": "1182",
                            "最低價": "1176",
                            "收盤價": "1180",
                            "成交量": "1",
                        },
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    adapter = NStockIntradayAdapter(
        lambda _symbol, _timeout: IntradayProviderPayload(
            raw_text=payload,
            status="available",
            url="https://example.test/nstock",
            status_code=200,
            content_type="application/json",
        ),
        clock=lambda: now,
    )
    executor = TaiwanIntradayAcquisitionExecutor(
        nstock=adapter,
        yahoo=YahooIntradayAdapter(
            lambda *_args: IntradayProviderPayload(
                raw_text=None,
                status="failed",
                url="https://example.test/yahoo",
            ),
            clock=lambda: now,
        ),
        clock=lambda: now,
    )
    db, engine = _db()
    try:
        result = refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
            descriptors=(NSTOCK_INTRADAY_DESCRIPTOR,),
            acquisition=executor,
        )
        points, metadata = project_taiwan_intraday_bars(db, result)

        coverage = metadata["series_coverage"]
        assert len(points) == 2
        assert coverage["status"] == "trailing_window"
        assert coverage["opening_covered"] is False
        assert coverage["continuous_session_covered"] is False
        assert coverage["session_volume_complete"] is False
        assert coverage["gap_reason"] == "provider_trailing_window"
        assert coverage["expected_point_count_approx"] == 265
    finally:
        db.close()
        engine.dispose()


def test_shared_plan_falls_back_to_yahoo_without_intraday_service_selection() -> None:
    now = datetime(2026, 8, 26, 10, 1, tzinfo=TAIPEI)
    executor, calls = _executor(now, nstock_status="failed")
    db, engine = _db()
    try:
        result = refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
            descriptors=(NSTOCK_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_DESCRIPTOR),
            acquisition=executor,
        )

        assert calls == ["nstock", "yahoo_finance_chart"]
        assert result.acquisition.providers_attempted == (
            "nstock",
            "yahoo_finance_chart",
        )
        assert result.resolved.bars[-1].lineage.provider == "yahoo_finance_chart"
        assert result.resolved.health.status is ResolvedEvidenceStatus.FALLBACK
        assert result.resolved.health.fallback_used is True
        assert db.query(RawFetchResult).count() == 2
        assert {row.provider for row in db.query(MarketIntradayBar).all()} == {
            "yahoo_finance_chart"
        }
    finally:
        db.close()
        engine.dispose()


def test_cache_only_history_and_trend_do_not_call_provider_or_commit(monkeypatch) -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    executor, _ = _executor(now)
    db, engine = _db()
    try:
        refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
            acquisition=executor,
        )

        def forbidden(*_args, **_kwargs):
            raise AssertionError("cache-only intraday GET attempted a side effect")

        monkeypatch.setattr(
            "app.market.providers.tw_intraday_bars.http_get",
            forbidden,
        )
        monkeypatch.setattr(db, "commit", forbidden)
        statements: list[str] = []

        def capture_select(
            _connection,
            _cursor,
            statement: str,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_select)
        try:
            shared = read_taiwan_intraday_bars(
                db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
                requested_at=now,
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture_select)
        history = intraday.get_market_intraday_history(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            refresh=True,
            requested_at=now,
        )

        assert shared.acquisition.attempted is False
        raw_receipt_selects = [
            statement
            for statement in statements
            if "raw_fetch_result" in statement.lower()
        ]
        assert raw_receipt_selects
        assert all(
            "raw_text" not in statement.lower()
            for statement in raw_receipt_selects
        )
        assert all(
            "content_hash" in statement.lower()
            and "parser_version" in statement.lower()
            for statement in raw_receipt_selects
        )
        assert history["read_policy"] == "cache_only"
        assert history["point_count"] == 1
        assert history["finalized_bar_count"] == 1
        assert history["refreshed_count"] == 0
        public_history = MarketIntradayChartRead.model_validate(history)
        assert public_history.points[0].finalized is True
        assert public_history.points[0].indicator_eligible is True
        assert public_history.points[0].bar_type == "regular_interval"
        assert public_history.points[0].price_semantics == "intraday_bar_close"
    finally:
        db.close()
        engine.dispose()


def test_today_projection_enriches_canonical_bar_semantics(monkeypatch) -> None:
    db, engine = _db()
    try:
        monkeypatch.setattr(
            intraday,
            "read_taiwan_intraday_bars",
            lambda *_args, **_kwargs: object(),
        )
        monkeypatch.setattr(
            intraday,
            "project_taiwan_intraday_bars",
            lambda *_args, **_kwargs: (
                [
                    {
                        "time": datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI),
                        "price": 1178.0,
                        "close": 1178.0,
                        "volume": 1000,
                        "finalization": "final",
                    },
                    {
                        "time": datetime(2026, 8, 26, 10, 1, tzinfo=TAIPEI),
                        "price": 1180.0,
                        "close": 1180.0,
                        "volume": 1000,
                        "finalization": "provisional",
                    },
                ],
                {
                    "provider": "nstock",
                    "source": "nstock_minute_stock_data",
                    "series_coverage": {"status": "complete_prefix"},
                },
            ),
        )
        monkeypatch.setattr(
            intraday,
            "_attach_cached_public_quote",
            lambda _db, *, stock_id, result: result,
        )
        monkeypatch.setattr(
            intraday,
            "get_taiwan_disposition_status",
            lambda *_args, **_kwargs: {},
        )
        intraday._INTRADAY_CACHE.clear()

        result = intraday._load_intraday_trend_uncached(
            db,
            stock_id="2330",
            market="TWSE",
            cache_key="test:today-contract",
        )
        public = IntradayTrendRead.model_validate(result)

        assert public.bar_contract_version == "tw.intraday.bar.v1"
        assert public.finalized_bar_count == 1
        assert public.indicator_eligible_count == 1
        assert public.points[0].indicator_eligible is True
        assert public.points[1].indicator_eligible is False
        assert public.points[1].finalization == "provisional"
    finally:
        intraday._INTRADAY_CACHE.clear()
        db.close()
        engine.dispose()


def test_intraday_service_no_longer_owns_provider_io_fallback_or_transaction() -> None:
    source = inspect.getsource(intraday)
    assert "query1.finance.yahoo.com" not in source
    assert "shop.nstock.tw" not in source
    assert "_fetch_nstock_intraday" not in source
    assert "_fetch_yahoo_intraday" not in source
    assert "_upsert_market_intraday_bars" not in source
    assert "db.commit" not in source
    assert "refresh: bool = False" in source


def test_intraday_executor_rejects_multi_route_plan_before_provider_io() -> None:
    now = datetime(2026, 8, 26, 10, 1, tzinfo=TAIPEI)
    requirement = build_taiwan_intraday_requirement(
        instrument=_instrument(),
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=now,
        acquiring=True,
    )
    plan = plan_data_acquisition_v2(requirement, TW_INTRADAY_DESCRIPTORS)
    executor, calls = _executor(now)

    assert len(plan.routes) == 2
    with pytest.raises(ValueError, match="one Gateway-controlled route"):
        executor.acquire_bar_observations(requirement, plan)
    assert calls == []


def test_all_taiwan_intraday_providers_advertise_base_1m_only() -> None:
    assert all(descriptor.intervals == ("1m",) for descriptor in TW_INTRADAY_DESCRIPTORS)
    assert YAHOO_INTRADAY_DESCRIPTOR.max_range_days == 5


@pytest.mark.parametrize("interval", ["5m", "15m", "30m", "1h", "4h"])
def test_higher_timeframe_refresh_fails_before_provider_io_or_persistence(
    interval: str,
) -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    executor, calls = _executor(now, nstock_status="failed")
    db, engine = _db()
    try:
        with pytest.raises(ValueError, match="TW_BASE_BAR_INTERVAL_REQUIRED"):
            refresh_taiwan_intraday_bars(
                db,
                stock_id="2330",
                interval=interval,
                range_value="1d",
                requested_at=now,
                descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
                acquisition=executor,
            )

        assert calls == []
        assert db.query(MarketIntradayBar).count() == 0
        assert db.query(MarketIntradayBarLineage).count() == 0
    finally:
        db.close()
        engine.dispose()
