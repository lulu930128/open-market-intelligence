from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market.tw_bar_aggregation import observed_trade_coverage
from app.market.tw_bar_contracts import (
    TaiwanBarOutwardState,
    TaiwanBarSeriesRead,
    TaiwanHistoryCoverage,
    TaiwanHistoryStatus,
    TaiwanReconciliationStatus,
    TaiwanReleaseStatus,
)
from app.market.tw_bar_identity import build_taiwan_bar_series_identity
from app.market.tw_technical_service import (
    BarSeriesRevisionConflict,
    TaiwanTechnicalService,
    TaiwanTechnicalStatus,
    build_taiwan_technical_capability_contract,
)
from app.market.technical_evidence import calculate_canonical_indicator_points
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)


TAIPEI = timezone(timedelta(hours=8))
INSTRUMENT = InstrumentKey(
    market=Market.TW,
    symbol="2330",
    instrument_type=InstrumentType.STOCK,
    venue="TWSE",
)


def _series(*, technical_eligible: bool = True) -> TaiwanBarSeriesRead:
    start = datetime(2026, 6, 1, tzinfo=TAIPEI)
    bars: list[BarObservation] = []
    states: list[TaiwanBarOutwardState] = []
    for offset in range(80):
        bar_start = start + timedelta(days=offset)
        price = Decimal("100") + Decimal(offset) / Decimal("2")
        bar = BarObservation(
            instrument=INSTRUMENT,
            lineage=SourceLineage(
                provider="twse_openapi",
                source="twse_daily_ohlcv",
                authority=AuthorityClass.EXCHANGE,
                raw_contract_version="twse.daily.v1",
                event_at=bar_start + timedelta(hours=14),
                received_at=bar_start + timedelta(hours=15),
                fetched_at=bar_start + timedelta(hours=15),
                content_hash=f"hash-{offset}",
            ),
            interval="1d",
            start_at=bar_start,
            end_at=bar_start + timedelta(days=1),
            open_price=price,
            high_price=price + Decimal("2"),
            low_price=price - Decimal("1"),
            close_price=price + Decimal("1"),
            volume=Quantity(
                value=Decimal(10_000 + offset * 100),
                unit=QuantityUnit.SHARE,
            ),
            volume_status="observed",
            price_basis="raw",
            turnover_value=Decimal(1_000_000 + offset * 10_000),
            turnover_currency="TWD",
            trade_count=1_000 + offset,
            finalization=BarFinalization.FINAL,
        )
        bars.append(bar)
        states.append(
            TaiwanBarOutwardState(
                start_at=bar_start,
                finalization=BarFinalization.FINAL,
                authority=AuthorityClass.EXCHANGE,
                official=True,
                release_status=TaiwanReleaseStatus.RELEASED,
                reconciliation_status=TaiwanReconciliationStatus.MATCHED,
                persisted=True,
                source_interval="1d",
                technical_eligible=technical_eligible,
            )
        )
    resolved_bars = tuple(bars)
    coverage = observed_trade_coverage(
        resolved_bars,
        trading_policy_version="tw.trading_policy.daily.v1",
    )
    identity = build_taiwan_bar_series_identity(
        instrument=INSTRUMENT,
        requested_interval="1d",
        base_interval="1d",
        bars=resolved_bars,
        coverage=coverage,
        aggregation_version=None,
        state={"technical_eligible": technical_eligible},
    )
    return TaiwanBarSeriesRead(
        instrument=INSTRUMENT,
        requested_interval="1d",
        base_interval="1d",
        derived=False,
        bars=resolved_bars,
        bar_states=tuple(states),
        bucket_coverage=coverage,
        history=TaiwanHistoryCoverage(
            requested_from=resolved_bars[0].start_at,
            requested_to=resolved_bars[-1].end_at,
            available_from=resolved_bars[0].start_at,
            available_to=resolved_bars[-1].end_at,
            requested_session_count=len(resolved_bars),
            covered_session_count=len(resolved_bars),
            history_status=TaiwanHistoryStatus.READY,
            requested_coverage_satisfied=True,
        ),
        identity=identity,
    )


