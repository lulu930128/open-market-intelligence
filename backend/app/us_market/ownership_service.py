from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import USSecOwnershipFiling, USStockMaster
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.us_market.errors import (
    USMarketConfigurationError,
    USMarketDataFetchError,
    USStockNotFoundError,
)
from app.us_market.ownership_store import (
    get_insider_transactions_contract,
    persist_form4_filing,
    update_form4_sync_state,
)
from app.us_market.providers import sec as sec_provider
from app.us_market.sec_ownership import (
    parse_form4_submission_entries,
    parse_form4_xml,
)
from app.us_market.sources import normalize_us_symbol
from app.us_market.watchlist_store import list_us_watchlist_symbols


ProgressCallback = Callable[[int | None, int | None, str | None], None]


def _sec_user_agent() -> str:
    value = str(settings.us_sec_user_agent or "").strip().strip('"').strip("'")
    if not value or "set US_SEC_USER_AGENT" in value:
        raise USMarketConfigurationError(
            "US_SEC_USER_AGENT is not configured. Set a descriptive User-Agent before calling SEC EDGAR APIs."
        )
    return value


def _stock(db: Session, symbol: str) -> USStockMaster:
    normalized = normalize_us_symbol(symbol)
    row = db.query(USStockMaster).filter(USStockMaster.symbol == normalized).first()
    if row is None:
        raise USStockNotFoundError(f"US symbol='{normalized}' was not found.")
    if not str(row.cik or "").strip():
        raise USMarketConfigurationError(
            f"US symbol='{normalized}' has no SEC CIK in the symbol master."
        )
    return row


def _record_sync_event(
    db: Session,
    *,
    symbol: str,
    status: str,
    source_url: str | None,
    message: str,
    detail: dict[str, Any],
    error: BaseException | None = None,
    commit: bool = False,
) -> None:
    failure = provider_http_failure(error) if error is not None else None
    fields: dict[str, Any] = {}
    if failure is not None:
        fields = failure.provider_event_fields()
        fields.pop("market", None)
        fields.pop("provider", None)
        fields.pop("resource", None)
        fields.pop("target", None)
        fields.pop("status", None)
        fields.pop("source_url", None)
        fields.pop("error_message", None)
        source_url = source_url or failure.source_url
    record_provider_event(
        db,
        market="us",
        provider="sec_edgar",
        resource="sec_insider_transactions",
        target=symbol,
        status=status,
        source_url=source_url,
        message=message,
        error_message=str(error) if error is not None else None,
        detail=detail,
        commit=commit,
        **fields,
    )


