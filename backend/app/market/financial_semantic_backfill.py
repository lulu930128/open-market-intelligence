from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
import json
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    RawFetchResult,
    TaiwanFinancialFiling,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_parse_runs import (
    PARSE_OUTPUT_HASH_VERSION,
    canonical_fact_output_hash,
)


BACKFILL_VERSION = "tw-financial-legacy-backfill-v1"
MAX_BACKFILL_ROWS = 10_000

_DURATION_METRICS = {
    "revenue": ("營業收入", "income", "company"),
    "gross_profit": ("營業毛利", "income", "company"),
    "operating_income": ("營業利益", "income", "company"),
    "net_income": ("本期淨利", "income", "company"),
    "net_income_attributable_parent": (
        "歸屬於母公司業主之淨利",
        "income",
        "parent",
    ),
    "eps": ("基本每股盈餘", "per_share", "parent"),
}
_INSTANT_METRICS = {
    "total_assets": ("資產總額", "balance", "company"),
    "total_equity": ("權益總額", "balance", "company"),
    "parent_equity": ("歸屬於母公司業主之權益", "balance", "parent"),
    "book_value_per_share": ("每股參考淨值", "per_share", "parent"),
}


def _quarter_end(fiscal_year: int, fiscal_quarter: int) -> date:
    return {
        1: date(fiscal_year, 3, 31),
        2: date(fiscal_year, 6, 30),
        3: date(fiscal_year, 9, 30),
        4: date(fiscal_year, 12, 31),
    }[fiscal_quarter]


def _duration_scope(fiscal_quarter: int) -> str:
    return {
        1: "ytd_3m",
        2: "ytd_6m",
        3: "ytd_9m",
        4: "annual_12m",
    }[fiscal_quarter]


def _decimal_value(value: Any) -> Decimal:
    return Decimal(str(value))


def _filing_identity(
    row: FinancialMetricQuarterly,
    raw: RawFetchResult,
) -> tuple[str, str]:
    source_document_id = f"legacy-raw-{raw.id}:{row.stock_id}:{row.period}"
    content_hash = raw.content_hash or f"raw-result-{raw.id}"
    return source_document_id, content_hash


def _fact_payloads(
    row: FinancialMetricQuarterly,
    *,
    filing_id: int,
) -> list[dict[str, Any]]:
    period_end = _quarter_end(row.fiscal_year, row.quarter)
    period_start = date(row.fiscal_year, 1, 1)
    payloads: list[dict[str, Any]] = []

    for column_name, (source_label, statement_type, attribution_scope) in (
        _DURATION_METRICS.items()
    ):
        value = getattr(row, column_name)
        if value is None:
            continue
        is_per_share = column_name == "eps"
        payloads.append(
            {
                "filing_id": filing_id,
                "stock_id": row.stock_id,
                "fact_key": f"{column_name}|current|{row.period}",
                "metric_code": "basic_eps" if is_per_share else column_name,
                "source_label": source_label,
                "source_value": _decimal_value(value),
                "source_value_text": str(value),
                "source_unit": "TWD_per_share" if is_per_share else "TWD_thousand",
                "unit_inference_source": (
                    "legacy endpoint contract; verify original label in raw_fetch_result"
                ),
                "currency": "TWD",
                "statement_type": statement_type,
                "period_kind": "duration",
                "period_scope": _duration_scope(row.quarter),
                "period_start": period_start,
                "period_end": period_end,
                "months_covered": row.quarter * 3,
                "fiscal_year": row.fiscal_year,
                "fiscal_quarter": row.quarter,
                "consolidation_scope": "unknown",
                "attribution_scope": attribution_scope,
                "eps_kind": "basic" if is_per_share else "not_applicable",
                "presentation_role": "current_period",
                "source_share_basis_id": None,
                "source_restated": None,
                "source_restated_status": "unknown",
            }
        )

    for column_name, (source_label, statement_type, attribution_scope) in (
        _INSTANT_METRICS.items()
    ):
        value = getattr(row, column_name)
        if value is None:
            continue
        is_per_share = column_name == "book_value_per_share"
        payloads.append(
            {
                "filing_id": filing_id,
                "stock_id": row.stock_id,
                "fact_key": f"{column_name}|current|{row.period}",
                "metric_code": column_name,
                "source_label": source_label,
                "source_value": _decimal_value(value),
                "source_value_text": str(value),
                "source_unit": "TWD_per_share" if is_per_share else "TWD_thousand",
                "unit_inference_source": (
                    "legacy endpoint contract; verify original label in raw_fetch_result"
                ),
                "currency": "TWD",
                "statement_type": statement_type,
                "period_kind": "instant",
                "period_scope": "instant_period_end",
                "period_start": None,
                "period_end": period_end,
                "months_covered": None,
                "fiscal_year": row.fiscal_year,
                "fiscal_quarter": row.quarter,
                "consolidation_scope": "unknown",
                "attribution_scope": attribution_scope,
                "eps_kind": "not_applicable",
                "presentation_role": "current_period",
                "source_share_basis_id": None,
                "source_restated": None,
                "source_restated_status": "unknown",
            }
        )
    return payloads


