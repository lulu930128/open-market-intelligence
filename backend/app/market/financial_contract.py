from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any, Sequence

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    MonthlyRevenue,
    SourceRegistry,
    TaiwanFinancialBasisAssessment,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_parse_runs import canonical_parse_run_id_for_filing
from app.market.financial_metric_normalization import (
    DerivedFinancialMetric,
    NormalizedPeriodFact,
    calculate_pe_snapshot,
    calculate_ttm_eps,
    derive_single_quarter_eps,
    display_decimal,
    reconcile_annual_to_discrete,
    source_decimal_places,
    source_rounding_tolerance,
)
from app.market.financial_metric_semantics import (
    source_reported_financial_semantics,
)
from app.market.financial_valuation import (
    DailyCloseValuationInput,
    resolve_latest_completed_daily_close,
)
from app.market.monthly_revenue_continuity import (
    analyze_monthly_revenue_continuity,
)


FINANCIAL_CONTRACT_VERSION = "omi.financial.v1"
FINANCIAL_CONTRACT_MODES = frozenset(
    {"current_comparable", "as_reported_as_of"}
)
TRUSTED_NORMALIZED_SOURCE_LEVELS = frozenset(
    {"official", "regulated_filing", "verified_official_mirror"}
)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _legacy_financial_row(row: Any) -> dict[str, Any]:
    payload = {
        key: _json_value(_value(row, key))
        for key in (
            "id",
            "source_id",
            "raw_result_id",
            "stock_id",
            "period",
            "fiscal_year",
            "quarter",
            "report_date",
            "released_at",
            "filed_at",
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "net_income_attributable_parent",
            "eps",
            "total_assets",
            "total_equity",
            "parent_equity",
            "book_value_per_share",
            "roe",
            "roa",
        )
    }
    payload.update(source_reported_financial_semantics(row))
    return payload