def sync_form4_symbol(
    db: Session,
    *,
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    max_filings: int = 50,
) -> dict[str, Any]:
    configured_max = max(int(settings.us_sec_form4_max_filings_per_symbol), 1)
    if max_filings < 1 or max_filings > min(configured_max, 500):
        raise ValueError(
            f"max_filings must be between 1 and {min(configured_max, 500)}."
        )
    if from_date and to_date and from_date > to_date:
        raise ValueError("from_date cannot be after to_date.")

    stock = _stock(db, symbol)
    normalized = stock.symbol
    cik = f"{int(str(stock.cik).strip()):010d}"
    submissions_url: str | None = None
    try:
        submissions, submissions_url = sec_provider.fetch_sec_submissions_payload(
            cik=cik,
            sec_user_agent=_sec_user_agent(),
            timeout_seconds=max(int(settings.us_market_http_timeout_seconds), 1),
        )
        entries = parse_form4_submission_entries(
            submissions,
            from_date=from_date,
            to_date=to_date,
            limit=max_filings,
        )
        existing_accessions = {
            value
            for (value,) in db.query(USSecOwnershipFiling.accession_number)
            .filter(USSecOwnershipFiling.issuer_cik == cik)
            .filter(
                USSecOwnershipFiling.accession_number.in_(
                    [entry.accession_number for entry in entries] or ["<none>"]
                )
            )
            .all()
        }

        parsed_filings = []
        errors: list[str] = []
        request_count = 1
        for entry in entries:
            if entry.accession_number in existing_accessions:
                continue
            try:
                xml, source_url = sec_provider.fetch_sec_ownership_xml(
                    issuer_cik=cik,
                    accession_number=entry.accession_number,
                    primary_document=entry.primary_document,
                    sec_user_agent=_sec_user_agent(),
                    timeout_seconds=max(int(settings.us_market_http_timeout_seconds), 1),
                )
                request_count += 1
                if len(xml) > min(int(settings.us_sec_ownership_max_archive_bytes), 10 * 1024 * 1024):
                    raise ValueError("SEC ownership XML exceeded the configured document size bound.")
                filing = parse_form4_xml(
                    xml,
                    accession_number=entry.accession_number,
                    filing_date=entry.filing_date,
                    accepted_at=entry.accepted_at,
                    source_url=source_url,
                )
                if filing.issuer_cik != cik:
                    raise ValueError(
                        f"SEC ownership issuer CIK mismatch for accession {entry.accession_number}."
                    )
                parsed_filings.append(filing)
            except Exception as exc:
                errors.append(f"{entry.accession_number}: {exc}")

        inserted_count = 0
        transaction_count = 0
        position_count = 0
        for filing in parsed_filings:
            result = persist_form4_filing(db, filing)
            inserted_count += int(bool(result["inserted"]))
            transaction_count += int(result["transaction_count"])
            position_count += int(result["position_count"])

        latest = entries[0] if entries else None
        status = "partial" if errors else "current" if entries else "ready_empty"
        update_form4_sync_state(
            db,
            symbol=normalized,
            issuer_cik=cik,
            status=status,
            latest_accession_number=latest.accession_number if latest else None,
            latest_filing_date=latest.filing_date if latest else None,
            fetched_count=len(parsed_filings),
            errors=errors,
            source_url=submissions_url,
        )
        detail = {
            "status": status,
            "submission_count": len(entries),
            "already_local_count": len(existing_accessions),
            "fetched_count": len(parsed_filings),
            "inserted_count": inserted_count,
            "transaction_count": transaction_count,
            "position_count": position_count,
            "error_count": len(errors),
            "request_count": request_count,
            "request_limit": max_filings + 1,
        }
        _record_sync_event(
            db,
            symbol=normalized,
            status="partial" if errors else "success",
            source_url=submissions_url,
            message="SEC Form 4 sync completed with warnings." if errors else "SEC Form 4 sync completed.",
            detail=detail,
        )
        db.commit()
        return {
            **detail,
            "symbol": normalized,
            "cik": cik,
            "latest_accession_number": latest.accession_number if latest else None,
            "latest_filing_date": latest.filing_date.isoformat() if latest else None,
            "errors": errors,
        }
    except (USStockNotFoundError, USMarketConfigurationError, ValueError):
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        try:
            _record_sync_event(
                db,
                symbol=normalized,
                status="error",
                source_url=submissions_url,
                message="SEC Form 4 sync failed.",
                detail={"max_filings": max_filings},
                error=exc,
                commit=True,
            )
        except Exception:
            db.rollback()
        if isinstance(exc, USMarketDataFetchError):
            raise
        raise USMarketDataFetchError(str(exc)) from exc


def sync_form4_scope(
    db: Session,
    *,
    scope: str,
    symbol: str | None = None,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
    max_symbols: int = 25,
    max_filings_per_symbol: int = 50,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_scope = scope.strip().lower()
    if normalized_scope == "symbol":
        if not symbol:
            raise ValueError("symbol is required when scope='symbol'.")
        symbols = [normalize_us_symbol(symbol)]
    elif normalized_scope == "watchlist":
        symbols = list_us_watchlist_symbols(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
        )
    else:
        raise ValueError("scope must be 'symbol' or 'watchlist'.")
    if max_symbols < 1 or max_symbols > 100:
        raise ValueError("max_symbols must be between 1 and 100.")
    symbols = symbols[:max_symbols]

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total = max(len(symbols), 1)
    for index, target in enumerate(symbols, start=1):
        if progress_callback:
            progress_callback(index - 1, total, f"Refreshing SEC Form 4 for {target}.")
        try:
            results.append(
                sync_form4_symbol(
                    db,
                    symbol=target,
                    from_date=from_date,
                    to_date=to_date,
                    max_filings=max_filings_per_symbol,
                )
            )
        except Exception as exc:
            failures.append({"symbol": target, "error": str(exc)})
        if progress_callback:
            progress_callback(index, total, f"Processed SEC Form 4 for {target}.")

    status = "success" if not failures else "failed" if not results else "partial"
    return {
        "status": status,
        "scope": normalized_scope,
        "symbol_count": len(symbols),
        "success_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "failures": failures,
    }


def read_insider_transactions(
    db: Session,
    *,
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    codes: tuple[str, ...] = (),
    include_derivatives: bool = True,
    limit: int = 100,
    cursor: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _stock(db, symbol)
    return get_insider_transactions_contract(
        db,
        symbol=normalize_us_symbol(symbol),
        from_date=from_date,
        to_date=to_date,
        codes=codes,
        include_derivatives=include_derivatives,
        limit=limit,
        cursor=cursor,
        observation_hours=max(int(settings.us_sec_ownership_observation_hours), 1),
        now=now or datetime.now(timezone.utc),
    )


__all__ = [
    "read_insider_transactions",
    "sync_form4_scope",
    "sync_form4_symbol",
]
