from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Sequence


NORMALIZATION_VERSION = "tw-financial-normalization-v1"
PER_SHARE_FINANCIAL_PURPOSE = "per_share_financials"
READY_NORMALIZATION_STATUSES = frozenset({"normalized", "unchanged"})
VALID_MODES = frozenset({"current_comparable", "as_reported_as_of"})

NormalizationMode = Literal["current_comparable", "as_reported_as_of"]
AdjustmentTreatment = Literal["automatic", "official_restated"]
ResultStatus = Literal["ready", "normalized", "unchanged", "blocked", "disputed"]


@dataclass(frozen=True, slots=True)
class PerShareFinancialFact:
    fact_id: str
    stock_id: str
    fiscal_year: int
    fiscal_quarter: int
    metric_code: str
    period_scope: str
    period_end: date
    value: Decimal
    unit: str
    source_share_basis_id: str | None
    source_restated_status: str
    known_at: datetime | None = None
    source_decimal_places: int | None = None
    adjustment_treatment: AdjustmentTreatment = "automatic"


@dataclass(frozen=True, slots=True)
class ShareAdjustmentAction:
    action_id: str
    stock_id: str
    action_type: str
    effective_date: date
    adjustment_ratio: Decimal
    adjustment_purpose: str
    status: str
    known_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AdjustmentResolution:
    factor: Decimal | None
    status: ResultStatus
    action_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedPeriodFact:
    source_fact_id: str
    stock_id: str
    fiscal_year: int
    fiscal_quarter: int
    metric_code: str
    period_scope: str
    period_end: date
    normalized_value: Decimal | None
    normalized_unit: str
    adjustment_factor: Decimal | None
    comparison_basis_id: str
    normalization_status: ResultStatus
    normalization_version: str
    normalization_mode: NormalizationMode
    decision_usable: bool
    action_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
    known_at: datetime | None
    rounding_tolerance: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class DerivedFinancialMetric:
    metric_code: str
    stock_id: str
    fiscal_year: int
    fiscal_quarter: int
    period_end: date
    value: Decimal | None
    unit: str
    status: ResultStatus
    comparison_basis_id: str | None
    normalization_version: str
    normalization_mode: NormalizationMode
    input_fact_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
    known_at: datetime | None
    rounding_tolerance: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    valuation_metric: str
    value: Decimal | None
    price: Decimal
    price_as_of: datetime
    price_basis: str
    earnings_or_book_value: Decimal | None
    financial_basis: str
    financial_period_end: date | None
    status: ResultStatus
    decision_usable: bool
    input_fact_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnnualReconciliation:
    fiscal_year: int
    annual_value: Decimal | None
    discrete_sum: Decimal | None
    difference: Decimal | None
    tolerance: Decimal
    status: ResultStatus
    input_fact_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReturnRatioMetric:
    metric_code: str
    value_percent: Decimal | None
    numerator: Decimal | None
    average_denominator: Decimal | None
    period_months: int
    annualized: bool
    status: ResultStatus
    issue_codes: tuple[str, ...]


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _latest_known_at(values: Sequence[datetime | None]) -> datetime | None:
    known_values = [value for value in values if value is not None]
    return max(known_values) if known_values else None


def _period_ordinal(fiscal_year: int, fiscal_quarter: int) -> int:
    return fiscal_year * 4 + fiscal_quarter - 1


def _period_from_ordinal(ordinal: int) -> tuple[int, int]:
    fiscal_year, zero_based_quarter = divmod(ordinal, 4)
    return fiscal_year, zero_based_quarter + 1


def _expected_period_scope(fiscal_quarter: int) -> str | None:
    return {
        1: "ytd_3m",
        2: "ytd_6m",
        3: "ytd_9m",
        4: "annual_12m",
    }.get(fiscal_quarter)


def _valid_period_scopes(fiscal_quarter: int) -> frozenset[str]:
    expected = _expected_period_scope(fiscal_quarter)
    if expected is None:
        return frozenset()
    if fiscal_quarter == 1:
        return frozenset({expected})
    return frozenset({expected, "discrete_3m"})