def _series_with_current_partial(
    *,
    close_adjustment: Decimal = Decimal("0"),
) -> TaiwanBarSeriesRead:
    completed = _series()
    previous = completed.bars[-1]
    bar_start = previous.start_at + timedelta(days=1)
    close = previous.close_price + Decimal("2") + close_adjustment
    partial = BarObservation(
        instrument=INSTRUMENT,
        lineage=SourceLineage(
            provider="omi_taiwan_bar_service",
            source="tw.current_session.daily_projection",
            authority=AuthorityClass.DERIVED,
            raw_contract_version="tw.current_session.daily_projection.v1",
            event_at=bar_start + timedelta(hours=13, minutes=30),
            received_at=bar_start + timedelta(hours=13, minutes=31),
            fetched_at=bar_start + timedelta(hours=13, minutes=31),
            content_hash=f"partial-{close}",
        ),
        interval="1d",
        start_at=bar_start,
        end_at=bar_start + timedelta(days=1),
        open_price=previous.close_price,
        high_price=max(previous.close_price, close),
        low_price=min(previous.close_price, close),
        close_price=close,
        volume=None,
        volume_status="missing",
        price_basis="raw",
        turnover_value=None,
        turnover_currency=None,
        trade_count=None,
        finalization=BarFinalization.PROVISIONAL,
    )
    partial_state = TaiwanBarOutwardState(
        start_at=partial.start_at,
        finalization=BarFinalization.PROVISIONAL,
        authority=AuthorityClass.DERIVED,
        official=False,
        release_status=TaiwanReleaseStatus.PENDING_RELEASE,
        reconciliation_status=TaiwanReconciliationStatus.PENDING,
        persisted=False,
        source_interval="1m",
        technical_eligible=False,
    )
    bars = (*completed.bars, partial)
    states = (*completed.bar_states, partial_state)
    coverage = observed_trade_coverage(
        bars,
        trading_policy_version="tw.trading_policy.daily.v1",
    )
    identity = build_taiwan_bar_series_identity(
        instrument=INSTRUMENT,
        requested_interval="1d",
        base_interval="1d",
        bars=bars,
        coverage=coverage,
        aggregation_version=None,
        state={"current_partial": str(close)},
    )
    return completed.model_copy(
        update={
            "bars": bars,
            "bar_states": states,
            "bucket_coverage": coverage,
            "history": completed.history.model_copy(
                update={
                    "requested_to": partial.end_at,
                    "available_to": partial.end_at,
                    "requested_session_count": len(bars),
                    "covered_session_count": len(bars),
                }
            ),
            "identity": identity,
        }
    )


def test_technical_uses_exact_bar_series_identity_and_backend_math() -> None:
    bars = _series()

    result = TaiwanTechnicalService().calculate(
        bars,
        expected_series_revision=bars.identity.series_revision,
    )

    assert result.bar_series_fingerprint == bars.identity.series_fingerprint
    assert result.bar_lineage_digest == bars.identity.lineage_digest
    assert result.bar_state_digest == bars.identity.state_digest
    assert result.bar_series_revision == bars.identity.series_revision
    assert result.status is TaiwanTechnicalStatus.AVAILABLE
    assert result.points[-1]["algorithm_version"] == "tw.technical.indicators.v4"
    assert result.points[-1]["ma"]
    assert result.points[-1]["ema"]
    assert result.points[-1]["rsi"]
    assert result.points[-1]["macd"]
    assert result.points[-1]["kd"]
    assert result.points[-1]["atr"]
    assert result.points[-1]["adx"]
    assert result.points[-1]["bollinger"]
    assert result.points[-1]["donchian"]
    assert result.points[-1]["mfi"]
    assert result.points[-1]["roc"]
    assert result.points[-1]["vwap"] is None
    assert result.warmup["vwap"]["status"] == "unavailable"
    assert result.points[-1]["obv"] is not None


def test_response_limit_does_not_shrink_technical_calculation_window() -> None:
    bars = _series()

    result = TaiwanTechnicalService().calculate(bars, response_limit=8)

    assert result.calculation_bar_count == 80
    assert result.response_point_count == 8
    assert len(result.points) == 8
    assert result.warmup["ma"]["available_bars"] == 80
    assert result.warmup["ma"]["status"] == "ready"
    assert result.points[-1]["ma"]["ma60"] is not None


def test_revision_pin_mismatch_fails_closed() -> None:
    bars = _series()

    with pytest.raises(BarSeriesRevisionConflict) as exc_info:
        TaiwanTechnicalService().calculate(
            bars,
            expected_series_revision="0" * 64,
        )

    assert exc_info.value.current == bars.identity.series_revision


