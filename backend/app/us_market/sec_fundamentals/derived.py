from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable, Sequence

from app.us_market.sec_fundamentals.contracts import CanonicalFact, DerivedValue


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _input_ids(*facts: CanonicalFact) -> tuple[str, ...]:
    return _dedupe(fact.source_fact.fact_id for fact in facts)


def _derived(
    *,
    metric_code: str,
    fiscal_year: int | None,
    fiscal_quarter: int | None,
    period_end,
    value: Decimal | None,
    unit: str,
    status: str,
    derivation: str,
    formula: str | None,
    input_fact_ids: Iterable[str],
    issue_codes: Iterable[str] = (),
) -> DerivedValue:
    return DerivedValue(
        metric_code=metric_code,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_end=period_end,
        value=value,
        unit=unit,
        status=status,
        derivation=derivation,
        formula=formula,
        input_fact_ids=_dedupe(input_fact_ids),
        issue_codes=_dedupe(issue_codes),
    )


def _direct_quarter(metric_code: str, fact: CanonicalFact) -> DerivedValue:
    return _derived(
        metric_code=metric_code,
        fiscal_year=fact.period.fiscal_year,
        fiscal_quarter=fact.period.fiscal_quarter,
        period_end=fact.period.period_end,
        value=fact.value if fact.period.status == "ready" else None,
        unit=fact.unit.normalized_unit or fact.source_fact.unit,
        status="ready" if fact.period.status == "ready" else "blocked",
        derivation="direct",
        formula=None,
        input_fact_ids=(fact.source_fact.fact_id,),
        issue_codes=fact.period.issue_codes,
    )


def _subtract(
    *,
    metric_code: str,
    current: CanonicalFact,
    previous: CanonicalFact,
    fiscal_quarter: int,
    derivation: str,
) -> DerivedValue:
    unit = current.unit.normalized_unit or current.source_fact.unit
    issues: list[str] = []
    if current.period.status != "ready" or previous.period.status != "ready":
        issues.append("derived_input_not_ready")
    if current.unit.normalized_unit != previous.unit.normalized_unit:
        issues.append("derived_unit_mismatch")
    value = current.value - previous.value if not issues else None
    return _derived(
        metric_code=metric_code,
        fiscal_year=current.period.fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_end=current.period.period_end,
        value=value,
        unit=unit,
        status="ready" if not issues else "blocked",
        derivation=derivation,
        formula="current_ytd - previous_ytd",
        input_fact_ids=_input_ids(current, previous),
        issue_codes=issues,
    )


def _resolve_direct_conflict(
    direct: DerivedValue,
    alternative: DerivedValue | None,
) -> DerivedValue:
    if alternative is None or alternative.status != "ready":
        return direct
    if direct.status != "ready" or direct.value != alternative.value:
        return _derived(
            metric_code=direct.metric_code,
            fiscal_year=direct.fiscal_year,
            fiscal_quarter=direct.fiscal_quarter,
            period_end=direct.period_end,
            value=None,
            unit=direct.unit,
            status="disputed",
            derivation="direct_reconciliation",
            formula="direct == derived_alternative",
            input_fact_ids=(*direct.input_fact_ids, *alternative.input_fact_ids),
            issue_codes=("direct_derived_value_conflict",),
        )
    return _derived(
        metric_code=direct.metric_code,
        fiscal_year=direct.fiscal_year,
        fiscal_quarter=direct.fiscal_quarter,
        period_end=direct.period_end,
        value=direct.value,
        unit=direct.unit,
        status="ready",
        derivation="direct_reconciled",
        formula="direct == derived_alternative",
        input_fact_ids=(*direct.input_fact_ids, *alternative.input_fact_ids),
    )