def source_decimal_places(value_text: str | None) -> int | None:
    """Return the precision explicitly presented by the source document."""

    if value_text is None:
        return None
    cleaned = value_text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        exponent = Decimal(cleaned).as_tuple().exponent
    except Exception:
        return None
    return max(-exponent, 0)


def source_rounding_tolerance(
    *,
    decimal_places: int | None,
    adjustment_factor: Decimal | None,
) -> Decimal:
    if decimal_places is None or decimal_places < 0:
        return Decimal("0")
    if adjustment_factor is None or adjustment_factor <= 0:
        return Decimal("0")
    source_half_unit = Decimal("0.5").scaleb(-decimal_places)
    return source_half_unit / adjustment_factor


def resolve_per_share_adjustment(
    *,
    fact: PerShareFinancialFact,
    actions: Sequence[ShareAdjustmentAction],
    target_basis_date: date,
    mode: NormalizationMode,
    as_of: datetime | None = None,
) -> AdjustmentResolution:
    if mode not in VALID_MODES:
        return AdjustmentResolution(
            factor=None,
            status="blocked",
            action_ids=(),
            issue_codes=("normalization_mode_invalid",),
        )
    if target_basis_date < fact.period_end:
        return AdjustmentResolution(
            factor=None,
            status="blocked",
            action_ids=(),
            issue_codes=("target_share_basis_precedes_fact",),
        )
    if fact.adjustment_treatment not in {"automatic", "official_restated"}:
        return AdjustmentResolution(
            factor=None,
            status="blocked",
            action_ids=(),
            issue_codes=("adjustment_treatment_invalid",),
        )
    if mode == "as_reported_as_of":
        if as_of is None:
            return AdjustmentResolution(
                factor=None,
                status="blocked",
                action_ids=(),
                issue_codes=("as_of_required",),
            )
        if fact.known_at is None:
            return AdjustmentResolution(
                factor=None,
                status="blocked",
                action_ids=(),
                issue_codes=("fact_known_at_missing",),
            )
        if fact.known_at > as_of:
            return AdjustmentResolution(
                factor=None,
                status="blocked",
                action_ids=(),
                issue_codes=("fact_not_known_as_of",),
            )

    relevant_actions = sorted(
        (
            action
            for action in actions
            if action.stock_id == fact.stock_id
            and action.adjustment_purpose == PER_SHARE_FINANCIAL_PURPOSE
            and fact.period_end < action.effective_date <= target_basis_date
        ),
        key=lambda action: (action.effective_date, action.action_id),
    )

    factor = Decimal("1")
    action_ids: list[str] = []
    issues: list[str] = []
    for action in relevant_actions:
        action_ids.append(action.action_id)
        if action.status != "confirmed":
            issues.append("F003_corporate_action_unconfirmed")
            continue
        if action.adjustment_ratio <= 0:
            issues.append("F003_adjustment_ratio_invalid")
            continue
        if mode == "as_reported_as_of":
            if action.known_at is None:
                issues.append("action_known_at_missing")
                continue
            if as_of is not None and action.known_at > as_of:
                issues.append("action_not_known_as_of")
            continue
        factor *= action.adjustment_ratio

    if (
        fact.adjustment_treatment == "official_restated"
        and not relevant_actions
    ):
        issues.append("F003_restated_action_lineage_missing")
    if issues:
        return AdjustmentResolution(
            factor=None,
            status="blocked",
            action_ids=tuple(action_ids),
            issue_codes=_dedupe(issues),
        )
    if fact.adjustment_treatment == "official_restated":
        factor = Decimal("1")
    return AdjustmentResolution(
        factor=factor,
        status="ready",
        action_ids=tuple(action_ids),
        issue_codes=(),
    )