def build_legacy_financial_contract(
    *,
    stock_id: str,
    financial_history: Sequence[Any],
    revenue_history: Sequence[Any],
    mode: str = "current_comparable",
    as_of: datetime | None = None,
    revenue_continuity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in FINANCIAL_CONTRACT_MODES:
        raise ValueError(f"Unsupported financial contract mode: {mode}")
    resolved_as_of = as_of or datetime.now(timezone.utc)
    continuity = revenue_continuity or analyze_monthly_revenue_continuity(
        revenue_history
    )
    bounded_history = list(financial_history)[-8:]
    projected_history = [_legacy_financial_row(row) for row in bounded_history]
    warnings = [
        warning
        for row in projected_history
        for warning in row.get("normalization_warnings") or []
    ]
    issues = list(dict.fromkeys(warnings + list(continuity.get("issues") or [])))
    issues.extend(
        issue
        for issue in (
            "legacy_source_only",
            "normalized_financial_facts_unavailable",
            (
                "point_in_time_known_at_missing"
                if mode == "as_reported_as_of"
                else None
            ),
        )
        if issue and issue not in issues
    )
    has_financials = bool(projected_history)
    current_history = (
        projected_history
        if mode == "current_comparable"
        else []
    )
    source_refs = [
        {
            "type": "table",
            "name": "financial_metric_quarterly",
            "row_id": row.get("id"),
            "raw_result_id": row.get("raw_result_id"),
            "source_id": row.get("source_id"),
            "semantics": "source_reported_legacy",
        }
        for row in projected_history
    ]
    return {
        "contract_version": FINANCIAL_CONTRACT_VERSION,
        "target": {"market": "TW", "stock_id": stock_id},
        "as_of": resolved_as_of.isoformat(),
        "mode": mode,
        "as_reported": {
            "status": (
                "available_with_legacy_semantics"
                if has_financials and mode == "current_comparable"
                else "blocked"
                if has_financials
                else "missing"
            ),
            "amount_unit": "TWD_thousand",
            "per_share_unit": "TWD_per_share",
            "latest": current_history[-1] if current_history else None,
            "history": current_history,
        },
        "normalized": {
            "status": "blocked",
            "facts": [],
            "comparison_basis_id": None,
            "normalization_version": None,
        },
        "derived": {
            "status": "blocked",
            "single_quarter_eps": [],
            "annual_reconciliations": [],
            "ttm_eps": None,
            "ttm_eps_status": "blocked",
            "ttm_periods": [],
        },
        "valuation": {
            "status": "blocked",
            "pe_ttm": None,
            "price": None,
            "price_as_of": None,
            "financial_basis": None,
        },
        "quality": {
            "freshness": "unknown" if has_financials else "missing",
            "continuity": continuity.get("status", "missing"),
            "semantic_validity": (
                "unknown_share_basis" if has_financials else "not_applicable"
            ),
            "decision_usable": False,
            "issues": issues,
            "revenue_continuity": continuity,
        },
        "source_refs": source_refs,
    }


def _derived_payload(item: DerivedFinancialMetric) -> dict[str, Any]:
    return {
        "metric_code": item.metric_code,
        "period": f"{item.fiscal_year}Q{item.fiscal_quarter}",
        "period_end": item.period_end.isoformat(),
        "value": item.value,
        "unit": item.unit,
        "status": item.status,
        "comparison_basis_id": item.comparison_basis_id,
        "normalization_version": item.normalization_version,
        "input_fact_ids": list(item.input_fact_ids),
        "action_ids": list(item.action_ids),
        "issue_codes": list(item.issue_codes),
        "known_at": _iso_utc(item.known_at),
        "rounding_tolerance": item.rounding_tolerance,
    }


def build_normalized_financial_contract(
    *,
    baseline: dict[str, Any],
    normalized_facts: Sequence[NormalizedPeriodFact],
    revenue_continuity: dict[str, Any],
    price: Decimal | None = None,
    price_as_of: datetime | None = None,
    price_basis: str = "explicit_input",
    extra_issues: Sequence[str] = (),
) -> dict[str, Any]:
    contract = {
        **baseline,
        "as_reported": dict(baseline.get("as_reported") or {}),
        "quality": dict(baseline.get("quality") or {}),
        "source_refs": list(baseline.get("source_refs") or []),
    }
    facts = tuple(normalized_facts)
    discrete = derive_single_quarter_eps(facts)
    annual_reconciliations = tuple(
        reconcile_annual_to_discrete(
            annual_fact=fact,
            discrete_quarters=discrete,
        )
        for fact in facts
        if fact.fiscal_quarter == 4
        and fact.period_scope == "annual_12m"
    )
    ttm = calculate_ttm_eps(discrete)
    normalized_ready = bool(facts) and all(
        fact.decision_usable
        and fact.normalization_status in {"normalized", "unchanged"}
        and fact.normalized_value is not None
        for fact in facts
    )
    comparison_basis_ids = {
        fact.comparison_basis_id
        for fact in facts
        if fact.comparison_basis_id
    }
    versions = {
        fact.normalization_version
        for fact in facts
        if fact.normalization_version
    }
    normalized_payload = [
        {
            "source_fact_id": fact.source_fact_id,
            "period": f"{fact.fiscal_year}Q{fact.fiscal_quarter}",
            "period_scope": fact.period_scope,
            "period_end": fact.period_end.isoformat(),
            "metric_code": fact.metric_code,
            "normalized_value": fact.normalized_value,
            "normalized_unit": fact.normalized_unit,
            "adjustment_factor": fact.adjustment_factor,
            "comparison_basis_id": fact.comparison_basis_id,
            "normalization_status": fact.normalization_status,
            "normalization_version": fact.normalization_version,
            "normalization_mode": fact.normalization_mode,
            "decision_usable": fact.decision_usable,
            "action_ids": list(fact.action_ids),
            "issue_codes": list(fact.issue_codes),
            "known_at": _iso_utc(fact.known_at),
            "rounding_tolerance": fact.rounding_tolerance,
        }
        for fact in facts
    ]
    contract["normalized"] = {
        "status": "ready" if normalized_ready else "blocked",
        "facts": normalized_payload,
        "comparison_basis_id": (
            next(iter(comparison_basis_ids))
            if len(comparison_basis_ids) == 1
            else None
        ),
        "normalization_version": (
            next(iter(versions)) if len(versions) == 1 else None
        ),
    }
    ttm_periods = [
        f"{item.fiscal_year}Q{item.fiscal_quarter}"
        for item in discrete
        if item.status == "ready"
        and _period_ordinal(item.fiscal_year, item.fiscal_quarter)
        >= _period_ordinal(ttm.fiscal_year, ttm.fiscal_quarter) - 3
    ]
    contract["derived"] = {
        "status": ttm.status,
        "single_quarter_eps": [_derived_payload(item) for item in discrete],
        "annual_reconciliations": [
            {
                "fiscal_year": item.fiscal_year,
                "annual_value": item.annual_value,
                "discrete_sum": item.discrete_sum,
                "difference": item.difference,
                "tolerance": item.tolerance,
                "within_tolerance": (
                    item.difference is not None
                    and abs(item.difference) <= item.tolerance
                ),
                "status": item.status,
                "input_fact_ids": list(item.input_fact_ids),
                "issue_codes": list(item.issue_codes),
            }
            for item in annual_reconciliations
        ],
        "ttm_eps": display_decimal(ttm.value),
        "ttm_eps_exact": str(ttm.value) if ttm.value is not None else None,
        "ttm_eps_status": ttm.status,
        "ttm_rounding_tolerance": ttm.rounding_tolerance,
        "ttm_periods": ttm_periods,
        "input_fact_ids": list(ttm.input_fact_ids),
        "action_ids": list(ttm.action_ids),
        "issue_codes": list(ttm.issue_codes),
    }
    valuation = None
    if price is not None and price_as_of is not None:
        valuation = calculate_pe_snapshot(
            price=price,
            price_as_of=price_as_of,
            price_basis=price_basis,
            ttm_eps=ttm,
        )
    contract["valuation"] = {
        "status": valuation.status if valuation else "unavailable",
        "pe_ttm": display_decimal(valuation.value) if valuation else None,
        "pe_ttm_exact": (
            str(valuation.value)
            if valuation is not None and valuation.value is not None
            else None
        ),
        "price": valuation.price if valuation else price,
        "price_as_of": (
            valuation.price_as_of.isoformat()
            if valuation is not None
            else price_as_of.isoformat()
            if price_as_of is not None
            else None
        ),
        "price_basis": valuation.price_basis if valuation else price_basis,
        "financial_basis": (
            valuation.financial_basis if valuation else "ttm_basic_eps"
        ),
        "decision_usable": valuation.decision_usable if valuation else False,
        "input_fact_ids": (
            list(valuation.input_fact_ids) if valuation else []
        ),
        "issue_codes": (
            list(valuation.issue_codes)
            if valuation
            else ["valuation_price_missing"]
        ),
    }

    issues = list(extra_issues)
    issues.extend(
        issue
        for fact in facts
        for issue in fact.issue_codes
    )
    issues.extend(ttm.issue_codes)
    issues.extend(
        issue
        for reconciliation in annual_reconciliations
        for issue in reconciliation.issue_codes
    )
    issues.extend(revenue_continuity.get("issues") or [])
    if valuation:
        issues.extend(valuation.issue_codes)
    has_disputed_normalization = any(
        fact.normalization_status == "disputed"
        for fact in facts
    )
    has_disputed_reconciliation = any(
        item.status != "ready"
        for item in annual_reconciliations
    )
    decision_usable = (
        ttm.status == "ready"
        and bool(revenue_continuity.get("decision_usable"))
        and not issues
    )
    contract["quality"] = {
        "freshness": baseline.get("quality", {}).get("freshness", "unknown"),
        "continuity": revenue_continuity.get("status", "missing"),
        "semantic_validity": (
            "valid"
            if (
                ttm.status == "ready"
                and not extra_issues
                and not has_disputed_reconciliation
            )
            else "disputed"
            if (
                extra_issues
                or has_disputed_normalization
                or has_disputed_reconciliation
            )
            else "unknown_share_basis"
        ),
        "decision_usable": decision_usable,
        "issues": list(dict.fromkeys(issues)),
        "revenue_continuity": revenue_continuity,
    }
    return contract


def _period_ordinal(fiscal_year: int, fiscal_quarter: int) -> int:
    return fiscal_year * 4 + fiscal_quarter - 1


def _lineage_action_ids(value: str) -> tuple[str, ...]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    values = payload.get("corporate_action_ids")
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if item is not None)


