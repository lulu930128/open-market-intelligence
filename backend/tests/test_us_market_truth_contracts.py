from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    CapabilityExpectation,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    PriceUnit,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
)
from app.us_market.close_resolution_policy import (
    USCloseCandidateDecision,
    USCloseResolutionPolicy,
    USCloseResolutionPolicyContext,
    USProviderHintContext,
    reconcile_close_evidence,
    evaluate_provider_previous_close_hint,
)
from app.us_market.market_truth_contracts import (
    USChangeCalculationStatus,
    USChangeMetric,
    USCloseEvidence,
    USCloseEvidenceKind,
    USCloseComparisonSemantics,
    USCloseReconciliation,
    USCloseReconciliationState,
    USCloseRoles,
    USComparisonPurpose,
    USComparisonReference,
    USComponentRevisions,
    USEvidenceRelease,
    USMarketTruthAvailability,
    USMarketTruthComponentStatus,
    USMarketTruthHealth,
    USMarketTruthSnapshot,
    USObservation,
    USObservationKind,
    USOfficialCloseProof,
    build_evidence_revision,
    build_truth_revision,
)
from app.us_market.market_truth import _select_current


UTC = timezone.utc
NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
AAPL = InstrumentKey(
    market=Market.US,
    symbol="AAPL",
    instrument_type=InstrumentType.STOCK,
    venue="NASDAQ",
)
SOX = InstrumentKey(
    market=Market.US,
    symbol="^SOX",
    instrument_type=InstrumentType.INDEX,
    venue="NASDAQ_INDEX",
)


def _close(
    *,
    evidence_id: str = "daily:AAPL:2026-08-31:yahoo:v1",
    evidence_kind: USCloseEvidenceKind = USCloseEvidenceKind.COMPLETED_DAILY,
    instrument: InstrumentKey = AAPL,
    trade_date: date = date(2026, 8, 31),
    price: Decimal = Decimal("200"),
    currency: str = "USD",
    price_basis: str = "raw",
    authority: AuthorityClass = AuthorityClass.VENDOR,
    session: MarketSession = MarketSession.CLOSED,
    finalization: BarFinalization = BarFinalization.FINAL,
    release: USEvidenceRelease = USEvidenceRelease.RELEASED,
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH,
    official_close_proof: USOfficialCloseProof = USOfficialCloseProof.NONE,
    proof_source: str | None = None,
    proof_semantics: str | None = None,
    display_usable: bool = True,
    research_usable: bool = True,
    interval: bool = False,
) -> USCloseEvidence:
    return USCloseEvidence(
        evidence_key=f"{evidence_kind.value}:{instrument.symbol}:{trade_date}",
        evidence_id=evidence_id,
        observation_id=f"observation:{evidence_id}",
        semantic_fingerprint="a" * 64,
        instrument=instrument,
        trade_date=trade_date,
        price=price,
        price_unit=(
            PriceUnit.INDEX_POINT
            if instrument.instrument_type is InstrumentType.INDEX
            else PriceUnit.CURRENCY
        ),
        currency=(
            None if instrument.instrument_type is InstrumentType.INDEX else currency
        ),
        price_basis=price_basis,
        evidence_kind=evidence_kind,
        provider="yahoo_chart",
        source="yahoo.chart",
        authority=authority,
        session=session,
        event_at=NOW,
        fetched_at=NOW + timedelta(seconds=2),
        interval_start_at=(NOW - timedelta(minutes=1) if interval else None),
        interval_end_at=(NOW if interval else None),
        official_close_proof=official_close_proof,
        proof_source=proof_source,
        proof_semantics=proof_semantics,
        availability=USMarketTruthAvailability.AVAILABLE,
        finalization=finalization,
        release=release,
        freshness=freshness,
        expectedness=CapabilityExpectation.REQUIRED,
        display_usable=display_usable,
        research_usable=research_usable,
    )


