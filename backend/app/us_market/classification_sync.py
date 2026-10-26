"""Explicit bounded SEC SIC command using the existing Company Profile writer."""
from __future__ import annotations

from dataclasses import fields
from collections.abc import Callable
from typing import Annotated, Literal
from datetime import datetime, timezone
import hashlib
import time

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import USStockMaster
from app.observability.provider_http import ProviderHttpError
from app.us_market.catalog_store import us_common_stock_universe_filters
from app.us_market.errors import USMarketConfigurationError, USMarketDataFetchError
from app.us_market.fundamentals_store import upsert_us_company_profile_records
from app.us_market.providers import sec
from app.us_market.sources import USCompanyProfileRecord, _payload_hash


class USSicSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z][A-Z0-9.\-]{0,19}$")]] = Field(min_length=1, max_length=16)


class USSicSyncItem(BaseModel):
    symbol: str
    status: Literal["written", "skipped"]
    reason: str
    source_url: str | None = None


class USSicSyncResult(BaseModel):
    provider: Literal["sec_edgar_sic"] = "sec_edgar_sic"
    taxonomy: Literal["SIC"] = "SIC"
    effective_date: None = None
    status: Literal["complete", "partial", "skipped"]
    requested_count: int
    unique_count: int
    fetch_count: int
    max_http_attempts: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    items: list[USSicSyncItem]


class USSicCoverageSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_symbol: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9.\-]{0,19}$")
    universe_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_symbols: int = Field(default=64, ge=1, le=128)
    max_runtime_seconds: int = Field(default=120, ge=1, le=300)