def _json_string_list(value: str) -> tuple[str, ...]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ("normalization_issue_codes_invalid",)
    if not isinstance(payload, list):
        return ("normalization_issue_codes_invalid",)
    return tuple(str(item) for item in payload if item is not None)


def _block_untrusted_normalization(
    baseline: dict[str, Any],
    *,
    source_names: Sequence[str],
) -> dict[str, Any]:
    contract = {
        **baseline,
        "quality": dict(baseline.get("quality") or {}),
    }
    issues = list(contract["quality"].get("issues") or [])
    if "normalized_source_untrusted" not in issues:
        issues.append("normalized_source_untrusted")
    contract["quality"].update(
        {
            "semantic_validity": "disputed",
            "decision_usable": False,
            "issues": issues,
        }
    )
    contract["normalized"] = {
        **dict(contract.get("normalized") or {}),
        "status": "blocked",
        "untrusted_source_names": sorted(set(source_names)),
    }
    return contract


def _basis_assessment_requirements(value: str) -> list[str]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ["basis_assessment_requirements_invalid"]
    if not isinstance(payload, list):
        return ["basis_assessment_requirements_invalid"]
    return [str(item) for item in payload if item is not None]


def _apply_blocking_basis_assessment(
    baseline: dict[str, Any],
    *,
    assessment: TaiwanFinancialBasisAssessment,
) -> dict[str, Any]:
    contract = {
        **baseline,
        "quality": dict(baseline.get("quality") or {}),
        "source_refs": list(baseline.get("source_refs") or []),
    }
    issue_code = assessment.issue_code
    issues = list(contract["quality"].get("issues") or [])
    if issue_code not in issues:
        issues.append(issue_code)
    assessment_payload = {
        "assessment_type": assessment.assessment_type,
        "outcome": assessment.outcome,
        "effective_date": assessment.effective_date.isoformat(),
        "issue_code": issue_code,
        "rationale": assessment.rationale,
        "resolution_requirements": _basis_assessment_requirements(
            assessment.resolution_requirements_json
        ),
        "evidence_package_hash": assessment.evidence_package_hash,
        "known_at": _iso_utc(assessment.known_at),
        "reviewed_at": _iso_utc(assessment.reviewed_at),
        "reviewed_by": assessment.reviewed_by,
    }
    contract["basis_assessment"] = assessment_payload
    contract["normalized"] = {
        **dict(contract.get("normalized") or {}),
        "status": "blocked",
        "issue_codes": [issue_code],
    }
    contract["derived"] = {
        **dict(contract.get("derived") or {}),
        "status": "blocked",
        "ttm_eps": None,
        "ttm_eps_status": "blocked",
        "issue_codes": [issue_code],
    }
    contract["valuation"] = {
        **dict(contract.get("valuation") or {}),
        "status": "blocked",
        "pe_ttm": None,
        "issue_codes": [issue_code],
    }
    contract["quality"].update(
        {
            "semantic_validity": "accounting_basis_transition",
            "decision_usable": False,
            "issues": issues,
        }
    )
    contract["source_refs"].append(
        {
            "type": "table",
            "name": "tw_financial_basis_assessment",
            "row_id": assessment.id,
            "raw_result_id": assessment.raw_result_id,
            "assessment_type": assessment.assessment_type,
            "outcome": assessment.outcome,
            "evidence_package_hash": assessment.evidence_package_hash,
        }
    )
    return contract


