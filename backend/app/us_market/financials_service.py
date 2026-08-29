from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from app.db.models import USSecCompanyFact
from app.config import settings
from app.us_market import catalog_store, fundamentals_store
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.sec_fundamentals import (
    CANONICAL_METRICS,
    CanonicalFact,
    DerivedValue,
    SecFact,
    derive_discrete_quarters,
    derive_growth,
    derive_pair_metric,
    derive_ttm,
    evaluate_sec_filing_freshness,
    reconcile_annual,
    select_canonical_history,
)
from app.us_market.sec_fundamentals.submissions import (
    SEC_SUBMISSIONS_CACHE,
    submissions_cache_path_for_session,
)
from app.us_market.symbols import normalize_us_symbol


US_FINANCIAL_CONTRACT_VERSION = "omi.financial.v1"
SUPPORTED_MODES = frozenset({"current_comparable", "as_reported_as_of"})
SUPPORTED_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")
MAX_RAW_FACT_ROWS = 20_000


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _canonical_payload(fact: CanonicalFact) -> dict[str, Any]:
    source = fact.source_fact
    return {
        "metric_code": fact.metric_code,
        "value": str(fact.value),
        "unit": fact.unit.normalized_unit or source.unit,
        "currency": fact.unit.currency,
        "fiscal_year": fact.period.fiscal_year,
        "fiscal_quarter": fact.period.fiscal_quarter,
        "period_scope": fact.period.scope,
        "period_start": (
            fact.period.period_start.isoformat() if fact.period.period_start else None
        ),
        "period_end": fact.period.period_end.isoformat() if fact.period.period_end else None,
        "duration_days": fact.period.duration_days,
        "status": fact.period.status,
        "revision_kind": fact.revision_kind,
        "source_fact_id": source.fact_id,
        "taxonomy": source.taxonomy,
        "tag": source.tag,
        "raw_unit": source.unit,
        "reported_fiscal_year": source.fiscal_year,
        "reported_fiscal_period": source.fiscal_period,
        "form": source.form,
        "filed_date": source.filed_date.isoformat() if source.filed_date else None,
        "accession_number": source.accession_number,
        "frame": source.frame,
        "source_url": source.source_url,
        "issue_codes": list(fact.period.issue_codes),
    }


def _derived_payload(value: DerivedValue) -> dict[str, Any]:
    return {
        "metric_code": value.metric_code,
        "fiscal_year": value.fiscal_year,
        "fiscal_quarter": value.fiscal_quarter,
        "period": (
            f"{value.fiscal_year}Q{value.fiscal_quarter}"
            if value.fiscal_year is not None and value.fiscal_quarter is not None
            else None
        ),
        "period_end": value.period_end.isoformat() if value.period_end else None,
        "value": str(value.value) if value.value is not None else None,
        "unit": value.unit,
        "status": value.status,
        "derivation": value.derivation,
        "formula": value.formula,
        "input_fact_ids": list(value.input_fact_ids),
        "issue_codes": list(value.issue_codes),
    }


def _empty_contract(
    *,
    symbol: str,
    cik: str | None,
    entity_name: str | None,
    as_of: datetime,
    mode: str,
    status: str,
    issue_code: str,
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": US_FINANCIAL_CONTRACT_VERSION,
        "target": {
            "market": "US",
            "symbol": symbol,
            "cik": cik,
            "entity_name": entity_name,
        },
        "as_of": as_of.isoformat(),
        "mode": mode,
        "as_reported": {"status": status, "facts": []},
        "normalized": {"status": status, "facts": [], "metrics": {}},
        "derived": {
            "status": status,
            "quarterly": {},
            "ttm": {},
            "ratios": [],
            "growth": [],
            "annual_reconciliations": [],
        },
        "valuation": {
            "status": "unavailable",
            "pe_ttm": None,
            "price": None,
            "price_as_of": None,
            "financial_basis": "ttm_diluted_eps",
            "input_fact_ids": [],
            "issue_codes": ["valuation_inputs_missing"],
        },
        "quality": {
            "freshness": (freshness or {}).get("status", "missing"),
            "filing_freshness": freshness or {},
            "continuity": "missing",
            "semantic_validity": status,
            "supplemental_semantic_validity": status,
            "completeness": "missing",
            "decision_usable": False,
            "issues": [issue_code],
            "decision_blocking_issues": [issue_code],
            "non_blocking_issues": [],
            "revenue_continuity": {
                "status": "missing",
                "decision_usable": False,
                "issues": [issue_code],
            },
        },
        "source_refs": [],
    }


