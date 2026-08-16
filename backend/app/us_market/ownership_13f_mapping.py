from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    USSec13FWarehousePartition,
    USSecurityIdentifierMap,
    USStockMaster,
)
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.us_market.providers.openfigi import (
    OpenFigiMappingJob,
    cusip_mapping_job,
    fetch_openfigi_mappings,
)
from app.us_market.sec_ownership.form13f import normalize_cusip
from app.us_market.sec_ownership.form13f_warehouse import query_13f_parquet_context


UNAUTHENTICATED_SYNC_LIMIT = 25
AUTHENTICATED_REQUEST_INTERVAL_SECONDS = 0.26
RATE_LIMIT_DEFAULT_WAIT_SECONDS = 6.0
RATE_LIMIT_MAX_WAIT_SECONDS = 30.0
RATE_LIMIT_RETRY_LIMIT = 1


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _current_paths(db: Session) -> list[str]:
    partitions = (
        db.query(USSec13FWarehousePartition)
        .filter(
            USSec13FWarehousePartition.is_current.is_(True),
            USSec13FWarehousePartition.status == "completed",
        )
        .order_by(USSec13FWarehousePartition.period_key.asc())
        .all()
    )
    return [item.holdings_path for item in partitions]


def _candidate_cusips(
    db: Session,
    *,
    cusips: Iterable[str] | None,
    limit: int,
    mapping_version: str,
    refresh: bool,
) -> list[str]:
    if cusips is not None:
        normalized: list[str] = []
        for value in cusips:
            cusip = normalize_cusip(value)
            if cusip is None:
                raise ValueError(f"Invalid CUSIP value: {value!r}")
            if cusip not in normalized:
                normalized.append(cusip)
        return normalized[:limit]
    checked = (
        []
        if refresh
        else [
            (row.identifier_value, "checked")
            for row in db.query(USSecurityIdentifierMap)
            .filter(USSecurityIdentifierMap.mapping_version == mapping_version)
            .all()
        ]
    )
    rows = query_13f_parquet_context(
        _current_paths(db),
        """
        SELECT h.cusip
        FROM holdings h
        LEFT JOIN identifier_map checked ON checked.cusip = h.cusip
        WHERE h.issue_code IS NULL AND checked.cusip IS NULL
        GROUP BY h.cusip
        ORDER BY sum(h.reported_value_usd) DESC NULLS LAST, h.cusip
        LIMIT ?
        """,
        identifier_mappings=checked,
        parameters=[limit],
    )
    return [str(item["cusip"]) for item in rows]


def _decision(
    db: Session,
    *,
    job: OpenFigiMappingJob,
    response: dict[str, Any],
    mapping_version: str,
) -> dict[str, Any]:
    raw_candidates = response.get("data")
    candidates = [item for item in raw_candidates or [] if isinstance(item, dict)]
    equity = [
        item
        for item in candidates
        if str(item.get("marketSector") or "").strip().casefold() == "equity"
        and str(item.get("ticker") or "").strip()
    ]
    us_composites = [
        item
        for item in equity
        if str(item.get("exchCode") or item.get("exchangeCode") or "").strip().upper() == "US"
        and str(item.get("figi") or "").strip()
        == str(item.get("compositeFIGI") or "").strip()
    ]
    composite_candidates = [
        item
        for item in equity
        if str(item.get("figi") or "").strip()
        == str(item.get("compositeFIGI") or "").strip()
    ]
    decision_candidates = us_composites or composite_candidates or equity
    symbols = sorted(
        {
            str(item.get("ticker") or "").strip().upper()
            for item in decision_candidates
            if str(item.get("ticker") or "").strip()
        }
    )
    stocks = {
        item.symbol: item
        for item in db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(symbols or ["<none>"]))
        .all()
    }
    approved_symbols = sorted(set(symbols) & set(stocks))
    if len(approved_symbols) == 1 and len(symbols) == 1:
        status = "approved"
        confidence = "exact"
        symbol = approved_symbols[0]
    elif len(symbols) > 1 or len(approved_symbols) > 1:
        status = "ambiguous"
        confidence = "disputed"
        symbol = None
    elif symbols:
        status = "unverified"
        confidence = "unverified"
        symbol = None
    else:
        status = "unmapped"
        confidence = "unmapped"
        symbol = None
    selected = next(
        (
            item
            for item in decision_candidates
            if str(item.get("ticker") or "").strip().upper() == symbol
        ),
        decision_candidates[0] if decision_candidates else candidates[0] if candidates else {},
    )
    stock = stocks.get(symbol) if symbol else None
    return {
        "identifier_type": job.identifier_type,
        "identifier_value": job.identifier_value,
        "mapping_version": mapping_version,
        "figi": selected.get("figi") or None,
        "composite_figi": selected.get("compositeFIGI") or None,
        "share_class_figi": selected.get("shareClassFIGI") or None,
        "symbol": symbol,
        "issuer_cik": stock.cik if stock is not None else None,
        "exchange_code": selected.get("exchCode") or selected.get("exchangeCode") or None,
        "market_sector": selected.get("marketSector") or None,
        "security_type": selected.get("securityType") or None,
        "security_type2": selected.get("securityType2") or None,
        "mapping_source": "openfigi",
        "status": status,
        "confidence": confidence,
        "evidence_json": _json(
            {
                "request": job.request_payload(),
                "response": response,
                "candidate_symbols": symbols,
                "approved_symbol_candidates": approved_symbols,
                "all_equity_candidate_count": len(equity),
                "us_composite_candidate_count": len(us_composites),
                "decision_rule": "single_us_composite_equity_ticker_present_in_us_stock_master",
            }
        ),
    }


