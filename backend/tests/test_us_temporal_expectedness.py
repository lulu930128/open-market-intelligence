from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai.decision_envelope_v4 import _brief_capability_summary
from app.market_data.contracts import (
    CapabilityExpectation,
    EvidenceFreshness,
    InstrumentType,
    TradeObservationState,
)
from app.us_market.temporal_expectedness import (
    USCapabilityAvailability,
    USCapabilityExpectationOutcome,
    USCapabilitySessionScope,
    USCapabilitySupportStatus,
    USTradeRecency,
    build_us_capability_expectation,
    build_us_session_date_relation,
    evaluate_us_selected_evidence_temporal,
    select_us_intraday_trade_date,
)


NEW_YORK = ZoneInfo("America/New_York")


def _projection(
    *,
    capability_id: str = "quote.snapshot",
    phase: str,
    availability: USCapabilityAvailability,
    freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN,
    trade_state: TradeObservationState = TradeObservationState.UNKNOWN,
    trade_recency: USTradeRecency = USTradeRecency.UNKNOWN,
):
    return build_us_capability_expectation(
        capability_id=capability_id,
        market_phase=phase,
        requested_session_scope=USCapabilitySessionScope.ALL,
        instrument_type=InstrumentType.STOCK,
        availability=availability,
        evidence_freshness=freshness,
        provider_snapshot_freshness=freshness,
        trade_state=trade_state,
        trade_recency=trade_recency,
    )


def test_premarket_cache_miss_is_expected_but_missing() -> None:
    projection = _projection(
        phase="pre_market",
        availability=USCapabilityAvailability.MISSING,
    )

    assert projection.expectation is CapabilityExpectation.EXPECTED
    assert projection.expected_session_scope is USCapabilitySessionScope.EXTENDED
    assert projection.outcome is USCapabilityExpectationOutcome.EXPECTED_BUT_MISSING
    assert projection.requirement_satisfied is False
    assert projection.reason_code == "EXPECTED_CURRENT_QUOTE_MISSING"


def test_regular_intraday_cache_miss_is_required() -> None:
    projection = _projection(
        capability_id="intraday.bars",
        phase="regular",
        availability=USCapabilityAvailability.MISSING,
    )

    assert projection.expectation is CapabilityExpectation.REQUIRED
    assert projection.required_now is True
    assert projection.expected_session_scope is USCapabilitySessionScope.REGULAR
    assert projection.reason_code == "EXPECTED_INTRADAY_BARS_MISSING"


def test_closed_empty_is_not_expected_instead_of_missing_defect() -> None:
    projection = _projection(
        phase="market_closed",
        availability=USCapabilityAvailability.MISSING,
    )

    assert projection.expectation is CapabilityExpectation.NOT_EXPECTED
    assert projection.outcome is USCapabilityExpectationOutcome.NOT_EXPECTED
    assert projection.requirement_satisfied is None
    assert projection.reason_code == "MARKET_CLOSED"


def test_fresh_provider_snapshot_with_old_trade_is_not_current() -> None:
    projection = _projection(
        phase="pre_market",
        availability=USCapabilityAvailability.AVAILABLE,
        freshness=EvidenceFreshness.FRESH,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        trade_recency=USTradeRecency.OLD,
    )

    assert projection.outcome is USCapabilityExpectationOutcome.STALE
    assert projection.requirement_satisfied is False
    assert projection.reason_code == "LAST_TRADE_OLD"


def test_selected_evidence_keeps_event_recency_separate_from_fetch_recency() -> None:
    now = datetime(2026, 9, 2, 11, 0, tzinfo=NEW_YORK)
    temporal = evaluate_us_selected_evidence_temporal(
        now=now,
        market_phase="regular",
        session_scope=USCapabilitySessionScope.ALL,
        event_at=now - timedelta(minutes=16),
        fetched_at=now - timedelta(seconds=5),
        selected_freshness=EvidenceFreshness.FRESH,
    )

    assert temporal.current_session_satisfied is True
    assert temporal.provider_snapshot_freshness is EvidenceFreshness.FRESH
    assert temporal.trade_recency is USTradeRecency.OLD
    assert temporal.evidence_freshness is EvidenceFreshness.STALE