def _observation(
    *,
    observation_id: str = "quote:AAPL:current",
    currency: str = "USD",
    price_basis: str = "raw",
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH,
    trade_date: date = date(2026, 9, 1),
    session: MarketSession = MarketSession.PRE_OPEN,
    current_session_expected: bool = True,
    current_session_satisfied: bool = True,
    research_usable: bool = True,
) -> USObservation:
    return USObservation(
        observation_id=observation_id,
        kind=USObservationKind.QUOTE,
        instrument=AAPL,
        trade_date=trade_date,
        price=Decimal("201"),
        price_unit=PriceUnit.CURRENCY,
        currency=currency,
        price_basis=price_basis,
        session=session,
        event_at=NOW,
        fetched_at=NOW,
        selected_provider="fixture",
        selected_source="fixture.quote",
        selection_reason="FIXTURE_SELECTED",
        fallback_used=False,
        availability=USMarketTruthAvailability.AVAILABLE,
        freshness=freshness,
        current_session_expected=current_session_expected,
        current_session_satisfied=current_session_satisfied,
        expectedness=CapabilityExpectation.EXPECTED,
        display_usable=True,
        research_usable=research_usable,
    )


def test_market_truth_current_selection_rejects_previous_session_observation() -> None:
    previous_session = _observation(
        trade_date=date(2026, 9, 1),
        session=MarketSession.CONTINUOUS,
        current_session_satisfied=False,
    )

    assert (
        _select_current(
            (previous_session,),
            market_phase="regular",
            expected_trade_date=date(2026, 9, 2),
        )
        is None
    )


def test_market_truth_current_selection_accepts_expected_session_date() -> None:
    current_session = _observation(
        trade_date=date(2026, 9, 2),
        session=MarketSession.CONTINUOUS,
    )

    assert _select_current(
        (current_session,),
        market_phase="regular",
        expected_trade_date=date(2026, 9, 2),
    ) is current_session


def test_market_truth_current_selection_preserves_stale_session_identity() -> None:
    stale_current_session = _observation(
        trade_date=date(2026, 9, 2),
        session=MarketSession.CONTINUOUS,
        freshness=EvidenceFreshness.STALE,
        research_usable=False,
    )

    assert _select_current(
        (stale_current_session,),
        market_phase="regular",
        expected_trade_date=date(2026, 9, 2),
    ) is stale_current_session


def _reference(evidence: USCloseEvidence) -> USComparisonReference:
    return USComparisonReference(
        reference_id="reference:AAPL:headline",
        evidence_id=evidence.evidence_id,
        purpose=USComparisonPurpose.HEADLINE_CHANGE,
        instrument=evidence.instrument,
        reference_trade_date=evidence.trade_date,
        price=evidence.price,
        price_unit=evidence.price_unit,
        currency=evidence.currency,
        price_basis=evidence.price_basis,
        calculation_eligible=True,
        display_usable=True,
        research_usable=True,
        reason_code="LATEST_COMPLETED_CLOSE",
    )


def test_index_point_reference_is_materialized_without_currency() -> None:
    instrument = InstrumentKey(
        market=Market.US,
        symbol="^GSPC",
        instrument_type=InstrumentType.INDEX,
        venue="SP_INDEX",
    )

    reference = USComparisonReference(
        reference_id="reference:^GSPC:headline",
        evidence_id="daily:^GSPC:2026-08-31",
        purpose=USComparisonPurpose.HEADLINE_CHANGE,
        instrument=instrument,
        reference_trade_date=date(2026, 8, 31),
        price=Decimal("6450"),
        price_unit=PriceUnit.INDEX_POINT,
        currency=None,
        price_basis="raw",
        calculation_eligible=True,
        display_usable=True,
        research_usable=True,
        reason_code="RESOLVED_CLOSE_REFERENCE",
    )

    assert reference.currency is None
    assert reference.calculation_eligible is True


def _metric(observation: USObservation, reference: USComparisonReference) -> USChangeMetric:
    return USChangeMetric(
        metric_id="metric:AAPL:headline",
        purpose=USComparisonPurpose.HEADLINE_CHANGE,
        observation_id=observation.observation_id,
        reference_id=reference.reference_id,
        absolute_change=Decimal("1"),
        percent_change=Decimal("0.5"),
        calculation_status=USChangeCalculationStatus.CALCULATED,
        reason_code="CALCULATED",
        display_usable=True,
        research_usable=True,
    )