def sync_us_sic_coverage(db: Session, *, request: USSicCoverageSyncRequest,
                         progress_callback=None, monotonic=time.monotonic) -> dict:
    """Resumable keyset pages over the existing universe and profile writer.

    Successful sub-batches are committed by that writer. A restarted page skips
    already-classified members; failed targets stay behind the returned cursor.
    No automatic full-universe run or provider call is admitted by a read.
    """
    from app.us_market.classification import read_us_classification

    request = USSicCoverageSyncRequest.model_validate(request.model_dump())
    if db.new or db.dirty or db.deleted:
        raise ValueError("SEC SIC coverage requires a clean Session")
    started = monotonic()
    before = read_us_classification(db, now=datetime.now(timezone.utc))
    identities = db.query(USStockMaster.symbol, USStockMaster.cik).filter(*us_common_stock_universe_filters()).order_by(USStockMaster.symbol).all()
    digest = hashlib.sha256("\n".join(f"{r.symbol}|{r.cik or ''}" for r in identities).encode()).hexdigest()
    if request.universe_hash is not None and request.universe_hash != digest:
        raise ValueError("US_CLASSIFICATION_UNIVERSE_CHANGED_RESTART_PAGE")
    if request.after_symbol is not None and request.universe_hash is None:
        raise ValueError("US_CLASSIFICATION_CURSOR_REQUIRES_UNIVERSE_HASH")
    profiles = before["profiles"]
    missing = [r.symbol for r in identities if not (profiles.get(r.symbol, {}).get("sector") and profiles.get(r.symbol, {}).get("industry"))]
    pending = [symbol for symbol in missing if request.after_symbol is None or symbol > request.after_symbol]
    selected = pending[:request.max_symbols]
    items, fetch_count = [], 0
    cursor = request.after_symbol
    retry_symbols = []
    start = 0
    while start < len(selected):
        # Reserve the worst-case bounded SEC HTTP time for a sub-batch; do not
        # silently overrun the page deadline with additional batches.
        remaining = request.max_runtime_seconds - (monotonic() - started)
        if remaining < 2 * max(1, min(30, settings.us_market_http_timeout_seconds)) + 2:
            break
        max_per_call = 2 * max(1, min(30, settings.us_market_http_timeout_seconds)) + 2
        batch_size = min(16, max(1, int(remaining // max_per_call)))
        # Each admitted sub-batch is bounded; the last in-flight request may
        # finish after the soft page deadline, by at most one policy timeout.
        batch = selected[start:start + batch_size]
        result = sync_us_sic_classification(db, request=USSicSyncRequest(symbols=batch))
        items.extend(item.model_dump(mode="json") for item in result.items)
        fetch_count += result.fetch_count
        retry_symbols = [item.symbol for item in result.items if item.reason.startswith("SOURCE_FAILED")]
        if progress_callback:
            progress_callback(len(items), len(selected), "Committed SEC SIC coverage sub-batch.")
        if retry_symbols:
            break
        cursor = batch[-1]
        start += len(batch)
    after = read_us_classification(db, now=datetime.now(timezone.utc))
    remaining_after_cursor = [s for s in pending if cursor is None or s > cursor]
    return {"provider": "sec_edgar_sic", "taxonomy": "SIC", "status": "partial" if after["coverage"]["unknown_count"] else "complete",
            "scan_complete": not remaining_after_cursor and not retry_symbols,
            "stop_reason": "source_failure" if retry_symbols else "page_or_time_bound" if remaining_after_cursor else "page_scan_complete",
            "universe_hash": digest, "next_cursor": cursor, "continuation_required": bool(remaining_after_cursor or retry_symbols),
            "requested_count": len(selected), "processed_count": len(items), "fetch_count": fetch_count,
            "max_http_attempts": fetch_count * sec.DEFAULT_SEC_REQUEST_POLICY.max_attempts,
            "retry_symbols": retry_symbols, "items": items,
            "coverage": after["coverage"], "missing_cik_count": sum(sec.sec_cik_identity(r.cik) is None for r in identities),
            "effective_date_status": "unknown", "classification_complete": after["coverage"]["unknown_count"] == 0,
            "resume_policy": "same_universe_keyset; committed_profiles_skipped; failed_batch_cursor_not_advanced"}


def sync_us_sic_classification(db: Session, *, request: USSicSyncRequest,
                               progress_callback: Callable | None = None) -> USSicSyncResult:
    # Revalidate even for internal callers using model_construct; no bypass of bounds.
    request = USSicSyncRequest.model_validate(request.model_dump())
    from app.us_market.service import _require_sec_user_agent

    user_agent = _require_sec_user_agent()
    policy = sec.DEFAULT_SEC_REQUEST_POLICY
    if policy.max_attempts > 2 or policy.min_interval_seconds < 0.25:
        raise USMarketConfigurationError("SEC SIC requires the existing bounded SEC request policy.")
    # This command must own a clean Session; the writer commits exactly once.
    if db.new or db.dirty or db.deleted:
        raise ValueError("SEC SIC sync requires a clean Session")
    symbols = list(dict.fromkeys(request.symbols))
    with db.no_autoflush:
        identities = {row.symbol: row.cik for row in db.query(USStockMaster.symbol, USStockMaster.cik)
                      .filter(*us_common_stock_universe_filters(), USStockMaster.symbol.in_(symbols)).all()}
    records = []
    items = []
    fetch_count = 0
    for symbol in symbols:
        if progress_callback is not None:
            progress_callback(len(items), len(symbols), f"Reading SEC SIC for {symbol}.")
        reason = None
        source_url = None
        cik = sec.sec_cik_identity(identities.get(symbol))
        if symbol not in identities:
            reason = "NOT_ELIGIBLE_ORDINARY_STOCK"
        elif cik is None:
            reason = "MISSING_OR_INVALID_CIK"
        else:
            fetch_count += 1
            try:
                payload, source_url = sec.fetch_sec_submissions_payload(
                    cik=cik, sec_user_agent=user_agent,
                    timeout_seconds=max(1, min(30, settings.us_market_http_timeout_seconds)),
                )
            except ProviderHttpError as exc:
                reason = f"SOURCE_FAILED:{exc.status}"
            except USMarketDataFetchError:
                reason = "SOURCE_FAILED:invalid_payload"
            except ValueError:
                reason = "SOURCE_FAILED:invalid_json"
            if reason is None:
                try:
                    classification = sec.parse_sec_sic_classification(payload, cik=cik, symbol=symbol)
                except ValueError as exc:
                    reason = str(exc)
                else:
                    values = {field.name: None for field in fields(USCompanyProfileRecord)}
                    values.update(provider="sec_edgar_sic", symbol=symbol,
                                  company_name=payload.get("name") if isinstance(payload.get("name"), str) else None,
                                  sector=f"SIC {classification.sic[:2]}xx",
                                  industry=f"SIC {classification.sic} · {classification.description}",
                                  source_url=source_url, raw_payload_hash=_payload_hash(payload))
                    records.append(USCompanyProfileRecord(**values))
        items.append(USSicSyncItem(symbol=symbol, status="skipped" if reason else "written",
                                   reason=reason or "SEC_SIC_IDENTITY_VERIFIED", source_url=source_url))
    counts = {"inserted_count": 0, "updated_count": 0}
    if records:
        try:
            counts = upsert_us_company_profile_records(db, records)
        except Exception:
            db.rollback()
            raise
    skipped = sum(item.status == "skipped" for item in items)
    return USSicSyncResult(status="skipped" if not records else "partial" if skipped else "complete",
                           requested_count=len(request.symbols), unique_count=len(symbols),
                           fetch_count=fetch_count, max_http_attempts=fetch_count * policy.max_attempts,
                           skipped_count=skipped, items=items, **counts)