def test_ineligible_bar_state_returns_unavailable_without_local_fallback() -> None:
    result = TaiwanTechnicalService().calculate(_series(technical_eligible=False))

    assert result.status is TaiwanTechnicalStatus.UNAVAILABLE
    assert result.points == ()
    assert "TW_TECHNICAL_BAR_STATE_NOT_ELIGIBLE" in result.limitations


def test_terminal_current_partial_preserves_finalized_decision_points() -> None:
    result = TaiwanTechnicalService().calculate(_series_with_current_partial())

    assert result.status is TaiwanTechnicalStatus.PARTIAL
    assert result.calculation_bar_count == 81
    assert result.decision_bar_count == 80
    assert len(result.points) == 80
    assert result.points[-1]["ma"]["ma60"] is not None
    assert result.current_partial is not None
    assert result.current_partial.decision_usable is False
    assert result.current_partial.price_based_observation_usable is True
    assert result.current_partial.volume_based_observation_usable is False
    assert result.current_partial.point["ma"]["ma60"] is not None
    assert result.current_partial.point["volume_ma"] is None
    assert result.current_partial.point["pvo"] is None
    assert result.current_partial.point["mfi"] is None
    assert result.current_partial.point["obv"] is None
    assert (
        result.current_partial.indicator_applicability["pvo"]
        == "not_applicable_missing_final_volume"
    )


def test_current_partial_changes_observation_not_finalized_decision_revision() -> None:
    first = TaiwanTechnicalService().calculate(
        _series_with_current_partial(close_adjustment=Decimal("0"))
    )
    second = TaiwanTechnicalService().calculate(
        _series_with_current_partial(close_adjustment=Decimal("1"))
    )

    assert first.technical_revision == second.technical_revision
    assert first.current_partial is not None
    assert second.current_partial is not None
    assert (
        first.current_partial.observation_revision
        != second.current_partial.observation_revision
    )


def test_capability_and_parameter_contract_are_backend_owned() -> None:
    contract = build_taiwan_technical_capability_contract()

    assert contract["calculation_owner"] == "TaiwanTechnicalService"
    assert contract["frontend_fallback_allowed"] is False
    assert contract["parameter_contract"]["authority"] == "backend"
    assert contract["indicators"]["ma"]["status"] == "available"
    assert contract["indicators"]["vwap"]["status"] == "available"
    assert contract["indicators"]["vwap"]["non_applicable_intervals"] == [
        "1d",
        "1w",
        "1mo",
    ]
    assert contract["indicators"]["obv"]["status"] == "available"
    assert contract["indicators"]["psar"]["status"] == "pending"


def test_vwap_and_obv_do_not_carry_through_missing_volume() -> None:
    points = [
        {
            "time": datetime(2026, 6, 1, 9, 0, tzinfo=TAIPEI),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        },
        {
            "time": datetime(2026, 6, 1, 9, 1, tzinfo=TAIPEI),
            "open": 10,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": None,
        },
        {
            "time": datetime(2026, 6, 1, 9, 2, tzinfo=TAIPEI),
            "open": 11,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 200,
        },
    ]

    calculated = calculate_canonical_indicator_points(points)

    assert calculated[0]["vwap"] == 10.0
    assert calculated[0]["obv"] == 0.0
    assert calculated[1]["vwap"] is None
    assert calculated[1]["obv"] is None
    assert calculated[2]["vwap"] == 12.0
    assert calculated[2]["obv"] == 0.0


def test_canonical_daily_series_does_not_publish_session_vwap() -> None:
    result = TaiwanTechnicalService().calculate(_series())

    assert result.points
    assert all(point["vwap"] is None for point in result.points)
    assert result.warmup["vwap"]["status"] == "unavailable"
    assert "TW_VWAP_NOT_APPLICABLE_FOR_INTERVAL" in result.limitations


def test_intraday_vwap_resets_on_new_taiwan_session() -> None:
    points = [
        {
            "time": datetime(2026, 6, 1, 13, 24, tzinfo=TAIPEI),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        },
        {
            "time": datetime(2026, 6, 2, 9, 0, tzinfo=TAIPEI),
            "open": 20,
            "high": 21,
            "low": 19,
            "close": 20,
            "volume": 100,
        },
    ]

    calculated = calculate_canonical_indicator_points(points, interval="1m")

    assert calculated[0]["vwap"] == 10.0
    assert calculated[1]["vwap"] == 20.0