def normalize_per_share_fact(
    *,
    fact: PerShareFinancialFact,
    resolution: AdjustmentResolution,
    comparison_basis_id: str,
    mode: NormalizationMode,
    normalization_version: str = NORMALIZATION_VERSION,
) -> NormalizedPeriodFact:
    issues = list(resolution.issue_codes)
    if not fact.source_share_basis_id:
        issues.append("F002_share_basis_unverified")
    if fact.metric_code not in {"basic_eps", "diluted_eps", "book_value_per_share"}:
        issues.append("metric_not_per_share")
    if fact.unit != "TWD_per_share":
        issues.append("per_share_unit_invalid")
    if fact.period_scope not in _valid_period_scopes(fact.fiscal_quarter):
        issues.append("period_scope_mismatch")
    if resolution.factor is None or resolution.factor <= 0:
        issues.append("F003_adjustment_factor_unavailable")
    elif fact.adjustment_treatment == "official_restated":
        if fact.source_restated_status != "confirmed":
            issues.append("F003_official_restatement_unconfirmed")
        if not resolution.action_ids:
            issues.append("F003_restated_action_lineage_missing")
    elif resolution.factor != 1:
        if fact.source_restated_status == "confirmed":
            issues.append("F003_double_adjustment_risk")
        elif fact.source_restated_status != "not_restated":
            issues.append("F003_source_restatement_unknown")
        if not resolution.action_ids:
            issues.append("F003_adjustment_lineage_missing")
    elif fact.source_restated_status not in {
        "confirmed",
        "not_restated",
    }:
        issues.append("F003_source_restatement_unknown")

    if issues:
        return NormalizedPeriodFact(
            source_fact_id=fact.fact_id,
            stock_id=fact.stock_id,
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fact.fiscal_quarter,
            metric_code=fact.metric_code,
            period_scope=fact.period_scope,
            period_end=fact.period_end,
            normalized_value=None,
            normalized_unit=fact.unit,
            adjustment_factor=resolution.factor,
            comparison_basis_id=comparison_basis_id,
            normalization_status="blocked",
            normalization_version=normalization_version,
            normalization_mode=mode,
            decision_usable=False,
            action_ids=resolution.action_ids,
            issue_codes=_dedupe(issues),
            known_at=fact.known_at,
            rounding_tolerance=source_rounding_tolerance(
                decimal_places=fact.source_decimal_places,
                adjustment_factor=resolution.factor,
            ),
        )

    factor = resolution.factor or Decimal("1")
    normalized_value = fact.value / factor
    status: ResultStatus = (
        "normalized"
        if factor != 1 or fact.adjustment_treatment == "official_restated"
        else "unchanged"
    )
    return NormalizedPeriodFact(
        source_fact_id=fact.fact_id,
        stock_id=fact.stock_id,
        fiscal_year=fact.fiscal_year,
        fiscal_quarter=fact.fiscal_quarter,
        metric_code=fact.metric_code,
        period_scope=fact.period_scope,
        period_end=fact.period_end,
        normalized_value=normalized_value,
        normalized_unit=fact.unit,
        adjustment_factor=factor,
        comparison_basis_id=comparison_basis_id,
        normalization_status=status,
        normalization_version=normalization_version,
        normalization_mode=mode,
        decision_usable=True,
        action_ids=resolution.action_ids,
        issue_codes=(),
        known_at=fact.known_at,
        rounding_tolerance=source_rounding_tolerance(
            decimal_places=fact.source_decimal_places,
            adjustment_factor=factor,
        ),
    )


def normalize_per_share_series(
    *,
    facts: Sequence[PerShareFinancialFact],
    actions: Sequence[ShareAdjustmentAction],
    target_basis_date: date,
    comparison_basis_id: str,
    mode: NormalizationMode = "current_comparable",
    as_of: datetime | None = None,
    normalization_version: str = NORMALIZATION_VERSION,
) -> tuple[NormalizedPeriodFact, ...]:
    results = []
    for fact in sorted(
        facts,
        key=lambda item: (
            item.fiscal_year,
            item.fiscal_quarter,
            item.fact_id,
        ),
    ):
        resolution = resolve_per_share_adjustment(
            fact=fact,
            actions=actions,
            target_basis_date=target_basis_date,
            mode=mode,
            as_of=as_of,
        )
        results.append(
            normalize_per_share_fact(
                fact=fact,
                resolution=resolution,
                comparison_basis_id=comparison_basis_id,
                mode=mode,
                normalization_version=normalization_version,
            )
        )
    return tuple(results)


