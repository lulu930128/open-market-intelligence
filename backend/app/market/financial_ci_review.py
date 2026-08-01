from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TaiwanFinancialFiling, TaiwanFinancialParseRun
from app.market.financial_ci_rollout import (
    MAX_CI_INGESTION_BATCH_SYMBOLS,
    MAX_CI_PLAN_PERIODS,
    OFFICIAL_FILING_KIND,
)
from app.market.financial_parse_runs import review_financial_parse_run


CI_PARSE_REVIEW_BATCH_CONTRACT_VERSION = "omi.tw-financial-ci-parse-review.v1"
CI_PARSER_VERSION = "mops-ixbrl-v4"
_STOCK_ID_RE = re.compile(r"^[0-9A-Z]{2,20}$")


def _normalize_request(
    *,
    stock_ids: Sequence[str],
    periods: Sequence[tuple[int, int]],
) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    normalized_stock_ids = tuple(
        dict.fromkeys(str(stock_id).strip().upper() for stock_id in stock_ids)
    )
    if not normalized_stock_ids:
        raise ValueError("at least one explicit stock_id is required")
    if len(normalized_stock_ids) > MAX_CI_INGESTION_BATCH_SYMBOLS:
        raise ValueError(
            "at most "
            f"{MAX_CI_INGESTION_BATCH_SYMBOLS} symbols may be reviewed per batch"
        )
    invalid_stock_ids = [
        stock_id
        for stock_id in normalized_stock_ids
        if not _STOCK_ID_RE.fullmatch(stock_id)
    ]
    if invalid_stock_ids:
        raise ValueError(f"invalid stock_ids: {invalid_stock_ids}")

    normalized_periods = tuple(
        sorted(dict.fromkeys((int(year), int(quarter)) for year, quarter in periods))
    )
    if not normalized_periods:
        raise ValueError("at least one explicit period is required")
    if len(normalized_periods) > MAX_CI_PLAN_PERIODS:
        raise ValueError(
            f"at most {MAX_CI_PLAN_PERIODS} periods may be reviewed per batch"
        )
    invalid_periods = [
        (year, quarter)
        for year, quarter in normalized_periods
        if year < 2000 or quarter not in {1, 2, 3, 4}
    ]
    if invalid_periods:
        raise ValueError(f"invalid periods: {invalid_periods}")
    return normalized_stock_ids, normalized_periods


def _review_candidates_for_symbol(
    db: Session,
    *,
    stock_id: str,
    periods: Sequence[tuple[int, int]],
) -> list[tuple[str, TaiwanFinancialParseRun]]:
    candidates: list[tuple[str, TaiwanFinancialParseRun]] = []
    for year, quarter in periods:
        period_label = f"{year}Q{quarter}"
        filings = (
            db.query(TaiwanFinancialFiling)
            .filter(
                TaiwanFinancialFiling.stock_id == stock_id,
                TaiwanFinancialFiling.filing_kind == OFFICIAL_FILING_KIND,
                TaiwanFinancialFiling.fiscal_year == year,
                TaiwanFinancialFiling.fiscal_quarter == quarter,
            )
            .order_by(TaiwanFinancialFiling.id)
            .all()
        )
        if not filings:
            raise ValueError(f"official filing missing: {stock_id} {period_label}")

        successful_runs: list[tuple[TaiwanFinancialFiling, TaiwanFinancialParseRun]] = []
        for filing in filings:
            runs = (
                db.query(TaiwanFinancialParseRun)
                .filter(
                    TaiwanFinancialParseRun.filing_id == filing.id,
                    TaiwanFinancialParseRun.parser_version == CI_PARSER_VERSION,
                    TaiwanFinancialParseRun.parse_status == "succeeded",
                )
                .order_by(TaiwanFinancialParseRun.id)
                .all()
            )
            output_hashes = {run.output_hash for run in runs}
            if len(output_hashes) > 1:
                raise ValueError(
                    "parser output conflict for one filing: "
                    f"{stock_id} {period_label} filing_id={filing.id}"
                )
            if runs:
                successful_runs.append((filing, runs[-1]))

        if not successful_runs:
            raise ValueError(
                f"successful {CI_PARSER_VERSION} output missing: "
                f"{stock_id} {period_label}"
            )
        content_hashes = {filing.content_hash for filing, _ in successful_runs}
        if len(content_hashes) > 1:
            raise ValueError(
                "filing version conflict requires reconciliation: "
                f"{stock_id} {period_label}"
            )
        selected_filing, selected_run = max(
            successful_runs,
            key=lambda item: item[1].id,
        )
        if selected_run.output_hash is None:
            raise ValueError(
                f"parse output hash missing: {stock_id} {period_label}"
            )
        candidates.append((period_label, selected_run))
    return candidates


