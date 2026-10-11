"""Existing MIS owner boundary: volume is not a substitute for an actual price."""
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import StockMaster, TaiwanIntradayStockState
from app.market.providers.twse_mis_current_breadth import _classify_message
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_discovery import build_tw_intraday_radar_snapshot
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states
from app.market.tw_intraday_state import attach_current_market_lineage_to_stock_rows
from app.market.tw_intraday_discovery import read_tw_intraday_discovery


@pytest.mark.parametrize("price,expected", [("-", None), (None, None), ("NaN", None), ("1815.0000", 1815)])
def test_mis_original_owner_does_not_infer_price_from_volume_ohl_or_indicative(price, expected):
    # Reconstructed parser case, not an assertion that original wire msgArray
    # was archived. Positive formal z is accepted; other fields cannot replace it.
    message = dict(c="6442", d="20261007", t="09:43:34", z=price, v="2489", tv="1",
                   y="1650", o="1715", h="1815", l="1715", pz="1815", ps="9", ts="0")
    result = _classify_message(message, "TWSE")
    assert result["current_price"] == expected
    assert result["has_actual_trade"] is (expected is not None)
    assert result["cumulative_volume_lots"] == 2489
    assert result["actual_trade_reason_code"] == ("ACTUAL_TRADE_PRICE_AVAILABLE" if expected else "ACTUAL_TRADE_PRICE_MISSING")


def test_persisted_6442_missing_price_component_remains_blocked():
    path = Path(__file__).parent / "fixtures/intraday_radar/6442_20261007_missing_price.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    row = fixture["row"]
    assert fixture["raw_receipt_id"] == 621552
    assert row["actual_trade_reason_code"] == "ACTUAL_TRADE_PRICE_MISSING"
    assert fixture["missing_z_rescue"]["status"] == "skipped"
    at = datetime(2026, 10, 7, 9, 44, tzinfo=TAIWAN_TZ)
    row.update(provider="twse_mis", source="twse_mis_live_breadth", raw_result_id="raw_fetch_result:621552")
    engine = create_engine("sqlite:///:memory:")
    for table in (StockMaster.__table__, TaiwanIntradayStockState.__table__):
        table.create(engine)
    with Session(engine) as db:
        db.add(StockMaster(stock_id="6442", stock_name="6442", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
        persist_taiwan_intraday_stock_states(db, rows=[row], now=at)
        result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
        assert result.coverage.observed_count == 1
        assert result.coverage.coverage_count == result.coverage.ranking_eligible_count == 0
        assert result.status == "blocked" and not result.candidates
    engine.dispose()


def test_6442_missing_z_then_later_z_preserves_receipt_and_point_in_time_gap():
    engine = create_engine("sqlite:///:memory:")
    for table in (StockMaster.__table__, TaiwanIntradayStockState.__table__):
        table.create(engine)
    first = datetime(2026, 10, 7, 9, 44, tzinfo=TAIWAN_TZ)
    later = datetime(2026, 10, 7, 10, 3, tzinfo=TAIWAN_TZ)
    original = dict(c="6442", d="20261007", t="09:43:34", z="-", v="2489", tv="1",
                    y="1650", o="1715", h="1815", l="1715", pz="1815", ps="9", ts="0",
                    _omi_received_at=first.isoformat())
    with Session(engine) as db:
        db.add(StockMaster(stock_id="6442", stock_name="6442", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
        for raw, receipt, received in ((original, 101, first),
                ({**original, "z": "1815", "v": "2600", "t": "10:03:00", "_omi_received_at": later.isoformat()}, 102, later)):
            row = _classify_message(raw, "TWSE")
            # Aggregate receipt finishes later than this instrument's batch.
            rows = attach_current_market_lineage_to_stock_rows([row], summary={
                "indices": [{"market": "TWSE", "breadth": {"raw_result_id": receipt,
                    "provider": "twse_mis", "source": "twse_mis_live_breadth",
                    "as_of": received, "observation_received_at": (received + timedelta(seconds=10)).isoformat()}}]})
            assert rows[0]["observation_received_at"] == received.isoformat()
            persist_taiwan_intraday_stock_states(db, rows=rows, now=received)
            result = read_tw_intraday_discovery(db, evaluated_at=received)
            if receipt == 101:
                before = result
                assert row["current_price"] is None and not row["has_actual_trade"]
                assert result.coverage.actual_price_unavailable_count == 1
                assert result.coverage.coverage_count == 0
            else:
                assert row["current_price"] == 1815 and row["has_actual_trade"]
                assert result.coverage.actual_trade_price_count == 1
                assert result.coverage.ranking_eligible_count == 1
                assert result.coverage.count_ratios["actual_price"] == 1
        assert before.coverage.actual_price_unavailable_count == 1
        # Latest storage cannot rewrite what was known at the first evaluation.
        historical = read_tw_intraday_discovery(db, evaluated_at=first)
        assert historical.coverage.observed_count == 0
        samples = json.loads(db.query(TaiwanIntradayStockState).one().samples_json)
        assert all(sample["received_at"] >= later.isoformat() for sample in samples)
    engine.dispose()
