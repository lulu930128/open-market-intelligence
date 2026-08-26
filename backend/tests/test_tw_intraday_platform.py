from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    StockMaster,
)
from app.market import intraday
from app.market.providers.tw_intraday_bars import (
    IntradayProviderPayload,
    NStockIntradayAdapter,
    YahooIntradayAdapter,
)
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_capabilities import (
    NSTOCK_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_DESCRIPTOR,
)
from app.market.tw_intraday_platform import (
    project_taiwan_intraday_bars,
    read_taiwan_intraday_bars,
    refresh_taiwan_intraday_bars,
)
from app.market_data.policies import RealtimePolicy
from app.market_data.contracts import DatasetHealthStatus


TAIPEI = timezone(timedelta(hours=8))


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


def _yahoo_payload(now: datetime) -> str:
    timestamps = [
        int(now.replace(hour=9, minute=0, second=0).timestamp()),
        int(now.replace(hour=9, minute=1, second=0).timestamp()),
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

        assert calls == ["nstock"]
        assert result.persistence.committed is True
        assert result.resolved.bars
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.STALE
        assert result.resolved.bars[-1].lineage.provider == "nstock"
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


def test_shared_plan_falls_back_to_yahoo_without_intraday_service_selection() -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
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
        shared = read_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            requested_at=now,
        )
        history = intraday.get_market_intraday_history(
            db,
            stock_id="2330",
            interval="1m",
            range_value="1d",
            refresh=True,
        )

        assert shared.acquisition.attempted is False
        assert history["read_policy"] == "cache_only"
        assert history["point_count"] == 2
        assert history["refreshed_count"] == 0
    finally:
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


def test_four_hour_local_aggregation_persists_derived_component_lineage() -> None:
    now = datetime(2026, 8, 26, 10, 1, 30, tzinfo=TAIPEI)
    executor, calls = _executor(now, nstock_status="failed")
    db, engine = _db()
    try:
        result = refresh_taiwan_intraday_bars(
            db,
            stock_id="2330",
            interval="4h",
            range_value="1d",
            requested_at=now,
            descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
            acquisition=executor,
        )
        points, metadata = project_taiwan_intraday_bars(db, result)

        assert calls == ["yahoo_finance_chart"]
        assert len(points) == 1
        assert points[0]["source_interval"] == "1h"
        assert points[0]["calculation_version"] == "omi.aggregate.4h.v1"
        assert points[0]["component_raw_result_ids"]
        assert metadata["component_raw_result_ids"]
        lineage = db.query(MarketIntradayBarLineage).one()
        assert lineage.source_interval == "1h"
        assert lineage.calculation_version == "omi.aggregate.4h.v1"
    finally:
        db.close()
        engine.dispose()
