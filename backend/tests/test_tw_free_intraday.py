from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, MarketIntradayBar
from app.market.providers.fugle_http import FugleHttpAdapter, FugleHttpPayload
from app.market.providers.fugle_realtime import fugle_cumulative_fields
from app.market.public_quote_platform import build_taiwan_public_quote_requirement
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market.tw_intraday_capabilities import FUGLE_HTTP_INTRADAY_DESCRIPTOR
from app.market.tw_realtime_capabilities import FUGLE_HTTP_QUOTE_DESCRIPTOR
from app.market.tw_bar_service import TaiwanBarService
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import InstrumentKey
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
from app.ai.market_context.taiwan_projection import _compact_intraday_history
from app.market.tw_intraday_value import reconcile_taiwan_intraday_volume

NOW = datetime(2026, 10, 28, 9, 2, 30, tzinfo=TAIWAN_TZ)
INSTRUMENT = InstrumentKey(market="TW", symbol="6488", venue="TPEX", instrument_type="stock")


def quote_payload():
    return {"symbol": "6488", "type": "EQUITY", "exchange": "TPEX", "market": "OTC",
        "date": NOW.date().isoformat(), "lastTrade": {"price": 100, "size": 2, "time": int(NOW.timestamp() * 1e6)},
        "total": {"tradeVolume": 6, "tradeValue": 602000, "time": int(NOW.timestamp() * 1e6)}}


def candles_payload():
    return {**{k: v for k, v in quote_payload().items() if k not in {"total", "lastTrade"}},
        "timeframe": "1", "data": [{"date": NOW.replace(minute=i, second=0).isoformat(),
            "open": 99, "high": 103, "low": 98, "close": 102, "volume": i + 1,
            "average": 777} for i in range(3)]}


def acquire(payload, *, bars=False):
    req = (build_taiwan_intraday_requirement(instrument=INSTRUMENT, interval="1m", range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW, acquiring=True) if bars else
        build_taiwan_public_quote_requirement(instrument=INSTRUMENT, policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW))
    descriptor = FUGLE_HTTP_INTRADAY_DESCRIPTOR if bars else FUGLE_HTTP_QUOTE_DESCRIPTOR
    route = plan_data_acquisition_v2(req, (descriptor,)).routes[0]
    adapter = FugleHttpAdapter(clock=lambda: NOW, reader=lambda *args: FugleHttpPayload(
        raw_text=json.dumps(payload), status_code=200, external_calls=1))
    return req, adapter.acquire_route(req, route)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(StockMaster(stock_id="6488", stock_name="test", market="TPEX", instrument_type="stock", is_active=True))
        session.commit()
        yield session
    engine.dispose()


def test_quote_totals_persist_reread_with_separate_event_clock(db):
    payload = quote_payload()
    payload["lastTrade"]["time"] -= 60_000_000
    req, result = acquire(payload)
    assert result.observations[0].cumulative_turnover_value == Decimal(602000)
    assert TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(req, result).committed
    quote = TaiwanPublicQuoteRepository(db).load_quote_candidates(INSTRUMENT, requested_at=NOW)[0].observation
    assert quote.cumulative_quantity.value == 6000
    assert quote.cumulative_turnover_value == 602000
    assert quote.cumulative_turnover_currency == "TWD"
    assert quote.cumulative_event_at == NOW
    assert quote.lineage.event_at == NOW - timedelta(minutes=1)
    assert quote.lineage.authority.value == "vendor"
    assert quote.cumulative_scope == "regular_board_lot"


@pytest.mark.parametrize("mutation", ["missing_time", "future", "previous_day", "oddlot", "trial"])
def test_rejected_totals_never_restore_unscoped_lots(mutation):
    payload = quote_payload()
    if mutation == "missing_time": payload["total"].pop("time")
    if mutation == "future": payload["total"]["time"] += 1_000_000
    if mutation == "previous_day": payload["total"]["time"] -= 86_400_000_000
    if mutation == "oddlot": payload["type"] = "oddlot"
    if mutation == "trial": payload["isTrial"] = True
    assert not fugle_cumulative_fields(payload, trade_date=NOW.date(), received_at=NOW)
    _, result = acquire(payload)
    if result.observations:
        assert result.observations[0].cumulative_quantity is None
        assert result.observations[0].cumulative_turnover_value is None


