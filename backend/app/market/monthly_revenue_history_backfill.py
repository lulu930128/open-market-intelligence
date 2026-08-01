from __future__ import annotations

import hashlib
import time
from datetime import date
from html.parser import HTMLParser

import requests
from sqlalchemy.orm import Session

from app.db.models import MonthlyRevenue, RawFetchResult, SourceRegistry, StockMaster
from app.http_client import new_session
from app.market.taiwan_rules import expected_monthly_revenue_period
from app.parsers.twse_common import parse_float, parse_int


MOPS_REVENUE_HISTORY_BASE_URL = "https://mopsov.twse.com.tw/nas/t21"
MOPS_REVENUE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MARKET_PATHS = {
    "TWSE": "sii",
    "TPEX": "otc",
}
MAX_CACHED_PERIOD_ROWS = 5_000
STOCK_LOOKUP_BATCH_SIZE = 500


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "tr":
            self._in_row = True
            self._current_row = []
            return

        if self._in_row and normalized_tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if self._in_row and normalized_tag in {"td", "th"}:
            self._in_cell = False
            cell_text = " ".join("".join(self._current_cell).replace("\xa0", " ").split())
            self._current_row.append(cell_text)
            self._current_cell = []
            return

        if normalized_tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
            self._in_row = False
            self._in_cell = False
            self._current_row = []
            self._current_cell = []


def _month_floor(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _month_span(start_period: date, end_period: date) -> int:
    return (end_period.year - start_period.year) * 12 + end_period.month - start_period.month + 1


def _normalize_market(market: str | None) -> str:
    normalized = (market or "").upper()
    if normalized in {"TWSE", "TSE", "上市"}:
        return "TWSE"
    if normalized in {"TPEX", "OTC", "上櫃"}:
        return "TPEX"
    raise ValueError(f"Unsupported stock market for monthly revenue history: {market or '-'}")


def _get_stock(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is None:
        raise ValueError(f"Stock '{stock_id}' is not configured in stock_master.")
    return stock


def _get_monthly_revenue_source(db: Session, market: str) -> SourceRegistry:
    sources = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category == "monthly_revenue")
        .filter(SourceRegistry.parser_type == "monthly_revenue")
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )
    market_token = "TPEX" if market == "TPEX" else "TWSE"

    for source in sources:
        if market_token in source.source_name.upper():
            return source

    raise ValueError(f"{market_token} monthly revenue source is not configured.")


def _target_months(
    db: Session,
    stock_id: str,
    from_period: date | None,
    to_period: date | None,
    lookback_months: int,
) -> list[date]:
    del db, stock_id
    end_period = (
        _month_floor(to_period)
        if to_period is not None
        else expected_monthly_revenue_period()
    )
    if from_period is not None:
        start_period = _month_floor(from_period)
        month_count = min(_month_span(start_period, end_period), lookback_months)
        start_period = _add_months(end_period, -(month_count - 1))
    else:
        start_period = _add_months(end_period, -(lookback_months - 1))

    if end_period < start_period:
        return []

    months = []
    current = end_period
    while current >= start_period:
        months.append(current)
        current = _add_months(current, -1)
    return months


def _history_url(market: str, period: date, company_type: int = 0) -> str:
    if company_type not in {0, 1}:
        raise ValueError("MOPS monthly-revenue company_type must be 0 or 1.")
    roc_year = period.year - 1911
    market_path = MARKET_PATHS[market]
    return (
        f"{MOPS_REVENUE_HISTORY_BASE_URL}/{market_path}/"
        f"t21sc03_{roc_year}_{period.month}_{company_type}.html"
    )


def _get_cached_raw_result(
    db: Session,
    source_id: int,
    url: str,
) -> RawFetchResult | None:
    return (
        db.query(RawFetchResult)
        .filter(RawFetchResult.source_id == source_id)
        .filter(RawFetchResult.url == url)
        .filter(RawFetchResult.status_code == 200)
        .filter(RawFetchResult.raw_text.is_not(None))
        .order_by(RawFetchResult.id.desc())
        .first()
    )