def derive_single_quarter_eps(
    facts: Sequence[NormalizedPeriodFact],
) -> tuple[DerivedFinancialMetric, ...]:
    grouped: dict[tuple[int, int], list[NormalizedPeriodFact]] = {}
    for fact in facts:
        grouped.setdefault((fact.fiscal_year, fact.fiscal_quarter), []).append(fact)

    results: list[DerivedFinancialMetric] = []
    derived_by_period: dict[tuple[int, int], DerivedFinancialMetric] = {}
    for period in sorted(grouped):
        candidates = grouped[period]
        direct_candidates = [
            item for item in candidates if item.period_scope == "discrete_3m"
        ]
        cumulative_candidates = [
            item
            for item in candidates
            if item.period_scope == _expected_period_scope(item.fiscal_quarter)
        ]
        if direct_candidates:
            current = direct_candidates[0]
            selected_candidates = direct_candidates
        elif cumulative_candidates:
            current = cumulative_candidates[0]
            selected_candidates = cumulative_candidates
        else:
            current = candidates[0]
            selected_candidates = candidates
        issues: list[str] = []
        inputs = [current]
        rounding_tolerance = current.rounding_tolerance
        extra_input_fact_ids: list[str] = []
        extra_action_ids: list[str] = []
        extra_known_at: list[datetime | None] = []
        if len(selected_candidates) != 1:
            issues.append("F007_duplicate_financial_period")
        if current.metric_code != "basic_eps":
            issues.append("metric_not_basic_eps")
        if current.normalization_status not in READY_NORMALIZATION_STATUSES:
            issues.extend(current.issue_codes or ("normalization_not_ready",))
        if not current.decision_usable or current.normalized_value is None:
            issues.append("normalization_not_decision_usable")
        if current.period_scope not in _valid_period_scopes(
            current.fiscal_quarter
        ):
            issues.append("period_scope_mismatch")

        previous: NormalizedPeriodFact | None = None
        use_direct_value = (
            current.period_scope == "discrete_3m"
            or current.fiscal_quarter == 1
        )
        use_prior_discrete_sum = False
        prior_discrete: list[DerivedFinancialMetric] = []
        if current.fiscal_quarter > 1 and not use_direct_value:
            previous_candidates = grouped.get(
                (current.fiscal_year, current.fiscal_quarter - 1),
                [],
            )
            expected_previous_scope = _expected_period_scope(
                current.fiscal_quarter - 1
            )
            previous_cumulative = [
                item
                for item in previous_candidates
                if item.period_scope == expected_previous_scope
            ]
            if len(previous_cumulative) == 1:
                previous = previous_cumulative[0]
                inputs.append(previous)
                rounding_tolerance += previous.rounding_tolerance
                if previous.normalization_status not in READY_NORMALIZATION_STATUSES:
                    issues.extend(
                        previous.issue_codes
                        or ("previous_normalization_not_ready",)
                    )
                if not previous.decision_usable or previous.normalized_value is None:
                    issues.append("previous_normalization_not_decision_usable")
                if previous.comparison_basis_id != current.comparison_basis_id:
                    issues.append("F002_mixed_share_basis")
                if previous.normalized_unit != current.normalized_unit:
                    issues.append("normalized_unit_mismatch")
                if previous.normalization_version != current.normalization_version:
                    issues.append("normalization_version_mismatch")
                if previous.normalization_mode != current.normalization_mode:
                    issues.append("normalization_mode_mismatch")
            else:
                prior_discrete = [
                    derived_by_period.get(
                        (current.fiscal_year, prior_quarter)
                    )
                    for prior_quarter in range(1, current.fiscal_quarter)
                ]
                if (
                    any(item is None for item in prior_discrete)
                    or len(prior_discrete) != current.fiscal_quarter - 1
                ):
                    issues.append(
                        "F007_previous_ytd_period_missing_or_duplicate"
                    )
                else:
                    usable_prior = [
                        item for item in prior_discrete if item is not None
                    ]
                    use_prior_discrete_sum = True
                    for item in usable_prior:
                        rounding_tolerance += item.rounding_tolerance
                        if item.status != "ready" or item.value is None:
                            issues.extend(
                                item.issue_codes
                                or ("previous_normalization_not_ready",)
                            )
                        if item.comparison_basis_id != current.comparison_basis_id:
                            issues.append("F002_mixed_share_basis")
                        if item.unit != current.normalized_unit:
                            issues.append("normalized_unit_mismatch")
                        if (
                            item.normalization_version
                            != current.normalization_version
                        ):
                            issues.append("normalization_version_mismatch")
                        if item.normalization_mode != current.normalization_mode:
                            issues.append("normalization_mode_mismatch")
                        extra_input_fact_ids.extend(item.input_fact_ids)
                        extra_action_ids.extend(item.action_ids)
                        extra_known_at.append(item.known_at)

        if issues:
            value = None
            status: ResultStatus = "blocked"
        elif use_direct_value:
            value = current.normalized_value
            status = "ready"
        elif previous is not None:
            value = current.normalized_value - previous.normalized_value
            status = "ready"
        elif use_prior_discrete_sum:
            value = current.normalized_value - sum(
                (
                    item.value
                    for item in prior_discrete
                    if item is not None and item.value is not None
                ),
                Decimal("0"),
            )
            status = "ready"
        else:
            value = None
            status = "blocked"
            issues.append("F007_previous_ytd_period_missing_or_duplicate")

        result = DerivedFinancialMetric(
                metric_code="single_quarter_basic_eps",
                stock_id=current.stock_id,
                fiscal_year=current.fiscal_year,
                fiscal_quarter=current.fiscal_quarter,
                period_end=current.period_end,
                value=value,
                unit=current.normalized_unit,
                status=status,
                comparison_basis_id=current.comparison_basis_id,
                normalization_version=current.normalization_version,
                normalization_mode=current.normalization_mode,
                input_fact_ids=_dedupe(
                    [item.source_fact_id for item in inputs]
                    + extra_input_fact_ids
                ),
                action_ids=_dedupe(
                    [
                        action_id
                        for item in inputs
                        for action_id in item.action_ids
                    ]
                    + extra_action_ids
                ),
                issue_codes=_dedupe(issues),
                known_at=_latest_known_at(
                    [item.known_at for item in inputs] + extra_known_at
                ),
                rounding_tolerance=rounding_tolerance,
            )
        results.append(result)
        derived_by_period[period] = result
    return tuple(results)