@dataclass(frozen=True, slots=True)
class ResolvedValuationPrice:
    close_price: Decimal
    trade_date: date
    provider: str | None
    source: str | None
    event_at: str | None
    price_basis: str | None


def _latest_price(db: Session, *, symbol: str) -> ResolvedValuationPrice | None:
    resolved = USDailyOhlcvPlatform(db).read(symbol=symbol, bars=1)
    if not resolved.postcondition_satisfied:
        return None
    bars = resolved.projection.get("bars") or []
    if not bars:
        return None
    bar = bars[-1]
    close = bar.get("close_price")
    end_at = bar.get("end_at")
    if close is None or end_at is None:
        return None
    return ResolvedValuationPrice(
        close_price=Decimal(str(close)),
        trade_date=datetime.fromisoformat(str(end_at)).date(),
        provider=resolved.projection.get("selected_provider"),
        source=resolved.projection.get("selected_source"),
        event_at=resolved.projection.get("selected_event_at"),
        price_basis=bar.get("price_basis"),
    )


def _period_key(value: DerivedValue) -> tuple[int, int] | None:
    if value.fiscal_year is None or value.fiscal_quarter is None:
        return None
    return value.fiscal_year, value.fiscal_quarter


def _pair_by_period(
    left: Sequence[DerivedValue],
    right: Sequence[DerivedValue],
    *,
    metric_code: str,
    operation: str,
) -> list[DerivedValue]:
    right_by_period = {
        key: item for item in right if (key := _period_key(item)) is not None
    }
    return [
        derive_pair_metric(
            metric_code=metric_code,
            left=item,
            right=right_by_period[key],
            operation=operation,
        )
        for item in left
        if (key := _period_key(item)) is not None and key in right_by_period
    ]


def _growth_series(
    values: Sequence[DerivedValue],
    *,
    metric_code: str,
    comparison: str,
) -> list[DerivedValue]:
    by_period = {
        key: item for item in values if (key := _period_key(item)) is not None
    }
    gap = 1 if comparison == "qoq" else 4
    results: list[DerivedValue] = []
    for key, current in sorted(by_period.items()):
        ordinal = key[0] * 4 + key[1] - 1 - gap
        previous_year, zero_based_quarter = divmod(ordinal, 4)
        previous = by_period.get((previous_year, zero_based_quarter + 1))
        if previous is None:
            continue
        results.append(
            derive_growth(
                metric_code=metric_code,
                current=current,
                previous=previous,
                comparison=comparison,
            )
        )
    return results