def build_database_financial_contract(
    db: Session,
    *,
    stock_id: str,
    mode: str = "current_comparable",
    as_of: datetime | None = None,
    financial_history: Sequence[Any] | None = None,
    revenue_history: Sequence[Any] | None = None,
    price: Decimal | None = None,
    price_as_of: datetime | None = None,
    price_basis: str = "explicit_input",
    normalized_period_limit: int = 9,
) -> dict[str, Any]:
    if normalized_period_limit < 5 or normalized_period_limit > 41:
        raise ValueError("normalized_period_limit must be between 5 and 41")
    if financial_history is None:
        financial_history = (
            db.query(FinancialMetricQuarterly)
            .filter(FinancialMetricQuarterly.stock_id == stock_id)
            .order_by(
                FinancialMetricQuarterly.fiscal_year.desc(),
                FinancialMetricQuarterly.quarter.desc(),
            )
            .limit(8)
            .all()
        )
        financial_history = list(reversed(financial_history))
    if revenue_history is None:
        revenue_history = (
            db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.stock_id == stock_id)
            .order_by(MonthlyRevenue.period.desc())
            .limit(24)
            .all()
        )
        revenue_history = list(reversed(revenue_history))
    continuity = analyze_monthly_revenue_continuity(revenue_history)
    baseline = build_legacy_financial_contract(
        stock_id=stock_id,
        financial_history=financial_history,
        revenue_history=revenue_history,
        mode=mode,
        as_of=as_of,
        revenue_continuity=continuity,
    )

    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("tw_financial_normalized_fact"):
        return baseline
    if inspect(bind).has_table("tw_financial_basis_assessment"):
        assessment_query = (
            db.query(TaiwanFinancialBasisAssessment)
            .filter(
                TaiwanFinancialBasisAssessment.stock_id == stock_id,
                TaiwanFinancialBasisAssessment.normalization_mode == mode,
            )
        )
        if mode == "as_reported_as_of":
            if as_of is None:
                return baseline
            assessment_query = assessment_query.filter(
                TaiwanFinancialBasisAssessment.known_at <= as_of,
                TaiwanFinancialBasisAssessment.reviewed_at <= as_of,
            )
        active_assessment = (
            assessment_query.order_by(
                TaiwanFinancialBasisAssessment.reviewed_at.desc(),
                TaiwanFinancialBasisAssessment.id.desc(),
            ).first()
        )
        if active_assessment is not None and active_assessment.outcome == "blocked":
            return _apply_blocking_basis_assessment(
                baseline,
                assessment=active_assessment,
            )
    query = (
        db.query(
            TaiwanFinancialNormalizedFact,
            TaiwanFinancialStatementFact,
            TaiwanFinancialFiling,
            SourceRegistry.priority,
            SourceRegistry.reliability_level,
            SourceRegistry.source_name,
        )
        .join(
            TaiwanFinancialStatementFact,
            TaiwanFinancialStatementFact.id
            == TaiwanFinancialNormalizedFact.source_fact_id,
        )
        .join(
            TaiwanFinancialParseRun,
            TaiwanFinancialParseRun.id
            == TaiwanFinancialStatementFact.parse_run_id,
        )
        .join(
            TaiwanFinancialFiling,
            TaiwanFinancialFiling.id
            == TaiwanFinancialParseRun.filing_id,
        )
        .join(
            SourceRegistry,
            SourceRegistry.id == TaiwanFinancialFiling.source_id,
        )
        .filter(
            TaiwanFinancialStatementFact.stock_id == stock_id,
            TaiwanFinancialStatementFact.metric_code == "basic_eps",
            TaiwanFinancialStatementFact.filing_id
            == TaiwanFinancialFiling.id,
            TaiwanFinancialParseRun.parse_status == "succeeded",
            TaiwanFinancialParseRun.id
            == canonical_parse_run_id_for_filing(
                TaiwanFinancialStatementFact.filing_id,
                reviewed_as_of=(
                    as_of if mode == "as_reported_as_of" else None
                ),
            ),
            TaiwanFinancialNormalizedFact.normalization_mode == mode,
        )
    )
    if mode == "as_reported_as_of":
        if as_of is None:
            return baseline
        query = query.filter(
            TaiwanFinancialFiling.known_at.is_not(None),
            TaiwanFinancialFiling.known_at <= as_of,
            TaiwanFinancialNormalizedFact.derived_at <= as_of,
        )
    rows = query.all()
    if not rows:
        return baseline
    trusted_rows = [
        row
        for row in rows
        if row[4] in TRUSTED_NORMALIZED_SOURCE_LEVELS
    ]
    if not trusted_rows:
        return _block_untrusted_normalization(
            baseline,
            source_names=[str(row[5]) for row in rows],
        )
    rows = trusted_rows

    grouped: dict[
        tuple[int, int, str],
        list[tuple[Any, Any, Any, int, str, str]],
    ] = {}
    for row in rows:
        normalized, fact, filing, _priority, _reliability, _source_name = row
        grouped.setdefault(
            (
                fact.fiscal_year,
                fact.fiscal_quarter or 0,
                fact.period_scope or "unknown",
            ),
            [],
        ).append(
            (
                normalized,
                fact,
                filing,
                _priority,
                _reliability,
                _source_name,
            )
        )

    selected = []
    conflicts: list[str] = []
    selected_periods = set(
        sorted({(key[0], key[1]) for key in grouped})[
            -normalized_period_limit:
        ]
    )
    grouped_semantics = sorted(
        (
            (semantic_key, candidates)
            for semantic_key, candidates in grouped.items()
            if (semantic_key[0], semantic_key[1]) in selected_periods
        ),
        key=lambda item: item[0],
    )
    for semantic_key, candidates in grouped_semantics:
        best_priority = min(candidate[3] for candidate in candidates)
        preferred = [
            candidate
            for candidate in candidates
            if candidate[3] == best_priority
        ]
        values = {
            candidate[0].normalized_value
            for candidate in preferred
            if candidate[0].normalization_status in {"normalized", "unchanged"}
        }
        preferred.sort(
            key=lambda candidate: (
                candidate[2].known_at
                or candidate[2].fetched_at,
                candidate[0].derived_at,
                candidate[0].id,
            ),
            reverse=True,
        )
        selected.append(preferred[0])
        if len(values) > 1:
            conflicts.append(
                "normalized_source_conflict_"
                f"{semantic_key[0]}Q{semantic_key[1]}_{semantic_key[2]}"
            )

    normalized_facts = []
    for (
        normalized,
        fact,
        filing,
        _priority,
        _reliability,
        _source_name,
    ) in selected:
        conflict_code = (
            "normalized_source_conflict_"
            f"{fact.fiscal_year}Q{fact.fiscal_quarter}_"
            f"{fact.period_scope or 'unknown'}"
        )
        has_conflict = conflict_code in conflicts
        decimal_places = source_decimal_places(fact.source_value_text)
        normalized_facts.append(
            NormalizedPeriodFact(
            source_fact_id=str(fact.id),
            stock_id=fact.stock_id,
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fact.fiscal_quarter or 0,
            metric_code=fact.metric_code,
            period_scope=fact.period_scope,
            period_end=fact.period_end,
            normalized_value=normalized.normalized_value,
            normalized_unit=normalized.normalized_unit or fact.source_unit,
            adjustment_factor=normalized.adjustment_factor,
            comparison_basis_id=normalized.comparison_basis_id,
            normalization_status=(
                "disputed" if has_conflict else normalized.normalization_status
            ),
            normalization_version=normalized.normalization_version,
            normalization_mode=normalized.normalization_mode,
            decision_usable=normalized.decision_usable and not has_conflict,
            action_ids=_lineage_action_ids(normalized.lineage_json),
            issue_codes=(
                ("normalized_source_conflict",)
                if has_conflict
                else _json_string_list(normalized.issue_codes_json or "[]")
            ),
            known_at=filing.known_at,
            rounding_tolerance=source_rounding_tolerance(
                decimal_places=decimal_places,
                adjustment_factor=normalized.adjustment_factor,
            ),
        )
        )
    daily_close_resolution: DailyCloseValuationInput | None = None
    if price is None and price_as_of is None:
        daily_close_resolution = resolve_latest_completed_daily_close(
            db,
            stock_id=stock_id,
            as_of=as_of,
        )
        price = daily_close_resolution.price
        price_as_of = daily_close_resolution.price_as_of
        price_basis = daily_close_resolution.price_basis

    contract = build_normalized_financial_contract(
        baseline=baseline,
        normalized_facts=normalized_facts,
        revenue_continuity=continuity,
        price=price,
        price_as_of=price_as_of,
        price_basis=price_basis,
        extra_issues=conflicts,
    )
    if daily_close_resolution is not None:
        contract["valuation"].update(
            daily_close_resolution.valuation_context()
        )
        if daily_close_resolution.issue_codes:
            contract["valuation"]["issue_codes"] = list(
                daily_close_resolution.issue_codes
            )
        source_ref = daily_close_resolution.source_ref()
        if source_ref is not None:
            contract["source_refs"].append(source_ref)
    contract["source_refs"].extend(
        [
            {
                "type": "table",
                "name": "tw_financial_normalized_fact",
                "row_id": normalized.id,
                "source_fact_id": fact.id,
                "parse_run_id": fact.parse_run_id,
                "filing_id": filing.id,
                "source_id": filing.source_id,
                "source_name": source_name,
                "source_reliability": reliability,
                "normalization_version": normalized.normalization_version,
            }
            for (
                normalized,
                fact,
                filing,
                _priority,
                reliability,
                source_name,
            ) in selected
        ]
    )
    return contract