def derive_discrete_quarters(
    facts: Sequence[CanonicalFact],
    *,
    metric_code: str,
) -> tuple[DerivedValue, ...]:
    by_year: dict[int, dict[str, CanonicalFact]] = defaultdict(dict)
    for fact in facts:
        if fact.metric_code != metric_code or fact.period.fiscal_year is None:
            continue
        existing = by_year[fact.period.fiscal_year].get(fact.period.scope)
        if existing is None or (
            (fact.source_fact.filed_date or fact.period.period_end)
            > (existing.source_fact.filed_date or existing.period.period_end)
        ):
            by_year[fact.period.fiscal_year][fact.period.scope] = fact

    results: list[DerivedValue] = []
    for fiscal_year in sorted(by_year):
        scopes = by_year[fiscal_year]
        ytd_q1 = scopes.get("ytd_3m")
        ytd_q2 = scopes.get("ytd_6m")
        ytd_q3 = scopes.get("ytd_9m")
        annual = scopes.get("annual_12m")
        direct_candidates = [
            fact
            for fact in facts
            if fact.metric_code == metric_code
            and fact.period.fiscal_year == fiscal_year
            and fact.period.scope == "discrete_3m"
            and fact.period.fiscal_quarter in {2, 3, 4}
        ]
        directs = {
            fact.period.fiscal_quarter: fact
            for fact in direct_candidates
        }

        if ytd_q1 is not None:
            results.append(_direct_quarter(metric_code, ytd_q1))

        q2_alternative = (
            _subtract(
                metric_code=metric_code,
                current=ytd_q2,
                previous=ytd_q1,
                fiscal_quarter=2,
                derivation="ytd_subtraction",
            )
            if ytd_q2 is not None and ytd_q1 is not None
            else None
        )
        if directs.get(2) is not None:
            results.append(
                _resolve_direct_conflict(
                    _direct_quarter(metric_code, directs[2]),
                    q2_alternative,
                )
            )
        elif ytd_q2 is not None:
            results.append(
                q2_alternative
                if q2_alternative is not None
                else _derived(
                    metric_code=metric_code,
                    fiscal_year=fiscal_year,
                    fiscal_quarter=2,
                    period_end=ytd_q2.period.period_end,
                    value=None,
                    unit=ytd_q2.unit.normalized_unit or ytd_q2.source_fact.unit,
                    status="blocked",
                    derivation="ytd_subtraction",
                    formula="Q2 YTD - Q1 YTD",
                    input_fact_ids=(ytd_q2.source_fact.fact_id,),
                    issue_codes=("missing_predecessor_ytd",),
                )
            )

        q3_alternative = (
            _subtract(
                metric_code=metric_code,
                current=ytd_q3,
                previous=ytd_q2,
                fiscal_quarter=3,
                derivation="ytd_subtraction",
            )
            if ytd_q3 is not None and ytd_q2 is not None
            else None
        )
        if directs.get(3) is not None:
            results.append(
                _resolve_direct_conflict(
                    _direct_quarter(metric_code, directs[3]),
                    q3_alternative,
                )
            )
        elif ytd_q3 is not None:
            results.append(
                q3_alternative
                if q3_alternative is not None
                else _derived(
                    metric_code=metric_code,
                    fiscal_year=fiscal_year,
                    fiscal_quarter=3,
                    period_end=ytd_q3.period.period_end,
                    value=None,
                    unit=ytd_q3.unit.normalized_unit or ytd_q3.source_fact.unit,
                    status="blocked",
                    derivation="ytd_subtraction",
                    formula="Q3 YTD - Q2 YTD",
                    input_fact_ids=(ytd_q3.source_fact.fact_id,),
                    issue_codes=("missing_predecessor_ytd",),
                )
            )

        q4_alternative = (
            _subtract(
                metric_code=metric_code,
                current=annual,
                previous=ytd_q3,
                fiscal_quarter=4,
                derivation="annual_subtraction",
            )
            if annual is not None and ytd_q3 is not None
            else None
        )
        if directs.get(4) is not None:
            results.append(
                _resolve_direct_conflict(
                    _direct_quarter(metric_code, directs[4]),
                    q4_alternative,
                )
            )
        elif annual is not None:
            results.append(
                q4_alternative
                if q4_alternative is not None
                else _derived(
                    metric_code=metric_code,
                    fiscal_year=fiscal_year,
                    fiscal_quarter=4,
                    period_end=annual.period.period_end,
                    value=None,
                    unit=annual.unit.normalized_unit or annual.source_fact.unit,
                    status="blocked",
                    derivation="annual_subtraction",
                    formula="annual - Q3 YTD",
                    input_fact_ids=(annual.source_fact.fact_id,),
                    issue_codes=("missing_nine_month_ytd",),
                )
            )

    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.fiscal_year or 0,
                item.fiscal_quarter or 0,
            ),
        )
    )