def _snapshot(
    *,
    evidence: USCloseEvidence,
    observation: USObservation | None = None,
    reference: USComparisonReference | None = None,
    metric: USChangeMetric | None = None,
) -> USMarketTruthSnapshot:
    observation = observation or _observation()
    reference = reference or _reference(evidence)
    metric = metric or _metric(observation, reference)
    revisions = USComponentRevisions(
        quote_revision="quote-v1",
        intraday_revision="bars-v1",
        close_revision="close-v1",
        daily_revision="daily-v1",
        calendar_revision="calendar-v1",
    )
    evidence_revision = build_evidence_revision((evidence,))
    truth_revision = build_truth_revision(
        contract_version="omi.market.us_truth_snapshot.v1",
        evidence_revision=evidence_revision,
        market_phase="pre_market",
        component_revisions=revisions,
        selected_observation_ids=(
            observation.observation_id,
            observation.observation_id,
            observation.observation_id,
        ),
        references=(reference,),
        metrics=(metric,),
        reconciliation=None,
    )
    resolved_health = ResolvedEvidenceHealth(
        status=ResolvedEvidenceStatus.SELECTED,
        selected_provider="fixture",
        selected_source="fixture",
        selected_session=MarketSession.PRE_OPEN,
        selected_event_at=NOW,
        selection_reason="FIXTURE_SELECTED",
        facts_usable=True,
        research_usable=True,
    )
    component_status = USMarketTruthComponentStatus(
        availability=USMarketTruthAvailability.AVAILABLE,
        reason_code="COMPONENT_AVAILABLE",
        resolved_health=resolved_health,
    )
    return USMarketTruthSnapshot(
        evaluated_at=NOW,
        evaluation_id="evaluation-1",
        evidence_revision=evidence_revision,
        truth_revision=truth_revision,
        component_revisions=revisions,
        instrument=AAPL,
        market_phase="pre_market",
        expectation=CapabilityExpectation.EXPECTED,
        latest_observation=observation,
        current_observation=observation,
        headline_observation=observation,
        close_evidence=(evidence,),
        close_roles=USCloseRoles(latest_completed_id=evidence.evidence_id),
        comparison_references=(reference,),
        change_metrics=(metric,),
        health=USMarketTruthHealth(
            quote=component_status,
            intraday=component_status,
            daily=component_status,
        ),
    )


def test_evidence_revision_changes_when_price_is_corrected_under_same_logical_key() -> None:
    original = _close()
    corrected = original.model_copy(
        update={
            "price": Decimal("201"),
            "semantic_fingerprint": "b" * 64,
        }
    )

    assert original.evidence_key == corrected.evidence_key
    assert build_evidence_revision((original,)) != build_evidence_revision((corrected,))


def test_official_close_requires_explicit_proof() -> None:
    with pytest.raises(ValidationError, match="requires explicit proof"):
        _close(
            evidence_kind=USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
        )


def test_time_bucket_does_not_make_index_official() -> None:
    evidence = _close(
        evidence_id="close-boundary:SOX:v1",
        evidence_kind=USCloseEvidenceKind.UNVERIFIED_CLOSE_BOUNDARY_BAR,
        instrument=SOX,
        session=MarketSession.CLOSING_AUCTION,
        research_usable=False,
    )

    decision = USCloseResolutionPolicy().evaluate(evidence)

    assert decision.decision is USCloseCandidateDecision.INELIGIBLE
    assert decision.reason_code == "UNVERIFIED_CLOSE_BOUNDARY"


def test_index_official_close_rejects_stock_sale_condition_proof() -> None:
    evidence = _close(
        evidence_id="official:SOX:v1",
        evidence_kind=USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
        instrument=SOX,
        session=MarketSession.CLOSING_AUCTION,
        official_close_proof=USOfficialCloseProof.PROVIDER_SALE_CONDITION,
        proof_source="vendor_sale_condition",
        proof_semantics="closing_sale_condition",
    )

    decision = USCloseResolutionPolicy().evaluate(evidence)

    assert decision.decision is USCloseCandidateDecision.INELIGIBLE
    assert decision.reason_code == "OFFICIAL_EVENT_POLICY_MISMATCH"