@pytest.mark.parametrize("value,expected", [(None, None), (0, Decimal(0)), (-1, None)])
def test_amount_missing_zero_negative_are_distinct(value, expected):
    payload = quote_payload(); payload["total"]["tradeValue"] = value
    _, result = acquire(payload)
    assert result.observations[0].cumulative_turnover_value == expected
    from app.market.quote_volume import project_taiwan_cumulative_totals
    from app.market_data.contracts import EvidenceFreshness
    quote = result.observations[0].model_copy(update={"cumulative_freshness": EvidenceFreshness.FRESH})
    assert project_taiwan_cumulative_totals(quote)["cumulative_trade_value_evidence"]["fresh_amount_usable"] is (expected is not None)


def test_candles_dedup_sort_partial_and_canonical_outward_amount(db):
    payload = candles_payload()
    payload["data"] = [payload["data"][2], payload["data"][0], payload["data"][1], payload["data"][1]]
    req, result = acquire(payload, bars=True)
    assert len(result.observations) == 3
    assert [bar.start_at.minute for bar in result.observations] == [0, 1, 2]
    assert result.observations[-1].finalization.value == "provisional"
    assert all(bar.turnover_value is None for bar in result.observations)
    owner = TaiwanIntradayBarTransaction(db)
    owner.persist_bar_acquisition(req, result)
    owner.persist_bar_acquisition(req, result)
    assert db.query(MarketIntradayBar).count() == 3
    series = TaiwanBarService(db).read_bars(instrument_id="6488", interval="1m",
        from_time=NOW.replace(minute=0, second=0), to_time=NOW, requested_at=NOW, include_partial=True)
    projected = _compact_intraday_history(project_taiwan_bar_series(series), point_limit=30)
    assert len(projected["points"]) == 2  # canonical range ends before the forming bucket closes
    assert projected["points"][0]["approx_trade_value"] == 101000
    assert projected["points"][0]["trade_value_method"] == "hlc3_times_volume_shares"
    assert projected["approx_vwap"] == 101
    assert projected["official_vwap"] is None
    assert projected["trade_value_coverage"]["estimated_count"] == 2
    assert projected["window_trade_value"] == 303000


@pytest.mark.parametrize("body", [[], None, 42, "object"])
def test_legal_json_non_object_returns_typed_failure(body):
    _, result = acquire(body)
    assert result.summary.status.value == "failed"
    assert result.receipts[0].error_message == "FUGLE_SCHEMA_OBJECT_REQUIRED"
    assert result.provider_health[0].operational.value == "failed"


def test_conflicting_duplicate_missing_volume_and_missing_price_are_not_fabricated():
    payload = candles_payload()
    payload["data"][0]["volume"] = None
    payload["data"][1].pop("high")
    payload["data"].append({**payload["data"][2], "volume": 10})
    _, result = acquire(payload, bars=True)
    assert len(result.observations) == 1
    assert result.observations[0].volume is None
    assert "FUGLE_REJECTED_BAR_COUNT:2" in result.summary.limitations


@pytest.mark.parametrize("scope,delta,status,reason", [
    ("observed_window", 0, "not_comparable", "partial_window"),
    ("session_prefix", 1, "not_comparable", "event_time_unaligned"),
    ("session_prefix", 0, "matched", "aligned_prefix"),
])
def test_reconciliation_needs_complete_aligned_prefix(scope, delta, status, reason):
    series = {"trade_value_coverage": {"scope": scope, "providers": ["nstock"]},
        "bar_volume_scope": "regular_session_board_lot_observed_window",
        "bar_volume_sum_shares": 6000, "bar_volume_trade_date": NOW.date().isoformat(),
        "bar_volume_latest_time": NOW.isoformat()}
    quote = {"cumulative_trade_value_evidence": {"scope": "regular_session_board_lot_cumulative",
        "volume_shares": 6000, "trade_date": NOW.date().isoformat(), "provider": "fugle_marketdata",
        "event_time": (NOW + timedelta(seconds=delta)).isoformat()}}
    result = reconcile_taiwan_intraday_volume(series, quote)
    assert (result["status"], result["reason"]) == (status, reason)
    quote["cumulative_trade_value_evidence"]["volume_shares"] = 5000
    if scope == "session_prefix" and delta == 0:
        correction = reconcile_taiwan_intraday_volume(series, quote)
        assert correction["difference_shares"] == -1000
        assert correction["reason"] == "source_correction_or_scope_difference"


