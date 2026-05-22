from __future__ import annotations

import hashlib
import time
from datetime import date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MonthlyRevenue, RawFetchResult, SourceRegistry, StockMaster
from app.parsers.twse_common import parse_float, parse_int


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
MOPS_REVENUE_HISTORY_BASE_URL = "https://mopsov.twse.com.tw/nas/t21"
MOPS_REVENUE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MARKET_PATHS = {
    "TWSE": "sii",
    "TPEX": "otc",
}


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


def _previous_month(value: date) -> date:
    return _add_months(_month_floor(value), -1)


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


def _latest_known_period(db: Session, stock_id: str) -> date:
    latest = (
        db.query(func.max(MonthlyRevenue.period))
        .filter(MonthlyRevenue.stock_id == stock_id)
        .scalar()
    )
    if latest is not None:
        return _month_floor(latest)

    return _previous_month(datetime.now(TAIWAN_TZ).date())


def _target_months(
    db: Session,
    stock_id: str,
    from_period: date | None,
    to_period: date | None,
    lookback_months: int,
) -> list[date]:
    end_period = _month_floor(to_period) if to_period is not None else _latest_known_period(db, stock_id)
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


def _history_url(market: str, period: date) -> str:
    roc_year = period.year - 1911
    market_path = MARKET_PATHS[market]
    return (
        f"{MOPS_REVENUE_HISTORY_BASE_URL}/{market_path}/"
        f"t21sc03_{roc_year}_{period.month}_0.html"
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

    session = requests.Session()
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

        url = _history_url(market=market, period=period)

        try:
            raw_result = _get_cached_raw_result(db=db, source_id=source.id, url=url)
            if raw_result is not None:
                cached_count += 1
            else:
                raw_text, status_code, content_type = _fetch_month_html(session=session, url=url)
                fetched_count += 1
                raw_result = _create_raw_result(
                    db=db,
                    source_id=source.id,
                    url=url,
                    raw_text=raw_text,
                    status_code=status_code,
                    content_type=content_type,
                )

            cells = _stock_row_from_html(raw_result.raw_text or "", stock_id=stock_id)
            if cells is None:
                db.commit()
                results.append(
                    {
                        "period": period.isoformat(),
                        "status": "no_data",
                        "raw_result_id": raw_result.id,
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


__all__ = ["ensure_stock_monthly_revenue_history"]
