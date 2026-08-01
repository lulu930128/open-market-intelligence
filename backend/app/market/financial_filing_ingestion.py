from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from typing import Any
import re

from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialFiling,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_parse_runs import (
    canonical_fact_output_hash,
    parse_diagnostics,
)
from app.market.providers.mops_financial_filing import (
    MOPS_IXBRL_URL,
    MOPS_SOURCE_NAME,
    MopsFinancialFetchBatch,
    fetch_mops_financial_filings,
)
from app.parsers.mops_ixbrl import (
    PARSER_VERSION,
    ParsedMopsIxbrl,
    parse_mops_ixbrl,
)


MAX_INGESTION_PERIODS = 8
MAX_REPLAY_FILINGS = 8
_STOCK_ID_RE = re.compile(r"^[0-9A-Za-z.-]{1,20}$")


def _ensure_source(
    db: Session,
    *,
    apply: bool,
) -> tuple[SourceRegistry | None, bool]:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == MOPS_SOURCE_NAME)
        .first()
    )
    if source is not None:
        if source.reliability_level != "official":
            raise ValueError(
                f"{MOPS_SOURCE_NAME} exists with non-official reliability "
                f"{source.reliability_level!r}"
            )
        if apply:
            source.parser_type = PARSER_VERSION
        return source, False
    if not apply:
        return None, True
    source = SourceRegistry(
        source_name=MOPS_SOURCE_NAME,
        source_type="official_filing",
        category="financial_filing",
        endpoint_url=MOPS_IXBRL_URL,
        enabled=True,
        fetch_interval_minutes=None,
        priority=5,
        parser_type=PARSER_VERSION,
        auth_type="none",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    return source, True


def _fact_payload(
    filing_id: int,
    parse_run_id: int,
    item: Any,
) -> dict[str, Any]:
    return {
        "filing_id": filing_id,
        "parse_run_id": parse_run_id,
        "stock_id": item.stock_id if hasattr(item, "stock_id") else None,
        "fact_key": item.fact_key,
        "metric_code": item.metric_code,
        "source_label": item.source_label,
        "source_value": item.source_value,
        "source_value_text": item.source_value_text,
        "source_unit": item.source_unit,
        "unit_inference_source": item.unit_inference_source,
        "currency": item.currency,
        "statement_type": item.statement_type,
        "period_kind": item.period_kind,
        "period_scope": item.period_scope,
        "period_start": item.period_start,
        "period_end": item.period_end,
        "months_covered": item.months_covered,
        "fiscal_year": item.fiscal_year,
        "fiscal_quarter": item.fiscal_quarter,
        "consolidation_scope": item.consolidation_scope,
        "attribution_scope": item.attribution_scope,
        "eps_kind": item.eps_kind,
        "presentation_role": item.presentation_role,
        "source_share_basis_id": item.source_share_basis_id,
        "source_restated": item.source_restated,
        "source_restated_status": item.source_restated_status,
    }


def _assert_existing_fact(
    existing: TaiwanFinancialStatementFact,
    payload: dict[str, Any],
) -> None:
    comparable_fields = (
        "filing_id",
        "parse_run_id",
        "metric_code",
        "source_value",
        "source_unit",
        "period_start",
        "period_end",
        "period_scope",
        "presentation_role",
        "source_share_basis_id",
    )
    conflicts = [
        field
        for field in comparable_fields
        if getattr(existing, field) != payload[field]
    ]
    if conflicts:
        raise ValueError(
            f"stored official fact conflicts with parsed filing: "
            f"fact_id={existing.id} fields={conflicts}"
        )


def _quarter_end(fiscal_year: int, fiscal_quarter: int) -> date:
    return {
        1: date(fiscal_year, 3, 31),
        2: date(fiscal_year, 6, 30),
        3: date(fiscal_year, 9, 30),
        4: date(fiscal_year, 12, 31),
    }[fiscal_quarter]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("official filing timestamp must include timezone evidence")
    return value.astimezone(timezone.utc)


def _same_utc_instant(stored: datetime | None, expected: datetime) -> bool:
    if stored is None:
        return False
    normalized_stored = (
        stored.replace(tzinfo=timezone.utc)
        if stored.tzinfo is None
        else stored.astimezone(timezone.utc)
    )
    return normalized_stored == _utc(expected)


def _persist_parse_output(
    db: Session,
    *,
    filing: TaiwanFinancialFiling | None,
    raw: RawFetchResult | None,
    parsed: ParsedMopsIxbrl,
    stock_id: str,
    apply: bool,
    replayed_from_raw: bool,
) -> dict[str, Any]:
    output_hash = canonical_fact_output_hash(parsed.facts)
    diagnostics_json = parse_diagnostics(
        contexts_seen=len(parsed.contexts),
        units_seen=len(parsed.units),
        numeric_facts_seen=parsed.numeric_fact_count,
        facts=parsed.facts,
        replayed_from_raw=replayed_from_raw,
    )
    parse_run = None
    if filing is not None and filing.id is not None:
        parse_run = (
            db.query(TaiwanFinancialParseRun)
            .filter(
                TaiwanFinancialParseRun.filing_id == filing.id,
                TaiwanFinancialParseRun.parser_version == PARSER_VERSION,
                TaiwanFinancialParseRun.output_hash == output_hash,
            )
            .one_or_none()
        )

    if parse_run is not None:
        stored_facts = (
            db.query(TaiwanFinancialStatementFact)
            .filter(
                TaiwanFinancialStatementFact.parse_run_id == parse_run.id,
            )
            .order_by(TaiwanFinancialStatementFact.fact_key)
            .all()
        )
        if parse_run.parse_status != "succeeded":
            raise ValueError(
                f"matching parse output is not successful: parse_run_id={parse_run.id}"
            )
        if parse_run.fact_count != len(stored_facts):
            raise ValueError(
                "stored parse run fact count mismatch: "
                f"parse_run_id={parse_run.id} declared={parse_run.fact_count} "
                f"actual={len(stored_facts)}"
            )
        expected_by_key = {item.fact_key: item for item in parsed.facts}
        stored_by_key = {item.fact_key: item for item in stored_facts}
        if set(expected_by_key) != set(stored_by_key):
            raise ValueError(
                "stored parse run fact keys differ from deterministic replay: "
                f"parse_run_id={parse_run.id}"
            )
        for fact_key, item in expected_by_key.items():
            payload = _fact_payload(filing.id, parse_run.id, item)
            payload["stock_id"] = stock_id
            _assert_existing_fact(stored_by_key[fact_key], payload)
        if canonical_fact_output_hash(stored_facts) != parse_run.output_hash:
            raise ValueError(
                "stored parse run facts no longer match output hash: "
                f"parse_run_id={parse_run.id}"
            )
        return {
            "parse_run_created": 0,
            "parse_run_reused": 1,
            "parse_run_id": parse_run.id,
            "parse_status": parse_run.parse_status,
            "review_status": parse_run.review_status,
            "output_hash": output_hash,
            "facts_created": 0,
            "facts_reused": len(stored_facts),
            "diagnostics_json": diagnostics_json,
        }

    if apply:
        if filing is None or filing.id is None:
            raise RuntimeError("filing must exist before parse run")
        parse_run = TaiwanFinancialParseRun(
            filing_id=filing.id,
            raw_result_id=raw.id if raw is not None else filing.raw_result_id,
            parser_version=PARSER_VERSION,
            parsed_at=datetime.now(timezone.utc),
            parse_status="succeeded",
            review_status="pending",
            output_hash=output_hash,
            fact_count=len(parsed.facts),
            diagnostics_json=diagnostics_json,
            reviewed_at=None,
            reviewed_by=None,
        )
        db.add(parse_run)
        db.flush()
        for item in parsed.facts:
            payload = _fact_payload(filing.id, parse_run.id, item)
            payload["stock_id"] = stock_id
            db.add(TaiwanFinancialStatementFact(**payload))
        db.flush()

    return {
        "parse_run_created": 1,
        "parse_run_reused": 0,
        "parse_run_id": parse_run.id if parse_run is not None else None,
        "parse_status": "succeeded",
        "review_status": "pending",
        "output_hash": output_hash,
        "facts_created": len(parsed.facts),
        "facts_reused": 0,
        "diagnostics_json": diagnostics_json,
    }


def ingest_mops_financial_filings(
    db: Session,
    *,
    stock_id: str,
    periods: Sequence[tuple[int, int]],
    report_id: str = "C",
    apply: bool = False,
    timeout_seconds: int = 30,
    fetcher: Callable[..., MopsFinancialFetchBatch] = fetch_mops_financial_filings,
) -> dict[str, Any]:
    """Fetch and persist official filings; caller owns commit and rollback."""

    normalized_stock_id = stock_id.strip()
    if not _STOCK_ID_RE.fullmatch(normalized_stock_id):
        raise ValueError(f"invalid stock_id: {stock_id!r}")
    normalized_periods = tuple(sorted(set(periods)))
    if not normalized_periods:
        raise ValueError("at least one filing period is required")
    if len(normalized_periods) > MAX_INGESTION_PERIODS:
        raise ValueError(
            f"at most {MAX_INGESTION_PERIODS} filing periods may be ingested"
        )
    if any(quarter not in {1, 2, 3, 4} for _, quarter in normalized_periods):
        raise ValueError("filing quarters must be between 1 and 4")

    batch = fetcher(
        stock_id=normalized_stock_id,
        periods=normalized_periods,
        report_id=report_id,
        timeout_seconds=timeout_seconds,
    )
    if {
        (item.fiscal_year, item.fiscal_quarter) for item in batch.filings
    } != set(normalized_periods):
        raise ValueError("provider batch does not exactly match requested periods")

    source, source_created = _ensure_source(db, apply=apply)
    summary: dict[str, Any] = {
        "ingestion_version": PARSER_VERSION,
        "mode": "apply" if apply else "dry_run",
        "stock_id": normalized_stock_id,
        "periods": [f"{year}Q{quarter}" for year, quarter in normalized_periods],
        "requested_report_id": report_id,
        "report_id": batch.selected_report_id or report_id,
        "request_count": batch.request_count,
        "request_limit": (
            batch.request_limit
            if batch.request_limit is not None
            else len(normalized_periods)
            + len({year for year, _ in normalized_periods})
        ),
        "source_created": int(source_created),
        "source_reused": int(not source_created),
        "raw_results_created": 0,
        "raw_results_reused": 0,
        "filings_created": 0,
        "filings_reused": 0,
        "parse_runs_created": 0,
        "parse_runs_reused": 0,
        "facts_created": 0,
        "facts_reused": 0,
        "numeric_facts_seen": 0,
        "canonical_facts_selected": 0,
        "documents": [],
    }

    for fetched in batch.filings:
        summary["numeric_facts_seen"] += fetched.parsed.numeric_fact_count
        summary["canonical_facts_selected"] += len(fetched.parsed.facts)
        raw = None
        filing = None
        if source is not None:
            raw = (
                db.query(RawFetchResult)
                .filter(
                    RawFetchResult.source_id == source.id,
                    RawFetchResult.url == fetched.ixbrl_url,
                    RawFetchResult.content_hash == fetched.content_hash,
                )
                .first()
            )
            filing = (
                db.query(TaiwanFinancialFiling)
                .filter(
                    TaiwanFinancialFiling.source_id == source.id,
                    TaiwanFinancialFiling.stock_id == normalized_stock_id,
                    TaiwanFinancialFiling.source_document_id
                    == fetched.document.filename,
                    TaiwanFinancialFiling.content_hash == fetched.content_hash,
                )
                .first()
            )

        if raw is None:
            summary["raw_results_created"] += 1
            if apply:
                if source is None:
                    raise RuntimeError("official source must exist before raw result")
                raw = RawFetchResult(
                    source_id=source.id,
                    fetched_at=fetched.fetched_at,
                    url=fetched.ixbrl_url,
                    method="GET",
                    status_code=200,
                    content_type=fetched.content_type,
                    content_hash=fetched.content_hash,
                    raw_text=fetched.decoded_text,
                    parser_version=PARSER_VERSION,
                )
                db.add(raw)
                db.flush()
        else:
            summary["raw_results_reused"] += 1

        if filing is None:
            summary["filings_created"] += 1
            if apply:
                if source is None:
                    raise RuntimeError("official source must exist before filing")
                supersedes = (
                    db.query(TaiwanFinancialFiling)
                    .filter(
                        TaiwanFinancialFiling.source_id == source.id,
                        TaiwanFinancialFiling.stock_id == normalized_stock_id,
                        TaiwanFinancialFiling.source_document_id
                        == fetched.document.filename,
                        TaiwanFinancialFiling.content_hash != fetched.content_hash,
                    )
                    .order_by(TaiwanFinancialFiling.id.desc())
                    .first()
                )
                filing = TaiwanFinancialFiling(
                    source_id=source.id,
                    raw_result_id=raw.id if raw is not None else None,
                    supersedes_filing_id=supersedes.id if supersedes else None,
                    stock_id=normalized_stock_id,
                    source_document_id=fetched.document.filename,
                    source_document_url=fetched.ixbrl_url,
                    content_hash=fetched.content_hash,
                    filing_kind="mops_ixbrl_financial_report",
                    fiscal_year=fetched.fiscal_year,
                    fiscal_quarter=fetched.fiscal_quarter,
                    period_end=_quarter_end(
                        fetched.fiscal_year,
                        fetched.fiscal_quarter,
                    ),
                    announced_at=None,
                    filed_at=_utc(fetched.document.uploaded_at),
                    provider_generated_at=None,
                    fetched_at=fetched.fetched_at,
                    known_at=_utc(fetched.document.uploaded_at),
                    parser_version=PARSER_VERSION,
                )
                db.add(filing)
                db.flush()
        else:
            summary["filings_reused"] += 1
            if (
                not _same_utc_instant(
                    filing.filed_at,
                    fetched.document.uploaded_at,
                )
                or not _same_utc_instant(
                    filing.known_at,
                    fetched.document.uploaded_at,
                )
            ):
                raise ValueError(
                    "stored official filing timestamp conflicts with the "
                    f"document registry: filing_id={filing.id}"
                )

        parse_result = _persist_parse_output(
            db,
            filing=filing,
            raw=raw,
            parsed=fetched.parsed,
            stock_id=normalized_stock_id,
            apply=apply,
            replayed_from_raw=False,
        )
        summary["parse_runs_created"] += parse_result["parse_run_created"]
        summary["parse_runs_reused"] += parse_result["parse_run_reused"]
        summary["facts_created"] += parse_result["facts_created"]
        summary["facts_reused"] += parse_result["facts_reused"]

        summary["documents"].append(
            {
                "period": f"{fetched.fiscal_year}Q{fetched.fiscal_quarter}",
                "source_document_id": fetched.document.filename,
                "ixbrl_url": fetched.ixbrl_url,
                "content_hash": fetched.content_hash,
                "filed_at": fetched.document.uploaded_at.isoformat(),
                "file_size_bytes": fetched.document.file_size_bytes,
                "correction_status": fetched.document.correction_status,
                "canonical_fact_count": len(fetched.parsed.facts),
                "parse_run_id": parse_result["parse_run_id"],
                "parse_status": parse_result["parse_status"],
                "parse_review_status": parse_result["review_status"],
                "parse_output_hash": parse_result["output_hash"],
                "eps_facts": [
                    {
                        "metric_code": fact.metric_code,
                        "fiscal_year": fact.fiscal_year,
                        "fiscal_quarter": fact.fiscal_quarter,
                        "presentation_role": fact.presentation_role,
                        "source_value": str(fact.source_value),
                        "source_unit": fact.source_unit,
                        "source_share_basis_id": fact.source_share_basis_id,
                        "source_restated_status": fact.source_restated_status,
                        "fact_key": fact.fact_key,
                    }
                    for fact in fetched.parsed.facts
                    if fact.metric_code in {"basic_eps", "diluted_eps"}
                ],
            }
        )
    if apply:
        if source is not None:
            source.last_success_at = max(
                filing.fetched_at for filing in batch.filings
            )
        db.flush()
    return summary


def replay_stored_mops_financial_filings(
    db: Session,
    *,
    filing_ids: Sequence[int],
    apply: bool = False,
) -> dict[str, Any]:
    """Deterministically reparse bounded stored MOPS raw payloads.

    The caller owns commit and rollback. Replay never fetches the network and
    never overwrites an existing parse run or statement fact.
    """

    normalized_ids = tuple(sorted(set(int(item) for item in filing_ids)))
    if not normalized_ids:
        raise ValueError("at least one filing_id is required")
    if len(normalized_ids) > MAX_REPLAY_FILINGS:
        raise ValueError(
            f"at most {MAX_REPLAY_FILINGS} filings may be replayed at once"
        )
    filings = (
        db.query(TaiwanFinancialFiling)
        .filter(TaiwanFinancialFiling.id.in_(normalized_ids))
        .order_by(TaiwanFinancialFiling.id)
        .all()
    )
    if {item.id for item in filings} != set(normalized_ids):
        missing = sorted(set(normalized_ids) - {item.id for item in filings})
        raise ValueError(f"filings not found: {missing}")

    summary: dict[str, Any] = {
        "replay_version": PARSER_VERSION,
        "mode": "apply" if apply else "dry_run",
        "filing_ids": list(normalized_ids),
        "parse_runs_created": 0,
        "parse_runs_reused": 0,
        "facts_created": 0,
        "facts_reused": 0,
        "documents": [],
    }
    for filing in filings:
        if filing.raw_result_id is None:
            raise ValueError(
                f"filing has no raw_result_id and cannot be replayed: {filing.id}"
            )
        raw = (
            db.query(RawFetchResult)
            .filter(RawFetchResult.id == filing.raw_result_id)
            .one_or_none()
        )
        if raw is None or not raw.raw_text:
            raise ValueError(
                f"stored raw payload is unavailable for filing: {filing.id}"
            )
        if filing.fiscal_quarter not in {1, 2, 3, 4}:
            raise ValueError(
                f"filing quarter is not replayable: filing_id={filing.id}"
            )
        report_id = (
            "A"
            if "_AI2." in filing.source_document_id.upper()
            else "C"
        )
        source_share_basis_id = (
            f"{filing.stock_id}:{filing.fiscal_year}Q"
            f"{filing.fiscal_quarter}:{filing.content_hash[:16]}:presentation"
        )
        parsed = parse_mops_ixbrl(
            raw.raw_text,
            stock_id=filing.stock_id,
            fiscal_year=filing.fiscal_year,
            fiscal_quarter=filing.fiscal_quarter,
            report_id=report_id,
            source_share_basis_id=source_share_basis_id,
        )
        result = _persist_parse_output(
            db,
            filing=filing,
            raw=raw,
            parsed=parsed,
            stock_id=filing.stock_id,
            apply=apply,
            replayed_from_raw=True,
        )
        summary["parse_runs_created"] += result["parse_run_created"]
        summary["parse_runs_reused"] += result["parse_run_reused"]
        summary["facts_created"] += result["facts_created"]
        summary["facts_reused"] += result["facts_reused"]
        summary["documents"].append(
            {
                "filing_id": filing.id,
                "stock_id": filing.stock_id,
                "period": f"{filing.fiscal_year}Q{filing.fiscal_quarter}",
                "source_document_id": filing.source_document_id,
                "raw_result_id": raw.id,
                "parser_version": PARSER_VERSION,
                "parse_run_id": result["parse_run_id"],
                "parse_status": result["parse_status"],
                "parse_review_status": result["review_status"],
                "parse_output_hash": result["output_hash"],
                "canonical_fact_count": len(parsed.facts),
                "diagnostics": result["diagnostics_json"],
            }
        )
    return summary


__all__ = [
    "MAX_INGESTION_PERIODS",
    "MAX_REPLAY_FILINGS",
    "ingest_mops_financial_filings",
    "replay_stored_mops_financial_filings",
]
