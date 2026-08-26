from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    AuthorityClass,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    QuoteObservation,
    SourceLineage,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.quality_policy import (
    QualityReasonCode,
    authority_satisfies,
    evaluate_candidate_quality,
    required_fields_for,
)


NOW = datetime(2026, 8, 26, 2, 0, tzinfo=timezone.utc)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _lineage(
    *,
    authority: AuthorityClass = AuthorityClass.EXCHANGE,
    event_at: datetime = NOW - timedelta(seconds=5),
    complete: bool = False,
) -> SourceLineage:
    values = {
        "provider": "provider_a",
        "source": "provider_a.quote",
        "authority": authority,
        "event_at": event_at,
    }
    if complete:
        values.update(
            {
                "raw_contract_version": "provider_a.quote.v1",
                "received_at": event_at + timedelta(milliseconds=100),
                "fetched_at": event_at + timedelta(milliseconds=200),
                "observation_id": "taiwan_stock_quote_snapshot:41",
                "raw_receipt_id": "raw_fetch_result:73",
                "content_hash": "a" * 64,
            }
        )
    return SourceLineage(**values)


def _quote(
    *,
    lineage: SourceLineage | None = None,
    state: ObservationState = ObservationState.AVAILABLE,
    price: Decimal | None = Decimal("100"),
) -> QuoteObservation:
    return QuoteObservation(
        instrument=_instrument(),
        lineage=lineage or _lineage(),
        state=state,
        last_trade_price=price,
    )


def _requirement(
    *,
    request_fields: tuple[str, ...] = (),
    quality_fields: tuple[str, ...] = (),
    minimum_authority: AuthorityClass | None = None,
    allow_partial: bool = False,
    require_canonical_lineage: bool = False,
    realtime_policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    max_age_seconds: int = 60,
) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=SnapshotCapabilityRequest(
            capability_id="quote.snapshot",
            required_fields=request_fields,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=realtime_policy,
        session=MarketSession.CONTINUOUS,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=max_age_seconds),
        quality=QualityRequirement(
            required_fields=quality_fields,
            minimum_authority=minimum_authority,
            allow_partial=allow_partial,
            require_canonical_lineage=require_canonical_lineage,
        ),
        bounds=RequestBounds(
            max_provider_attempts=(0 if realtime_policy is RealtimePolicy.CACHE_ONLY else 1),
            max_external_calls=(0 if realtime_policy is RealtimePolicy.CACHE_ONLY else 1),
        ),
    )


def test_required_fields_are_normalized_unique_and_merged_in_order() -> None:
    requirement = _requirement(
        request_fields=("last_trade_price",),
        quality_fields=("currency", "last_trade_price"),
    )
    assert required_fields_for(requirement) == ("last_trade_price", "currency")

    with pytest.raises(ValidationError, match="must be unique"):
        SnapshotCapabilityRequest(
            capability_id="quote.snapshot",
            required_fields=("last_trade_price", "last_trade_price"),
        )
    with pytest.raises(ValidationError, match="valid field paths"):
        QualityRequirement(required_fields=("lineage..provider",))


@pytest.mark.parametrize(
    ("actual", "minimum", "expected"),
    (
        (AuthorityClass.EXCHANGE, AuthorityClass.BROKER, True),
        (AuthorityClass.BROKER, AuthorityClass.BROKER, True),
        (AuthorityClass.VENDOR, AuthorityClass.BROKER, False),
        (AuthorityClass.CACHE, AuthorityClass.DERIVED, False),
        (AuthorityClass.CACHE, None, True),
    ),
)
def test_authority_floor_uses_explicit_policy(
    actual: AuthorityClass,
    minimum: AuthorityClass | None,
    expected: bool,
) -> None:
    assert authority_satisfies(actual, minimum) is expected


def test_required_field_and_authority_fail_closed_with_stable_reasons() -> None:
    evaluation = evaluate_candidate_quality(
        _quote(
            lineage=_lineage(authority=AuthorityClass.VENDOR),
            price=None,
        ),
        requirement=_requirement(
            request_fields=("last_trade_price",),
            minimum_authority=AuthorityClass.BROKER,
        ),
        freshness=EvidenceFreshness.FRESH,
    )

    assert evaluation.eligible is False
    assert evaluation.facts_usable is False
    assert evaluation.research_usable is False
    assert evaluation.reason_code is QualityReasonCode.REQUIRED_FIELDS_MISSING
    assert evaluation.reason_codes == (
        QualityReasonCode.REQUIRED_FIELDS_MISSING,
        QualityReasonCode.AUTHORITY_BELOW_MINIMUM,
    )
    assert evaluation.missing_fields == ("last_trade_price",)


