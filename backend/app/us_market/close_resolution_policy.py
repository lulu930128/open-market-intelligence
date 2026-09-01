"""Pure, default-deny US close evidence policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from app.market_data.contracts import (
    BarFinalization,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    MarketSession,
)
from app.us_market.market_truth_contracts import (
    USCloseEvidence,
    USCloseComparisonSemantics,
    USCloseEvidenceKind,
    USCloseReconciliation,
    USCloseReconciliationState,
    USEvidenceRelease,
    USMarketTruthAvailability,
    USOfficialCloseProof,
)


class USCloseCandidateDecision(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class USCloseCandidateEvaluation:
    decision: USCloseCandidateDecision
    priority: int | None
    reason_code: str
    policy_id: str


@dataclass(frozen=True)
class USCloseResolutionPolicyContext:
    instrument: InstrumentKey
    evidence_provider: str
    evidence_source: str
    official_close_proof: USOfficialCloseProof
    proof_source: str | None
    proof_semantics: str | None

    @classmethod
    def from_evidence(
        cls,
        evidence: USCloseEvidence,
    ) -> "USCloseResolutionPolicyContext":
        return cls(
            instrument=evidence.instrument,
            evidence_provider=evidence.provider,
            evidence_source=evidence.source,
            official_close_proof=evidence.official_close_proof,
            proof_source=evidence.proof_source,
            proof_semantics=evidence.proof_semantics,
        )


@dataclass(frozen=True)
class USProviderHintContext:
    expected_trade_date: date
    quote_trade_date: date
    same_observation_provider: bool
    provider_semantics_verified: bool
    corporate_action_ambiguous: bool = False
    stronger_conflict: bool = False


@dataclass(frozen=True)
class USProviderHintEvaluation:
    eligible: bool
    display_usable: bool
    research_usable: bool
    reason_code: str


@dataclass(frozen=True)
class USCloseTolerancePolicy:
    policy_id: str
    absolute_tolerance: Decimal
    basis_point_tolerance: Decimal


@dataclass(frozen=True)
class _USOfficialCloseAuthorityRule:
    policy_id: str
    proof: USOfficialCloseProof
    proof_sources: frozenset[str]
    proof_semantics: frozenset[str]


_VENUE_ALIASES = {
    "NASDAQ GLOBAL SELECT": "NASDAQ",
    "NASDAQ GLOBAL MARKET": "NASDAQ",
    "NASDAQ CAPITAL MARKET": "NASDAQ",
    "NEW YORK STOCK EXCHANGE": "NYSE",
    "NYSE ARCA": "NYSE_ARCA",
}


CLOSE_AUTHORITY_RULES: dict[str, _USOfficialCloseAuthorityRule] = {
    "NASDAQ": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.nasdaq_cross.v1",
        proof=USOfficialCloseProof.EXCHANGE_MARKER,
        proof_sources=frozenset({"nasdaq_closing_cross"}),
        proof_semantics=frozenset({"nasdaq_closing_cross"}),
    ),
    "NYSE": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.nyse_auction.v1",
        proof=USOfficialCloseProof.EXCHANGE_MARKER,
        proof_sources=frozenset({"nyse_closing_auction"}),
        proof_semantics=frozenset({"nyse_closing_auction"}),
    ),
    "NYSE_ARCA": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.nyse_arca_auction.v1",
        proof=USOfficialCloseProof.EXCHANGE_MARKER,
        proof_sources=frozenset({"nyse_arca_closing_auction"}),
        proof_semantics=frozenset({"nyse_arca_closing_auction"}),
    ),
}


INDEX_CLOSE_AUTHORITY_RULES: dict[str, _USOfficialCloseAuthorityRule] = {
    "^SOX": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.sox_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"nasdaq_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
    "^IXIC": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.ixic_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"nasdaq_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
    "^NDX": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.ndx_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"nasdaq_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
    "^GSPC": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.gspc_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"sp_global_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
    "^DJI": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.dji_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"sp_dow_jones_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
    "^VIX": _USOfficialCloseAuthorityRule(
        policy_id="omi.us.close_authority.vix_index.v1",
        proof=USOfficialCloseProof.INDEX_OFFICIAL_VALUE,
        proof_sources=frozenset({"cboe_index_official"}),
        proof_semantics=frozenset({"official_index_close"}),
    ),
}


def close_tolerance_policy(instrument_type: InstrumentType) -> USCloseTolerancePolicy:
    if instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}:
        return USCloseTolerancePolicy(
            policy_id="omi.us.close_tolerance.equity.v1",
            absolute_tolerance=Decimal("0.01"),
            basis_point_tolerance=Decimal("1"),
        )
    if instrument_type is InstrumentType.INDEX:
        return USCloseTolerancePolicy(
            policy_id="omi.us.close_tolerance.index.v1",
            absolute_tolerance=Decimal("0.1"),
            basis_point_tolerance=Decimal("0.5"),
        )
    return USCloseTolerancePolicy(
        policy_id="omi.us.close_tolerance.generic.v1",
        absolute_tolerance=Decimal("0"),
        basis_point_tolerance=Decimal("0"),
    )


def reconcile_close_evidence(
    primary: USCloseEvidence,
    secondary: USCloseEvidence,
) -> USCloseReconciliation:
    if primary.instrument != secondary.instrument:
        raise ValueError("close reconciliation instrument mismatch")
    if primary.trade_date != secondary.trade_date:
        raise ValueError("close reconciliation trade-date mismatch")
    if (
        primary.price_unit != secondary.price_unit
        or primary.currency != secondary.currency
        or primary.price_basis != secondary.price_basis
    ):
        raise ValueError("close reconciliation price semantics mismatch")
    policy = close_tolerance_policy(primary.instrument.instrument_type)
    difference = abs(primary.price - secondary.price)
    bps = difference / primary.price * Decimal("10000")
    within = (
        difference <= policy.absolute_tolerance
        or bps <= policy.basis_point_tolerance
    )
    semantics = close_comparison_semantics(primary, secondary)
    state = (
        USCloseReconciliationState.MATCHED
        if within
        else USCloseReconciliationState.DIVERGED
        if semantics
        in {
            USCloseComparisonSemantics.OFFICIAL_VS_REGULAR_INTERVAL,
            USCloseComparisonSemantics.OFFICIAL_VS_PROVIDER_HINT,
            USCloseComparisonSemantics.INTERVAL_VS_PROVIDER_HINT,
        }
        else USCloseReconciliationState.MISMATCHED
    )
    return USCloseReconciliation(
        trade_date=primary.trade_date,
        primary_evidence_id=primary.evidence_id,
        secondary_evidence_ids=(secondary.evidence_id,),
        state=state,
        comparison_semantics=semantics,
        absolute_difference=difference,
        relative_difference_bps=bps,
        tolerance_policy_id=policy.policy_id,
        tolerance_basis="combined",
        within_tolerance=within,
        limitations=(
            ("PROVIDER_HINT_RECONCILIATION_DIAGNOSTIC_ONLY",)
            if USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT
            in {primary.evidence_kind, secondary.evidence_kind}
            else ()
        ),
    )


def close_comparison_semantics(
    primary: USCloseEvidence,
    secondary: USCloseEvidence,
) -> USCloseComparisonSemantics:
    kinds = {primary.evidence_kind, secondary.evidence_kind}
    official = {
        USCloseEvidenceKind.COMPLETED_DAILY,
        USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT,
    }
    if kinds.issubset(official):
        return USCloseComparisonSemantics.OFFICIAL_VS_OFFICIAL
    if kinds & official and USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE in kinds:
        return USCloseComparisonSemantics.OFFICIAL_VS_REGULAR_INTERVAL
    if kinds & official and USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT in kinds:
        return USCloseComparisonSemantics.OFFICIAL_VS_PROVIDER_HINT
    if (
        USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE in kinds
        and USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT in kinds
    ):
        return USCloseComparisonSemantics.INTERVAL_VS_PROVIDER_HINT
    return USCloseComparisonSemantics.SAME_SEMANTICS


def evaluate_provider_previous_close_hint(
    evidence: USCloseEvidence,
    *,
    context: USProviderHintContext,
) -> USProviderHintEvaluation:
    """Apply the deterministic limited-fallback gate."""

    if evidence.evidence_kind is not USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT:
        return USProviderHintEvaluation(False, False, False, "NOT_PROVIDER_HINT")
    if evidence.trade_date != context.expected_trade_date:
        return USProviderHintEvaluation(False, False, False, "HINT_DATE_MISMATCH")
    if context.quote_trade_date <= context.expected_trade_date:
        return USProviderHintEvaluation(False, False, False, "QUOTE_DATE_NOT_AFTER_HINT")
    if not context.same_observation_provider:
        return USProviderHintEvaluation(False, False, False, "HINT_LINEAGE_MISMATCH")
    if not context.provider_semantics_verified:
        return USProviderHintEvaluation(False, False, False, "HINT_SEMANTICS_UNVERIFIED")
    if context.corporate_action_ambiguous:
        return USProviderHintEvaluation(False, False, False, "CORPORATE_ACTION_AMBIGUOUS")
    if context.stronger_conflict:
        return USProviderHintEvaluation(False, False, False, "STRONGER_CLOSE_CONFLICT")
    if evidence.freshness not in {EvidenceFreshness.LIVE, EvidenceFreshness.FRESH}:
        return USProviderHintEvaluation(False, False, False, "HINT_STALE")
    return USProviderHintEvaluation(
        True,
        True,
        False,
        "PROVIDER_PREVIOUS_CLOSE_LIMITED",
    )


class USCloseResolutionPolicy:
    """Rank only already-resolved canonical evidence.

    A timestamp in the close window never proves an official auction/cross.  An
    official event needs an explicit proof marker and an instrument-specific
    policy match.
    """

    policy_id = "omi.us.close_resolution.v1"

    def evaluate(
        self,
        evidence: USCloseEvidence,
        *,
        context: USCloseResolutionPolicyContext | None = None,
    ) -> USCloseCandidateEvaluation:
        resolved_context = context or USCloseResolutionPolicyContext.from_evidence(
            evidence
        )
        if (
            resolved_context.instrument != evidence.instrument
            or resolved_context.evidence_provider != evidence.provider
            or resolved_context.evidence_source != evidence.source
        ):
            return USCloseCandidateEvaluation(
                USCloseCandidateDecision.INELIGIBLE,
                None,
                "POLICY_CONTEXT_IDENTITY_MISMATCH",
                self.policy_id,
            )
        if evidence.availability is not USMarketTruthAvailability.AVAILABLE:
            return USCloseCandidateEvaluation(
                USCloseCandidateDecision.INELIGIBLE,
                None,
                "CLOSE_UNAVAILABLE",
                self.policy_id,
            )

        if evidence.evidence_kind is USCloseEvidenceKind.COMPLETED_DAILY:
            if (
                evidence.release is USEvidenceRelease.RELEASED
                and evidence.finalization is not BarFinalization.PROVISIONAL
                and evidence.research_usable
            ):
                return USCloseCandidateEvaluation(
                    USCloseCandidateDecision.ELIGIBLE,
                    1,
                    "EXACT_RELEASED_DAILY",
                    self.policy_id,
                )
            return USCloseCandidateEvaluation(
                USCloseCandidateDecision.INELIGIBLE,
                None,
                "DAILY_NOT_RELEASED_OR_USABLE",
                self.policy_id,
            )

        if evidence.evidence_kind is USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT:
            authority_rule = self._official_event_rule(resolved_context)
            if authority_rule is None:
                return USCloseCandidateEvaluation(
                    USCloseCandidateDecision.INELIGIBLE,
                    None,
                    "OFFICIAL_CLOSE_RULE_UNDECLARED",
                    self.policy_id,
                )
            if (
                resolved_context.official_close_proof is not authority_rule.proof
                or resolved_context.proof_source not in authority_rule.proof_sources
                or resolved_context.proof_semantics
                not in authority_rule.proof_semantics
            ):
                return USCloseCandidateEvaluation(
                    USCloseCandidateDecision.INELIGIBLE,
                    None,
                    "OFFICIAL_EVENT_POLICY_MISMATCH",
                    authority_rule.policy_id,
                )
            return USCloseCandidateEvaluation(
                USCloseCandidateDecision.ELIGIBLE,
                2,
                "VERIFIED_OFFICIAL_CLOSE",
                authority_rule.policy_id,
            )

        if (
            evidence.evidence_kind
            is USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE
        ):
            if (
                evidence.session is MarketSession.CONTINUOUS
                and evidence.interval_start_at is not None
                and evidence.interval_end_at is not None
                and evidence.finalization is not BarFinalization.PROVISIONAL
                and evidence.display_usable
            ):
                return USCloseCandidateEvaluation(
                    USCloseCandidateDecision.ELIGIBLE,
                    3,
                    "FINALIZED_REGULAR_INTERVAL_LIMITED",
                    self.policy_id,
                )

        if evidence.evidence_kind is USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT:
            return USCloseCandidateEvaluation(
                USCloseCandidateDecision.INELIGIBLE,
                None,
                "PROVIDER_HINT_REQUIRES_CONTEXT_GATE",
                self.policy_id,
            )

        return USCloseCandidateEvaluation(
            USCloseCandidateDecision.INELIGIBLE,
            None,
            "UNVERIFIED_CLOSE_BOUNDARY",
            self.policy_id,
        )

    @staticmethod
    def _official_event_rule(
        context: USCloseResolutionPolicyContext,
    ) -> _USOfficialCloseAuthorityRule | None:
        instrument_type = context.instrument.instrument_type
        if instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}:
            venue = str(context.instrument.venue or "").strip().upper()
            normalized = _VENUE_ALIASES.get(venue, venue)
            return CLOSE_AUTHORITY_RULES.get(normalized)
        if instrument_type is InstrumentType.INDEX:
            return INDEX_CLOSE_AUTHORITY_RULES.get(context.instrument.symbol.upper())
        return None


__all__ = [
    "USCloseCandidateDecision",
    "USCloseCandidateEvaluation",
    "USCloseResolutionPolicyContext",
    "USCloseResolutionPolicy",
    "USCloseTolerancePolicy",
    "USProviderHintContext",
    "USProviderHintEvaluation",
    "evaluate_provider_previous_close_hint",
    "close_comparison_semantics",
    "close_tolerance_policy",
    "reconcile_close_evidence",
]