def derive_ttm(
    quarters: Sequence[DerivedValue],
    *,
    metric_code: str,
) -> DerivedValue:
    ready = {
        (item.fiscal_year, item.fiscal_quarter): item
        for item in quarters
        if item.metric_code == metric_code
        and item.status == "ready"
        and item.value is not None
        and item.fiscal_year is not None
        and item.fiscal_quarter is not None
    }
    if not ready:
        return _derived(
            metric_code=f"{metric_code}_ttm",
            fiscal_year=None,
            fiscal_quarter=None,
            period_end=None,
            value=None,
            unit="unknown",
            status="blocked",
            derivation="ttm_sum",
            formula="sum(latest four discrete quarters)",
            input_fact_ids=(),
            issue_codes=("ttm_inputs_missing",),
        )

    latest_year, latest_quarter = max(
        ready,
        key=lambda period: period[0] * 4 + period[1] - 1,
    )
    latest_ordinal = latest_year * 4 + latest_quarter - 1
    required_periods = []
    for ordinal in range(latest_ordinal - 3, latest_ordinal + 1):
        year, zero_based_quarter = divmod(ordinal, 4)
        required_periods.append((year, zero_based_quarter + 1))

    inputs = [ready.get(period) for period in required_periods]
    if any(item is None for item in inputs):
        return _derived(
            metric_code=f"{metric_code}_ttm",
            fiscal_year=latest_year,
            fiscal_quarter=latest_quarter,
            period_end=ready[(latest_year, latest_quarter)].period_end,
            value=None,
            unit=ready[(latest_year, latest_quarter)].unit,
            status="blocked",
            derivation="ttm_sum",
            formula="sum(latest four discrete quarters)",
            input_fact_ids=(
                fact_id
                for item in inputs
                if item is not None
                for fact_id in item.input_fact_ids
            ),
            issue_codes=("ttm_period_missing",),
        )

    resolved_inputs = [item for item in inputs if item is not None]
    units = {item.unit for item in resolved_inputs}
    if len(units) != 1:
        return _derived(
            metric_code=f"{metric_code}_ttm",
            fiscal_year=latest_year,
            fiscal_quarter=latest_quarter,
            period_end=resolved_inputs[-1].period_end,
            value=None,
            unit="mixed",
            status="blocked",
            derivation="ttm_sum",
            formula="sum(latest four discrete quarters)",
            input_fact_ids=(
                fact_id for item in resolved_inputs for fact_id in item.input_fact_ids
            ),
            issue_codes=("ttm_unit_mismatch",),
        )

    return _derived(
        metric_code=f"{metric_code}_ttm",
        fiscal_year=latest_year,
        fiscal_quarter=latest_quarter,
        period_end=resolved_inputs[-1].period_end,
        value=sum((item.value for item in resolved_inputs if item.value is not None), Decimal("0")),
        unit=resolved_inputs[-1].unit,
        status="ready",
        derivation="ttm_sum",
        formula="Q-3 + Q-2 + Q-1 + Q0",
        input_fact_ids=(
            fact_id for item in resolved_inputs for fact_id in item.input_fact_ids
        ),
    )


def derive_pair_metric(
    *,
    metric_code: str,
    left: DerivedValue,
    right: DerivedValue,
    operation: str,
) -> DerivedValue:
    issues: list[str] = []
    if left.status != "ready" or right.status != "ready":
        issues.append("derived_input_not_ready")
    if operation != "growth_percent" and left.period_end != right.period_end:
        issues.append("derived_period_mismatch")

    value: Decimal | None = None
    unit = left.unit
    formula: str
    if operation == "subtract":
        formula = "left - right"
        if left.unit != right.unit:
            issues.append("derived_unit_mismatch")
        if not issues and left.value is not None and right.value is not None:
            value = left.value - right.value
    elif operation == "add":
        formula = "left + right"
        if left.unit != right.unit:
            issues.append("derived_unit_mismatch")
        if not issues and left.value is not None and right.value is not None:
            value = left.value + right.value
    elif operation == "margin_percent":
        formula = "left / right * 100"
        unit = "percent"
        if left.unit != right.unit:
            issues.append("derived_unit_mismatch")
        if right.value == 0:
            issues.append("zero_denominator")
        if not issues and left.value is not None and right.value is not None:
            value = left.value / right.value * Decimal("100")
    elif operation == "growth_percent":
        formula = "(left / right - 1) * 100"
        unit = "percent"
        if left.unit != right.unit:
            issues.append("derived_unit_mismatch")
        if right.value == 0:
            issues.append("zero_denominator")
        if not issues and left.value is not None and right.value is not None:
            value = (left.value / right.value - Decimal("1")) * Decimal("100")
    else:
        raise ValueError(f"Unsupported derived operation: {operation}")

    return _derived(
        metric_code=metric_code,
        fiscal_year=left.fiscal_year,
        fiscal_quarter=left.fiscal_quarter,
        period_end=left.period_end,
        value=value,
        unit=unit,
        status="ready" if not issues else "blocked",
        derivation=operation,
        formula=formula,
        input_fact_ids=(*left.input_fact_ids, *right.input_fact_ids),
        issue_codes=issues,
    )