def ws_acquire(payload, req):
    from hashlib import sha256
    from app.market.providers.fugle_realtime import FugleStreamRecord, fugle_quote_acquisition
    raw = json.dumps({"data": payload})
    record = FugleStreamRecord("aggregates", "6488", payload, raw,
        sha256(raw.encode()).hexdigest(), NOW, NOW, 0)
    return fugle_quote_acquisition(record, req)


def test_ws_without_date_roundtrip_and_same_event_incomplete_replacement(db):
    payload = quote_payload(); payload.pop("date")
    req, _ = acquire(quote_payload())
    owner = TaiwanPublicQuoteTransaction(db)
    owner.persist_quote_acquisition(req, ws_acquire(payload, req))
    quote = TaiwanPublicQuoteRepository(db).load_quote_candidates(INSTRUMENT, requested_at=NOW)[0].observation
    assert quote.cumulative_turnover_value == 602000
    # Complete HTTP may replace WS; a subsequent incomplete WS may not erase it.
    _, http = acquire(quote_payload()); owner.persist_quote_acquisition(req, http)
    payload["total"].pop("tradeValue")
    receipt = owner.persist_quote_acquisition(req, ws_acquire(payload, req))
    assert "FUGLE_SAME_EVENT_INCOMPLETE_SOURCE_REPLACEMENT_REJECTED" in receipt.limitations
    quote = TaiwanPublicQuoteRepository(db).load_quote_candidates(INSTRUMENT, requested_at=NOW)[0].observation
    assert quote.cumulative_turnover_value == 602000
    assert quote.lineage.source == "fugle_intraday_quote"


@pytest.mark.parametrize("policy", [RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE])
def test_fresh_mis_price_without_amount_triggers_only_authorized_amount_fetch(db, policy):
    from types import SimpleNamespace
    from app.market.providers.tw_public_quote import TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR
    from app.market.public_quote_acquisition import TaiwanPublicQuoteAcquisitionExecutor
    from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote, read_taiwan_public_last_trade_quote
    from app.market.quote_volume import project_taiwan_cumulative_totals
    raw = json.dumps({"msgArray": [{"c": "6488", "ex": "otc", "d": "20261028", "t": "09:02:30",
        "z": "100", "tv": "2", "v": "6", "ts": "0"}]})
    fake_mis = TaiwanPublicQuoteAcquisitionExecutor(clock=lambda: NOW, fetchers={TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id:
        lambda *a: SimpleNamespace(text=raw, status_code=200, headers={}, url="https://mis.twse.com.tw/stock/api/getStockInfo.jsp")})
    acquire_taiwan_public_last_trade_quote(db, stock_id="6488", policy=policy, requested_at=NOW,
        acquisition=fake_mis, descriptors=(TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,))
    before = read_taiwan_public_last_trade_quote(db, stock_id="6488", requested_at=NOW)
    assert before.resolved.quote.last_trade_price == 100
    assert before.resolved.quote.cumulative_turnover_value is None
    calls = []
    fugle = FugleHttpAdapter(clock=lambda: NOW, reader=lambda *args: (
        calls.append(args) or FugleHttpPayload(json.dumps(quote_payload()), 200, external_calls=1)))
    result = acquire_taiwan_public_last_trade_quote(db, stock_id="6488", policy=policy, requested_at=NOW,
        acquisition=TaiwanPublicQuoteAcquisitionExecutor(clock=lambda: NOW, fugle=fugle),
        descriptors=(FUGLE_HTTP_QUOTE_DESCRIPTOR,), timeout_seconds=3, max_external_calls=1)
    assert len(calls) == 1 and result.acquisition.external_calls == 1
    after = read_taiwan_public_last_trade_quote(db, stock_id="6488", requested_at=NOW)
    assert len(calls) == 1  # cache-only reread never acquires
    assert after.resolved.quote.last_trade_price == before.resolved.quote.last_trade_price
    evidence = project_taiwan_cumulative_totals(after.resolved.quote)["cumulative_trade_value_evidence"]
    assert evidence["value"] == 602000 and evidence["provider"] == "fugle_marketdata"
    assert evidence["official"] is False


def stored_series(db):
    req, acquired = acquire(candles_payload(), bars=True)
    TaiwanIntradayBarTransaction(db).persist_bar_acquisition(req, acquired)
    return TaiwanBarService(db).read_bars(instrument_id="6488", interval="1m",
        from_time=NOW.replace(minute=0, second=0), to_time=NOW, requested_at=NOW, include_partial=True)