def review_ci_parse_run_batch(
    db: Session,
    *,
    stock_ids: Sequence[str],
    periods: Sequence[tuple[int, int]],
    reviewer: str,
    reviewed_at: datetime,
    apply: bool = False,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Review an explicit parser-v4 batch with per-symbol isolation.

    Every run is rehashed by ``review_financial_parse_run`` immediately before
    approval. A symbol either commits all requested periods or none of them.
    """

    normalized_reviewer = reviewer.strip()
    if not normalized_reviewer:
        raise ValueError("reviewer is required")
    if reviewed_at.tzinfo is None:
        raise ValueError("reviewed_at must include timezone evidence")
    normalized_reviewed_at = reviewed_at.astimezone(timezone.utc)
    normalized_stock_ids, normalized_periods = _normalize_request(
        stock_ids=stock_ids,
        periods=periods,
    )

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for stock_id in normalized_stock_ids:
        try:
            candidates = _review_candidates_for_symbol(
                db,
                stock_id=stock_id,
                periods=normalized_periods,
            )
            reviews = [
                {
                    "period": period_label,
                    **review_financial_parse_run(
                        db,
                        parse_run_id=run.id,
                        expected_output_hash=str(run.output_hash),
                        reviewer=normalized_reviewer,
                        decision="approved",
                        apply=apply,
                        reviewed_at=normalized_reviewed_at,
                    ),
                }
                for period_label, run in candidates
            ]
            if apply:
                db.commit()
            else:
                db.rollback()
            results.append(
                {
                    "stock_id": stock_id,
                    "status": "approved" if apply else "validated",
                    "review_count": len(reviews),
                    "changed_count": sum(bool(item["changed"]) for item in reviews),
                    "reviews": reviews,
                }
            )
        except Exception as exc:
            db.rollback()
            failure = {
                "stock_id": stock_id,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            failures.append(failure)
            if fail_fast:
                raise

    succeeded_count = len(results)
    failed_count = len(failures)
    status = "complete"
    if failed_count and succeeded_count:
        status = "partial"
    elif failed_count:
        status = "failed"
    return {
        "contract_version": CI_PARSE_REVIEW_BATCH_CONTRACT_VERSION,
        "mode": "apply" if apply else "dry_run",
        "parser_version": CI_PARSER_VERSION,
        "reviewer": normalized_reviewer,
        "reviewed_at": normalized_reviewed_at.isoformat(),
        "stock_ids": list(normalized_stock_ids),
        "periods": [f"{year}Q{quarter}" for year, quarter in normalized_periods],
        "status": status,
        "succeeded_count": succeeded_count,
        "failed_count": failed_count,
        "results": results,
        "failures": failures,
        "boundaries": [
            "approval_rehashes_the_exact_stored_output",
            "each_symbol_is_transaction_isolated",
            "parse_approval_does_not_imply_normalization_approval",
        ],
    }


__all__ = [
    "CI_PARSE_REVIEW_BATCH_CONTRACT_VERSION",
    "CI_PARSER_VERSION",
    "review_ci_parse_run_batch",
]
