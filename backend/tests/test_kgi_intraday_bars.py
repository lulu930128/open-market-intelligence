from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    StockMaster,
)
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.providers.kgi_intraday_bars import kgi_minute_kbar_acquisition
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market_data.contracts import (
    BarFinalization,
    InstrumentKey,
    InstrumentType,
    Market,
)
from app.market_data.policies import RealtimePolicy


TAIPEI = timezone(timedelta(hours=8))


def test_kgi_buffer_materializes_only_closed_minutes_with_canonical_lineage() -> None:
    now = datetime(2026, 8, 31, 10, 2, 30, tzinfo=TAIPEI)
    instrument = InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )
    requirement = build_taiwan_intraday_requirement(
        instrument=instrument,
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=now,
        acquiring=True,
    )
    stream = {
        "stock_id": "2330",
        "minute_kbars": [
            {
                "event_id": "kbar:2330:202608311001:1",
                "event_time": "2026-08-31T10:01:00+08:00",
                "received_at": "2026-08-31T10:01:01+08:00",
                "open": 2395,
                "high": 2400,
                "low": 2390,
                "close": 2398,
                "volume_lots": 12,
                "total_amount": 28_776_000,
            },
            {
                "event_id": "kbar:2330:202608311003:1",
                "event_time": "2026-08-31T10:03:00+08:00",
                "received_at": "2026-08-31T10:02:20+08:00",
                "open": 2398,
                "high": 2401,
                "low": 2398,
                "close": 2400,
                "volume_lots": 3,
                "total_amount": 7_200_000,
            },
        ],
    }

    acquisition = kgi_minute_kbar_acquisition(stream, requirement)

    assert len(acquisition.observations) == 1
    observation = acquisition.observations[0]
    assert observation.finalization is BarFinalization.FINAL
    assert observation.lineage.provider == "kgi_superpy"
    assert observation.lineage.source == "kgi_superpy_minute_kbars"
    assert observation.start_at == datetime(2026, 8, 31, 10, 0, tzinfo=TAIPEI)
    assert observation.end_at == datetime(2026, 8, 31, 10, 1, tzinfo=TAIPEI)
    assert observation.lineage.event_at == observation.end_at
    assert int(observation.volume.value) == 12_000
    assert observation.turnover_value is None
    assert "KGI_PROVIDER_BUCKET_END_NORMALIZED_TO_CANONICAL_START" in (
        acquisition.summary.limitations
    )
    assert "KGI_CUMULATIVE_TOTAL_AMOUNT_NOT_PROJECTED_AS_MINUTE_TURNOVER" in (
        acquisition.summary.limitations
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
            )
        )
        db.commit()
        persisted = TaiwanIntradayBarTransaction(db).persist_bar_acquisition(
            requirement,
            acquisition,
        )
        assert persisted.committed is True
        row = db.query(MarketIntradayBar).one()
        assert row.provider == "kgi_superpy"
        assert row.trade_volume == 12_000
        assert db.query(MarketIntradayBarLineage).one().finalization == "final"
    finally:
        db.close()
        engine.dispose()


def test_kgi_closing_auction_rows_do_not_enter_continuous_minute_bars() -> None:
    requested_at = datetime(2026, 9, 1, 13, 31, tzinfo=TAIPEI)
    instrument = InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )
    requirement = build_taiwan_intraday_requirement(
        instrument=instrument,
        interval="1m",
        range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=requested_at,
        acquiring=True,
    )
    acquisition = kgi_minute_kbar_acquisition(
        {
            "stock_id": "2330",
            "minute_kbars": [
                {
                    "event_time": "2026-09-01T13:25:00+08:00",
                    "received_at": "2026-09-01T13:25:01+08:00",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume_lots": 1,
                    "total_amount": 100000,
                },
                {
                    "event_time": "2026-09-01T13:28:00+08:00",
                    "received_at": "2026-09-01T13:28:01+08:00",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume_lots": 1,
                    "total_amount": 100000,
                },
            ],
        },
        requirement,
    )
    assert [item.start_at.minute for item in acquisition.observations] == [24]
