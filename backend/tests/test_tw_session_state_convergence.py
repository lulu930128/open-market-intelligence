from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (Base, TaiwanMarketMinuteState, StockMaster, StockProfile,
                           SourceRegistry, RawFetchResult, TaiwanIssuedSharesDaily)
from app.market.tw_market_dashboard import _build_index_estimates, estimate_cap_weighted_index
from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_market_dashboard_schemas import TaiwanDashboardBreadthRead
from app.ai.market_context.taiwan_market import _market_indices_capability
from test_taiwan_market_state import market_summary_payload


def test_current_index_never_becomes_official_close():
    summary = {"indices": [{"index_id": "TAIEX", "market": "TWSE", "close": 47408.4,
        "as_of": "2026-09-09T09:17:00+08:00", "source": "fugle_indices_stream"}]}
    result = _market_indices_capability(db=None,
        dependencies=SimpleNamespace(get_market_index_summary=lambda *a, **k: summary),
        generated_at=datetime(2026, 9, 9, 9, 17, tzinfo=TAIWAN_TZ))
    official = result["items"][0]["official_close"]
    assert all(official[key] is None for key in ("value", "trade_date", "as_of", "source"))


def test_auction_breadth_survives_dashboard_schema():
    auction = {"status": "partial", "advance_count": 2, "decision_usable": False}
    result = TaiwanDashboardBreadthRead(market="TWSE", status="partial", session_phase="preopen",
        price_semantics="unavailable", provisional=True, decision_usable=False,
        universe=10, coverage=0, advance=0, decline=0, unchanged=0, unknown=10,
        coverage_ratio=0, auction_breadth=auction).model_dump()
    assert result["auction_breadth"] == auction


def test_tpex_estimate_uses_dated_shares_instead_of_company_profile():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = SourceRegistry(source_name="shares-fixture", source_type="official", category="market")
        db.add(source)
        db.flush()
        raw = RawFetchResult(source_id=source.id, content_hash="shares-fixture")
        db.add(raw)
        db.flush()
        stock = StockMaster(stock_id="6488", stock_name="Test", market="TPEX", instrument_type="stock")
        db.add(stock)
        db.add(StockProfile(source_id=source.id, raw_result_id=raw.id,
            stock_id="6488", market="TPEX", issued_shares=999, report_date=date(2026, 9, 8)))
        for day, shares in ((date(2026, 9, 8), 100), (date(2026, 9, 10), 500)):
            db.add(TaiwanIssuedSharesDaily(source_id=source.id, raw_result_id=raw.id,
                stock_id="6488", market="TPEX", trade_date=day, issued_shares=shares))
        db.flush()
        with patch("app.market.tw_market_dashboard.estimate_cap_weighted_index",
                   wraps=estimate_cap_weighted_index) as estimate:
            result = _build_index_estimates(db, [stock], {}, session_phase="preopen", trade_date=date(2026, 9, 9))
        tpex = next(item for item in result if item["market"] == "TPEX")
        assert tpex["shares_as_of"] == date(2026, 9, 8)
        components = [call.kwargs["components"] for call in estimate.call_args_list if call.kwargs["components"]]
        assert components[0][0]["shares"] == 100
    engine.dispose()


def test_old_breadth_cannot_create_a_new_complete_minute():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        payload = market_summary_payload(date(2026, 9, 9), hour=9, minute=18,
            twse_trade_value=144312276164, tpex_trade_value=44570705063)
        persist_taiwan_market_minute_state(db, payload=payload)
        payload["as_of"] = "2026-09-09T09:19:55+08:00"
        for item in payload["indices"]:
            item["current_data_core"]["index"]["as_of"] = payload["as_of"]
        persist_taiwan_market_minute_state(db, payload=payload)
        rows = db.query(TaiwanMarketMinuteState).filter(TaiwanMarketMinuteState.minute_at >= datetime(2026, 9, 9, 9, 19)).all()
        assert {row.trade_value_quality_status for row in rows} == {"component_time_mismatch"}
        result = read_taiwan_market_volume_state(db)
        assert result["current_cumulative_trade_value"] is None
        assert result["one_minute_trade_value_change"] is None
    engine.dispose()


def test_delta_requires_adjacent_comparable_monotonic_minutes():
    for prior_minute, current_value in ((16, 120), (17, 80), (17, 100)):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for minute, value in ((prior_minute, 100), (18, current_value)):
                persist_taiwan_market_minute_state(db, payload=market_summary_payload(
                    date(2026, 9, 9), hour=9, minute=minute, twse_trade_value=value, tpex_trade_value=20))
            result = read_taiwan_market_volume_state(db)
            assert result["one_minute_trade_value_change"] == (0 if prior_minute == 17 and current_value == 100 else None)
        engine.dispose()