def test_zero_is_present_but_empty_collection_is_missing() -> None:
    quote = _quote(price=Decimal("100"))
    evaluation = evaluate_candidate_quality(
        quote,
        requirement=_requirement(quality_fields=("trade_state",)),
        freshness=EvidenceFreshness.FRESH,
    )
    assert evaluation.eligible is True

    empty_nested = evaluate_candidate_quality(
        quote,
        requirement=_requirement(quality_fields=("lineage.content_hash",)),
        freshness=EvidenceFreshness.FRESH,
    )
    assert empty_nested.reason_code is QualityReasonCode.REQUIRED_FIELDS_MISSING


def test_partial_requires_explicit_allowance_and_remains_not_research_usable() -> None:
    quote = _quote(state=ObservationState.PARTIAL)

    rejected = evaluate_candidate_quality(
        quote,
        requirement=_requirement(allow_partial=False),
        freshness=EvidenceFreshness.FRESH,
    )
    assert rejected.eligible is False
    assert rejected.reason_code is QualityReasonCode.PARTIAL_NOT_ALLOWED

    allowed = evaluate_candidate_quality(
        quote,
        requirement=_requirement(allow_partial=True),
        freshness=EvidenceFreshness.FRESH,
    )
    assert allowed.eligible is True
    assert allowed.facts_usable is True
    assert allowed.research_usable is False
    assert allowed.reason_code is QualityReasonCode.PARTIAL_ALLOWED


def test_canonical_lineage_is_explicit_and_complete() -> None:
    optional = evaluate_candidate_quality(
        _quote(lineage=_lineage()),
        requirement=_requirement(require_canonical_lineage=False),
        freshness=EvidenceFreshness.FRESH,
    )
    assert optional.eligible is True

    incomplete = evaluate_candidate_quality(
        _quote(lineage=_lineage()),
        requirement=_requirement(require_canonical_lineage=True),
        freshness=EvidenceFreshness.FRESH,
    )
    assert incomplete.eligible is False
    assert incomplete.reason_code is QualityReasonCode.CANONICAL_LINEAGE_INCOMPLETE
    assert incomplete.missing_lineage_fields == (
        "raw_contract_version",
        "received_at",
        "fetched_at",
        "observation_id",
        "raw_receipt_id",
        "content_hash",
    )

    complete = evaluate_candidate_quality(
        _quote(lineage=_lineage(complete=True)),
        requirement=_requirement(require_canonical_lineage=True),
        freshness=EvidenceFreshness.FRESH,
    )
    assert complete.eligible is True
    assert complete.reason_code is QualityReasonCode.ELIGIBLE


def test_missing_future_and_unusable_freshness_are_hard_rejections() -> None:
    missing = evaluate_candidate_quality(
        _quote(state=ObservationState.MISSING, price=None),
        requirement=_requirement(),
        freshness=EvidenceFreshness.FRESH,
    )
    assert missing.reason_code is QualityReasonCode.OBSERVATION_MISSING
    assert missing.eligible is False

    future = evaluate_candidate_quality(
        _quote(lineage=_lineage(event_at=NOW + timedelta(minutes=6))),
        requirement=_requirement(),
        freshness=EvidenceFreshness.FRESH,
    )
    assert future.reason_code is QualityReasonCode.FUTURE_TIMESTAMP
    assert future.eligible is False

    unknown = evaluate_candidate_quality(
        _quote(),
        requirement=_requirement(),
        freshness=EvidenceFreshness.UNKNOWN,
    )
    assert unknown.reason_code is QualityReasonCode.FRESHNESS_UNUSABLE
    assert unknown.eligible is False


def test_stale_facts_remain_eligible_but_require_live_fails_closed() -> None:
    stale_quote = _quote(lineage=_lineage(event_at=NOW - timedelta(minutes=10)))

    prefer_live = evaluate_candidate_quality(
        stale_quote,
        requirement=_requirement(max_age_seconds=60),
        freshness=EvidenceFreshness.FRESH,
    )
    assert prefer_live.eligible is True
    assert prefer_live.facts_usable is True
    assert prefer_live.research_usable is False
    assert prefer_live.reason_code is QualityReasonCode.STALE_EVIDENCE

    require_live = evaluate_candidate_quality(
        stale_quote,
        requirement=_requirement(
            realtime_policy=RealtimePolicy.REQUIRE_LIVE,
            max_age_seconds=60,
        ),
        freshness=EvidenceFreshness.LIVE,
    )
    assert require_live.eligible is False
    assert require_live.reason_codes == (
        QualityReasonCode.STALE_EVIDENCE,
        QualityReasonCode.LIVE_REQUIRED,
    )


def test_indicative_evidence_is_never_relabelled_research_ready() -> None:
    evaluation = evaluate_candidate_quality(
        _quote(state=ObservationState.INDICATIVE),
        requirement=_requirement(),
        freshness=EvidenceFreshness.LIVE,
    )
    assert evaluation.eligible is True
    assert evaluation.facts_usable is True
    assert evaluation.research_usable is False
    assert evaluation.reason_code is QualityReasonCode.INDICATIVE_EVIDENCE