def calculate_ttm_eps(
    discrete_quarters: Sequence[DerivedFinancialMetric],
    *,
    end_period: tuple[int, int] | None = None,
) -> DerivedFinancialMetric:
    if not discrete_quarters:
        return DerivedFinancialMetric(
            metric_code="ttm_basic_eps",
            stock_id="",
            fiscal_year=0,
            fiscal_quarter=0,
            period_end=date.min,
            value=None,
            unit="TWD_per_share",
            status="blocked",
            comparison_basis_id=None,
            normalization_version=NORMALIZATION_VERSION,
            normalization_mode="current_comparable",
            input_fact_ids=(),
            action_ids=(),
            issue_codes=("F007_ttm_inputs_missing",),
            known_at=None,
            rounding_tolerance=Decimal("0"),
        )

    grouped: dict[tuple[int, int], list[DerivedFinancialMetric]] = {}
    for item in discrete_quarters:
        grouped.setdefault((item.fiscal_year, item.fiscal_quarter), []).append(item)
    if end_period is None:
        end_period = max(grouped)
    end_ordinal = _period_ordinal(*end_period)
    expected_periods = [
        _period_from_ordinal(ordinal)
        for ordinal in range(end_ordinal - 3, end_ordinal + 1)
    ]
    selected: list[DerivedFinancialMetric] = []
    issues: list[str] = []
    for period in expected_periods:
        candidates = grouped.get(period, [])
        if len(candidates) != 1:
            issues.append("F007_ttm_period_missing_or_duplicate")
            continue
        selected.append(candidates[0])

    reference = grouped.get(end_period, [discrete_quarters[-1]])[0]
    for item in selected:
        if item.metric_code != "single_quarter_basic_eps":
            issues.append("F001_ttm_requires_discrete_eps")
        if item.status != "ready" or item.value is None:
            issues.extend(item.issue_codes or ("F007_ttm_input_not_ready",))
        if item.stock_id != reference.stock_id:
            issues.append("ttm_stock_mismatch")
        if item.comparison_basis_id != reference.comparison_basis_id:
            issues.append("F002_mixed_share_basis")
        if item.unit != reference.unit:
            issues.append("ttm_unit_mismatch")
        if item.normalization_version != reference.normalization_version:
            issues.append("normalization_version_mismatch")
        if item.normalization_mode != reference.normalization_mode:
            issues.append("normalization_mode_mismatch")

    value = (
        sum((item.value for item in selected), Decimal("0"))
        if not issues and len(selected) == 4
        else None
    )
    return DerivedFinancialMetric(
        metric_code="ttm_basic_eps",
        stock_id=reference.stock_id,
        fiscal_year=end_period[0],
        fiscal_quarter=end_period[1],
        period_end=reference.period_end,
        value=value,
        unit=reference.unit,
        status="ready" if value is not None else "blocked",
        comparison_basis_id=reference.comparison_basis_id,
        normalization_version=reference.normalization_version,
        normalization_mode=reference.normalization_mode,
        input_fact_ids=_dedupe(
            [
                fact_id
                for item in selected
                for fact_id in item.input_fact_ids
            ]
        ),
        action_ids=_dedupe(
            [
                action_id
                for item in selected
                for action_id in item.action_ids
            ]
        ),
        issue_codes=_dedupe(issues),
        known_at=_latest_known_at([item.known_at for item in selected]),
        rounding_tolerance=sum(
            (item.rounding_tolerance for item in selected),
            Decimal("0"),
        ),
    )