def derive_growth(
    *,
    metric_code: str,
    current: DerivedValue,
    previous: DerivedValue,
    comparison: str,
) -> DerivedValue:
    expected_gap = {"qoq": 1, "yoy": 4}.get(comparison)
    if expected_gap is None:
        raise ValueError("comparison must be qoq or yoy")
    issues: list[str] = []
    if current.status != "ready" or previous.status != "ready":
        issues.append("derived_input_not_ready")
    if current.unit != previous.unit:
        issues.append("derived_unit_mismatch")
    if previous.value == 0:
        issues.append("zero_denominator")
    if None in {
        current.fiscal_year,
        current.fiscal_quarter,
        previous.fiscal_year,
        previous.fiscal_quarter,
    }:
        issues.append("growth_period_missing")
    else:
        current_ordinal = current.fiscal_year * 4 + current.fiscal_quarter - 1
        previous_ordinal = previous.fiscal_year * 4 + previous.fiscal_quarter - 1
        if current_ordinal - previous_ordinal != expected_gap:
            issues.append("growth_period_not_comparable")

    value = None
    if not issues and current.value is not None and previous.value is not None:
        value = (current.value / previous.value - Decimal("1")) * Decimal("100")
    return _derived(
        metric_code=metric_code,
        fiscal_year=current.fiscal_year,
        fiscal_quarter=current.fiscal_quarter,
        period_end=current.period_end,
        value=value,
        unit="percent",
        status="ready" if not issues else "blocked",
        derivation=f"{comparison}_growth",
        formula="(current / comparison - 1) * 100",
        input_fact_ids=(*current.input_fact_ids, *previous.input_fact_ids),
        issue_codes=issues,
    )


def reconcile_annual(
    *,
    metric_code: str,
    annual: CanonicalFact,
    quarters: Sequence[DerivedValue],
) -> DerivedValue:
    fiscal_year = annual.period.fiscal_year
    matching = [
        item
        for item in quarters
        if item.metric_code == metric_code and item.fiscal_year == fiscal_year
    ]
    issues: list[str] = []
    if len(matching) != 4 or {item.fiscal_quarter for item in matching} != {1, 2, 3, 4}:
        issues.append("annual_reconciliation_quarters_missing")
    if any(item.status != "ready" or item.value is None for item in matching):
        issues.append("annual_reconciliation_input_not_ready")
    normalized_unit = annual.unit.normalized_unit or annual.source_fact.unit
    if any(item.unit != normalized_unit for item in matching):
        issues.append("annual_reconciliation_unit_mismatch")

    difference = None
    if not issues:
        discrete_sum = sum(
            (item.value for item in matching if item.value is not None),
            Decimal("0"),
        )
        difference = annual.value - discrete_sum
        if difference != 0:
            issues.append("annual_discrete_value_conflict")
    return _derived(
        metric_code=f"{metric_code}_annual_reconciliation",
        fiscal_year=fiscal_year,
        fiscal_quarter=4,
        period_end=annual.period.period_end,
        value=difference,
        unit=normalized_unit,
        status="ready" if not issues else "disputed",
        derivation="annual_reconciliation",
        formula="annual - sum(Q1..Q4)",
        input_fact_ids=(
            annual.source_fact.fact_id,
            *(fact_id for item in matching for fact_id in item.input_fact_ids),
        ),
        issue_codes=issues,
    )