def test_nasdaq_official_close_requires_declared_venue_proof_contract() -> None:
    evidence = _close(
        evidence_id="official:AAPL:v1",
        evidence_kind=USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
        session=MarketSession.CLOSING_AUCTION,
        official_close_proof=USOfficialCloseProof.EXCHANGE_MARKER,
        proof_source="nasdaq_closing_cross",
        proof_semantics="nasdaq_closing_cross",
    )

    decision = USCloseResolutionPolicy().evaluate(evidence)

    assert decision.decision is USCloseCandidateDecision.ELIGIBLE
    assert decision.policy_id == "omi.us.close_authority.nasdaq_cross.v1"


def test_official_close_policy_defaults_to_deny_for_undeclared_venue() -> None:
    instrument = AAPL.model_copy(update={"venue": "UNDECLARED"})
    evidence = _close(
        evidence_id="official:AAPL:undeclared:v1",
        evidence_kind=USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
        instrument=instrument,
        session=MarketSession.CLOSING_AUCTION,
        official_close_proof=USOfficialCloseProof.EXCHANGE_MARKER,
        proof_source="nasdaq_closing_cross",
        proof_semantics="nasdaq_closing_cross",
    )

    decision = USCloseResolutionPolicy().evaluate(evidence)

    assert decision.decision is USCloseCandidateDecision.INELIGIBLE
    assert decision.reason_code == "OFFICIAL_CLOSE_RULE_UNDECLARED"


def test_close_policy_rejects_context_that_does_not_match_evidence_identity() -> None:
    evidence = _close()
    context = USCloseResolutionPolicyContext.from_evidence(evidence)
    context = USCloseResolutionPolicyContext(
        instrument=context.instrument,
        evidence_provider=context.evidence_provider,
        evidence_source="different.source",
        official_close_proof=context.official_close_proof,
        proof_source=context.proof_source,
        proof_semantics=context.proof_semantics,
    )

    decision = USCloseResolutionPolicy().evaluate(evidence, context=context)

    assert decision.decision is USCloseCandidateDecision.INELIGIBLE
    assert decision.reason_code == "POLICY_CONTEXT_IDENTITY_MISMATCH"


def test_sox_official_close_uses_index_identity_rule() -> None:
    evidence = _close(
        evidence_id="official:SOX:v2",
        evidence_kind=USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
        instrument=SOX,
        session=MarketSession.CLOSED,
        official_close_proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_source="nasdaq_index_official",
        proof_semantics="official_index_close",
    )

    decision = USCloseResolutionPolicy().evaluate(evidence)

    assert decision.decision is USCloseCandidateDecision.ELIGIBLE
    assert decision.policy_id == "omi.us.close_authority.sox_index.v1"


def test_provider_previous_close_hint_is_deterministic_limited_fallback() -> None:
    hint = _close(
        evidence_id="hint:AAPL:2026-08-31:yahoo:v1",
        evidence_kind=USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT,
        release=USEvidenceRelease.NOT_APPLICABLE,
        research_usable=False,
    )
    context = USProviderHintContext(
        expected_trade_date=date(2026, 8, 31),
        quote_trade_date=date(2026, 9, 1),
        same_observation_provider=True,
        provider_semantics_verified=True,
    )

    result = evaluate_provider_previous_close_hint(hint, context=context)

    assert result.eligible is True
    assert result.display_usable is True
    assert result.research_usable is False
    assert result.reason_code == "PROVIDER_PREVIOUS_CLOSE_LIMITED"


def test_provider_hint_rejects_corporate_action_ambiguity() -> None:
    hint = _close(
        evidence_kind=USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT,
        release=USEvidenceRelease.NOT_APPLICABLE,
        research_usable=False,
    )
    context = USProviderHintContext(
        expected_trade_date=date(2026, 8, 31),
        quote_trade_date=date(2026, 9, 1),
        same_observation_provider=True,
        provider_semantics_verified=True,
        corporate_action_ambiguous=True,
    )

    result = evaluate_provider_previous_close_hint(hint, context=context)

    assert result.eligible is False
    assert result.reason_code == "CORPORATE_ACTION_AMBIGUOUS"


def test_snapshot_rejects_dangling_reference() -> None:
    evidence = _close()
    reference = _reference(evidence).model_copy(update={"evidence_id": "missing"})

    with pytest.raises(ValidationError, match="dangling evidence id"):
        _snapshot(evidence=evidence, reference=reference)


