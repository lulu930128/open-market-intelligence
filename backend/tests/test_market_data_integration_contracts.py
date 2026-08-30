from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    ResolvedBarSeries,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    BarCoverageRequirement,
    BarSeriesResolutionMode,
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    EvidenceTarget,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshCoverageScopeV1,
    RefreshCursorV1,
    RefreshRequirementV1,
    RequestBounds,
    SnapshotCapabilityRequest,
    adapt_v1_requirement,
)
from app.market_data.policies import DataPurpose, DataRequirement, RealtimePolicy


NOW = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _bar_request() -> BarCapabilityRequest:
    return BarCapabilityRequest(
        capability_id="daily.ohlcv",
        interval="1d",
        start_at=datetime.combine(date(2026, 8, 20), time(9), tzinfo=timezone.utc),
        end_at=datetime.combine(date(2026, 8, 21), time(13, 30), tzinfo=timezone.utc),
        max_bars=2,
        completed_only=True,
    )


def _requirement(**overrides) -> DataRequirementV2:
    values = {
        "target": InstrumentTarget(instrument=_instrument()),
        "request": _bar_request(),
        "purpose": DataPurpose.RESEARCH,
        "realtime_policy": RealtimePolicy.COMPLETED_SESSION,
        "session": MarketSession.CLOSED,
        "requested_at": NOW,
        "freshness": FreshnessRequirement(max_age_seconds=604800),
        "bounds": RequestBounds(max_rows=10),
    }
    values.update(overrides)
    return DataRequirementV2(**values)


def _missing_bars() -> ResolvedBarSeries:
    return ResolvedBarSeries(
        health=ResolvedEvidenceHealth(
            status=ResolvedEvidenceStatus.POLICY_UNSATISFIED,
            selection_reason="COMPLETED_SESSION_NO_ELIGIBLE_CANDIDATE",
        )
    )


def test_requirement_v2_serializes_typed_target_request_and_bounds() -> None:
    payload = _requirement().model_dump(mode="json")

    assert payload["contract_version"] == "omi.market.data_requirement.v2"
    assert payload["target"]["kind"] == "instrument"
    assert payload["request"]["kind"] == "bars"
    assert payload["request"]["capability_id"] == "daily.ohlcv"
    assert payload["bounds"]["max_external_calls"] == 0
    assert payload["request"]["series_resolution"] == "single_candidate"
    assert payload["freshness"]["evidence_target"] == "current"


def test_freshness_requirement_has_typed_evidence_target() -> None:
    latest = FreshnessRequirement(
        max_age_seconds=300,
        evidence_target=EvidenceTarget.LATEST_AVAILABLE,
    )

    assert latest.evidence_target is EvidenceTarget.LATEST_AVAILABLE
    assert latest.model_dump(mode="json")["evidence_target"] == "latest_available"


def test_bar_coverage_is_explicit_and_does_not_repurpose_max_bars() -> None:
    request = _bar_request().model_copy(
        update={"coverage": BarCoverageRequirement(minimum_bar_count=2)}
    )
    requirement = _requirement(request=request)

    assert requirement.request.max_bars == 2
    assert requirement.request.coverage is not None
    assert requirement.request.coverage.minimum_bar_count == 2

    with pytest.raises(ValidationError, match="cannot exceed max_bars"):
        _requirement(
            request=_bar_request().model_copy(
                update={"coverage": BarCoverageRequirement(minimum_bar_count=3)}
            )
        )


def test_timestamp_composition_is_explicit_and_completed_session_only() -> None:
    composed_request = _bar_request().model_copy(
        update={"series_resolution": BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP}
    )
    composed = _requirement(request=composed_request)
    assert (
        composed.request.series_resolution
        is BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP
    )

    with pytest.raises(ValidationError, match="requires completed_session"):
        _requirement(
            request=composed_request,
            realtime_policy=RealtimePolicy.PREFER_LIVE,
            bounds=RequestBounds(
                max_rows=10,
                max_provider_attempts=1,
                max_external_calls=1,
            ),
        )


def test_requirement_forbids_provider_control_and_external_cache_work() -> None:
    payload = _requirement().model_dump(mode="python")
    payload["provider"] = "twse_openapi"
    with pytest.raises(ValidationError, match="Extra inputs"):
        DataRequirementV2(**payload)

    with pytest.raises(ValidationError, match="must forbid external acquisition"):
        _requirement(bounds=RequestBounds(max_external_calls=1, max_provider_attempts=1))


def test_requirement_target_and_capability_kinds_must_match() -> None:
    with pytest.raises(ValidationError, match="dataset capability requests"):
        _requirement(
            request=DatasetCapabilityRequest(
                capability_id="daily.ohlcv",
                from_date=date(2026, 8, 21),
                to_date=date(2026, 8, 21),
            )
        )
    with pytest.raises(ValidationError, match="dataset targets"):
        _requirement(
            target=DatasetTarget(
                market=Market.TW,
                dataset_id="tw.daily.ohlcv.full_market",
                scope_key="TW:ordinary_stocks",
            )
        )