def build_us_sec_financial_contract(
    db: Session,
    *,
    symbol: str,
    mode: str = "current_comparable",
    periods: int = 8,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported US financial contract mode: {mode}")
    if periods < 4 or periods > 12:
        raise ValueError("periods must be between 4 and 12")

    stock = catalog_store.get_us_stock(db, symbol=symbol)
    normalized_symbol = normalize_us_symbol(stock.symbol)
    resolved_as_of = _utc(as_of) or datetime.now(timezone.utc)
    latest_filing = fundamentals_store.latest_us_sec_filing_fact(
        db,
        symbol=normalized_symbol,
    )
    snapshot = (
        SEC_SUBMISSIONS_CACHE.get(
            stock.cik,
            cache_path=submissions_cache_path_for_session(
                db,
                configured_path=settings.us_sec_submissions_cache_path,
            ),
        )
        if stock.cik
        else None
    )
    remote_filing = snapshot.latest_relevant_filing if snapshot else None
    freshness = evaluate_sec_filing_freshness(
        local_accession_number=latest_filing.accession_number if latest_filing else None,
        local_filing_date=latest_filing.filed_date if latest_filing else None,
        local_fetched_at=latest_filing.fetched_at if latest_filing else None,
        expected_accession_number=(
            remote_filing.accession_number if remote_filing else None
        ),
        expected_filing_date=remote_filing.filing_date if remote_filing else None,
        last_checked_at=snapshot.fetched_at if snapshot else None,
        now=resolved_as_of,
        stale_after=timedelta(hours=24),
    ).to_dict()

    if mode == "as_reported_as_of":
        return _empty_contract(
            symbol=normalized_symbol,
            cik=stock.cik,
            entity_name=stock.sec_company_name,
            as_of=resolved_as_of,
            mode=mode,
            status="blocked",
            issue_code="as_reported_history_not_available",
            freshness=freshness,
        )
    if stock.is_etf or stock.asset_type.lower() in {"etf", "index", "fund"}:
        return _empty_contract(
            symbol=normalized_symbol,
            cik=stock.cik,
            entity_name=stock.sec_company_name,
            as_of=resolved_as_of,
            mode=mode,
            status="not_applicable",
            issue_code="sec_whole_company_fundamentals_not_applicable",
            freshness=freshness,
        )

    all_tags = {
        tag.tag for spec in CANONICAL_METRICS.values() for tag in spec.tags
    }
    rows = (
        db.query(USSecCompanyFact)
        .filter(USSecCompanyFact.symbol == normalized_symbol)
        .filter(USSecCompanyFact.form.in_(SUPPORTED_FORMS))
        .filter(USSecCompanyFact.tag.in_(all_tags))
        .order_by(
            USSecCompanyFact.period_end_date.desc(),
            USSecCompanyFact.filed_date.desc(),
            USSecCompanyFact.id.desc(),
        )
        .limit(MAX_RAW_FACT_ROWS)
        .all()
    )
    taxonomies = {
        str(value[0])
        for value in (
            db.query(USSecCompanyFact.taxonomy)
            .filter(USSecCompanyFact.symbol == normalized_symbol)
            .distinct()
            .all()
        )
    }
    raw_facts = tuple(SecFact.from_raw(row) for row in rows)
    if not raw_facts:
        issue = (
            "unsupported_ifrs_taxonomy"
            if "ifrs-full" in taxonomies and "us-gaap" not in taxonomies
            else "canonical_sec_facts_missing"
        )
        return _empty_contract(
            symbol=normalized_symbol,
            cik=stock.cik,
            entity_name=stock.sec_company_name,
            as_of=resolved_as_of,
            mode=mode,
            status="partial" if taxonomies else "missing",
            issue_code=issue,
            freshness=freshness,
        )

    selections: dict[str, tuple] = {}
    canonical: dict[str, list[CanonicalFact]] = {}
    issues: list[str] = []
    selection_limit = min(max(periods * 4, 20), 80)
    for metric_code, spec in CANONICAL_METRICS.items():
        metric_selections = select_canonical_history(
            raw_facts,
            spec=spec,
            expected_currency="USD",
            period_limit=selection_limit,
        )
        selections[metric_code] = metric_selections
        canonical[metric_code] = [
            selection.selected
            for selection in metric_selections
            if selection.selected is not None
        ]
        issues.extend(
            issue
            for selection in metric_selections
            for issue in selection.issue_codes
        )

    quarters: dict[str, tuple[DerivedValue, ...]] = {}
    ttm_values: dict[str, DerivedValue] = {}
    duration_metrics = [
        metric_code
        for metric_code, spec in CANONICAL_METRICS.items()
        if spec.statement_kind == "duration"
    ]
    for metric_code in duration_metrics:
        quarter_values = derive_discrete_quarters(
            canonical[metric_code],
            metric_code=metric_code,
        )
        quarters[metric_code] = quarter_values
        if quarter_values:
            ttm_values[metric_code] = derive_ttm(
                quarter_values,
                metric_code=metric_code,
            )

    ratios: list[DerivedValue] = []
    for numerator, result_metric in (
        ("gross_profit", "gross_margin"),
        ("operating_income", "operating_margin"),
        ("net_income", "net_margin"),
    ):
        ratios.extend(
            _pair_by_period(
                quarters.get(numerator, ()),
                quarters.get("revenue", ()),
                metric_code=result_metric,
                operation="margin_percent",
            )
        )

    free_cash_flow = _pair_by_period(
        quarters.get("operating_cash_flow", ()),
        quarters.get("capex", ()),
        metric_code="free_cash_flow",
        operation="subtract",
    )
    growth: list[DerivedValue] = []
    for source_metric in ("revenue", "net_income"):
        for comparison in ("qoq", "yoy"):
            growth.extend(
                _growth_series(
                    quarters.get(source_metric, ()),
                    metric_code=f"{source_metric}_{comparison}_growth",
                    comparison=comparison,
                )
            )

    annual_reconciliations: list[DerivedValue] = []
    for metric_code in duration_metrics:
        annual_reconciliations.extend(
            reconcile_annual(
                metric_code=metric_code,
                annual=annual,
                quarters=quarters.get(metric_code, ()),
            )
            for annual in canonical[metric_code]
            if annual.period.scope == "annual_12m"
        )

    latest_instants: dict[str, DerivedValue] = {}
    for metric_code, spec in CANONICAL_METRICS.items():
        if spec.statement_kind != "instant" or not canonical[metric_code]:
            continue
        fact = max(
            canonical[metric_code],
            key=lambda item: item.period.period_end,
        )
        latest_instants[metric_code] = DerivedValue(
            metric_code=metric_code,
            fiscal_year=fact.period.fiscal_year,
            fiscal_quarter=fact.period.fiscal_quarter,
            period_end=fact.period.period_end,
            value=fact.value,
            unit=fact.unit.normalized_unit or fact.source_fact.unit,
            status="ready" if fact.period.status == "ready" else "blocked",
            derivation="direct",
            formula=None,
            input_fact_ids=(fact.source_fact.fact_id,),
            issue_codes=fact.period.issue_codes,
        )

    debt_total = latest_instants.get("debt_total")
    if debt_total is None and {
        "debt_current",
        "debt_noncurrent",
    }.issubset(latest_instants):
        debt_total = derive_pair_metric(
            metric_code="debt_total",
            left=latest_instants["debt_current"],
            right=latest_instants["debt_noncurrent"],
            operation="add",
        )
    net_debt = None
    if debt_total is not None and latest_instants.get("cash") is not None:
        net_debt = derive_pair_metric(
            metric_code="net_debt",
            left=debt_total,
            right=latest_instants["cash"],
            operation="subtract",
        )

    bounded_quarters = {
        metric_code: values[-periods:]
        for metric_code, values in quarters.items()
        if values
    }
    bounded_ratios = ratios[-(periods * 3) :]
    bounded_free_cash_flow = free_cash_flow[-periods:]
    bounded_growth = growth[-(periods * 4) :]
    bounded_annual_reconciliations = annual_reconciliations[-periods:]
    bounded_derived = [
        *(item for values in bounded_quarters.values() for item in values),
        *ttm_values.values(),
        *bounded_ratios,
        *bounded_free_cash_flow,
        *bounded_growth,
        *bounded_annual_reconciliations,
        *(value for value in (debt_total, net_debt) if value is not None),
    ]
    issues.extend(
        issue
        for item in bounded_derived
        if item.status in {"blocked", "disputed"}
        for issue in item.issue_codes
    )
    for required_metric in ("revenue", "net_income"):
        if not canonical[required_metric]:
            issues.append(f"required_metric_missing:{required_metric}")

    revenue_ttm = ttm_values.get("revenue")
    net_income_ttm = ttm_values.get("net_income")
    required_ttm_ready = all(
        value is not None and value.status == "ready"
        for value in (revenue_ttm, net_income_ttm)
    )
    critical_quarters = [
        item
        for metric_code in ("revenue", "net_income")
        for item in bounded_quarters.get(metric_code, ())[-4:]
    ]
    has_critical_dispute = any(
        item.status == "disputed" for item in critical_quarters
    )
    has_supplemental_dispute = any(
        item.status == "disputed" for item in bounded_derived
    )
    completeness = "ready" if required_ttm_ready else "partial"
    decision_usable = bool(
        freshness.get("decision_usable")
        and required_ttm_ready
        and not has_critical_dispute
    )
    decision_blocking_issues = _dedupe(
        (
            *(
                issue
                for value in (revenue_ttm, net_income_ttm)
                if value is not None and value.status != "ready"
                for issue in value.issue_codes
            ),
            *(("required_metric_ttm_missing",) if not required_ttm_ready else ()),
            *(("required_metric_disputed",) if has_critical_dispute else ()),
            *freshness.get("issue_codes", []),
        )
    )
    non_blocking_issues = _dedupe(
        issue
        for issue in issues
        if issue not in decision_blocking_issues
    )

    price_row = _latest_price(db, symbol=normalized_symbol)
    eps_ttm = ttm_values.get("eps_diluted") or ttm_values.get("eps_basic")
    valuation_issues: list[str] = []
    pe_ttm: Decimal | None = None
    price: Decimal | None = None
    if price_row is None or price_row.close_price is None:
        valuation_issues.append("valuation_price_missing")
    else:
        price = Decimal(str(price_row.close_price))
    if eps_ttm is None or eps_ttm.status != "ready" or eps_ttm.value is None:
        valuation_issues.append("valuation_ttm_eps_missing")
    elif eps_ttm.value <= 0:
        valuation_issues.append("valuation_ttm_eps_non_positive")
    if not valuation_issues and price is not None and eps_ttm is not None and eps_ttm.value:
        pe_ttm = price / eps_ttm.value

    normalized_facts = [
        fact
        for values in canonical.values()
        for fact in values
    ]
    normalized_facts.sort(
        key=lambda fact: (
            fact.period.period_end,
            fact.metric_code,
            fact.period.scope,
        )
    )
    bounded_normalized = normalized_facts[-(periods * len(CANONICAL_METRICS)) :]
    source_refs = [
        {
            "type": "sec_filing_fact",
            "provider": "sec_edgar",
            "fact_id": fact.source_fact.fact_id,
            "accession_number": fact.source_fact.accession_number,
            "taxonomy": fact.source_fact.taxonomy,
            "tag": fact.source_fact.tag,
            "source_url": fact.source_fact.source_url,
        }
        for fact in bounded_normalized
    ]
    if price_row is not None:
        source_refs.append(
            {
                "type": "daily_price",
                "provider": price_row.provider,
                "trade_date": price_row.trade_date.isoformat(),
                "source": price_row.source,
                "event_at": price_row.event_at,
            }
        )

    return {
        "contract_version": US_FINANCIAL_CONTRACT_VERSION,
        "target": {
            "market": "US",
            "symbol": normalized_symbol,
            "cik": stock.cik,
            "entity_name": stock.sec_company_name,
            "currency": "USD",
        },
        "as_of": resolved_as_of.isoformat(),
        "mode": mode,
        "as_reported": {
            "status": "available",
            "latest_filing": {
                "accession_number": latest_filing.accession_number if latest_filing else None,
                "filed_date": (
                    latest_filing.filed_date.isoformat()
                    if latest_filing and latest_filing.filed_date
                    else None
                ),
            },
            "facts": [_canonical_payload(fact) for fact in bounded_normalized],
        },
        "normalized": {
            "status": completeness,
            "facts": [_canonical_payload(fact) for fact in bounded_normalized],
            "metrics": {
                metric_code: [
                    _canonical_payload(fact) for fact in values[-periods:]
                ]
                for metric_code, values in canonical.items()
                if values
            },
        },
        "derived": {
            "status": completeness,
            "quarterly": {
                metric_code: [_derived_payload(item) for item in values]
                for metric_code, values in bounded_quarters.items()
            },
            "ttm": {
                metric_code: _derived_payload(value)
                for metric_code, value in ttm_values.items()
            },
            "free_cash_flow": [_derived_payload(item) for item in bounded_free_cash_flow],
            "ratios": [_derived_payload(item) for item in bounded_ratios],
            "growth": [_derived_payload(item) for item in bounded_growth],
            "annual_reconciliations": [
                _derived_payload(item) for item in bounded_annual_reconciliations
            ],
            "latest_balance": {
                metric_code: _derived_payload(value)
                for metric_code, value in latest_instants.items()
            },
            "debt_total": _derived_payload(debt_total) if debt_total else None,
            "net_debt": _derived_payload(net_debt) if net_debt else None,
        },
        "valuation": {
            "status": "ready" if pe_ttm is not None else "unavailable",
            "pe_ttm": str(pe_ttm) if pe_ttm is not None else None,
            "price": str(price) if price is not None else None,
            "price_as_of": price_row.trade_date.isoformat() if price_row else None,
            "price_basis": price_row.price_basis if price_row else None,
            "price_provider": price_row.provider if price_row else None,
            "financial_basis": (
                eps_ttm.metric_code if eps_ttm is not None else "ttm_diluted_eps"
            ),
            "input_fact_ids": list(eps_ttm.input_fact_ids) if eps_ttm else [],
            "issue_codes": valuation_issues,
        },
        "quality": {
            "freshness": freshness.get("status", "unknown"),
            "filing_freshness": freshness,
            "continuity": "ready" if required_ttm_ready else "partial",
            "semantic_validity": (
                "disputed"
                if has_critical_dispute
                else "valid"
                if required_ttm_ready
                else "partial"
            ),
            "supplemental_semantic_validity": (
                "disputed" if has_supplemental_dispute else "valid"
            ),
            "completeness": completeness,
            "decision_usable": decision_usable,
            "issues": _dedupe((*decision_blocking_issues, *non_blocking_issues)),
            "decision_blocking_issues": decision_blocking_issues,
            "non_blocking_issues": non_blocking_issues,
            "revenue_continuity": {
                "status": revenue_ttm.status if revenue_ttm else "missing",
                "decision_usable": bool(revenue_ttm and revenue_ttm.status == "ready"),
                "issues": list(revenue_ttm.issue_codes) if revenue_ttm else ["revenue_ttm_missing"],
            },
        },
        "source_refs": source_refs,
    }


__all__ = [
    "MAX_RAW_FACT_ROWS",
    "SUPPORTED_MODES",
    "US_FINANCIAL_CONTRACT_VERSION",
    "build_us_sec_financial_contract",
]