def backfill_legacy_financial_semantics(
    db: Session,
    *,
    stock_ids: Sequence[str] | None = None,
    limit: int = 1_000,
    apply: bool = False,
) -> dict[str, Any]:
    """Project legacy wide rows into raw semantic facts without claiming normalization.

    The caller owns commit and rollback. ``apply=False`` performs a deterministic
    dry-run and does not mutate the session.
    """

    if limit < 1 or limit > MAX_BACKFILL_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_BACKFILL_ROWS}")
    normalized_stock_ids = tuple(
        dict.fromkeys(
            stock_id.strip()
            for stock_id in (stock_ids or ())
            if stock_id and stock_id.strip()
        )
    )

    query = (
        db.query(FinancialMetricQuarterly, RawFetchResult)
        .join(
            RawFetchResult,
            RawFetchResult.id == FinancialMetricQuarterly.raw_result_id,
        )
        .order_by(
            FinancialMetricQuarterly.stock_id.asc(),
            FinancialMetricQuarterly.fiscal_year.asc(),
            FinancialMetricQuarterly.quarter.asc(),
            FinancialMetricQuarterly.source_id.asc(),
            FinancialMetricQuarterly.id.asc(),
        )
    )
    if normalized_stock_ids:
        query = query.filter(FinancialMetricQuarterly.stock_id.in_(normalized_stock_ids))
    rows = query.limit(limit).all()

    summary: dict[str, Any] = {
        "backfill_version": BACKFILL_VERSION,
        "mode": "apply" if apply else "dry_run",
        "requested_stock_ids": list(normalized_stock_ids),
        "limit": limit,
        "legacy_rows_selected": len(rows),
        "filings_created": 0,
        "filings_existing": 0,
        "parse_runs_created": 0,
        "parse_runs_existing": 0,
        "facts_created": 0,
        "facts_existing": 0,
        "source_values_skipped": 0,
        "normalization_ready_rows": 0,
        "normalization_blocked_rows": len(rows),
        "metric_counts": {},
        "issue_counts": {
            "known_at_missing": len(rows),
            "consolidation_scope_unknown": len(rows),
            "share_basis_unverified": len(rows),
            "source_restatement_unknown": len(rows),
            "legacy_roe_roa_not_promoted_to_source_fact": len(rows),
        },
    }
    metric_counts: Counter[str] = Counter()

    contexts = []
    raw_result_ids = {raw.id for _, raw in rows}
    row_stock_ids = {row.stock_id for row, _ in rows}
    existing_filings = []
    if raw_result_ids and row_stock_ids:
        existing_filings = (
            db.query(TaiwanFinancialFiling)
            .filter(
                TaiwanFinancialFiling.raw_result_id.in_(raw_result_ids),
                TaiwanFinancialFiling.stock_id.in_(row_stock_ids),
            )
            .all()
        )
    filing_by_identity = {
        (
            filing.source_id,
            filing.stock_id,
            filing.source_document_id,
            filing.content_hash,
        ): filing
        for filing in existing_filings
    }
    new_filings: list[TaiwanFinancialFiling] = []

    for row, raw in rows:
        source_document_id, content_hash = _filing_identity(row, raw)
        identity = (
            row.source_id,
            row.stock_id,
            source_document_id,
            content_hash,
        )
        filing = filing_by_identity.get(identity)
        filing_is_new = filing is None
        if filing_is_new:
            summary["filings_created"] += 1
            if apply:
                filing = TaiwanFinancialFiling(
                    source_id=row.source_id,
                    raw_result_id=raw.id,
                    supersedes_filing_id=None,
                    stock_id=row.stock_id,
                    source_document_id=source_document_id,
                    source_document_url=raw.url,
                    content_hash=content_hash,
                    filing_kind="provider_financial_snapshot",
                    fiscal_year=row.fiscal_year,
                    fiscal_quarter=row.quarter,
                    period_end=_quarter_end(row.fiscal_year, row.quarter),
                    announced_at=None,
                    filed_at=None,
                    provider_generated_at=None,
                    fetched_at=raw.fetched_at,
                    known_at=None,
                    parser_version=raw.parser_version or BACKFILL_VERSION,
                )
                new_filings.append(filing)
                filing_by_identity[identity] = filing
        else:
            summary["filings_existing"] += 1
        contexts.append((row, raw, filing))

    if apply and new_filings:
        db.add_all(new_filings)
        db.flush()

    filing_ids = {
        filing.id
        for _, _, filing in contexts
        if filing is not None and filing.id is not None
    }
    existing_parse_runs = []
    if filing_ids:
        existing_parse_runs = (
            db.query(TaiwanFinancialParseRun)
            .filter(TaiwanFinancialParseRun.filing_id.in_(filing_ids))
            .all()
        )
    parse_run_by_identity = {
        (
            run.filing_id,
            run.parser_version,
            run.output_hash,
        ): run
        for run in existing_parse_runs
    }
    planned: list[
        tuple[
            FinancialMetricQuarterly,
            RawFetchResult,
            TaiwanFinancialFiling | None,
            TaiwanFinancialParseRun | None,
            list[dict[str, Any]],
        ]
    ] = []
    new_parse_runs: list[TaiwanFinancialParseRun] = []

    for row, raw, filing in contexts:
        simulated_filing_id = filing.id if filing is not None else -row.id
        payloads = _fact_payloads(row, filing_id=simulated_filing_id)
        parser_version = (
            filing.parser_version
            if filing is not None
            else raw.parser_version or BACKFILL_VERSION
        )
        output_hash = canonical_fact_output_hash(payloads)
        parse_run = (
            parse_run_by_identity.get(
                (filing.id, parser_version, output_hash)
            )
            if filing is not None and filing.id is not None
            else None
        )
        if parse_run is None:
            summary["parse_runs_created"] += 1
            if apply:
                if filing is None or filing.id is None:
                    raise RuntimeError("filing must exist before parse run")
                parse_run = TaiwanFinancialParseRun(
                    filing_id=filing.id,
                    raw_result_id=raw.id,
                    parser_version=parser_version,
                    parsed_at=raw.fetched_at,
                    parse_status="succeeded",
                    review_status="approved",
                    output_hash=output_hash,
                    fact_count=len(payloads),
                    diagnostics_json=json.dumps(
                        {
                            "backfill_version": BACKFILL_VERSION,
                            "output_hash_contract": PARSE_OUTPUT_HASH_VERSION,
                            "legacy_source_values_selected": len(payloads),
                        },
                        sort_keys=True,
                    ),
                    reviewed_at=raw.fetched_at,
                    reviewed_by=f"system:{BACKFILL_VERSION}",
                )
                new_parse_runs.append(parse_run)
                parse_run_by_identity[
                    (filing.id, parser_version, output_hash)
                ] = parse_run
        else:
            summary["parse_runs_existing"] += 1
        planned.append((row, raw, filing, parse_run, payloads))

    if apply and new_parse_runs:
        db.add_all(new_parse_runs)
        db.flush()

    parse_run_ids = {
        parse_run.id
        for _, _, _, parse_run, _ in planned
        if parse_run is not None and parse_run.id is not None
    }
    existing_fact_keys = set()
    if parse_run_ids:
        existing_fact_keys = set(
            db.query(
                TaiwanFinancialStatementFact.parse_run_id,
                TaiwanFinancialStatementFact.fact_key,
            )
            .filter(TaiwanFinancialStatementFact.parse_run_id.in_(parse_run_ids))
            .all()
        )
    new_facts: list[TaiwanFinancialStatementFact] = []

    for row, _raw, filing, parse_run, payloads in planned:
        present_source_values = len(payloads)
        summary["source_values_skipped"] += (
            len(_DURATION_METRICS) + len(_INSTANT_METRICS) - present_source_values
        )
        for payload in payloads:
            metric_counts[payload["metric_code"]] += 1
            simulated_parse_run_id = (
                parse_run.id if parse_run is not None else -row.id
            )
            payload["parse_run_id"] = simulated_parse_run_id
            fact_identity = (
                payload["parse_run_id"],
                payload["fact_key"],
            )
            if fact_identity in existing_fact_keys:
                summary["facts_existing"] += 1
                continue
            summary["facts_created"] += 1
            if apply:
                if filing is None or parse_run is None:
                    raise RuntimeError("filing and parse run must exist before facts")
                new_facts.append(TaiwanFinancialStatementFact(**payload))

    if apply and new_facts:
        db.add_all(new_facts)
        db.flush()
    summary["metric_counts"] = dict(sorted(metric_counts.items()))
    return summary