@pytest.mark.parametrize("first_volume,first_amount,expected", [(None, 100000, 102), (0, 100000, 102), (0, 0, 102), (1000, 100000, 101)])
def test_amount_denominator_uses_only_matching_volume_and_mixed_never_doubles(db, first_volume, first_amount, expected):
    from app.market.tw_intraday_value import project_taiwan_intraday_values
    from app.market_data.contracts import Quantity
    series = stored_series(db)
    first = series.bars[0].model_copy(update={"turnover_value": Decimal(first_amount), "turnover_currency": "TWD",
        "volume": Quantity(value=first_volume, unit="share") if first_volume is not None else None})
    second = series.bars[1].model_copy(update={"volume": Quantity(value=1000, unit="share"),
        "high_price": Decimal(102), "low_price": Decimal(102), "close_price": Decimal(102)})
    from types import SimpleNamespace
    prefix = SimpleNamespace(status=SimpleNamespace(value="complete_prefix"), snapshot_bar_count=2)
    result = project_taiwan_intraday_values(series.model_copy(update={"bars": (first, second), "current_session_coverage": prefix}))
    assert result.metadata["approx_vwap"] == expected
    assert result.points[0].trade_value == first_amount and result.points[0].approx_trade_value is None
    assert result.metadata["official_vwap"] is None
    if first_volume == 0 and first_amount:
        assert "ZERO_VOLUME_POSITIVE_AMOUNT_EXCLUDED_FROM_VWAP" in result.metadata["trade_value_coverage"]["limitations"]
        assert result.metadata["trade_value_coverage"]["scope"] == "session_prefix"
        assert result.metadata["estimated_cumulative_trade_value"] is None


@pytest.mark.parametrize("interval", ["1d", "1w", "1mo"])
def test_daily_turnover_never_generates_intraday_scope_or_vwap(db, interval):
    projected = project_taiwan_bar_series(stored_series(db).model_copy(update={"requested_interval": interval}))
    assert "approx_vwap" not in projected and "bar_volume_scope" not in projected


def test_provisional_cutoff_never_claims_future_end(db):
    from app.market.tw_intraday_value import project_taiwan_intraday_values
    series = stored_series(db)
    _, acquired = acquire(candles_payload(), bars=True)
    result = project_taiwan_intraday_values(series.model_copy(update={"bars": acquired.observations}))
    assert result.points[-1].trade_value_asof == NOW
    assert result.metadata["bar_volume_latest_time"] == NOW.isoformat()
    assert result.metadata["trade_value_coverage"]["scope"] == "observed_window"


@pytest.mark.parametrize("explicit_date", [False, True])
def test_public_generated_continuation_binds_window_before_io(db, monkeypatch, explicit_date):
    from app.ai import ask as ask_module
    from app.ai.schemas import AiAskRequest
    params = {"intraday_interval": "1m", "session_scope": "regular"}
    if explicit_date:
        params["trade_date"] = NOW.date().isoformat()
    payload = AiAskRequest(contract_version="omi.decision.v4", question="6488 分K",
        target={"type": "tw_stock", "id": "6488", "market": "TW"},
        mode="data_only", output="evidence_only", payload_level="full",
        selection={"include": ["intraday.bars"], "max_response_bytes": 200000},
        analysis_horizon="intraday",
        realtime_policy="prefer_live", market_data_params=params,
        allow_external_fetch=False, allow_llm=False, allow_write=False)
    monkeypatch.setattr(ask_module.portfolio_service, "get_position_context_for_scope", lambda *a, **kw: None)
    response = ask_module.ask(db, payload)
    plan = response["continuation"]["fill_plan"]
    action = next(item for item in plan["actions"] if item["capability"] == "intraday.bars")
    invoke = action["invoke"]["arguments"]
    assert invoke["market_data_params"]["trade_date"] == NOW.date().isoformat()
    # A valid invocation reaches the pure read; mutations fail before any IO.
    class ReadStarted(BaseException): pass
    calls = []
    monkeypatch.setattr(ask_module.tools, "acquire_taiwan_quote_evidence_projection", lambda **kw: calls.append(kw))
    monkeypatch.setattr(ask_module, "_read_data_only", lambda *a, **kw: (_ for _ in ()).throw(ReadStarted()))
    with pytest.raises(ReadStarted):
        ask_module.ask(db, AiAskRequest(**invoke))
    import copy
    for mutation in ("interval", "date", "extended", "all", "target", "action", "capability", "unselected", "next_session"):
        invalid = copy.deepcopy(invoke)
        if mutation == "interval": invalid["market_data_params"]["intraday_interval"] = "5m"
        if mutation == "date": invalid["market_data_params"]["trade_date"] = "2026-10-27"
        if mutation in {"extended", "all"}: invalid["market_data_params"]["session_scope"] = mutation
        if mutation == "target": invalid["target"]["id"] = "2330"
        if mutation == "action": invalid["continuation"]["selected_action_ids"] = ["fill_invalid"]
        if mutation == "capability": invalid["selection"] = {"include": ["daily.ohlcv"]}
        if mutation == "unselected": invalid["continuation"]["selected_action_ids"] = []
        with monkeypatch.context() as m:
            if mutation == "next_session":
                from app.ai import capability_contract as contract
                original = contract._taiwan_fill_window
                m.setattr(contract, "_taiwan_fill_window", lambda p: {**original(p), "fill_plan_session": "2026-10-29"})
            try:
                ask_module.ask(db, AiAskRequest(**invalid))
            except ValueError:
                pass
            else:
                # An unknown instrument may fail target resolution before the
                # continuation validator; the pure read sentinel still forbids IO.
                assert mutation == "target"
    assert calls == []


