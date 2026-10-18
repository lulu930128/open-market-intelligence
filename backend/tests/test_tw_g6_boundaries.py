"""Synthetic G6 receipt and Account boundaries; no production IO."""
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from app.ai import ask as ask_module
from app.ai.schemas import AiAskRequest
from app.db.models import RawFetchResult, StockMaster, TaiwanStockQuoteSnapshot
from app.market.public_quote_platform import (
    acquire_taiwan_session_close, project_taiwan_session_close, read_taiwan_session_close,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import InstrumentKey, InstrumentType, Market, MarketSession
from test_tw_public_quote_platform import db, _executor, _records, _raw_with_message_updates, _persist_breadth_trade


@pytest.mark.parametrize("bridge", ["quote", "breadth"])
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("receipt_minute,qualified", [(31, False), (32, False), (34, True)])
@pytest.mark.parametrize("symbol,venue,price", [("3324", "TPEX", "1540"), ("2883", "TWSE", "38.8")])
def test_close_confirmation_uses_original_receipt_not_later_fetch(db, bridge, batch, receipt_minute, qualified, symbol, venue, price):
    db.add(StockMaster(stock_id=symbol, stock_name="Synthetic close", market=venue, instrument_type="stock"))
    db.commit()
    received = datetime(2026, 10, 12, 13, receipt_minute, tzinfo=TAIWAN_TZ)
    later = received.replace(hour=14, minute=29)
    if bridge == "quote":
        raw_text = _raw_with_message_updates(_records()["2330"], c=symbol,
            ex="otc" if venue == "TPEX" else "tse", d="20261012", t="13:30:00", z=price,
            tlong=str(int(received.replace(minute=30).timestamp() * 1000)))
        acquire_taiwan_session_close(db, stock_id=symbol, requested_at=received,
            acquisition=_executor(raw_text, received.astimezone(timezone.utc)))
        row = db.query(TaiwanStockQuoteSnapshot).one()
        raw = db.get(RawFetchResult, row.raw_result_id)
        raw.fetched_at = later.astimezone(timezone.utc)
    else:
        row = _persist_breadth_trade(db, received_at=received)
        raw = db.get(RawFetchResult, row.raw_result_id)
        raw.fetched_at = later.astimezone(timezone.utc)
        row.fetched_at = raw.fetched_at
        row.observation_state = "stale"
        row.venue = venue
        states = json.loads(row.price_states_json)
        states[symbol] = states.pop("2330")
        states[symbol]["price"] = price
        states[symbol]["lineage"]["fetched_at"] = later.isoformat()
        states[symbol]["current_price_verified"] = False
        row.price_states_json = json.dumps(states)
    db.commit()
    now = later.replace(hour=15, minute=0)
    instrument = InstrumentKey(market=Market.TW, symbol=symbol, venue=venue, instrument_type=InstrumentType.STOCK)
    repository = TaiwanPublicQuoteRepository(db)
    if batch:
        repository.preload_session_close_candidates((instrument,), requested_at=now)
    with patch("app.market.public_quote_platform.TaiwanPublicQuoteRepository", return_value=repository):
        result = read_taiwan_session_close(db, stock_id=symbol, requested_at=now)
    projected = project_taiwan_session_close(result)
    assert projected["available"] is qualified
    assert (projected["status"] == "session_final") is qualified
    assert projected["official_daily"] is False
    assert result.acquisition.external_calls == 0
    if qualified:
        assert projected["confirmed_at"] == received
    # Protect SQL admission independently from the diagnostic price-state bridge.
    if bridge == "quote" and not qualified:
        assert db.query(TaiwanStockQuoteSnapshot).filter(
            *repository._session_close_storage_predicates(now.date())).count() == 0
        assert repository._decode_row(instrument, row).confirmed_at == received


@pytest.mark.parametrize("mode", ["data_only", "brief"])
@pytest.mark.parametrize("question", ["2330 quote only", "2330 只要收盤價，不要分析持倉",
    "2330 盤中均價", "2330 institutional holdings", "2330 disposition quote",
    "2330 假設成本1500，計算停損風險"])
def test_public_quote_never_reads_private_account(db, mode, question):
    payload = AiAskRequest(contract_version="omi.decision.v4", question=question,
        target={"type": "tw_stock", "id": "2330"}, mode=mode, output="evidence_only",
        selection={"required": ["quote.snapshot", "quote.session_close"]},
        realtime_policy="cache_only", allow_external_fetch=False, allow_llm=False, allow_write=False)
    private = {"has_position_context": True, "entry_price": 987654.321,
               "source": "PRIVATE_ACCOUNT_SENTINEL", "holding_id": 987654321}
    with patch.object(ask_module.portfolio_service, "get_position_context_for_scope", return_value=private) as lookup:
        response = ask_module.ask(db, payload)
    lookup.assert_not_called()
    encoded = json.dumps(response, ensure_ascii=False, default=str)
    assert "PRIVATE_ACCOUNT_SENTINEL" not in encoded and "987654" not in encoded


@pytest.mark.parametrize("question,intents", [("我的2330持倉現在該停損嗎？", []),
    ("2330", ["position_risk_decision"]), ("Review my 2330 position", [])])
def test_explicit_position_question_still_reads_saved_context(db, question, intents):
    payload = AiAskRequest(contract_version="omi.decision.v4", question=question, intents=intents,
        target={"type": "tw_stock", "id": "2330"}, mode="data_only",
        selection={"required": ["quote.snapshot"]}, realtime_policy="cache_only",
        allow_external_fetch=False, allow_llm=False, allow_write=False)
    context = {"has_position_context": True, "entry_price": 1500, "source": "SYNTHETIC_TEST_ONLY"}
    with patch.object(ask_module.portfolio_service, "get_position_context_for_scope", return_value=context) as lookup:
        response = ask_module.ask(db, payload)
    lookup.assert_called_once_with(db, scope_type="stock", scope_id="2330")
    assert "SYNTHETIC_TEST_ONLY" in json.dumps(response, ensure_ascii=False, default=str)
