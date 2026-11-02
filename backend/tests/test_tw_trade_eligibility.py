"""Narrow F04 fixtures: historical dates are research inputs, never live prices."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_trade_eligibility import (
    BorrowEvidence, BrokerEligibilityEvidence, CapitalAmount, EligibilityEvidence,
    EligibilityEvent, EligibilityPrice, EligibilityRequest, EventCoverage,
    EventRiskPolicy, EvidenceStamp, FundingEvidence, MarginContext,
    RegulationEvidence, evaluate_tw_trade_eligibility, holding_sessions,
    read_tw_trade_eligibility_evidence,
)


CUTOFF = datetime(2026, 10, 27, 16, tzinfo=TAIWAN_TZ)
AS_OF = date(2026, 10, 27)
ENTRY = date(2026, 10, 28)
EVENT_TYPES = tuple(key for key in EventRiskPolicy.model_fields if key != "version")


def stamp(**changes):
    return EvidenceStamp(**{"source": "fixture-owner", "as_of": AS_OF,
        "available_at": CUTOFF - timedelta(minutes=1), "status": "current", **changes})


def price(value="48.5", **changes):
    return EligibilityPrice(price=Decimal(value), evidence=stamp(**changes), qualified=True)


def request(**changes):
    return EligibilityRequest(**{"stock_id": "3481", "market": "TWSE", "direction": "short",
        "as_of_trade_date": AS_OF, "requested_at": CUTOFF, "entry_trade_date": ENTRY,
        "horizon_sessions": 10, "quantity": 1000, "candidate_research_eligible": True,
        "reference_price": price(), "current_quote": price(), **changes})


def evidence(**changes):
    return EligibilityEvidence(**{"stock_id": "3481", "market": "TWSE",
        "event_coverage": EventCoverage(status="complete", date_from=ENTRY,
            date_to=date(2026, 12, 1), covered_event_types=EVENT_TYPES, sources=(stamp(),)),
        "regulation": RegulationEvidence(evidence=stamp(), disposition_active=False,
            margin_trading_suspended=False),
        "borrow": BorrowEvidence(broker_id="fixture-broker", evidence=stamp(),
            available_shares=1000, valid_until=CUTOFF + timedelta(minutes=1)),
        "funding": FundingEvidence(available=CapitalAmount(amount_twd="100000", evidence=stamp()),
            required=CapitalAmount(amount_twd="50000.25", evidence=stamp(source="F03-all-in-requirement"))),
        "broker": BrokerEligibilityEvidence(broker_id="fixture-broker", evidence=stamp(), eligible=True),
        **changes})


def event(kind="investor_conference", day=date(2026, 11, 3), **changes):
    return EligibilityEvent(**{"event_type": kind, "start_date": day, "end_date": day,
        "event_time": "14:00", "evidence": stamp(source="MOPS cached fixture"), **changes})


def codes(result):
    return {item.code for item in result.ineligibility_reason}


@pytest.mark.parametrize("symbol,day", [
    ("2303", date(2026, 10, 28)), ("2409", date(2026, 10, 29)), ("2344", date(2026, 11, 3)),
])
@pytest.mark.parametrize("horizon", [10, 15])
def test_historical_conferences_are_ranking_risk_without_banning_research(symbol, day, horizon):
    req = request(stock_id=symbol, horizon_sessions=horizon)
    ev = evidence(stock_id=symbol, events=(event(day=day),))
    result = evaluate_tw_trade_eligibility(req, ev)
    assert result.research_eligible is True
    assert result.regulation_eligible is True
    assert result.broker_execution_eligible is True  # Explicit synthetic broker evidence only.
    assert result.event_risk[0].event.start_date == day
    assert result.event_risk[0].event.event_time == "14:00"
    assert result.event_risk_score == 2
    assert result.event_risk[0].event.evidence.available_at < CUTOFF
    assert len(result.holding_sessions) == horizon
    assert result.model_dump(mode="json")["request"]["stock_id"] == symbol


def test_exact_session_windows_and_weekend_event_boundaries():
    ten, fifteen = request(), request(horizon_sessions=15)
    assert holding_sessions(ten)[-1] == date(2026, 11, 10)
    assert holding_sessions(fifteen)[-1] == date(2026, 11, 17)
    events = (event(day=date(2026, 10, 27)), event(day=ENTRY),
        event("ex_dividend", date(2026, 10, 31)), event(day=date(2026, 11, 10)),
        event(day=date(2026, 11, 11)))
    r10 = evaluate_tw_trade_eligibility(ten, evidence(events=events))
    r15 = evaluate_tw_trade_eligibility(fifteen, evidence(events=events))
    assert [r.event.start_date for r in r10.event_risk] == [ENTRY, date(2026, 10, 31), date(2026, 11, 10)]
    assert len(r15.event_risk) == 4


@pytest.mark.parametrize("reference,current,research,execution", [
    ("199.5", "199.5", True, True), ("200", "199.5", False, False),
    ("200.5", "199.5", False, False), ("199.5", "200", True, False),
    ("199.5", "200.5", True, False),
])
def test_short_price_cap_is_strict_and_research_is_separate(reference, current, research, execution):
    result = evaluate_tw_trade_eligibility(request(reference_price=price(reference),
        current_quote=price(current)), evidence())
    assert result.research_eligible is research
    assert result.broker_execution_eligible is execution


@pytest.mark.parametrize("quote", [None, price(status="stale"), price(as_of=date(2026, 10, 26)),
    price(available_at=CUTOFF + timedelta(seconds=1)),
    EligibilityPrice(price=48, evidence=stamp(), qualified=False)])
def test_current_quote_missing_stale_or_unqualified_leaves_execution_unknown(quote):
    result = evaluate_tw_trade_eligibility(request(current_quote=quote), evidence())
    assert result.research_eligible is True
    assert result.current_price_eligible == "unknown"
    assert result.broker_execution_eligible == "unknown"
    assert "CURRENT_QUOTE_UNKNOWN" in codes(result)


@pytest.mark.parametrize("reference", [None, price(status="stale"),
    price(available_at=CUTOFF + timedelta(days=1))])
def test_missing_or_future_reference_does_not_qualify_research(reference):
    result = evaluate_tw_trade_eligibility(request(reference_price=reference), evidence())
    assert result.research_eligible == "unknown"
    assert result.broker_execution_eligible == "unknown"
    assert "REFERENCE_PRICE_UNKNOWN" in codes(result)


@pytest.mark.parametrize("disposition,suspended,expected,code", [
    (True, False, False, "ACTIVE_DISPOSITION"),
    (False, True, False, "MARGIN_TRADING_SUSPENDED"),
    (False, False, True, None), (False, None, "unknown", "REGULATION_UNKNOWN"),
    (None, None, "unknown", "REGULATION_UNKNOWN"),
])
def test_regulation_axes(disposition, suspended, expected, code):
    reg = RegulationEvidence(evidence=stamp(), disposition_active=disposition,
        margin_trading_suspended=suspended)
    result = evaluate_tw_trade_eligibility(request(), evidence(regulation=reg))
    assert result.regulation_eligible == expected
    assert result.research_eligible is True
    if code:
        assert code in codes(result)


@pytest.mark.parametrize("borrow,expected", [
    (None, "unknown"),
    (BorrowEvidence(broker_id="fixture-broker", evidence=stamp(), available_shares=0,
        valid_until=CUTOFF + timedelta(minutes=1)), False),
    (BorrowEvidence(broker_id="fixture-broker", evidence=stamp(), available_shares=999,
        valid_until=CUTOFF + timedelta(minutes=1)), False),
    (BorrowEvidence(broker_id="fixture-broker", evidence=stamp(), available_shares=9999,
        valid_until=CUTOFF - timedelta(seconds=1)), "unknown"),
])
def test_public_margin_and_no_disposition_never_imply_broker_borrow(borrow, expected):
    margin = MarginContext(evidence=stamp(), short_balance_lots=20000, short_limit_lots=50000)
    result = evaluate_tw_trade_eligibility(request(), evidence(borrow=borrow, margin=margin))
    assert result.borrow_available == expected
    assert result.regulation_eligible is True
    assert result.broker_execution_eligible == expected
    assert result.evidence.margin.short_limit_lots == 50000


@pytest.mark.parametrize("available,required,expected", [
    (None, "50000", "unknown"), ("100000", None, "unknown"),
    ("49999.99", "50000", False), ("50000", "50000", True), ("0", "50000", False),
])
def test_f03_capital_requirement_and_user_budget_remain_explicit(available, required, expected):
    funds = FundingEvidence(
        available=CapitalAmount(amount_twd=available, evidence=stamp()) if available is not None else None,
        required=CapitalAmount(amount_twd=required, evidence=stamp(source="F03")) if required is not None else None)
    result = evaluate_tw_trade_eligibility(request(), evidence(funding=funds))
    assert result.funding_sufficient == expected
    assert result.broker_execution_eligible == expected
    assert result.research_eligible is True


@pytest.mark.parametrize("fund_stamp", [stamp(status="stale"),
    stamp(available_at=CUTOFF + timedelta(days=1))])
def test_outdated_or_future_user_funding_is_unknown(fund_stamp):
    funds = FundingEvidence(available=CapitalAmount(amount_twd=100000, evidence=fund_stamp),
        required=evidence().funding.required)
    result = evaluate_tw_trade_eligibility(request(), evidence(funding=funds))
    assert result.funding_sufficient == "unknown"


@pytest.mark.parametrize("kind", ["short_sale_suspension", "mandatory_cover", "suspension"])
def test_restrictions_block_only_an_overlapping_planned_holding(kind):
    inside = evaluate_tw_trade_eligibility(request(), evidence(events=(event(kind),)))
    outside = evaluate_tw_trade_eligibility(request(), evidence(events=(event(kind, date(2026, 11, 11)),)))
    longer = evaluate_tw_trade_eligibility(request(horizon_sessions=15),
        evidence(events=(event(kind, date(2026, 11, 11)),)))
    assert inside.regulation_eligible is False
    assert inside.broker_execution_eligible is False
    assert inside.research_eligible is True
    assert outside.regulation_eligible is True
    assert not outside.event_risk
    assert longer.regulation_eligible is False


@pytest.mark.parametrize("coverage", [EventCoverage(),
    EventCoverage(status="partial", date_from=ENTRY, date_to=date(2026, 12, 1), sources=(stamp(),)),
    EventCoverage(status="complete", date_from=ENTRY, date_to=date(2026, 11, 1), sources=(stamp(),), covered_event_types=EVENT_TYPES),
    EventCoverage(status="complete", date_from=ENTRY, date_to=date(2026, 12, 1), sources=(stamp(),), covered_event_types=EVENT_TYPES, truncated=True),
])
def test_empty_or_partial_event_coverage_does_not_mean_clear(coverage):
    result = evaluate_tw_trade_eligibility(request(), evidence(event_coverage=coverage))
    assert result.event_risk_score is None
    assert result.event_coverage_complete is False
    assert result.broker_execution_eligible == "unknown"
    assert result.research_eligible is True
    assert "EVENT_COVERAGE_INCOMPLETE" in codes(result)


def test_events_are_deduplicated_and_future_cache_does_not_leak_into_replay():
    known = event()
    future = event("mandatory_cover", evidence=stamp(available_at=CUTOFF + timedelta(days=1)))
    unverified = event(evidence=stamp(status="stale"))
    ev = evidence(events=(unverified, known, known, future, event("ex_dividend", status="cancelled")))
    result = evaluate_tw_trade_eligibility(request(), ev)
    assert len(result.event_risk) == 1
    assert result.event_risk[0].verified
    assert result.observed_event_risk_score == 2
    assert result.event_risk_score is None
    assert result.regulation_eligible is True
    assert "EVENT_EVIDENCE_UNVERIFIED" in codes(result)
    assert result == evaluate_tw_trade_eligibility(request(), ev)
    custom = evaluate_tw_trade_eligibility(request(), ev,
        EventRiskPolicy(version="fixture.v2", investor_conference=7))
    assert custom.observed_event_risk_score == 7
    assert custom.event_policy.version == "fixture.v2"


def test_one_event_id_cannot_be_double_weighted_as_conference_and_report():
    ev = evidence(events=(event(event_id="same-fact"), event("financial_report", event_id="same-fact")))
    result = evaluate_tw_trade_eligibility(request(), ev)
    assert len(result.event_risk) == 1
    assert result.event_risk[0].event.event_type == "financial_report"
    assert result.event_risk_score == 3
    with pytest.raises(ValidationError, match="distinct policy version"):
        EventRiskPolicy(investor_conference=7)


def test_long_does_not_require_short_inventory_or_short_price_cap():
    result = evaluate_tw_trade_eligibility(request(direction="long", reference_price=price("1000"),
        current_quote=price("1000")), evidence(borrow=None,
        events=(event("mandatory_cover"),), regulation=RegulationEvidence(
            evidence=stamp(), disposition_active=False, margin_trading_suspended=True)))
    assert result.borrow_available == "unknown"  # Cash long does not require borrow.
    assert result.broker_execution_eligible is True


def test_broker_and_calendar_unknown_and_known_blocks_dominate(monkeypatch):
    import app.market.tw_trade_eligibility as module

    assert evaluate_tw_trade_eligibility(request(), evidence(broker=None)).broker_execution_eligible == "unknown"
    wrong_broker = BrokerEligibilityEvidence(broker_id="other", eligible=True, evidence=stamp())
    assert "BROKER_IDENTITY_MISMATCH" in codes(evaluate_tw_trade_eligibility(request(), evidence(broker=wrong_broker)))
    monkeypatch.setattr(module, "has_taiwan_calendar_year", lambda year: False)
    unknown = evaluate_tw_trade_eligibility(request(), evidence())
    assert unknown.holding_sessions == ()
    assert unknown.broker_execution_eligible == "unknown"
    blocked = evaluate_tw_trade_eligibility(request(current_quote=price(status="stale")),
        evidence(regulation=RegulationEvidence(evidence=stamp(), disposition_active=True)))
    assert blocked.broker_execution_eligible is False


@pytest.mark.parametrize("changes", [
    {"quantity": 0}, {"quantity": True}, {"horizon_sessions": 14},
    {"candidate_research_eligible": 1}, {"entry_trade_date": date(2026, 10, 31)},
    {"requested_at": datetime(2026, 10, 27, 16)},
])
def test_invalid_inputs_are_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_identity_and_nonfinite_money_are_rejected():
    with pytest.raises(ValueError, match="identities"):
        evaluate_tw_trade_eligibility(request(), evidence(stock_id="2303"))
    for value in ("NaN", "Infinity", "-1"):
        with pytest.raises(ValidationError):
            CapitalAmount(amount_twd=value, evidence=stamp())


def test_read_seam_reuses_real_cache_owners_and_never_manufactures_borrow(monkeypatch):
    from app.market import service, tw_corporate_events, tw_disposition

    fetched = (CUTOFF - timedelta(minutes=1)).isoformat()
    config = tw_corporate_events.PROVIDER_CONFIG
    rows = [{"event_id": f"historical-{symbol}", "stock_id": symbol, "market": "TWSE",
        "event_type": "investor_conference", "start_date": day, "end_date": day,
        "start_time": "14:00", "title": "歷史法說 fixture", "provider": "mops",
        "source_name": config["mops_conference"]["source"]}
        for symbol, day in [("2303", "2026-10-28"), ("2409", "2026-10-29"), ("2344", "2026-11-03")]]
    cache = {"providers": {key: {"fetched_at": fetched, "entries": rows if key == "mops_conference" else []}
        for key in tw_corporate_events.CURRENT_PROVIDER_KEYS}}
    monkeypatch.setattr(tw_corporate_events, "read_taiwan_corporate_event_cache", lambda **kwargs: cache)
    monkeypatch.setattr(tw_disposition, "read_taiwan_disposition_cache", lambda **kwargs: {
        "providers": {"twse": {"fetched_at": fetched, "entries": []}}})
    listing = Mock(wraps=tw_corporate_events.list_taiwan_corporate_events)
    reg_read = Mock(wraps=tw_disposition.get_taiwan_disposition_status)
    monkeypatch.setattr(tw_corporate_events, "list_taiwan_corporate_events", listing)
    monkeypatch.setattr(tw_disposition, "get_taiwan_disposition_status", reg_read)
    no_refresh = Mock(side_effect=AssertionError("read seam must never refresh"))
    monkeypatch.setattr(tw_corporate_events, "refresh_taiwan_corporate_events", no_refresh)
    monkeypatch.setattr(tw_disposition, "refresh_taiwan_dispositions", no_refresh)
    margin_read = Mock(return_value=[SimpleNamespace(trade_date=AS_OF, updated_at=CUTOFF,
        id=3, raw_result_id=4, margin_today_balance=100, short_today_balance=50, short_next_limit=500)])
    monkeypatch.setattr(service, "list_stock_margin_trade_history", margin_read)
    db = object()
    for symbol in ("2303", "2409", "2344"):
        req = request(stock_id=symbol)
        ev = read_tw_trade_eligibility_evidence(req, db=db)
        result = evaluate_tw_trade_eligibility(req, ev)
        assert len(result.event_risk) == 1
        assert result.event_risk[0].verified
        assert ev.borrow is None
        assert result.borrow_available == "unknown"
        assert result.funding_sufficient == "unknown"
        assert result.broker_execution_eligible == "unknown"
        assert not result.event_coverage_complete
        assert ev.margin.short_limit_lots == 500
        assert ev.margin.evidence.source_ref == "margin_trading_daily:3:raw:4"
    assert listing.call_count == reg_read.call_count == margin_read.call_count == 3
    assert listing.call_args.kwargs["limit"] == 100
    assert listing.call_args.kwargs["date_to"] == date(2026, 11, 10)
    assert margin_read.call_args.kwargs == {"to_date": AS_OF, "limit": 1, "ascending": False}
    no_refresh.assert_not_called()
    margin_read.return_value[0].updated_at = CUTOFF + timedelta(days=1)
    future_margin = read_tw_trade_eligibility_evidence(request(stock_id="2303"), db=db).margin
    assert future_margin.evidence.status == "missing"
    assert future_margin.short_balance_lots is None
    assert future_margin.short_limit_lots is None