def test_current_session_projection_continuation_roundtrips_public_scope(db, monkeypatch):
    from app.ai import ask as ask_module, capability_contract as contract
    from app.ai.schemas import AiAskRequest
    from app.market import tw_intraday_platform
    from test_omi_mcp_server import load_server_module
    from unittest.mock import Mock, patch

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(contract, "datetime", FrozenDateTime)
    eligibility = tw_intraday_platform.completed_taiwan_intraday_repair_eligibility
    monkeypatch.setattr(tw_intraday_platform, "completed_taiwan_intraday_repair_eligibility",
        lambda trade_date, **kw: eligibility(trade_date, now=NOW))
    monkeypatch.setattr(ask_module.portfolio_service, "get_position_context_for_scope", lambda *a, **kw: None)
    series = TaiwanBarService(db).read_bars(instrument_id="6488", interval="1m",
        from_time=NOW.replace(minute=0, second=0), to_time=NOW, requested_at=NOW)
    projected = project_taiwan_bar_series(series, session_scope="current_session", expected_trade_date=NOW.date())
    assert projected["session_scope"] == "current_session" and projected["point_count"] == 0
    context = {"data": {"intraday_bars": projected}, "freshness": {"is_current": False}}
    monkeypatch.setattr(ask_module, "_read_data_only", lambda *a, **kw: ("omi.read_stock_context", context))
    acquire = Mock(side_effect=AssertionError("unexpected quote IO"))
    monkeypatch.setattr(ask_module.tools, "acquire_taiwan_quote_evidence_projection", acquire)
    payload = AiAskRequest(contract_version="omi.decision.v4", question="6488 intraday evidence",
        target={"type": "tw_stock", "id": "6488", "market": "TW"}, mode="data_only", output="evidence_only",
        selection={"include": ["intraday.bars"], "max_response_bytes": 350000}, payload_level="full",
        realtime_policy="cache_only", allow_external_fetch=False, allow_llm=False, allow_write=False,
        market_data_params={"trade_date": NOW.date().isoformat(), "intraday_interval": "1m", "session_scope": "regular"},
        refresh_policy={"before_answer": False})
    response = ask_module.ask(db, payload)
    plan = response["continuation"]["fill_plan"]
    action = next(item for item in plan["actions"] if item["capability"] == "intraday.bars")
    assert action["reason"] == "current_session_intraday"
    invoke = action["invoke"]["arguments"]
    assert invoke["market_data_params"]["session_scope"] == "regular"
    assert response["execution"]["tool_runs"] == []

    # Exercise the existing transport projection without reading local credentials.
    with patch.dict("os.environ", {}, clear=True):
        server = load_server_module()
    monkeypatch.setattr(server, "_default_allow_external_fetch", lambda args: True)
    public_args = {key: value for key, value in invoke.items() if key != "allow_external_fetch"}
    public_args.update(mode="data_only", payload_level="full", tool_budget={
        "max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 12},
        refresh_policy={"before_answer": True, "mode": "stale_first"})
    schema = server.ASK_TOOL["inputSchema"]["properties"]
    assert set(public_args) <= set(schema)
    assert public_args["market_data_params"]["session_scope"] in schema["market_data_params"]["properties"]["session_scope"]["enum"]
    forwarded = server._ask_payload(public_args)
    assert forwarded["continuation"] == invoke["continuation"]
    assert forwarded["market_data_params"]["session_scope"] == "regular"
    assert forwarded["allow_llm"] is False and forwarded["allow_write"] is False
    assert forwarded["allow_external_fetch"] is True
    trusted = ask_module.AiAskServerPolicy(can_external_fetch=True)
    # A full cache-only round trip succeeds without acquisition or job dispatch.
    cached = ask_module.ask(db, AiAskRequest(**{**forwarded, "realtime_policy": "cache_only"}), server_policy=trusted)
    assert cached["execution"]["tool_runs"] == []
    assert cached["continuation"]["fill_plan"]["plan_id"] == plan["plan_id"]

    class ReadStarted(BaseException): pass
    monkeypatch.setattr(ask_module, "_read_data_only", lambda *a, **kw: (_ for _ in ()).throw(ReadStarted()))
    # The authorized 1/1/12 command passes binding validation before the read seam.
    with pytest.raises(ReadStarted):
        ask_module.ask(db, AiAskRequest(**forwarded), server_policy=trusted)
    for changed_window in ({"trade_date": "2026-10-27"}, {"intraday_interval": "5m"},
                           {"session_scope": "extended"}, {"session_scope": "all"}):
        invalid = {**forwarded, "market_data_params": {**forwarded["market_data_params"], **changed_window}}
        with pytest.raises(ValueError, match="unknown or non-executable fill action"):
            ask_module.ask(db, AiAskRequest(**invalid), server_policy=trusted)
    acquire.assert_not_called()
    current = invoke["market_data_params"]
    action_id = lambda params, target=invoke["target"]: contract.fill_action_id(
        capability_id="intraday.bars", target=target, market_data_params=params)
    assert action_id({**current, "session_scope": "current_session"}) == action["action_id"]
    assert action_id({k: v for k, v in current.items() if k != "session_scope"}) == action["action_id"]
    for scope in ("extended", "all"):
        assert action_id({**current, "session_scope": scope}) != action["action_id"]
    previous = {**current, "trade_date": "2026-10-27"}
    assert action_id({**previous, "session_scope": "current_session"}) != action_id(previous)
    us_target = {"type": "us_stock", "id": "TSM", "market": "US"}
    assert action_id({**current, "session_scope": "current_session"}, us_target) != action_id(current, us_target)


def test_quote_elapsed_consumes_same_request_deadline(db, monkeypatch):
    from app.ai import ask as ask_module
    from app.ai.schemas import AiAskRequest
    clock = [0.0]
    seen = []
    monkeypatch.setattr(ask_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ask_module.portfolio_service, "get_position_context_for_scope", lambda *a, **kw: None)
    def slow_quote(**kwargs):
        seen.append(kwargs)
        clock[0] = 26.0
        return {}
    monkeypatch.setattr(ask_module.tools, "acquire_taiwan_quote_evidence_projection", slow_quote)
    monkeypatch.setattr(ask_module, "_read_data_only", lambda *a, **kw: ("reader", {"freshness": {"is_current": False}}))
    class StageReached(BaseException): pass
    def stage(**kwargs):
        budget = kwargs["payload"].tool_budget
        assert budget["max_calls"] == budget["max_external_fetches"] == budget["max_total_seconds"] == 0
        raise StageReached()
    monkeypatch.setattr(ask_module.ask_stages, "execute_tool_stages", stage)
    with pytest.raises(StageReached):
        ask_module.ask(db, AiAskRequest(contract_version="omi.decision.v4", question="6488",
            target={"type": "tw_stock", "id": "6488", "market": "TW"}, mode="data_only", output="evidence_only",
            selection={"include": ["quote.snapshot", "intraday.bars"]}, realtime_policy="prefer_live",
            allow_external_fetch=True,
            tool_budget={"max_calls": 4, "max_external_fetches": 2, "max_total_seconds": 25}),
            server_policy=ask_module.AiAskServerPolicy(can_external_fetch=True))
    assert seen[0]["timeout_seconds"] == 25 and seen[0]["max_external_calls"] == 1


def test_cumulative_clock_is_independent_of_price_and_drives_amount_demand(db):
    from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote, read_taiwan_public_last_trade_quote
    from app.market.public_quote_acquisition import TaiwanPublicQuoteAcquisitionExecutor
    from app.market.quote_volume import project_taiwan_cumulative_totals
    payload = quote_payload(); payload["total"]["time"] -= 600_000_000
    req, acquired = acquire(payload)
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(req, acquired)
    cached = read_taiwan_public_last_trade_quote(db, stock_id="6488", requested_at=NOW)
    amount = project_taiwan_cumulative_totals(cached.resolved.quote)["cumulative_trade_value_evidence"]
    assert amount["freshness"] == "stale" and amount["fresh_amount_usable"] is False
    assert cached.resolved.candidates[0].freshness.value in {"live", "fresh"}
    calls = []
    adapter = FugleHttpAdapter(clock=lambda: NOW, reader=lambda *a: calls.append(a) or FugleHttpPayload(json.dumps(quote_payload()), 200, external_calls=1))
    acquire_taiwan_public_last_trade_quote(db, stock_id="6488", policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW,
        acquisition=TaiwanPublicQuoteAcquisitionExecutor(clock=lambda: NOW, fugle=adapter), descriptors=(FUGLE_HTTP_QUOTE_DESCRIPTOR,))
    assert len(calls) == 1
    # Reverse clocks: a fresh amount must not make the old price live.
    payload = quote_payload(); payload["lastTrade"]["time"] -= 600_000_000
    req, acquired = acquire(payload)
    db.query(__import__('app.db.models', fromlist=['TaiwanStockQuoteSnapshot']).TaiwanStockQuoteSnapshot).delete()
    db.commit()
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(req, acquired)
    cached = read_taiwan_public_last_trade_quote(db, stock_id="6488", requested_at=NOW)
    assert cached.resolved.candidates[0].freshness.value == "stale"
    assert project_taiwan_cumulative_totals(cached.resolved.quote)["cumulative_trade_value_evidence"]["fresh_amount_usable"] is True


@pytest.mark.parametrize("seconds,calls", [(0, 1), (1, 0)])
def test_cold_session_close_zero_budget_never_resurrects_defaults(db, seconds, calls):
    from app.market.taiwan_quote_evidence import acquire_taiwan_quote_evidence_bundle
    from unittest.mock import Mock
    adapter = Mock()
    bundle = acquire_taiwan_quote_evidence_bundle(db, stock_id="6488", requested_at=NOW.replace(hour=15),
        requested_capabilities=("quote.session_close",), acquisition=adapter,
        timeout_seconds=seconds, max_external_calls=calls)
    assert not adapter.mock_calls
    assert "ACQUISITION_BUDGET_ZERO" in bundle.session_close.acquisition.limitations


def test_public_continuation_runs_existing_job_persists_rereads_and_replay_deduplicates(db, monkeypatch):
    from app.ai import ask as ask_module, agentic_common
    from app.ai.schemas import AiAskRequest
    from app.jobs import taiwan_intraday_demand as demand
    from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(ask_module.portfolio_service, "get_position_context_for_scope", lambda *a, **kw: None)
    monkeypatch.setattr(demand, "_now", lambda: NOW)
    monkeypatch.setattr(agentic_common, "_now", lambda: NOW)
    factory = sessionmaker(db.get_bind())
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    requests = []
    def reader(*args):
        requests.append(args)
        return FugleHttpPayload(json.dumps(candles_payload()), 200, external_calls=1)
    fake = FugleHttpAdapter(clock=lambda: NOW, reader=reader)
    monkeypatch.setattr(demand, "TaiwanIntradayAcquisitionExecutor", lambda **kw: TaiwanIntradayAcquisitionExecutor(fugle=fake, **kw))
    def sync_submit(task, job_id, **kwargs):
        task(job_id)
        db.expire_all()
    monkeypatch.setattr(demand.jobs, "submit_job_task", sync_submit)
    server = ask_module.AiAskServerPolicy(can_external_fetch=True)
    payload = AiAskRequest(contract_version="omi.decision.v4", question="6488 intraday evidence",
        target={"type": "tw_stock", "id": "6488", "market": "TW"}, mode="data_only", output="evidence_only",
        selection={"include": ["intraday.bars"], "max_response_bytes": 200000}, payload_level="full",
        realtime_policy="prefer_live", allow_external_fetch=True, allow_write=False, allow_llm=False,
        refresh_policy={"before_answer": False, "mode": "stale_first"})
    planned = ask_module.ask(db, payload, server_policy=server)
    invoke = planned["continuation"]["fill_plan"]["actions"][0]["invoke"]["arguments"]
    invoke.update(mode="data_only", allow_llm=False, allow_write=False,
        refresh_policy={"before_answer": True, "mode": "stale_first"}, payload_level="full")
    response = ask_module.ask(db, AiAskRequest(**invoke), server_policy=server)
    assert len(requests) == 1
    assert db.query(MarketIntradayBar).count() == 3
    assert response["execution"]["tool_runs"][0]["status"] == "success", response["execution"]["tool_runs"]
    intraday = response["evidence"]["data"]["intraday.bars"]
    assert intraday["points"] and intraday["points"][0]["approx_trade_value"] is not None
    assert intraday["volume_reconciliation"]["reason"] == "quote_cumulative_unavailable"
    repeated = ask_module.ask(db, AiAskRequest(**invoke), server_policy=server)
    assert len(requests) == 1 and db.query(MarketIntradayBar).count() == 3
    assert repeated["evidence"]["data"]["intraday.bars"]["points"]
    assert repeated["execution"]["tool_runs"][0]["job"]["deduplicated"] is True
    quote_req, quote_result = acquire(quote_payload())
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(quote_req, quote_result)
    cache_payload = payload.model_copy(update={"selection": {"include": ["quote.snapshot", "intraday.bars"],
        "max_response_bytes": 200000}, "realtime_policy": "cache_only", "allow_external_fetch": False})
    cached = ask_module.ask(db, cache_payload, server_policy=server)
    outward_quote = cached["evidence"]["data"]["quote.snapshot"]
    assert outward_quote["cumulative_trade_value"] == 602000
    assert outward_quote["cumulative_trade_value_evidence"]["source"] == "fugle_intraday_quote"
    assert cached["execution"]["tool_runs"] == []


@pytest.mark.parametrize("status,reason", [(401, "FUGLE_AUTH_FAILED"), (403, "FUGLE_PLAN_RESTRICTED"), (429, "FUGLE_RATE_LIMITED")])
def test_http_failures_are_typed_and_429_does_not_retry(monkeypatch, status, reason):
    from app.market.providers import fugle_http as http
    from types import SimpleNamespace
    from collections import deque
    from threading import Lock
    monkeypatch.setattr(http.settings, "fugle_api_key", "offline-fixture")
    monkeypatch.setattr(http, "_calls", deque())
    monkeypatch.setattr(http, "_cooldown_until", 0.0)
    monkeypatch.setattr(http, "_transport", Lock())
    calls = []
    monkeypatch.setattr(http, "get", lambda *a, **kw: calls.append(a) or SimpleNamespace(status_code=status, text="do not expose provider body"))
    result = http.read_fugle_http("quote", "6488", 1)
    assert result.error == reason and result.external_calls == 1 and result.raw_text is None
    if status == 429:
        second = http.read_fugle_http("candles", "6488", 1)
        assert second.error == reason and second.external_calls == 0
    assert len(calls) == 1


def test_timed_out_http_retains_single_flight_without_waiting_or_late_persistence(monkeypatch):
    from app.market.providers import fugle_http as http
    from collections import deque
    from threading import Lock, Event
    from types import SimpleNamespace
    release, finished = Event(), Event()
    monkeypatch.setattr(http.settings, "fugle_api_key", "offline-fixture")
    monkeypatch.setattr(http, "_calls", deque())
    monkeypatch.setattr(http, "_cooldown_until", 0.0)
    monkeypatch.setattr(http, "_transport", Lock())
    def delayed(*a, **kw):
        try:
            release.wait(2)
            return SimpleNamespace(status_code=200, text=json.dumps(quote_payload()))
        finally:
            finished.set()
    monkeypatch.setattr(http, "get", delayed)
    try:
        first = http.read_fugle_http("quote", "6488", 0)
        second = http.read_fugle_http("candles", "6488", 1)
        assert first.error == "FUGLE_TIMEOUT" and first.raw_text is None
        assert second.error == "FUGLE_PREVIOUS_TRANSPORT_IN_FLIGHT" and second.external_calls == 0
    finally:
        release.set()
        assert finished.wait(2)