def test_completed_session_bars_must_be_final_only() -> None:
    request = _bar_request().model_copy(update={"completed_only": False})
    with pytest.raises(ValidationError, match="completed_only"):
        _requirement(request=request)


def test_refresh_requirement_is_separate_bounded_mutation_without_provider() -> None:
    refresh = RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv",
        target=InstrumentTarget(instrument=_instrument()),
        from_date=date(2026, 8, 20),
        to_date=date(2026, 8, 21),
        requested_at=NOW,
        purpose=DataPurpose.REPAIR,
        reason_code="EXPECTED_SESSION_MISSING",
        coverage=RefreshCoverageScopeV1(
            scope_key="TW:2330",
            target_count=1,
            requested_symbols=("2330",),
            minimum_observation_count=260,
        ),
        continuation=RefreshCursorV1(checkpoint_id="repair-20260821"),
        max_provider_attempts=2,
        max_external_calls=2,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=2,
        postcondition="Latest persisted trade date reaches 2026-08-21.",
    )
    assert refresh.max_symbols == 1
    assert refresh.reason_code == "EXPECTED_SESSION_MISSING"
    assert refresh.coverage is not None
    assert refresh.coverage.target_count == 1
    assert refresh.coverage.minimum_observation_count == 260
    assert refresh.continuation is not None
    assert refresh.continuation.checkpoint_id == "repair-20260821"

    payload = refresh.model_dump(mode="python")
    payload["provider"] = "twse_openapi"
    with pytest.raises(ValidationError, match="Extra inputs"):
        RefreshRequirementV1(**payload)


def test_refresh_coverage_fails_closed_when_scope_exceeds_budget() -> None:
    values = {
        "dataset_id": "tw.daily.ohlcv",
        "target": InstrumentTarget(instrument=_instrument()),
        "requested_at": NOW,
        "purpose": DataPurpose.REPAIR,
        "reason_code": "EXPECTED_SESSION_MISSING",
        "coverage": RefreshCoverageScopeV1(
            scope_key="TW:two-symbols",
            target_count=2,
            requested_symbols=("2330", "2317"),
        ),
        "max_provider_attempts": 1,
        "max_external_calls": 1,
        "timeout_seconds": 30,
        "max_symbols": 1,
        "max_range_days": 1,
        "postcondition": "Expected completed session rereads as resolved evidence.",
    }
    with pytest.raises(ValidationError, match="exceeds max_symbols"):
        RefreshRequirementV1(**values)

    with pytest.raises(ValidationError, match="cursor or checkpoint_id"):
        RefreshCursorV1()


def test_v1_adapter_preserves_policy_without_adding_cache_io() -> None:
    legacy = DataRequirement(
        instrument=_instrument(),
        capability_id="quote.snapshot",
        realtime_policy=RealtimePolicy.CACHE_ONLY,
        purpose=DataPurpose.RESEARCH,
        session=MarketSession.CLOSED,
        instrument_tradability=InstrumentTradability.UNKNOWN,
        requested_at=NOW,
        max_age_seconds=60,
    )
    adapted = adapt_v1_requirement(legacy)

    assert isinstance(adapted.request, SnapshotCapabilityRequest)
    assert adapted.request.capability_id == "quote.snapshot"
    assert adapted.bounds.max_external_calls == 0
    assert adapted.bounds.max_provider_attempts == 0


def test_acquisition_summary_and_result_kind_fail_closed() -> None:
    with pytest.raises(ValidationError, match="non-attempted"):
        AcquisitionSummary(
            attempted=False,
            status=AcquisitionStatus.COMPLETED,
        )

    with pytest.raises(ValidationError, match="result_kind"):
        MarketDataResultV1(
            requirement=_requirement(),
            result_kind="quote",
            resolved=_missing_bars(),
        )


def test_raw_receipt_and_persistence_contracts_preserve_transaction_evidence() -> None:
    receipt = RawFetchReceiptV1(
        provider="twse_openapi",
        source="twse_openapi.daily",
        resource_id="STOCK_DAY_ALL",
        fetched_at=NOW,
        method="get",
        status_code=200,
        content_type="application/json",
        content_hash="a" * 64,
        raw_text="[]",
        parser_version="twse_stock_day_all_v1",
    )
    persisted = PersistenceSummary(
        attempted=True,
        committed=True,
        receipts_written=1,
        observations_written=2,
        raw_result_ids=(41,),
    )

    assert receipt.method == "GET"
    assert receipt.content_hash == "a" * 64
    assert persisted.committed is True
    assert persisted.raw_result_ids == (41,)

    with pytest.raises(ValidationError, match="non-attempted persistence"):
        PersistenceSummary(attempted=False, committed=True, observations_written=1)
    with pytest.raises(ValidationError, match="raw_result_ids must be unique"):
        PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=1,
            raw_result_ids=(1, 1),
        )
    with pytest.raises(ValidationError, match="cannot exceed observations_written"):
        PersistenceSummary(
            attempted=True,
            committed=True,
            observations_written=1,
            observations_inserted=1,
            observations_updated=1,
        )