def test_selected_evidence_accepts_recent_current_session_event() -> None:
    now = datetime(2026, 9, 2, 11, 0, tzinfo=NEW_YORK)
    temporal = evaluate_us_selected_evidence_temporal(
        now=now,
        market_phase="regular",
        session_scope=USCapabilitySessionScope.ALL,
        event_at=now - timedelta(seconds=60),
        fetched_at=now - timedelta(seconds=5),
        selected_freshness=EvidenceFreshness.FRESH,
    )

    assert temporal.current_session_satisfied is True
    assert temporal.trade_recency is USTradeRecency.CURRENT
    assert temporal.evidence_freshness is EvidenceFreshness.FRESH


def test_selected_evidence_rejects_previous_session_even_when_just_fetched() -> None:
    now = datetime(2026, 9, 2, 11, 0, tzinfo=NEW_YORK)
    temporal = evaluate_us_selected_evidence_temporal(
        now=now,
        market_phase="regular",
        session_scope=USCapabilitySessionScope.ALL,
        event_at=datetime(2026, 9, 1, 15, 59, tzinfo=NEW_YORK),
        fetched_at=now - timedelta(seconds=5),
        selected_freshness=EvidenceFreshness.FRESH,
    )

    assert temporal.current_session_satisfied is False
    assert temporal.trade_recency is USTradeRecency.HISTORICAL
    assert temporal.evidence_freshness is EvidenceFreshness.STALE


def test_intraday_date_selection_does_not_promote_previous_session() -> None:
    selection = select_us_intraday_trade_date(
        [date(2026, 9, 1)],
        now=datetime(2026, 9, 2, 9, 54, tzinfo=NEW_YORK),
        market_phase="regular",
    )

    assert selection.expected_trade_date == date(2026, 9, 2)
    assert selection.latest_available_trade_date == date(2026, 9, 1)
    assert selection.selected_trade_date is None
    assert selection.current_session_expected is True
    assert selection.current_session_satisfied is False
    assert selection.selection_reason == "EXPECTED_CURRENT_SESSION_MISSING"


def test_intraday_date_selection_prefers_current_session_from_mixed_cache() -> None:
    selection = select_us_intraday_trade_date(
        [date(2026, 9, 1), date(2026, 9, 2)],
        now=datetime(2026, 9, 2, 9, 54, tzinfo=NEW_YORK),
        market_phase="regular",
    )

    assert selection.selected_trade_date == date(2026, 9, 2)
    assert selection.current_session_satisfied is True
    assert selection.selection_reason == "CURRENT_SESSION_AVAILABLE"


def test_intraday_date_selection_allows_latest_historical_off_session() -> None:
    selection = select_us_intraday_trade_date(
        [date(2026, 9, 1), date(2026, 9, 2)],
        now=datetime(2026, 9, 2, 21, 0, tzinfo=NEW_YORK),
        market_phase="market_closed",
    )

    assert selection.expected_trade_date is None
    assert selection.selected_trade_date == date(2026, 9, 2)
    assert selection.current_session_expected is False
    assert selection.selection_reason == "LATEST_AVAILABLE_OFF_SESSION"


def test_awaiting_first_trade_is_valid_empty() -> None:
    projection = _projection(
        phase="after_hours",
        availability=USCapabilityAvailability.VALID_EMPTY,
        freshness=EvidenceFreshness.FRESH,
        trade_state=TradeObservationState.AWAITING_FIRST_TRADE,
        trade_recency=USTradeRecency.MISSING,
    )

    assert projection.outcome is USCapabilityExpectationOutcome.VALID_EMPTY
    assert projection.requirement_satisfied is True
    assert projection.reason_code == "NO_TRADE_OBSERVED"