def calculate_pe_snapshot(
    *,
    price: Decimal,
    price_as_of: datetime,
    price_basis: str,
    ttm_eps: DerivedFinancialMetric,
) -> ValuationSnapshot:
    issues: list[str] = []
    if price <= 0:
        issues.append("valuation_price_invalid")
    if ttm_eps.metric_code != "ttm_basic_eps":
        issues.append("valuation_financial_basis_invalid")
    if ttm_eps.status != "ready" or ttm_eps.value is None:
        issues.extend(ttm_eps.issue_codes or ("valuation_ttm_eps_not_ready",))
    elif ttm_eps.value <= 0:
        issues.append("valuation_ttm_eps_non_positive")

    value = price / ttm_eps.value if not issues and ttm_eps.value is not None else None
    return ValuationSnapshot(
        valuation_metric="pe_ttm",
        value=value,
        price=price,
        price_as_of=price_as_of,
        price_basis=price_basis,
        earnings_or_book_value=ttm_eps.value,
        financial_basis="ttm_basic_eps",
        financial_period_end=ttm_eps.period_end if ttm_eps.period_end != date.min else None,
        status="ready" if value is not None else "blocked",
        decision_usable=value is not None,
        input_fact_ids=ttm_eps.input_fact_ids,
        issue_codes=_dedupe(issues),
    )