def sync_13f_identifier_mappings(
    db: Session,
    *,
    cusips: Iterable[str] | None = None,
    max_identifiers: int = 25,
    refresh: bool = False,
) -> dict[str, Any]:
    configured_limit = max(int(settings.openfigi_max_jobs_per_sync), 1)
    if max_identifiers < 1 or max_identifiers > configured_limit:
        raise ValueError(f"max_identifiers must be between 1 and {configured_limit}.")
    api_key = str(settings.openfigi_api_key or "").strip() or None
    credential_mode = "authenticated" if api_key else "unauthenticated"
    bounded_limit = min(
        max_identifiers,
        configured_limit,
        configured_limit if api_key else UNAUTHENTICATED_SYNC_LIMIT,
    )
    mapping_version = str(settings.openfigi_mapping_version or "").strip()
    if not mapping_version:
        raise ValueError("OPENFIGI_MAPPING_VERSION must be configured.")
    requested = _candidate_cusips(
        db,
        cusips=cusips,
        limit=bounded_limit,
        mapping_version=mapping_version,
        refresh=refresh,
    )
    existing = {
        row.identifier_value: row
        for row in db.query(USSecurityIdentifierMap)
        .filter(
            USSecurityIdentifierMap.mapping_version == mapping_version,
            USSecurityIdentifierMap.identifier_value.in_(requested or ["<none>"]),
        )
        .all()
    }
    pending = [
        cusip
        for cusip in requested
        if refresh
        or cusip not in existing
        or existing[cusip].status in {"pending", "error"}
    ]
    batch_size = 100 if api_key else 5
    processed = 0
    retry_count = 0
    status_counts: dict[str, int] = {}
    errors: list[str] = []
    source_url: str | None = None
    last_request_started: float | None = None
    for offset in range(0, len(pending), batch_size):
        values = pending[offset : offset + batch_size]
        jobs = [cusip_mapping_job(value) for value in values]
        try:
            if api_key and last_request_started is not None:
                elapsed = time.monotonic() - last_request_started
                wait_seconds = AUTHENTICATED_REQUEST_INTERVAL_SECONDS - elapsed
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
            attempts = 0
            while True:
                last_request_started = time.monotonic()
                try:
                    responses, source_url = fetch_openfigi_mappings(
                        jobs,
                        api_key=api_key,
                        timeout_seconds=max(int(settings.openfigi_timeout_seconds), 1),
                    )
                    break
                except Exception as exc:
                    failure = provider_http_failure(exc)
                    if (
                        failure is None
                        or not failure.rate_limited
                        or attempts >= RATE_LIMIT_RETRY_LIMIT
                    ):
                        raise
                    retry_wait_seconds = min(
                        max(
                            float(
                                failure.retry_after_seconds
                                or RATE_LIMIT_DEFAULT_WAIT_SECONDS
                            ),
                            1.0,
                        ),
                        RATE_LIMIT_MAX_WAIT_SECONDS,
                    )
                    time.sleep(retry_wait_seconds)
                    attempts += 1
                    retry_count += 1
                    last_request_started = None
            now = datetime.now(timezone.utc)
            for job, response in zip(jobs, responses, strict=True):
                decision = _decision(
                    db,
                    job=job,
                    response=response,
                    mapping_version=mapping_version,
                )
                row = existing.get(job.identifier_value)
                if row is None:
                    row = USSecurityIdentifierMap(
                        identifier_type=job.identifier_type,
                        identifier_value=job.identifier_value,
                        mapping_version=mapping_version,
                    )
                    db.add(row)
                    existing[job.identifier_value] = row
                if row.manual_override:
                    continue
                for field, value in decision.items():
                    setattr(row, field, value)
                row.manual_override = False
                row.checked_at = now
                processed += 1
                status_counts[row.status] = status_counts.get(row.status, 0) + 1
            db.commit()
        except Exception as exc:
            db.rollback()
            errors.append(str(exc))
            break

    if errors and processed == 0:
        result_status = "error"
    elif errors or max_identifiers > bounded_limit:
        result_status = "partial"
    elif cusips is None and requested:
        result_status = "partial"
    else:
        result_status = "current"
    limitations: list[str] = []
    if not api_key:
        limitations.append(
            "OpenFIGI is running without an API key; each explicit sync is capped at 25 identifiers."
        )
    if max_identifiers > bounded_limit:
        limitations.append(
            f"Requested {max_identifiers} identifiers but the credential-mode bound is {bounded_limit}."
        )
    if cusips is None and requested:
        limitations.append(
            "This was one bounded full-market slice; rerun the mapping job until requested_count is zero."
        )
    detail = {
        "status": result_status,
        "mapping_version": mapping_version,
        "credential_mode": credential_mode,
        "requested_count": len(requested),
        "already_checked_count": len(requested) - len(pending),
        "pending_count": max(len(pending) - processed, 0),
        "processed_count": processed,
        "retry_count": retry_count,
        "status_counts": status_counts,
        "error_count": len(errors),
        "limitations": limitations,
    }
    record_provider_event(
        db,
        market="us",
        provider="openfigi",
        resource="sec_13f_identifier_mapping",
        target="cusip",
        status="success" if result_status == "current" else result_status,
        source_url=source_url,
        message=(
            "OpenFIGI 13F identifier mapping sync completed."
            if not errors
            else "OpenFIGI 13F identifier mapping sync completed with visible errors."
        ),
        error_message=errors[0] if errors else None,
        detail=detail,
    )
    db.commit()
    return {**detail, "errors": errors}


__all__ = [
    "AUTHENTICATED_REQUEST_INTERVAL_SECONDS",
    "RATE_LIMIT_DEFAULT_WAIT_SECONDS",
    "RATE_LIMIT_RETRY_LIMIT",
    "UNAUTHENTICATED_SYNC_LIMIT",
    "sync_13f_identifier_mappings",
]
