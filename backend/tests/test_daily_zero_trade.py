from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.tw_daily_day_state import TaiwanDailyState, TaiwanPriceBasis
from app.market import tw_corporate_events as events
from test_tw_daily_day_state import INSTRUMENT, LINEAGE, evidence, price, resolve
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row


def run_derived(basis=None, prior=True, **activity):
    previous = price().model_copy(update={
        "price_basis": "raw",
        "start_at": datetime(2026, 8, 3, 1, tzinfo=timezone.utc),
        "end_at": datetime(2026, 8, 3, 5, 30, tzinfo=timezone.utc)})
    from app.market.tw_daily_day_state import resolve_taiwan_daily_day_state
    prior_state = resolve_taiwan_daily_day_state(instrument=INSTRUMENT, trade_date=date(2026, 8, 3), market_open=True, prices=(previous,))
    basis = basis or TaiwanPriceBasis(status="unchanged", coverage="complete", lineage=(LINEAGE,), limitations=())
    row = evidence(**activity).model_copy(update={"lineage": LINEAGE.model_copy(update={"observation_id": "market_daily_price:2"})})
    current = resolve(daily=(row,), price_basis=basis)
    db = Mock()
    result = TaiwanOfficialDailyBarRepository(db).complete_no_trade_bars(
        resolved_bars=[previous] if prior else [], day_states=(prior_state, current))
    db.add.assert_not_called()
    db.commit.assert_not_called()
    return result


def test_safe_zero_trade_is_transparent_derived():
    bars, states = run_derived()
    assert len(bars) == 2 and not states[-1].blockers
    derived = bars[-1]
    assert derived.open_price == derived.high_price == derived.low_price == derived.close_price == Decimal(10)
    assert derived.volume.value == 0
    assert derived.lineage.authority.value == "derived"
    assert derived.derivation_kind == "official_zero_trade_carry_forward"
    assert "DERIVED_PREVIOUS_CLOSE_NOT_AN_EXECUTED_PRICE" in derived.limitations


@pytest.mark.parametrize("activity", [{"trade_value": 5000, "transaction_count": 6},
    {"trade_value": 1000, "transaction_count": 2}, {"volume": None}, {"transaction_count": None}])
def test_null_or_positive_activity_never_carries(activity):
    bars, states = run_derived(**activity)
    assert len(bars) == 1
    assert states[-1].state is not TaiwanDailyState.VERIFIED_NO_TRADE


@pytest.mark.parametrize("basis", [TaiwanPriceBasis(), TaiwanPriceBasis(status="changed", coverage="complete"),
    TaiwanPriceBasis(status="unchanged", coverage="partial")])
def test_unsafe_basis_never_carries(basis):
    bars, states = run_derived(basis=basis)
    assert len(bars) == 1 and states[-1].blockers


def test_missing_prior_never_carries():
    bars, states = run_derived(prior=False)
    assert not bars and "PRIOR_CANONICAL_CLOSE_MISSING" in states[-1].blockers


@pytest.mark.parametrize("failure", [None, "untrusted", "wrong_receipt_source", "before_release", "nonzero", "no_basis"])
def test_repository_day_state_query_only_raw_unchanged(db, tmp_path, monkeypatch, failure):
    from app.config import settings
    from app.db.models import StockMaster
    from app.sources.defaults import TPEX_DAILY_QUOTES_SOURCE_NAME
    from app.market.tw_bar_service import TaiwanBarService
    monkeypatch.setattr(settings, "tw_corporate_event_cache_path", tmp_path / "corporate.json")
    source, raw = _source_and_raw(db, source_name=TPEX_DAILY_QUOTES_SOURCE_NAME, parser_type="tpex_daily_quotes", priority=1)
    raw.status_code = 200
    raw.url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    if failure == "untrusted":
        source.reliability_level = "unknown"
    if failure == "wrong_receipt_source":
        other, _ = _source_and_raw(db, source_name="unrelated", parser_type="unknown", priority=10)
        raw.source_id = other.id
    if failure == "before_release":
        raw.fetched_at = datetime(2026, 8, 19, tzinfo=timezone.utc)
    db.add(StockMaster(stock_id="2330", market="TPEX", stock_name="fixture", instrument_type="stock"))
    first = _daily_row(source=source, raw=raw, trade_date=date(2026, 8, 20))
    zero = _daily_row(source=source, raw=raw, trade_date=date(2026, 8, 21), open_price=None,
        high_price=None, low_price=None, close_price=None, trade_volume=0)
    zero.trade_value = 5000 if failure == "nonzero" else 0
    zero.transaction_count = 6 if failure == "nonzero" else 0
    db.add_all([first, zero]); db.commit()
    if failure != "no_basis":
        monkeypatch.setattr(events, "resolve_taiwan_price_basis", lambda *a, **kw:
            TaiwanPriceBasis(status="unchanged", coverage="complete", lineage=(LINEAGE,), limitations=()))
    db.execute(text("PRAGMA query_only=ON"))
    result = TaiwanBarService(db).read_bars(instrument_id="2330", interval="1d",
        from_time=datetime(2026, 8, 20, tzinfo=timezone.utc), to_time=datetime(2026, 8, 22, tzinfo=timezone.utc),
        requested_at=datetime(2026, 8, 26, tzinfo=timezone.utc), limit=50)
    derived = [bar for bar in result.bars if bar.derivation_kind]
    assert bool(derived) is (failure is None)
    state = next(item for item in result.day_states if item.trade_date == date(2026, 8, 21))
    if failure == "nonzero":
        assert state.state is TaiwanDailyState.TRADE_ACTIVITY_WITHOUT_PRICE
    if failure == "no_basis":
        assert state.state is TaiwanDailyState.VERIFIED_NO_TRADE and state.blockers
    if derived:
        assert not result.bar_states[-1].official and not result.bar_states[-1].persisted
    db.expire_all()
    assert db.get(type(zero), zero.id).close_price is None
    assert db.execute(text("PRAGMA query_only")).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM market_daily_price")).scalar() == 2