def test_snapshot_rejects_incompatible_currency() -> None:
    evidence = _close()
    observation = _observation(currency="EUR")
    reference = _reference(evidence)
    metric = _metric(observation, reference)

    with pytest.raises(ValidationError, match="not price compatible"):
        _snapshot(
            evidence=evidence,
            observation=observation,
            reference=reference,
            metric=metric,
        )


def test_snapshot_preserves_stale_current_session_observation() -> None:
    evidence = _close()
    observation = _observation(
        freshness=EvidenceFreshness.STALE,
        research_usable=False,
    )

    snapshot = _snapshot(evidence=evidence, observation=observation)

    assert snapshot.current_observation == observation
    assert snapshot.current_observation.current_session_satisfied is True
    assert snapshot.current_observation.freshness is EvidenceFreshness.STALE
    assert snapshot.current_observation.research_usable is False


def test_observation_rejects_stale_research_usability() -> None:
    with pytest.raises(ValidationError, match="cannot be research usable"):
        _observation(freshness=EvidenceFreshness.STALE)


def test_reconciliation_requires_named_tolerance_policy() -> None:
    with pytest.raises(ValidationError, match="difference, and policy"):
        USCloseReconciliation(
            trade_date=date(2026, 8, 31),
            primary_evidence_id="daily-v1",
            secondary_evidence_ids=("interval-v1",),
            state=USCloseReconciliationState.MATCHED,
            absolute_difference=Decimal("0.01"),
            relative_difference_bps=Decimal("0.05"),
            within_tolerance=True,
        )


def test_reconciliation_uses_instrument_specific_named_policy() -> None:
    primary = _close(price=Decimal("200"))
    secondary = _close(
        evidence_id="interval:AAPL:2026-08-31:v1",
        evidence_kind=USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE,
        price=Decimal("199.995"),
        session=MarketSession.CONTINUOUS,
        release=USEvidenceRelease.NOT_APPLICABLE,
        research_usable=False,
        interval=True,
    )

    reconciliation = reconcile_close_evidence(primary, secondary)

    assert reconciliation.state is USCloseReconciliationState.MATCHED
    assert reconciliation.tolerance_policy_id == "omi.us.close_tolerance.equity.v1"
    assert reconciliation.absolute_difference == Decimal("0.005")


def test_official_vs_interval_difference_is_divergence_not_mismatch() -> None:
    primary = _close(price=Decimal("200"))
    secondary = _close(
        evidence_id="interval:AAPL:2026-08-31:v2",
        evidence_kind=USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE,
        price=Decimal("199"),
        session=MarketSession.CONTINUOUS,
        release=USEvidenceRelease.NOT_APPLICABLE,
        research_usable=False,
        interval=True,
    )

    reconciliation = reconcile_close_evidence(primary, secondary)

    assert reconciliation.state is USCloseReconciliationState.DIVERGED
    assert reconciliation.comparison_semantics is (
        USCloseComparisonSemantics.OFFICIAL_VS_REGULAR_INTERVAL
    )


def test_same_semantics_difference_remains_mismatch() -> None:
    primary = _close(price=Decimal("200"))
    secondary = _close(
        evidence_id="daily:AAPL:2026-08-31:second:v1",
        price=Decimal("199"),
    )

    reconciliation = reconcile_close_evidence(primary, secondary)

    assert reconciliation.state is USCloseReconciliationState.MISMATCHED
    assert reconciliation.comparison_semantics is (
        USCloseComparisonSemantics.OFFICIAL_VS_OFFICIAL
    )


def test_truth_revision_is_not_request_time_dependent() -> None:
    evidence = _close()
    snapshot = _snapshot(evidence=evidence)
    reference = snapshot.comparison_references[0]
    metric = snapshot.change_metrics[0]

    repeated = build_truth_revision(
        contract_version=snapshot.contract_version,
        evidence_revision=snapshot.evidence_revision,
        market_phase=snapshot.market_phase,
        component_revisions=snapshot.component_revisions,
        selected_observation_ids=(
            snapshot.latest_observation.observation_id,
            snapshot.current_observation.observation_id,
            snapshot.headline_observation.observation_id,
        ),
        references=(reference,),
        metrics=(metric,),
        reconciliation=None,
    )

    assert repeated == snapshot.truth_revision
