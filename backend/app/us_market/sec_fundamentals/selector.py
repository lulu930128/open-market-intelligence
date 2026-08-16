from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.us_market.sec_fundamentals.contracts import (
    CandidateSelection,
    CanonicalFact,
    CanonicalMetricSpec,
    PeriodScope,
    SecFact,
)
from app.us_market.sec_fundamentals.resolution import resolve_period, resolve_unit


SUPPORTED_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A"})


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _decimal_value(fact: SecFact) -> Decimal | None:
    if fact.value_text is None:
        return None
    try:
        value = Decimal(fact.value_text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _candidate_sort_key(
    candidate: CanonicalFact,
    *,
    tag_priority: dict[tuple[str, str], int],
) -> tuple:
    fact = candidate.source_fact
    return (
        fact.period_end_date or date.min,
        -tag_priority[(fact.taxonomy, fact.tag)],
        fact.filed_date or date.min,
        1 if (fact.form or "").endswith("/A") else 0,
        fact.accession_number or "",
        fact.fact_id,
    )


def select_canonical_fact(
    facts: Iterable[SecFact],
    *,
    spec: CanonicalMetricSpec,
    period_end: date | None = None,
    period_scope: PeriodScope | None = None,
    expected_currency: str | None = "USD",
) -> CandidateSelection:
    tag_priority = {
        (metric_tag.taxonomy, metric_tag.tag): index
        for index, metric_tag in enumerate(spec.tags)
    }
    matching_facts = [
        fact for fact in facts if (fact.taxonomy, fact.tag) in tag_priority
    ]
    selection_period_end = period_end
    if selection_period_end is None:
        dated_periods = [
            fact.period_end_date
            for fact in matching_facts
            if fact.period_end_date is not None
        ]
        selection_period_end = max(dated_periods) if dated_periods else None

    considered: list[str] = []
    issues: list[str] = []
    candidates: list[CanonicalFact] = []

    for fact in matching_facts:
        if (
            selection_period_end is not None
            and fact.period_end_date != selection_period_end
        ):
            continue
        considered.append(fact.fact_id)

        if fact.form not in SUPPORTED_FORMS:
            issues.append("unsupported_form")
            continue

        period = resolve_period(fact, statement_kind=spec.statement_kind)
        if period.status == "blocked":
            issues.extend(period.issue_codes)
            continue
        if period_scope is not None and period.scope != period_scope:
            continue

        unit = resolve_unit(fact.unit)
        if unit.status == "blocked":
            issues.extend(unit.issue_codes)
            continue
        if unit.kind != spec.unit_kind:
            issues.append("unit_kind_mismatch")
            continue
        if expected_currency is not None and unit.currency not in {None, expected_currency}:
            issues.append("currency_mismatch")
            continue

        value = _decimal_value(fact)
        if value is None:
            issues.append("invalid_decimal_value")
            continue

        candidates.append(
            CanonicalFact(
                metric_code=spec.metric_code,
                source_fact=fact,
                value=value,
                period=period,
                unit=unit,
                revision_kind="as_reported",
            )
        )

    if not candidates:
        return CandidateSelection(
            metric_code=spec.metric_code,
            status="blocked",
            selected=None,
            considered_fact_ids=tuple(considered),
            issue_codes=_dedupe((*issues, "no_eligible_fact")),
        )

    latest_period_end = max(
        candidate.source_fact.period_end_date or date.min for candidate in candidates
    )
    latest_candidates = [
        candidate
        for candidate in candidates
        if (candidate.source_fact.period_end_date or date.min) == latest_period_end
    ]
    latest_scopes = {candidate.period.scope for candidate in latest_candidates}
    if spec.statement_kind == "duration" and period_scope is None and len(latest_scopes) > 1:
        return CandidateSelection(
            metric_code=spec.metric_code,
            status="blocked",
            selected=None,
            considered_fact_ids=tuple(considered),
            issue_codes=_dedupe((*issues, "ambiguous_period_scope")),
        )

    currencies = {
        candidate.unit.currency
        for candidate in latest_candidates
        if candidate.unit.currency is not None
    }
    if expected_currency is None and len(currencies) > 1:
        return CandidateSelection(
            metric_code=spec.metric_code,
            status="disputed",
            selected=None,
            considered_fact_ids=tuple(considered),
            issue_codes=_dedupe((*issues, "mixed_currencies")),
        )

    selected = max(
        latest_candidates,
        key=lambda candidate: _candidate_sort_key(
            candidate,
            tag_priority=tag_priority,
        ),
    )
    selected_fact = selected.source_fact
    same_economic_period = [
        candidate
        for candidate in latest_candidates
        if candidate.source_fact.period_start_date == selected_fact.period_start_date
        and candidate.source_fact.period_end_date == selected_fact.period_end_date
        and candidate.source_fact.unit == selected_fact.unit
        and candidate.source_fact.tag == selected_fact.tag
    ]
    if (selected_fact.form or "").endswith("/A"):
        revision_kind = "amendment"
    elif any(
        candidate.source_fact.accession_number != selected_fact.accession_number
        for candidate in same_economic_period
    ):
        revision_kind = "later_filing"
    else:
        revision_kind = "as_reported"

    original_period_candidate = min(
        same_economic_period,
        key=lambda candidate: (
            candidate.source_fact.filed_date or date.max,
            candidate.source_fact.accession_number or "",
            candidate.source_fact.fact_id,
        ),
    )
    canonical_period = replace(
        selected.period,
        fiscal_year=original_period_candidate.period.fiscal_year,
        fiscal_quarter=original_period_candidate.period.fiscal_quarter,
    )

    selected = CanonicalFact(
        metric_code=selected.metric_code,
        source_fact=selected.source_fact,
        value=selected.value,
        period=canonical_period,
        unit=selected.unit,
        revision_kind=revision_kind,
    )
    selection_status = (
        "partial"
        if canonical_period.status == "partial" or selected.unit.status == "partial"
        else "ready"
    )
    return CandidateSelection(
        metric_code=spec.metric_code,
        status=selection_status,
        selected=selected,
        considered_fact_ids=tuple(considered),
        issue_codes=_dedupe((*issues, *canonical_period.issue_codes, *selected.unit.issue_codes)),
    )


def select_canonical_history(
    facts: Iterable[SecFact],
    *,
    spec: CanonicalMetricSpec,
    expected_currency: str | None = "USD",
    period_limit: int = 20,
) -> tuple[CandidateSelection, ...]:
    if period_limit < 1 or period_limit > 80:
        raise ValueError("period_limit must be between 1 and 80")

    fact_list = tuple(facts)
    period_keys: set[tuple[date, PeriodScope]] = set()
    tag_keys = {(item.taxonomy, item.tag) for item in spec.tags}
    for fact in fact_list:
        if (fact.taxonomy, fact.tag) not in tag_keys:
            continue
        period = resolve_period(fact, statement_kind=spec.statement_kind)
        if period.status == "blocked" or period.period_end is None:
            continue
        period_keys.add((period.period_end, period.scope))

    selected_keys = sorted(period_keys, reverse=True)[:period_limit]
    selections = [
        select_canonical_fact(
            fact_list,
            spec=spec,
            period_end=period_end,
            period_scope=period_scope,
            expected_currency=expected_currency,
        )
        for period_end, period_scope in selected_keys
    ]
    return tuple(
        sorted(
            selections,
            key=lambda item: (
                item.selected.period.period_end
                if item.selected and item.selected.period.period_end
                else date.min,
                item.selected.period.scope if item.selected else "",
            ),
        )
    )