def test_expected_stale_snapshot_is_not_ready() -> None:
    projection = _projection(
        phase="regular",
        availability=USCapabilityAvailability.AVAILABLE,
        freshness=EvidenceFreshness.STALE,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        trade_recency=USTradeRecency.OLD,
    )

    assert projection.outcome is USCapabilityExpectationOutcome.STALE
    assert projection.requirement_satisfied is False
    assert projection.reason_code == "PROVIDER_SNAPSHOT_STALE"


def test_descriptor_inventory_owns_applicability_and_support() -> None:
    projection = build_us_capability_expectation(
        capability_id="quote.snapshot",
        market_phase="pre_market",
        requested_session_scope=USCapabilitySessionScope.ALL,
        instrument_type=InstrumentType.STOCK,
        availability=USCapabilityAvailability.MISSING,
        descriptors=(),
    )

    assert projection.applicability.value == "not_applicable"
    assert projection.support_status is USCapabilitySupportStatus.UNSUPPORTED
    assert projection.outcome is USCapabilityExpectationOutcome.NOT_APPLICABLE


def test_ai_brief_preserves_backend_temporal_projection() -> None:
    expectedness = {
        "contract_version": "omi.us.capability_expectation.v1",
        "capability_id": "quote.snapshot",
        "market_phase": "after_hours",
        "expectation": "expected",
        "outcome": "expected_but_missing",
    }
    quote = _brief_capability_summary(
        "quote.snapshot",
        {
            "status": "missing",
            "market_phase": "after_hours",
            "capability_expectation": expectedness,
            "change_reference_price": 101.5,
            "change_reference_type": "current_day_regular_close",
            "change_reference_trade_date": "2026-08-28",
        },
    )
    bars = _brief_capability_summary(
        "intraday.bars",
        {
            "market_phase": "after_hours",
            "capability_expectation": {
                "intraday.bars": expectedness,
            },
            "change_reference_price": 101.5,
            "change_reference_type": "current_day_regular_close",
            "change_reference_trade_date": "2026-08-28",
            "points": [],
        },
    )

    assert quote["capability_expectation"] == expectedness
    assert quote["change_reference_type"] == "current_day_regular_close"
    assert bars["capability_expectation"] == {"intraday.bars": expectedness}
    assert bars["change_reference_price"] == 101.5


def test_us_session_date_relation_accepts_regular_quote_vs_completed_daily() -> None:
    relation = build_us_session_date_relation(
        quote_date="2026-08-31",
        completed_daily_date="2026-08-28",
        now=datetime(2026, 8, 31, 10, 0, tzinfo=NEW_YORK),
        market_phase="regular",
    )

    assert relation["status"] == "aligned"
    assert relation["expected"] is True
    assert relation["relation"] == "current_session_daily_pending_release"
    assert relation["expected_completed_daily_date"] == "2026-08-28"


def test_us_session_date_relation_accepts_post_release_same_date() -> None:
    relation = build_us_session_date_relation(
        quote_date="2026-08-31",
        completed_daily_date="2026-08-31",
        now=datetime(2026, 8, 31, 17, 0, tzinfo=NEW_YORK),
        market_phase="post_close",
    )

    assert relation["status"] == "aligned"
    assert relation["relation"] == "same_observation_date"


def test_us_session_date_relation_blocks_true_completed_daily_lag() -> None:
    relation = build_us_session_date_relation(
        quote_date="2026-09-01",
        completed_daily_date="2026-08-28",
        now=datetime(2026, 9, 1, 10, 0, tzinfo=NEW_YORK),
        market_phase="regular",
    )

    assert relation["status"] == "mismatch"
    assert relation["expected"] is False
    assert relation["relation"] == "completed_daily_lagging_expected_session"
    assert relation["expected_completed_daily_date"] == "2026-08-31"


def test_us_session_date_relation_accepts_weekend_completed_session() -> None:
    relation = build_us_session_date_relation(
        quote_date="2026-08-28",
        completed_daily_date="2026-08-28",
        now=datetime(2026, 8, 29, 12, 0, tzinfo=NEW_YORK),
        market_phase="market_closed",
    )

    assert relation["status"] == "aligned"
    assert relation["expected"] is True
