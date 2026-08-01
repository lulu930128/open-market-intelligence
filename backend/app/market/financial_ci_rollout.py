from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialBasisAssessment,
    TaiwanFinancialCorporateAction,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)


CI_ROLLOUT_CONTRACT_VERSION = "omi.tw-financial-ci-rollout.v1"
CI_ACCEPTANCE_SAMPLE_CONTRACT_VERSION = (
    "omi.tw-financial-ci-acceptance-sample.v1"
)
OFFICIAL_FILING_KIND = "mops_ixbrl_financial_report"
MAX_CI_PLAN_PERIODS = 8
MAX_CI_PLAN_PAGE_SIZE = 500
MAX_CI_INGESTION_BATCH_SYMBOLS = 20
_QUERY_CHUNK_SIZE = 400
_STOCK_ID_RE = re.compile(r"^[0-9A-Z]{2,20}$")

_REQUIRED_CURRENT_EPS_SCOPE = {
    1: "ytd_3m",
    2: "ytd_6m",
    3: "ytd_9m",
    4: "annual_12m",
}
_STAGE_PRIORITY = {
    "pending_parse_review": 0,
    "parser_contract_gap": 1,
    "needs_share_basis_review": 2,
    "needs_action_reconciliation": 3,
    "missing_official_filings": 4,
    "filing_version_conflict": 5,
    "basis_blocked": 6,
    "normalized_ready": 7,
}


@dataclass(frozen=True)
class _VariantBundle:
    symbols: tuple[str, ...]
    stock_names: dict[str, str]
    income_symbols: tuple[str, ...]
    balance_symbols: tuple[str, ...]
    issues: tuple[dict[str, Any], ...]


