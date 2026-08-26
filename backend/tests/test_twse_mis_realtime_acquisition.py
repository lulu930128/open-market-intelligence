from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    StockMaster,
    TaiwanStockAuctionSnapshot,
    TaiwanStockDepthLevel,
    TaiwanStockDepthSnapshot,
    TaiwanStockQuoteSnapshot,
)
from app.market.providers.twse_mis_realtime_acquisition import (
    TwseMisProviderSnapshot,
    TwseMisRealtimeAcquisitionAdapter,
)
from app.market.quote_depth import get_taiwan_stock_quote_depth
from app.market.taiwan_quote_evidence import (
    acquire_taiwan_quote_evidence_bundle,
)
from app.market.taiwan_realtime_platform import refresh_taiwan_realtime_snapshot
from app.market.tw_public_quote_contract import TWSE_MIS_QUOTE_RESOURCE_ID


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


def _payload(*, trial: bool = False) -> str:
    return json.dumps(
        {
            "rtcode": "0000",
            "msgArray": [
                {
                    "c": "2330",
                    "n": "台積電",
                    "ch": "tse_2330.tw",
                    "d": "20260826",
                    "t": "08:45:00" if trial else "10:00:00",
                    "z": "-" if trial else "1180",
                    "y": "1170",
                    "o": "-" if trial else "1170",
                    "h": "-" if trial else "1185",
                    "l": "-" if trial else "1165",
                    "v": "0" if trial else "100",
                    "tv": "2",
                    "b": "1175_1170_",
                    "g": "4_5_",
                    "a": "1180_1185_",
                    "f": "3_6_",
                    "ts": "1" if trial else "0",
                    "pz": "1178" if trial else "-",
                    "ps": "8" if trial else "-",
                }
            ],
        },
        ensure_ascii=False,
    )


def _adapter(raw_text: str, now: datetime, calls: list[tuple]) -> TwseMisRealtimeAcquisitionAdapter:
    def reader(symbol: str, venue: str | None, timeout: int) -> TwseMisProviderSnapshot:
        calls.append((symbol, venue, timeout))
        return TwseMisProviderSnapshot(
            raw_text=raw_text,
            status="available",
            url="https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
            status_code=200,
            content_type="application/json",
        )

    return TwseMisRealtimeAcquisitionAdapter(reader, clock=lambda: now)


def test_explicit_mis_refresh_fetches_once_and_persists_quote_and_typed_depth() -> None:
    now = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)
    calls: list[tuple] = []
    db, engine = _db()
    try:
        result = refresh_taiwan_realtime_snapshot(
            db,
            stock_id="2330",
            requested_at=now,
            acquisition=_adapter(_payload(), now, calls),
        )

        assert len(calls) == 1
        assert result.quote.persistence.committed is True
        assert result.depth.persistence.committed is True
        assert result.auction is None
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
        assert db.query(TaiwanStockDepthSnapshot).count() == 1
        assert db.query(TaiwanStockDepthLevel).count() == 4
        assert db.query(RawFetchResult).count() == 2

        projected = get_taiwan_stock_quote_depth(
            db=db,
            stock_id="2330",
            now=now,
        )
        assert projected["provider"] == "twse_mis"
        assert projected["last_price"] == 1180
        assert projected["depth_available"] is True
        assert projected["bid_levels"][0]["size_lots"] == 4
    finally:
        db.close()
        engine.dispose()


def test_explicit_preopen_refresh_persists_trial_only_as_auction() -> None:
    now = datetime(2026, 8, 26, 8, 45, tzinfo=TAIPEI)
    calls: list[tuple] = []
    db, engine = _db()
    try:
        result = refresh_taiwan_realtime_snapshot(
            db,
            stock_id="2330",
            requested_at=now,
            acquisition=_adapter(_payload(trial=True), now, calls),
        )

        assert len(calls) == 1
        assert result.auction is not None
        assert result.auction.persistence.committed is True
        assert db.query(TaiwanStockAuctionSnapshot).count() == 1
        quote_row = db.query(TaiwanStockQuoteSnapshot).one()
        assert quote_row.last_price is None
        projected = get_taiwan_stock_quote_depth(
            db=db,
            stock_id="2330",
            now=now,
        )
        assert projected["actual_trade_occurred"] is False
        assert projected["last_price"] is None
        assert projected["auction_indicative_available"] is True
        assert projected["indicative_match_price"] == 1178
    finally:
        db.close()
        engine.dispose()


def test_quote_bundle_acquisition_reports_requested_resource_and_materialization_scope() -> None:
    now = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)
    calls: list[tuple] = []
    db, engine = _db()
    try:
        bundle = acquire_taiwan_quote_evidence_bundle(
            db,
            stock_id="2330",
            requested_at=now,
            requested_capabilities=("quote.snapshot",),
            acquisition=_adapter(_payload(), now, calls),
        )

        assert len(calls) == 1
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
        assert db.query(TaiwanStockDepthSnapshot).count() == 0
        assert db.query(TaiwanStockAuctionSnapshot).count() == 0
        assert bundle.acquisition_scope is not None
        assert bundle.acquisition_scope.requested_capabilities == (
            "quote.snapshot",
        )
        assert bundle.acquisition_scope.acquired_resources == (
            TWSE_MIS_QUOTE_RESOURCE_ID,
        )
        assert bundle.acquisition_scope.materialized_capabilities == (
            "quote.snapshot",
        )
        assert bundle.acquisition_scope.limitations == ()
    finally:
        db.close()
        engine.dispose()