def _fetch_month_html(session: requests.Session, url: str) -> tuple[str, int, str | None]:
    response = session.get(url, headers=MOPS_REVENUE_HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "big5"
    return response.text, response.status_code, response.headers.get("content-type")


def _create_raw_result(
    db: Session,
    source_id: int,
    url: str,
    raw_text: str,
    status_code: int,
    content_type: str | None,
) -> RawFetchResult:
    raw_result = RawFetchResult(
        source_id=source_id,
        url=url,
        method="GET",
        status_code=status_code,
        content_type=(content_type or "text/html")[:120],
        content_hash=hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest(),
        raw_text=raw_text,
        parser_version="mops-monthly-revenue-history-v1",
    )
    db.add(raw_result)
    db.flush()
    return raw_result


def _stock_row_from_html(raw_text: str, stock_id: str) -> list[str] | None:
    parser = _TableRowParser()
    parser.feed(raw_text)

    for cells in parser.rows:
        if len(cells) >= 10 and cells[0].strip() == stock_id:
            return cells

    return None


def _stock_rows_from_html(raw_text: str) -> tuple[dict[str, list[str]], int, int]:
    parser = _TableRowParser()
    parser.feed(raw_text)

    rows_by_stock_id: dict[str, list[str]] = {}
    malformed_count = 0
    duplicate_count = 0
    for cells in parser.rows:
        if len(cells) < 10:
            malformed_count += 1
            continue
        stock_id = cells[0].strip()
        if not stock_id:
            malformed_count += 1
            continue
        if stock_id in rows_by_stock_id:
            duplicate_count += 1
            continue
        rows_by_stock_id[stock_id] = cells
    return rows_by_stock_id, malformed_count, duplicate_count


def _stocks_by_id(db: Session, stock_ids: set[str]) -> dict[str, StockMaster]:
    result: dict[str, StockMaster] = {}
    ordered_ids = sorted(stock_ids)
    for offset in range(0, len(ordered_ids), STOCK_LOOKUP_BATCH_SIZE):
        batch = ordered_ids[offset : offset + STOCK_LOOKUP_BATCH_SIZE]
        for stock in (
            db.query(StockMaster)
            .filter(StockMaster.stock_id.in_(batch))
            .all()
        ):
            result[stock.stock_id] = stock
    return result


def _monthly_revenue_payload(
    source_id: int,
    raw_result_id: int,
    period: date,
    stock_id: str,
    stock: StockMaster,
    market: str,
    cells: list[str],
) -> dict:
    return {
        "source_id": source_id,
        "raw_result_id": raw_result_id,
        "report_date": period,
        "period": period,
        "stock_id": stock_id,
        "stock_name": cells[1] or stock.stock_name,
        "market": market,
        "industry": stock.industry,
        "monthly_revenue": parse_int(cells[2]),
        "previous_month_revenue": parse_int(cells[3]),
        "previous_year_month_revenue": parse_int(cells[4]),
        "month_over_month_pct": parse_float(cells[5]),
        "year_over_year_pct": parse_float(cells[6]),
        "cumulative_revenue": parse_int(cells[7]),
        "previous_year_cumulative_revenue": parse_int(cells[8]),
        "cumulative_year_over_year_pct": parse_float(cells[9]),
        "note": cells[10] if len(cells) > 10 and cells[10] else None,
    }


def _upsert_monthly_revenue(db: Session, payload: dict) -> str:
    existing = (
        db.query(MonthlyRevenue)
        .filter(MonthlyRevenue.source_id == payload["source_id"])
        .filter(MonthlyRevenue.stock_id == payload["stock_id"])
        .filter(MonthlyRevenue.period == payload["period"])
        .first()
    )

    if existing is None:
        db.add(MonthlyRevenue(**payload))
        return "inserted"

    for key, value in payload.items():
        setattr(existing, key, value)
    return "updated"


def _monthly_revenue_payload_diff(
    existing: MonthlyRevenue,
    payload: dict,
) -> dict[str, dict[str, object]]:
    comparable_keys = (
        "report_date",
        "period",
        "stock_id",
        "stock_name",
        "market",
        "industry",
        "monthly_revenue",
        "previous_month_revenue",
        "previous_year_month_revenue",
        "month_over_month_pct",
        "year_over_year_pct",
        "cumulative_revenue",
        "previous_year_cumulative_revenue",
        "cumulative_year_over_year_pct",
        "note",
    )
    return {
        key: {
            "old": getattr(existing, key),
            "new": payload[key],
        }
        for key in comparable_keys
        if getattr(existing, key) != payload[key]
    }


def ensure_stock_monthly_revenue_history(
    db: Session,
    stock_id: str,
    from_period: date | None = None,
    to_period: date | None = None,
    lookback_months: int = 120,
    sleep_seconds: float = 0.05,
    skip_existing: bool = True,
) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = _normalize_market(stock.market)
    source = _get_monthly_revenue_source(db=db, market=market)
    months = _target_months(
        db=db,
        stock_id=stock_id,
        from_period=from_period,
        to_period=to_period,
        lookback_months=lookback_months,
    )

    session = new_session()
    results: list[dict] = []
    fetched_count = 0
    cached_count = 0
    skipped_existing_count = 0
    inserted_count = 0
    updated_count = 0
    error_count = 0

    for period in months:
        existing = (
            db.query(MonthlyRevenue.id)
            .filter(MonthlyRevenue.source_id == source.id)
            .filter(MonthlyRevenue.stock_id == stock_id)
            .filter(MonthlyRevenue.period == period)
            .first()
        )

        if skip_existing and existing is not None:
            skipped_existing_count += 1
            results.append(
                {
                    "period": period.isoformat(),
                    "status": "skipped_existing",
                    "raw_result_id": None,
                    "message": "Skipped because monthly revenue row already exists.",
                    "error_message": None,
                }
            )
            continue

        try:
            raw_result = None
            cells = None
            for company_type in (0, 1):
                url = _history_url(
                    market=market,
                    period=period,
                    company_type=company_type,
                )
                candidate_raw_result = _get_cached_raw_result(
                    db=db,
                    source_id=source.id,
                    url=url,
                )
                if candidate_raw_result is not None:
                    cached_count += 1
                else:
                    raw_text, status_code, content_type = _fetch_month_html(
                        session=session,
                        url=url,
                    )
                    fetched_count += 1
                    candidate_raw_result = _create_raw_result(
                        db=db,
                        source_id=source.id,
                        url=url,
                        raw_text=raw_text,
                        status_code=status_code,
                        content_type=content_type,
                    )

                candidate_cells = _stock_row_from_html(
                    candidate_raw_result.raw_text or "",
                    stock_id=stock_id,
                )
                if candidate_cells is not None:
                    raw_result = candidate_raw_result
                    cells = candidate_cells
                    break

            if cells is None:
                db.commit()
                results.append(
                    {
                        "period": period.isoformat(),
                        "status": "no_data",
                        "raw_result_id": raw_result.id if raw_result is not None else None,
                        "message": "Stock row was not found in MOPS monthly revenue page.",
                        "error_message": None,
                    }
                )
                continue

            payload = _monthly_revenue_payload(
                source_id=source.id,
                raw_result_id=raw_result.id,
                period=period,
                stock_id=stock_id,
                stock=stock,
                market=market,
                cells=cells,
            )
            mutation = _upsert_monthly_revenue(db=db, payload=payload)
            db.commit()

            if mutation == "inserted":
                inserted_count += 1
            else:
                updated_count += 1

            results.append(
                {
                    "period": period.isoformat(),
                    "status": mutation,
                    "raw_result_id": raw_result.id,
                    "message": "MOPS monthly revenue row saved.",
                    "error_message": None,
                }
            )
        except Exception as exc:
            db.rollback()
            error_count += 1
            results.append(
                {
                    "period": period.isoformat(),
                    "status": "error",
                    "raw_result_id": None,
                    "message": "MOPS monthly revenue history backfill failed.",
                    "error_message": str(exc),
                }
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    status = "success"
    if error_count:
        status = "partial_success" if inserted_count or updated_count or skipped_existing_count else "error"

    return {
        "status": status,
        "stock_id": stock_id,
        "market": market,
        "source_id": source.id,
        "requested_period_count": len(months),
        "fetched_count": fetched_count,
        "cached_count": cached_count,
        "skipped_existing_count": skipped_existing_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "error_count": error_count,
        "results": results,
    }


def backfill_monthly_revenue_period_from_cached_raw(
    db: Session,
    *,
    period: date,
    markets: tuple[str, ...] = ("TWSE", "TPEX"),
    company_types: tuple[int, ...] = (0, 1),
    stock_ids: tuple[str, ...] = (),
    apply: bool = False,
    max_candidates: int = MAX_CACHED_PERIOD_ROWS,
    fetch_missing: bool = False,
    refresh_documents: bool = False,
    max_fetches: int = 4,
) -> dict:
    """Fill one monthly-revenue period from already persisted MOPS HTML.

    This maintenance path is intentionally cache-only. It parses each market
    document once, inserts only missing rows, and leaves commit/rollback
    ownership with the caller.
    """

    target_period = _month_floor(period)
    if max_candidates < 1 or max_candidates > MAX_CACHED_PERIOD_ROWS:
        raise ValueError(
            f"max_candidates must be between 1 and {MAX_CACHED_PERIOD_ROWS}."
        )

    normalized_markets = tuple(
        dict.fromkeys(_normalize_market(market) for market in markets)
    )
    normalized_company_types = tuple(dict.fromkeys(int(value) for value in company_types))
    if not normalized_company_types or any(
        value not in {0, 1} for value in normalized_company_types
    ):
        raise ValueError("company_types must contain only 0 and/or 1.")
    if max_fetches < 0 or max_fetches > 4:
        raise ValueError("max_fetches must be between 0 and 4.")

    requested_stock_ids = {
        str(stock_id).strip()
        for stock_id in stock_ids
        if str(stock_id).strip()
    }
    planned_inserts: list[dict] = []
    planned_updates: list[
        tuple[MonthlyRevenue, dict, dict[str, dict[str, object]]]
    ] = []
    market_results: list[dict] = []
    cache_missing_markets: list[str] = []
    cache_missing_documents: list[str] = []
    fetch_errors: list[dict] = []
    fetched_count = 0
    fetch_attempt_count = 0
    session = new_session()

    for market in normalized_markets:
        source = _get_monthly_revenue_source(db=db, market=market)
        rows_by_stock_id: dict[str, tuple[list[str], RawFetchResult]] = {}
        document_results: list[dict] = []
        malformed_count = 0
        duplicate_count = 0
        for company_type in normalized_company_types:
            url = _history_url(
                market=market,
                period=target_period,
                company_type=company_type,
            )
            document_key = f"{market}:{company_type}"
            raw_result = _get_cached_raw_result(
                db=db,
                source_id=source.id,
                url=url,
            )
            document_status = "cached"
            should_fetch = refresh_documents or (
                raw_result is None and fetch_missing
            )
            if should_fetch:
                if fetch_attempt_count >= max_fetches:
                    raise ValueError(
                        f"Missing-document fetch limit exceeded ({max_fetches})."
                    )
                fetch_attempt_count += 1
                try:
                    raw_text, status_code, content_type = _fetch_month_html(
                        session=session,
                        url=url,
                    )
                    fetched_count += 1
                    fetched_hash = hashlib.sha256(
                        raw_text.encode("utf-8", errors="ignore")
                    ).hexdigest()
                    if (
                        raw_result is not None
                        and raw_result.content_hash == fetched_hash
                    ):
                        document_status = "unchanged"
                    elif apply:
                        raw_result = _create_raw_result(
                            db=db,
                            source_id=source.id,
                            url=url,
                            raw_text=raw_text,
                            status_code=status_code,
                            content_type=content_type,
                        )
                        document_status = (
                            "refreshed" if refresh_documents else "fetched"
                        )
                    else:
                        raw_result = RawFetchResult(
                            source_id=source.id,
                            url=url,
                            method="GET",
                            status_code=status_code,
                            content_type=(content_type or "text/html")[:120],
                            content_hash=fetched_hash,
                            raw_text=raw_text,
                            parser_version="mops-monthly-revenue-history-v1",
                        )
                        document_status = (
                            "refresh_dry_run"
                            if refresh_documents
                            else "fetch_dry_run"
                        )
                except Exception as exc:
                    fetch_errors.append(
                        {
                            "document": document_key,
                            "source_url": url,
                            "error_message": str(exc),
                        }
                    )
                    document_status = (
                        "refresh_error_cached"
                        if raw_result is not None
                        else "fetch_error"
                    )

            if raw_result is None:
                cache_missing_documents.append(document_key)
                document_results.append(
                    {
                        "company_type": company_type,
                        "status": document_status
                        if document_status == "fetch_error"
                        else "cache_missing",
                        "raw_result_id": None,
                        "source_url": url,
                        "parsed_stock_count": 0,
                    }
                )
                continue

            document_rows, document_malformed, document_duplicates = (
                _stock_rows_from_html(raw_result.raw_text or "")
            )
            malformed_count += document_malformed
            duplicate_count += document_duplicates
            for stock_id, cells in document_rows.items():
                if requested_stock_ids and stock_id not in requested_stock_ids:
                    continue
                if stock_id in rows_by_stock_id:
                    duplicate_count += 1
                    continue
                rows_by_stock_id[stock_id] = (cells, raw_result)
            document_results.append(
                {
                    "company_type": company_type,
                    "status": document_status,
                        "raw_result_id": raw_result.id,
                    "source_url": url,
                    "parsed_stock_count": len(document_rows),
                }
            )

        if not rows_by_stock_id:
            cache_missing_markets.append(market)
            market_results.append(
                {
                    "market": market,
                    "status": "cache_missing",
                    "source_id": source.id,
                    "documents": document_results,
                    "raw_result_ids": [],
                    "parsed_stock_count": 0,
                    "existing_count": 0,
                    "candidate_count": 0,
                    "unconfigured_stock_count": 0,
                    "market_mismatch_count": 0,
                    "malformed_row_count": 0,
                    "duplicate_source_row_count": 0,
                }
            )
            continue

        stocks_by_id = _stocks_by_id(db=db, stock_ids=set(rows_by_stock_id))
        existing_rows_by_stock_id = {
            row.stock_id: row
            for row in (
                db.query(MonthlyRevenue)
                .filter(MonthlyRevenue.source_id == source.id)
                .filter(MonthlyRevenue.period == target_period)
                .all()
            )
        }
        candidate_count = 0
        insert_candidate_count = 0
        update_candidate_count = 0
        insert_stock_ids: list[str] = []
        update_samples: list[dict] = []
        unconfigured_stock_count = 0
        market_mismatch_count = 0
        for stock_id, (cells, raw_result) in sorted(rows_by_stock_id.items()):
            stock = stocks_by_id.get(stock_id)
            if stock is None:
                unconfigured_stock_count += 1
                continue
            stock_market = _normalize_market(stock.market)
            if stock_market != market:
                market_mismatch_count += 1
            payload = _monthly_revenue_payload(
                source_id=source.id,
                raw_result_id=raw_result.id,
                period=target_period,
                stock_id=stock_id,
                stock=stock,
                market=stock_market,
                cells=cells,
            )
            existing = existing_rows_by_stock_id.get(stock_id)
            if existing is None:
                planned_inserts.append(payload)
                candidate_count += 1
                insert_candidate_count += 1
                if len(insert_stock_ids) < 50:
                    insert_stock_ids.append(stock_id)
            elif refresh_documents:
                changed_fields = _monthly_revenue_payload_diff(existing, payload)
                if changed_fields:
                    planned_updates.append((existing, payload, changed_fields))
                    candidate_count += 1
                    update_candidate_count += 1
                    if len(update_samples) < 50:
                        update_samples.append(
                            {
                                "stock_id": stock_id,
                                "changed_fields": changed_fields,
                            }
                        )

        market_results.append(
            {
                "market": market,
                "status": "ready",
                "source_id": source.id,
                "documents": document_results,
                "raw_result_ids": sorted(
                    {
                        raw_result.id
                        for _, raw_result in rows_by_stock_id.values()
                        if raw_result.id is not None
                    }
                ),
                "parsed_stock_count": len(rows_by_stock_id),
                "existing_count": len(existing_rows_by_stock_id),
                "candidate_count": candidate_count,
                "insert_candidate_count": insert_candidate_count,
                "update_candidate_count": update_candidate_count,
                "insert_stock_ids": insert_stock_ids,
                "update_samples": update_samples,
                "unconfigured_stock_count": unconfigured_stock_count,
                "market_mismatch_count": market_mismatch_count,
                "malformed_row_count": malformed_count,
                "duplicate_source_row_count": duplicate_count,
            }
        )

    total_candidates = len(planned_inserts) + len(planned_updates)
    if total_candidates > max_candidates:
        raise ValueError(
            "Cached monthly-revenue candidate count "
            f"{total_candidates} exceeds max_candidates={max_candidates}."
        )

    if apply and planned_inserts:
        db.add_all(MonthlyRevenue(**payload) for payload in planned_inserts)
    if apply and planned_updates:
        for existing, payload, _ in planned_updates:
            for key, value in payload.items():
                setattr(existing, key, value)
    if apply and (planned_inserts or planned_updates):
        db.flush()

    if cache_missing_markets or cache_missing_documents or fetch_errors:
        status = (
            "blocked"
            if len(cache_missing_markets) == len(normalized_markets)
            else "partial"
        )
    else:
        status = "applied" if apply else "dry_run_ready"

    return {
        "status": status,
        "mode": "apply" if apply else "dry_run",
        "cache_only": not fetch_missing and not refresh_documents,
        "refresh_documents": refresh_documents,
        "period": target_period.isoformat(),
        "markets": list(normalized_markets),
        "company_types": list(normalized_company_types),
        "requested_stock_ids": sorted(requested_stock_ids),
        "market_results": market_results,
        "cache_missing_markets": cache_missing_markets,
        "cache_missing_documents": cache_missing_documents,
        "fetch_errors": fetch_errors,
        "fetch_attempt_count": fetch_attempt_count,
        "fetched_count": fetched_count,
        "candidate_count": total_candidates,
        "insert_candidate_count": len(planned_inserts),
        "update_candidate_count": len(planned_updates),
        "inserted_count": len(planned_inserts) if apply else 0,
        "updated_count": len(planned_updates) if apply else 0,
        "max_candidates": max_candidates,
    }


__all__ = [
    "MAX_CACHED_PERIOD_ROWS",
    "backfill_monthly_revenue_period_from_cached_raw",
    "ensure_stock_monthly_revenue_history",
]