def _chunks(values: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for offset in range(0, len(values), _QUERY_CHUNK_SIZE):
        yield values[offset : offset + _QUERY_CHUNK_SIZE]


def _decode_resource_rows(
    payload: dict[str, Any],
    *,
    resource: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    entry = payload.get(resource)
    if entry is None:
        return [], {"code": "bundle_resource_missing", "resource": resource}
    raw_rows = entry.get("raw_text") if isinstance(entry, dict) else entry
    try:
        rows = json.loads(raw_rows) if isinstance(raw_rows, str) else raw_rows
    except (TypeError, json.JSONDecodeError) as exc:
        return [], {
            "code": "bundle_resource_malformed",
            "resource": resource,
            "detail": str(exc),
        }
    if not isinstance(rows, list):
        return [], {
            "code": "bundle_resource_not_a_list",
            "resource": resource,
        }
    mapping_rows = [row for row in rows if isinstance(row, dict)]
    if len(mapping_rows) != len(rows):
        return mapping_rows, {
            "code": "bundle_resource_non_object_rows",
            "resource": resource,
            "count": len(rows) - len(mapping_rows),
        }
    return mapping_rows, None


def parse_financial_bundle_variant(
    raw_text: str,
    *,
    variant: str = "ci",
) -> dict[str, Any]:
    """Extract a report-variant universe from a stored official bundle.

    The function is pure and never infers a variant from company names or legacy
    financial fields. Invalid/blank provider rows remain visible as issues.
    """

    normalized_variant = variant.strip().lower()
    if not re.fullmatch(r"[a-z]{2,8}", normalized_variant):
        raise ValueError(f"invalid financial variant: {variant!r}")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("stored financial bundle is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("stored financial bundle must be a JSON object")

    issues: list[dict[str, Any]] = []
    resource_symbols: dict[str, set[str]] = {}
    stock_names: dict[str, str] = {}
    for statement in ("income", "balance"):
        resource = f"{statement}_{normalized_variant}"
        rows, issue = _decode_resource_rows(payload, resource=resource)
        if issue is not None:
            issues.append(issue)
        symbols: set[str] = set()
        invalid_count = 0
        for row in rows:
            stock_id = str(
                row.get("公司代號")
                or row.get("公司代碼")
                or row.get("股票代號")
                or row.get("SecuritiesCompanyCode")
                or ""
            ).strip().upper()
            if not _STOCK_ID_RE.fullmatch(stock_id):
                invalid_count += 1
                continue
            symbols.add(stock_id)
            stock_name = str(
                row.get("公司名稱") or row.get("CompanyName") or ""
            ).strip()
            if stock_name:
                stock_names.setdefault(stock_id, stock_name)
        if invalid_count:
            issues.append(
                {
                    "code": "bundle_rows_without_valid_stock_id",
                    "resource": resource,
                    "count": invalid_count,
                }
            )
        resource_symbols[statement] = symbols

    income_symbols = resource_symbols.get("income", set())
    balance_symbols = resource_symbols.get("balance", set())
    income_only = sorted(income_symbols - balance_symbols)
    balance_only = sorted(balance_symbols - income_symbols)
    if income_only or balance_only:
        issues.append(
            {
                "code": "bundle_statement_coverage_mismatch",
                "income_only": income_only,
                "balance_only": balance_only,
            }
        )
    symbols = sorted(income_symbols | balance_symbols)
    result = _VariantBundle(
        symbols=tuple(symbols),
        stock_names={key: stock_names[key] for key in symbols if key in stock_names},
        income_symbols=tuple(sorted(income_symbols)),
        balance_symbols=tuple(sorted(balance_symbols)),
        issues=tuple(issues),
    )
    return {
        "variant": normalized_variant,
        "symbols": list(result.symbols),
        "stock_names": result.stock_names,
        "income_symbol_count": len(result.income_symbols),
        "balance_symbol_count": len(result.balance_symbols),
        "income_only": income_only,
        "balance_only": balance_only,
        "issues": list(result.issues),
    }


def _validate_plan_request(
    *,
    periods: Sequence[tuple[int, int]],
    offset: int,
    limit: int,
) -> tuple[tuple[int, int], ...]:
    normalized_periods = tuple(sorted(set(periods)))
    if not normalized_periods:
        raise ValueError("at least one target filing period is required")
    if len(normalized_periods) > MAX_CI_PLAN_PERIODS:
        raise ValueError(
            f"at most {MAX_CI_PLAN_PERIODS} filing periods may be planned"
        )
    if any(year < 1990 or quarter not in {1, 2, 3, 4} for year, quarter in normalized_periods):
        raise ValueError("target periods must use year >= 1990 and quarter 1 through 4")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit < 1 or limit > MAX_CI_PLAN_PAGE_SIZE:
        raise ValueError(
            f"limit must be between 1 and {MAX_CI_PLAN_PAGE_SIZE}"
        )
    return normalized_periods


def _current_variant_universe(
    db: Session,
    *,
    variant: str,
) -> dict[str, Any]:
    latest = (
        db.query(
            FinancialMetricQuarterly.fiscal_year,
            FinancialMetricQuarterly.quarter,
        )
        .filter(
            FinancialMetricQuarterly.fiscal_year.isnot(None),
            FinancialMetricQuarterly.quarter.isnot(None),
        )
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )
    if latest is None:
        raise ValueError("legacy financial coverage has no fiscal period")
    latest_year, latest_quarter = int(latest[0]), int(latest[1])
    raw_links = (
        db.query(
            FinancialMetricQuarterly.source_id,
            FinancialMetricQuarterly.raw_result_id,
        )
        .filter(
            FinancialMetricQuarterly.fiscal_year == latest_year,
            FinancialMetricQuarterly.quarter == latest_quarter,
        )
        .distinct()
        .all()
    )
    latest_raw_by_source: dict[int, int] = {}
    for source_id, raw_result_id in raw_links:
        latest_raw_by_source[int(source_id)] = max(
            int(raw_result_id),
            latest_raw_by_source.get(int(source_id), 0),
        )
    raw_ids = sorted(latest_raw_by_source.values())
    rows = (
        db.query(RawFetchResult, SourceRegistry)
        .join(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id)
        .filter(RawFetchResult.id.in_(raw_ids))
        .order_by(RawFetchResult.id)
        .all()
        if raw_ids
        else []
    )
    universe: set[str] = set()
    stock_names: dict[str, str] = {}
    symbol_strata: dict[str, set[str]] = defaultdict(set)
    snapshots: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    for raw, source in rows:
        try:
            parsed = parse_financial_bundle_variant(
                raw.raw_text or "",
                variant=variant,
            )
        except ValueError as exc:
            skipped_sources.append(
                {
                    "source_id": source.id,
                    "source_name": source.source_name,
                    "raw_result_id": raw.id,
                    "reason": str(exc),
                }
            )
            continue
        if not parsed["symbols"]:
            skipped_sources.append(
                {
                    "source_id": source.id,
                    "source_name": source.source_name,
                    "raw_result_id": raw.id,
                    "reason": f"no {variant} symbols in stored bundle",
                }
            )
            continue
        universe.update(parsed["symbols"])
        stock_names.update(parsed["stock_names"])
        source_name_lower = source.source_name.lower()
        if "tpex" in source_name_lower:
            stratum = "TPEX"
        elif "twse" in source_name_lower:
            stratum = "TWSE"
        else:
            stratum = f"SOURCE_{source.id}"
        for stock_id in parsed["symbols"]:
            symbol_strata[stock_id].add(stratum)
        snapshots.append(
            {
                "source_id": source.id,
                "source_name": source.source_name,
                "raw_result_id": raw.id,
                "income_symbol_count": parsed["income_symbol_count"],
                "balance_symbol_count": parsed["balance_symbol_count"],
                "union_symbol_count": len(parsed["symbols"]),
                "income_only": parsed["income_only"],
                "balance_only": parsed["balance_only"],
                "issues": parsed["issues"],
            }
        )
    if not universe:
        raise ValueError(
            f"no {variant} universe could be reconstructed from latest stored bundles"
        )
    return {
        "period": f"{latest_year}Q{latest_quarter}",
        "symbols": tuple(sorted(universe)),
        "stock_names": stock_names,
        "symbol_strata": {
            stock_id: tuple(sorted(strata))
            for stock_id, strata in symbol_strata.items()
        },
        "source_snapshots": snapshots,
        "skipped_sources": skipped_sources,
    }


def select_ci_acceptance_sample(
    db: Session,
    *,
    sample_size: int = 20,
    seed: str = "omi-ci-acceptance-v1",
    exclude_stock_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Select a deterministic, source-stratified CI acceptance sample.

    Ranking uses SHA-256 rather than runtime PRNG state, so the same database,
    seed, exclusions, and contract version always reproduce the same sample.
    """

    if sample_size < 1 or sample_size > 100:
        raise ValueError("sample_size must be between 1 and 100")
    normalized_seed = seed.strip()
    if not normalized_seed or len(normalized_seed) > 160:
        raise ValueError("seed must contain between 1 and 160 characters")
    normalized_exclusions = {
        str(stock_id).strip().upper() for stock_id in exclude_stock_ids
    }
    invalid_exclusions = sorted(
        stock_id
        for stock_id in normalized_exclusions
        if not _STOCK_ID_RE.fullmatch(stock_id)
    )
    if invalid_exclusions:
        raise ValueError(f"invalid excluded stock_ids: {invalid_exclusions}")

    snapshot = _current_variant_universe(db, variant="ci")
    available_symbols = [
        stock_id
        for stock_id in snapshot["symbols"]
        if stock_id not in normalized_exclusions
    ]
    if sample_size > len(available_symbols):
        raise ValueError(
            "sample_size exceeds the available ci universe after exclusions"
        )

    symbols_by_stratum: dict[str, list[str]] = defaultdict(list)
    multi_stratum_symbols: list[str] = []
    for stock_id in available_symbols:
        strata = snapshot["symbol_strata"].get(stock_id, ())
        if len(strata) != 1:
            multi_stratum_symbols.append(stock_id)
            stratum = "AMBIGUOUS" if strata else "UNMAPPED"
        else:
            stratum = strata[0]
        symbols_by_stratum[stratum].append(stock_id)

    total = len(available_symbols)
    exact_quotas = {
        stratum: sample_size * len(symbols) / total
        for stratum, symbols in symbols_by_stratum.items()
    }
    quotas = {
        stratum: min(len(symbols), int(exact_quotas[stratum]))
        for stratum, symbols in symbols_by_stratum.items()
    }
    remaining = sample_size - sum(quotas.values())
    remainder_order = sorted(
        symbols_by_stratum,
        key=lambda stratum: (
            -(exact_quotas[stratum] - int(exact_quotas[stratum])),
            stratum,
        ),
    )
    while remaining:
        allocated = False
        for stratum in remainder_order:
            if quotas[stratum] >= len(symbols_by_stratum[stratum]):
                continue
            quotas[stratum] += 1
            remaining -= 1
            allocated = True
            if remaining == 0:
                break
        if not allocated:
            raise RuntimeError("could not allocate the complete acceptance sample")

    selected: list[dict[str, Any]] = []
    for stratum in sorted(symbols_by_stratum):
        ranked = sorted(
            symbols_by_stratum[stratum],
            key=lambda stock_id: (
                hashlib.sha256(
                    (
                        f"{CI_ACCEPTANCE_SAMPLE_CONTRACT_VERSION}|"
                        f"{normalized_seed}|{stratum}|{stock_id}"
                    ).encode("utf-8")
                ).hexdigest(),
                stock_id,
            ),
        )
        for stock_id in ranked[: quotas[stratum]]:
            rank_hash = hashlib.sha256(
                (
                    f"{CI_ACCEPTANCE_SAMPLE_CONTRACT_VERSION}|"
                    f"{normalized_seed}|{stratum}|{stock_id}"
                ).encode("utf-8")
            ).hexdigest()
            selected.append(
                {
                    "stock_id": stock_id,
                    "stock_name": snapshot["stock_names"].get(stock_id),
                    "stratum": stratum,
                    "rank_hash": rank_hash,
                }
            )

    selected.sort(key=lambda item: (item["stratum"], item["rank_hash"]))
    return {
        "contract_version": CI_ACCEPTANCE_SAMPLE_CONTRACT_VERSION,
        "variant": "ci",
        "mode": "read_only_deterministic_sample",
        "seed": normalized_seed,
        "sample_size": sample_size,
        "universe_period": snapshot["period"],
        "universe_symbol_count": len(snapshot["symbols"]),
        "available_symbol_count": len(available_symbols),
        "excluded_stock_ids": sorted(normalized_exclusions),
        "stratum_population": {
            stratum: len(symbols)
            for stratum, symbols in sorted(symbols_by_stratum.items())
        },
        "stratum_sample_size": dict(sorted(quotas.items())),
        "multi_stratum_symbols": sorted(multi_stratum_symbols),
        "selected": selected,
        "boundaries": [
            "sample_selection_performs_no_network_or_database_write",
            "sample_validates_pipeline_behavior_not_every_symbol_value",
            "known_edge_sentinels_are_validated_separately",
            "any_semantic_mismatch_stops_production_promotion",
        ],
    }


def _all_for_symbols(
    db: Session,
    model: Any,
    stock_column: Any,
    symbols: Sequence[str],
) -> list[Any]:
    rows: list[Any] = []
    for chunk in _chunks(symbols):
        rows.extend(db.query(model).filter(stock_column.in_(chunk)).all())
    return rows


def build_ci_rollout_plan(
    db: Session,
    *,
    periods: Sequence[tuple[int, int]],
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Build a read-only, full-universe CI coverage and next-action plan."""

    target_periods = _validate_plan_request(
        periods=periods,
        offset=offset,
        limit=limit,
    )
    universe_snapshot = _current_variant_universe(db, variant="ci")
    symbols = tuple(universe_snapshot["symbols"])
    symbol_set = set(symbols)
    target_set = set(target_periods)

    legacy_rows = _all_for_symbols(
        db,
        FinancialMetricQuarterly,
        FinancialMetricQuarterly.stock_id,
        symbols,
    )
    legacy_periods: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in legacy_rows:
        if row.stock_id in symbol_set and row.fiscal_year and row.quarter:
            legacy_periods[row.stock_id].add((int(row.fiscal_year), int(row.quarter)))

    filings = _all_for_symbols(
        db,
        TaiwanFinancialFiling,
        TaiwanFinancialFiling.stock_id,
        symbols,
    )
    filings = [
        filing
        for filing in filings
        if filing.filing_kind == OFFICIAL_FILING_KIND
        and filing.fiscal_quarter is not None
        and (filing.fiscal_year, filing.fiscal_quarter) in target_set
    ]
    filings_by_symbol_period: dict[
        tuple[str, tuple[int, int]], list[TaiwanFinancialFiling]
    ] = defaultdict(list)
    for filing in filings:
        filings_by_symbol_period[
            (filing.stock_id, (filing.fiscal_year, int(filing.fiscal_quarter)))
        ].append(filing)

    filing_ids = sorted(filing.id for filing in filings)
    parse_runs: list[TaiwanFinancialParseRun] = []
    for chunk in _chunks(filing_ids):
        parse_runs.extend(
            db.query(TaiwanFinancialParseRun)
            .filter(TaiwanFinancialParseRun.filing_id.in_(chunk))
            .all()
        )
    approved_run_by_filing: dict[int, TaiwanFinancialParseRun] = {}
    for run in parse_runs:
        if run.parse_status != "succeeded" or run.review_status != "approved":
            continue
        previous = approved_run_by_filing.get(run.filing_id)
        if previous is None or run.id > previous.id:
            approved_run_by_filing[run.filing_id] = run

    approved_run_ids = sorted(run.id for run in approved_run_by_filing.values())
    facts: list[TaiwanFinancialStatementFact] = []
    for chunk in _chunks(approved_run_ids):
        facts.extend(
            db.query(TaiwanFinancialStatementFact)
            .filter(
                TaiwanFinancialStatementFact.parse_run_id.in_(chunk),
                TaiwanFinancialStatementFact.metric_code.in_(
                    ("basic_eps", "issued_capital")
                ),
                TaiwanFinancialStatementFact.presentation_role == "current_period",
            )
            .all()
        )
    scopes_by_run: dict[int, set[str]] = defaultdict(set)
    issued_capital_by_run: dict[int, set[str]] = defaultdict(set)
    for fact in facts:
        if fact.metric_code == "basic_eps":
            scopes_by_run[fact.parse_run_id].add(fact.period_scope)
        elif fact.metric_code == "issued_capital":
            issued_capital_by_run[fact.parse_run_id].add(str(fact.source_value))

    normalized_rows: list[
        tuple[TaiwanFinancialNormalizedFact, TaiwanFinancialStatementFact]
    ] = []
    for chunk in _chunks(symbols):
        normalized_rows.extend(
            db.query(TaiwanFinancialNormalizedFact, TaiwanFinancialStatementFact)
            .join(
                TaiwanFinancialStatementFact,
                TaiwanFinancialStatementFact.id
                == TaiwanFinancialNormalizedFact.source_fact_id,
            )
            .filter(
                TaiwanFinancialStatementFact.stock_id.in_(chunk),
                TaiwanFinancialStatementFact.metric_code == "basic_eps",
                TaiwanFinancialNormalizedFact.normalization_mode
                == "current_comparable",
                TaiwanFinancialNormalizedFact.decision_usable.is_(True),
                TaiwanFinancialNormalizedFact.normalization_status.in_(
                    ("normalized", "unchanged")
                ),
            )
            .all()
        )
    normalized_periods: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for _, fact in normalized_rows:
        if fact.fiscal_quarter is not None:
            normalized_periods[fact.stock_id].add(
                (fact.fiscal_year, int(fact.fiscal_quarter))
            )

    actions = _all_for_symbols(
        db,
        TaiwanFinancialCorporateAction,
        TaiwanFinancialCorporateAction.stock_id,
        symbols,
    )
    actions_by_symbol: dict[str, list[TaiwanFinancialCorporateAction]] = defaultdict(list)
    for action in actions:
        if action.adjustment_purpose == "per_share_financials":
            actions_by_symbol[action.stock_id].append(action)

    assessments = _all_for_symbols(
        db,
        TaiwanFinancialBasisAssessment,
        TaiwanFinancialBasisAssessment.stock_id,
        symbols,
    )
    latest_assessment: dict[str, TaiwanFinancialBasisAssessment] = {}
    for assessment in assessments:
        previous = latest_assessment.get(assessment.stock_id)
        if previous is None or (assessment.reviewed_at, assessment.id) > (
            previous.reviewed_at,
            previous.id,
        ):
            latest_assessment[assessment.stock_id] = assessment

    candidates: list[dict[str, Any]] = []
    request_limit = len(target_periods) + len({year for year, _ in target_periods})
    for stock_id in symbols:
        missing_periods: list[str] = []
        pending_periods: list[str] = []
        conflict_periods: list[str] = []
        scope_gap_periods: list[str] = []
        issued_capital_values: dict[str, list[str]] = {}
        period_states: list[dict[str, Any]] = []
        for year, quarter in target_periods:
            period_label = f"{year}Q{quarter}"
            period_filings = filings_by_symbol_period.get(
                (stock_id, (year, quarter)),
                [],
            )
            approved = [
                (filing, approved_run_by_filing[filing.id])
                for filing in period_filings
                if filing.id in approved_run_by_filing
            ]
            content_hashes = {filing.content_hash for filing, _ in approved}
            required_scope = _REQUIRED_CURRENT_EPS_SCOPE[quarter]
            approved_scopes = sorted(
                {
                    scope
                    for _, run in approved
                    for scope in scopes_by_run.get(run.id, set())
                }
            )
            period_capital_values = sorted(
                {
                    value
                    for _, run in approved
                    for value in issued_capital_by_run.get(run.id, set())
                }
            )
            if period_capital_values:
                issued_capital_values[period_label] = period_capital_values
            if not period_filings:
                missing_periods.append(period_label)
            elif not approved:
                pending_periods.append(period_label)
            elif len(content_hashes) > 1:
                conflict_periods.append(period_label)
            elif required_scope not in approved_scopes:
                scope_gap_periods.append(period_label)
            period_states.append(
                {
                    "period": period_label,
                    "filing_ids": sorted(filing.id for filing in period_filings),
                    "approved_parse_run_ids": sorted(run.id for _, run in approved),
                    "required_current_eps_scope": required_scope,
                    "current_basic_eps_scopes": approved_scopes,
                    "official_discrete_eps_present": "discrete_3m" in approved_scopes,
                    "issued_capital_values": period_capital_values,
                }
            )

        normalized_target = normalized_periods.get(stock_id, set()) & target_set
        assessment = latest_assessment.get(stock_id)
        per_share_actions = actions_by_symbol.get(stock_id, [])
        comparable_capital_values = {
            value
            for values in issued_capital_values.values()
            for value in values
        }
        capital_change_detected = len(comparable_capital_values) > 1
        if assessment is not None and assessment.outcome == "blocked":
            stage = "basis_blocked"
            next_action = "wait_for_same_basis_comparatives_or_review_new_evidence"
        elif conflict_periods:
            stage = "filing_version_conflict"
            next_action = "reconcile_filing_versions_before_canonical_selection"
        elif normalized_target == target_set:
            stage = "normalized_ready"
            next_action = "validate_ttm_price_and_public_runtime"
        elif missing_periods:
            stage = "missing_official_filings"
            next_action = "run_bounded_mops_filing_ingestion"
        elif pending_periods:
            stage = "pending_parse_review"
            next_action = "review_immutable_parse_outputs"
        elif scope_gap_periods:
            stage = "parser_contract_gap"
            next_action = "resolve_eps_scope_or_parser_mapping"
        elif per_share_actions or capital_change_detected:
            stage = "needs_action_reconciliation"
            next_action = "review_capital_change_restatement_and_action_evidence"
        else:
            stage = "needs_share_basis_review"
            next_action = "verify_unchanged_share_basis_and_build_clone_package"

        legacy_target = legacy_periods.get(stock_id, set()) & target_set
        candidates.append(
            {
                "stock_id": stock_id,
                "stock_name": universe_snapshot["stock_names"].get(stock_id),
                "stage": stage,
                "next_action": next_action,
                "legacy_period_count": len(legacy_periods.get(stock_id, set())),
                "legacy_target_period_count": len(legacy_target),
                "missing_official_periods": missing_periods,
                "pending_parse_review_periods": pending_periods,
                "filing_version_conflict_periods": conflict_periods,
                "parser_scope_gap_periods": scope_gap_periods,
                "normalized_target_period_count": len(normalized_target),
                "per_share_action_count": len(per_share_actions),
                "issued_capital_period_count": len(issued_capital_values),
                "issued_capital_values": issued_capital_values,
                "capital_change_detected": capital_change_detected,
                "basis_assessment": (
                    {
                        "assessment_type": assessment.assessment_type,
                        "outcome": assessment.outcome,
                    }
                    if assessment is not None
                    else None
                ),
                "estimated_ingestion_request_limit": request_limit,
                "periods": period_states,
            }
        )

    candidates.sort(
        key=lambda item: (
            _STAGE_PRIORITY[item["stage"]],
            -int(item["legacy_target_period_count"]),
            str(item["stock_id"]),
        )
    )
    stage_counts = Counter(item["stage"] for item in candidates)
    page = candidates[offset : offset + limit]
    return {
        "contract_version": CI_ROLLOUT_CONTRACT_VERSION,
        "variant": "ci",
        "mode": "read_only_plan",
        "universe_period": universe_snapshot["period"],
        "target_periods": [f"{year}Q{quarter}" for year, quarter in target_periods],
        "universe_symbol_count": len(symbols),
        "source_snapshots": universe_snapshot["source_snapshots"],
        "skipped_sources": universe_snapshot["skipped_sources"],
        "stage_counts": dict(sorted(stage_counts.items())),
        "page": {
            "offset": offset,
            "limit": limit,
            "returned": len(page),
            "has_more": offset + len(page) < len(candidates),
        },
        "candidates": page,
        "boundaries": [
            "ingestion_success_is_not_normalization_approval",
            "absence_of_stored_action_is_not_share_basis_proof",
            "planner_performs_no_network_or_database_write",
            "special_financial_variants_are_out_of_scope",
        ],
    }


def run_ci_filing_ingestion_batch(
    db: Session,
    *,
    stock_ids: Sequence[str],
    periods: Sequence[tuple[int, int]],
    max_provider_requests: int,
    timeout_seconds: int = 30,
    inter_symbol_delay_seconds: float = 0,
    apply: bool = False,
    fail_fast: bool = False,
    ingester: Callable[..., dict[str, Any]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run an explicit, bounded CI filing batch with per-symbol transactions.

    This is an operational write owner. Successful symbols commit independently;
    a failed symbol is rolled back and reported without contaminating other work.
    No parse run is approved and no normalization package is created here.
    """

    from app.market.financial_filing_ingestion import ingest_mops_financial_filings

    normalized_stock_ids = tuple(
        dict.fromkeys(str(stock_id).strip().upper() for stock_id in stock_ids)
    )
    if not normalized_stock_ids:
        raise ValueError("at least one explicit stock_id is required")
    if len(normalized_stock_ids) > MAX_CI_INGESTION_BATCH_SYMBOLS:
        raise ValueError(
            "at most "
            f"{MAX_CI_INGESTION_BATCH_SYMBOLS} symbols may be ingested per batch"
        )
    invalid = [
        stock_id
        for stock_id in normalized_stock_ids
        if not _STOCK_ID_RE.fullmatch(stock_id)
    ]
    if invalid:
        raise ValueError(f"invalid stock_ids: {invalid}")
    normalized_periods = _validate_plan_request(
        periods=periods,
        offset=0,
        limit=1,
    )
    if timeout_seconds < 1 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be between 1 and 120")
    if inter_symbol_delay_seconds < 0 or inter_symbol_delay_seconds > 60:
        raise ValueError(
            "inter_symbol_delay_seconds must be between 0 and 60"
        )
    if max_provider_requests < 1:
        raise ValueError("max_provider_requests must be positive")
    per_symbol_request_limit = len(normalized_periods) + len(
        {year for year, _ in normalized_periods}
    )
    planned_request_limit = per_symbol_request_limit * len(normalized_stock_ids)
    if planned_request_limit > max_provider_requests:
        raise ValueError(
            "planned provider request limit exceeds explicit ceiling: "
            f"planned={planned_request_limit} ceiling={max_provider_requests}"
        )

    universe = set(_current_variant_universe(db, variant="ci")["symbols"])
    out_of_scope = sorted(set(normalized_stock_ids) - universe)
    db.rollback()
    if out_of_scope:
        raise ValueError(f"stock_ids are not in the current ci universe: {out_of_scope}")

    ingest = ingester or ingest_mops_financial_filings
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    accounted_request_count = 0
    unknown_request_count_failure_count = 0
    for symbol_index, stock_id in enumerate(normalized_stock_ids):
        symbol_request_count: int | None = None
        symbol_request_accounted = False
        try:
            summary = ingest(
                db,
                stock_id=stock_id,
                periods=normalized_periods,
                report_id="AUTO",
                apply=apply,
                timeout_seconds=timeout_seconds,
            )
            symbol_request_count = int(summary.get("request_count") or 0)
            symbol_request_limit = int(
                summary.get("request_limit") or per_symbol_request_limit
            )
            if symbol_request_count > symbol_request_limit:
                raise ValueError(
                    "provider request count exceeded symbol limit: "
                    f"stock_id={stock_id} count={symbol_request_count} "
                    f"limit={symbol_request_limit}"
                )
            if accounted_request_count + symbol_request_count > max_provider_requests:
                raise ValueError(
                    "provider request count exceeded explicit batch ceiling: "
                    f"stock_id={stock_id} used={accounted_request_count} "
                    f"next={symbol_request_count} ceiling={max_provider_requests}"
                )
            accounted_request_count += symbol_request_count
            symbol_request_accounted = True
            if apply:
                db.commit()
            else:
                db.rollback()
            results.append(
                {
                    "stock_id": stock_id,
                    "status": "succeeded",
                    "summary": summary,
                }
            )
        except Exception as exc:
            db.rollback()
            if symbol_request_count is None:
                unknown_request_count_failure_count += 1
            elif not symbol_request_accounted:
                accounted_request_count += symbol_request_count
            failure = {
                "stock_id": stock_id,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "request_count": symbol_request_count,
                "request_count_status": (
                    "unknown_after_failure"
                    if symbol_request_count is None
                    else "reported_before_failure"
                ),
            }
            failures.append(failure)
            results.append(failure)
            if fail_fast:
                raise
        if (
            inter_symbol_delay_seconds > 0
            and symbol_index + 1 < len(normalized_stock_ids)
        ):
            sleeper(inter_symbol_delay_seconds)

    status = "complete"
    if failures and len(failures) == len(normalized_stock_ids):
        status = "failed"
    elif failures:
        status = "partial"
    return {
        "contract_version": CI_ROLLOUT_CONTRACT_VERSION,
        "operation": "ci_official_filing_ingestion",
        "mode": "apply" if apply else "dry_run",
        "status": status,
        "stock_ids": list(normalized_stock_ids),
        "periods": [f"{year}Q{quarter}" for year, quarter in normalized_periods],
        "report_id": "AUTO",
        "timeout_seconds": timeout_seconds,
        "inter_symbol_delay_seconds": inter_symbol_delay_seconds,
        "planned_request_limit": planned_request_limit,
        "max_provider_requests": max_provider_requests,
        "actual_request_count": (
            accounted_request_count
            if unknown_request_count_failure_count == 0
            else None
        ),
        "accounted_request_count": accounted_request_count,
        "request_count_complete": unknown_request_count_failure_count == 0,
        "unknown_request_count_failure_count": (
            unknown_request_count_failure_count
        ),
        "succeeded_count": len(normalized_stock_ids) - len(failures),
        "failed_count": len(failures),
        "results": results,
        "boundaries": [
            "ingestion_does_not_approve_parse_runs",
            "ingestion_does_not_create_normalized_facts",
            "single_symbol_failure_is_rolled_back",
            "inter_symbol_requests_are_explicitly_throttled_when_configured",
            "special_financial_variants_are_rejected",
        ],
    }


__all__ = [
    "CI_ACCEPTANCE_SAMPLE_CONTRACT_VERSION",
    "CI_ROLLOUT_CONTRACT_VERSION",
    "MAX_CI_INGESTION_BATCH_SYMBOLS",
    "MAX_CI_PLAN_PAGE_SIZE",
    "MAX_CI_PLAN_PERIODS",
    "build_ci_rollout_plan",
    "parse_financial_bundle_variant",
    "run_ci_filing_ingestion_batch",
    "select_ci_acceptance_sample",
]