def reconcile_annual_to_discrete(
    *,
    annual_fact: NormalizedPeriodFact,
    discrete_quarters: Sequence[DerivedFinancialMetric],
    tolerance: Decimal | None = None,
) -> AnnualReconciliation:
    issues: list[str] = []
    if annual_fact.fiscal_quarter != 4 or annual_fact.period_scope != "annual_12m":
        issues.append("annual_fact_scope_invalid")
    if (
        annual_fact.normalization_status not in READY_NORMALIZATION_STATUSES
        or annual_fact.normalized_value is None
    ):
        issues.extend(annual_fact.issue_codes or ("annual_fact_not_ready",))

    selected = [
        item
        for item in discrete_quarters
        if item.fiscal_year == annual_fact.fiscal_year
    ]
    by_quarter: dict[int, list[DerivedFinancialMetric]] = {}
    for item in selected:
        by_quarter.setdefault(item.fiscal_quarter, []).append(item)
    ordered: list[DerivedFinancialMetric] = []
    for quarter in range(1, 5):
        candidates = by_quarter.get(quarter, [])
        if len(candidates) != 1:
            issues.append("annual_reconciliation_period_missing_or_duplicate")
            continue
        current = candidates[0]
        ordered.append(current)
        if current.status != "ready" or current.value is None:
            issues.extend(current.issue_codes or ("annual_reconciliation_input_not_ready",))
        if current.comparison_basis_id != annual_fact.comparison_basis_id:
            issues.append("F002_mixed_share_basis")
        if current.normalization_version != annual_fact.normalization_version:
            issues.append("normalization_version_mismatch")
        if current.normalization_mode != annual_fact.normalization_mode:
            issues.append("normalization_mode_mismatch")

    discrete_sum = (
        sum((item.value for item in ordered), Decimal("0"))
        if not issues and len(ordered) == 4
        else None
    )
    difference = (
        discrete_sum - annual_fact.normalized_value
        if discrete_sum is not None and annual_fact.normalized_value is not None
        else None
    )
    effective_tolerance = (
        tolerance
        if tolerance is not None
        else annual_fact.rounding_tolerance
        + sum(
            (item.rounding_tolerance for item in ordered),
            Decimal("0"),
        )
    )
    if difference is not None and abs(difference) > effective_tolerance:
        issues.append("annual_reconciliation_mismatch")

    return AnnualReconciliation(
        fiscal_year=annual_fact.fiscal_year,
        annual_value=annual_fact.normalized_value,
        discrete_sum=discrete_sum,
        difference=difference,
        tolerance=effective_tolerance,
        status="ready" if not issues else "disputed",
        input_fact_ids=_dedupe(
            [annual_fact.source_fact_id]
            + [
                fact_id
                for item in ordered
                for fact_id in item.input_fact_ids
            ]
        ),
        issue_codes=_dedupe(issues),
    )


def calculate_return_ratio(
    *,
    metric_code: Literal["roe", "roa"],
    numerator: Decimal | None,
    beginning_denominator: Decimal | None,
    ending_denominator: Decimal | None,
    period_months: int,
    annualized: bool,
) -> ReturnRatioMetric:
    issues: list[str] = []
    if numerator is None:
        issues.append("return_ratio_numerator_missing")
    if beginning_denominator is None or ending_denominator is None:
        issues.append("return_ratio_average_denominator_missing")
    if period_months < 1 or period_months > 12:
        issues.append("return_ratio_period_months_invalid")

    average_denominator = None
    if beginning_denominator is not None and ending_denominator is not None:
        average_denominator = (beginning_denominator + ending_denominator) / Decimal("2")
        if average_denominator <= 0:
            issues.append("return_ratio_average_denominator_non_positive")

    value = None
    if not issues and numerator is not None and average_denominator is not None:
        value = numerator / average_denominator * Decimal("100")
        if annualized:
            value *= Decimal("12") / Decimal(period_months)

    return ReturnRatioMetric(
        metric_code=metric_code,
        value_percent=value,
        numerator=numerator,
        average_denominator=average_denominator,
        period_months=period_months,
        annualized=annualized,
        status="ready" if value is not None else "blocked",
        issue_codes=_dedupe(issues),
    )


def display_decimal(value: Decimal | None, places: int = 2) -> Decimal | None:
    if value is None:
        return None
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)
