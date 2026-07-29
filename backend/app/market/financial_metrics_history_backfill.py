from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import FinancialMetricQuarterly, RawFetchResult, SourceRegistry, StockMaster
from app.http_client import new_session
from app.market.taiwan_rules import expected_financial_metrics_period
from app.parsers.twse_common import parse_float


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
MOPS_FINANCIAL_BASE_URL = "https://mopsov.twse.com.tw/mops/web"
MOPS_FINANCIAL_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
MARKET_TYPEK = {
    "TWSE": "sii",
    "TPEX": "otc",
}
COMPANY_CODE_HEADER = "公司代號"


class _FinancialTableParser(HTMLParser):
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
            return

        if self._in_cell and normalized_tag == "br":
            self._current_cell.append(" ")

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


def _normalize_key(value: str | None) -> str:
    return "".join((value or "").split())


def _normalize_market(market: str | None) -> str:
    normalized = (market or "").upper()
    if normalized in {"TWSE", "TSE", "上市"}:
        return "TWSE"
    if normalized in {"TPEX", "OTC", "上櫃"}:
        return "TPEX"
    raise ValueError(f"Unsupported stock market for financial metrics history: {market or '-'}")


def _get_stock(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is None:
        raise ValueError(f"Stock '{stock_id}' is not configured in stock_master.")
    return stock


def _get_financial_source(db: Session, market: str) -> SourceRegistry:
    sources = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category == "financial_metrics")
        .filter(SourceRegistry.parser_type == "financial_metrics")
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )
    market_token = "TPEX" if market == "TPEX" else "TWSE"

    for source in sources:
        if market_token in source.source_name.upper():
            return source

    raise ValueError(f"{market_token} financial metrics source is not configured.")


def _previous_quarter(fiscal_year: int, quarter: int) -> tuple[int, int]:
    if quarter > 1:
        return fiscal_year, quarter - 1
    return fiscal_year - 1, 4


def _quarter_sequence(
    end_fiscal_year: int,
    end_quarter: int,
    lookback_quarters: int,
) -> list[tuple[int, int]]:
    quarters: list[tuple[int, int]] = []
    fiscal_year = end_fiscal_year
    quarter = end_quarter

    for _ in range(lookback_quarters):
        quarters.append((fiscal_year, quarter))
        fiscal_year, quarter = _previous_quarter(fiscal_year, quarter)

    return quarters


def _latest_reportable_quarter(today: date | None = None) -> tuple[int, int]:
    current = today or datetime.now(TAIWAN_TZ).date()
    period = expected_financial_metrics_period(
        now=datetime.combine(current, datetime.min.time(), tzinfo=TAIWAN_TZ)
    )
    return int(period[:4]), int(period[-1])


def _latest_known_quarter(db: Session, stock_id: str) -> tuple[int, int]:
    reportable = _latest_reportable_quarter()
    latest = (
        db.query(FinancialMetricQuarterly.fiscal_year, FinancialMetricQuarterly.quarter)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )

    if latest is not None:
        local = (latest.fiscal_year, latest.quarter)
        if local[0] * 10 + local[1] >= reportable[0] * 10 + reportable[1]:
            return local

    return reportable


def _target_quarters(
    db: Session,
    stock_id: str,
    from_fiscal_year: int | None,
    from_quarter: int | None,
    to_fiscal_year: int | None,
    to_quarter: int | None,
    lookback_quarters: int,
) -> list[tuple[int, int]]:
    end_year, end_quarter = (
        (to_fiscal_year, to_quarter)
        if to_fiscal_year is not None and to_quarter is not None
        else _latest_known_quarter(db=db, stock_id=stock_id)
    )
    quarters = _quarter_sequence(end_year, end_quarter, lookback_quarters)

    if from_fiscal_year is None or from_quarter is None:
        return quarters

    min_key = from_fiscal_year * 10 + from_quarter
    return [(year, quarter) for year, quarter in quarters if year * 10 + quarter >= min_key]


def _endpoint_url(statement: str) -> str:
    return f"{MOPS_FINANCIAL_BASE_URL}/ajax_t163sb{statement}"


def _fetch_statement_html(
    session: requests.Session,
    statement: str,
    market: str,
    fiscal_year: int,
    quarter: int,
) -> tuple[str, int, str | None, str]:
    url = _endpoint_url(statement)
    roc_year = fiscal_year - 1911
    response = session.post(
        url,
        data={
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "off": "1",
            "TYPEK": MARKET_TYPEK[market],
            "year": str(roc_year),
            "season": str(quarter),
        },
        headers={**MOPS_FINANCIAL_HEADERS, "Referer": f"{MOPS_FINANCIAL_BASE_URL}/t163sb{statement}"},
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text, response.status_code, response.headers.get("content-type"), url


def _bundle_cache_url(market: str, fiscal_year: int, quarter: int) -> str:
    return (
        f"{MOPS_FINANCIAL_BASE_URL}/ajax_t163sb04|ajax_t163sb05"
        f"?TYPEK={MARKET_TYPEK[market]}&year={fiscal_year - 1911}&season={quarter}"
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
        method="POST",
        status_code=status_code,
        content_type=(content_type or "text/html")[:120],
        content_hash=hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest(),
        raw_text=raw_text,
        parser_version="mops-financial-metrics-history-v1",
    )
    db.add(raw_result)
    db.flush()
    return raw_result


def _row_map_from_html(raw_text: str, stock_id: str) -> dict[str, str] | None:
    parser = _FinancialTableParser()
    parser.feed(raw_text)
    current_header: list[str] | None = None

    for row in parser.rows:
        if len(row) > 2 and _normalize_key(row[0]) == COMPANY_CODE_HEADER:
            current_header = row
            continue

        if row and row[0].strip() == stock_id and current_header is not None:
            return {
                _normalize_key(header): value
                for header, value in zip(current_header, row)
            }

    return None


def _safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def _first_float(row: dict[str, str] | None, keys: list[str]) -> float | None:
    if row is None:
        return None

    for key in keys:
        value = parse_float(row.get(_normalize_key(key)))
        if value is not None:
            return value
    return None


def _financial_payload(
    source_id: int,
    raw_result_id: int,
    fiscal_year: int,
    quarter: int,
    stock_id: str,
    stock: StockMaster,
    market: str,
    income: dict[str, str],
    balance: dict[str, str] | None,
) -> dict:
    net_income = _first_float(
        income,
        ["本期淨利（淨損）", "繼續營業單位本期淨利（淨損）"],
    )
    parent_net_income = _first_float(
        income,
        ["淨利（淨損）歸屬於母公司業主", "淨利(淨損)歸屬於母公司業主"],
    )
    total_assets = _first_float(balance, ["資產總計", "資產總額"])
    total_equity = _first_float(balance, ["權益總計", "權益總額"])
    parent_equity = _first_float(balance, ["歸屬於母公司業主之權益合計"])

    return {
        "source_id": source_id,
        "raw_result_id": raw_result_id,
        # The historical statement endpoint does not declare a publication or filing date.
        # Fetch time remains on RawFetchResult.fetched_at and must not be projected as report_date.
        "report_date": None,
        "released_at": None,
        "filed_at": None,
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "period": f"{fiscal_year}Q{quarter}",
        "stock_id": stock_id,
        "stock_name": income.get("公司名稱") or stock.stock_name,
        "market": market,
        "revenue": _first_float(income, ["營業收入", "收益"]),
        "gross_profit": _first_float(
            income,
            ["營業毛利（毛損）淨額", "營業毛利（毛損）"],
        ),
        "operating_income": _first_float(income, ["營業利益（損失）", "營業利益"]),
        "net_income": net_income,
        "net_income_attributable_parent": parent_net_income,
        "eps": _first_float(income, ["基本每股盈餘（元）"]),
        "total_assets": total_assets,
        "total_equity": total_equity,
        "parent_equity": parent_equity,
        "book_value_per_share": _first_float(balance, ["每股參考淨值"]),
        "roe": _safe_pct(parent_net_income or net_income, parent_equity or total_equity),
        "roa": _safe_pct(parent_net_income or net_income, total_assets),
    }


def _upsert_financial_metric(db: Session, payload: dict) -> str:
    existing = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.source_id == payload["source_id"])
        .filter(FinancialMetricQuarterly.stock_id == payload["stock_id"])
        .filter(FinancialMetricQuarterly.fiscal_year == payload["fiscal_year"])
        .filter(FinancialMetricQuarterly.quarter == payload["quarter"])
        .first()
    )

    if existing is None:
        db.add(FinancialMetricQuarterly(**payload))
        return "inserted"

    for key, value in payload.items():
        setattr(existing, key, value)
    return "updated"


def ensure_stock_financial_metrics_history(
    db: Session,
    stock_id: str,
    from_fiscal_year: int | None = None,
    from_quarter: int | None = None,
    to_fiscal_year: int | None = None,
    to_quarter: int | None = None,
    lookback_quarters: int = 40,
    sleep_seconds: float = 0.05,
    skip_existing: bool = True,
) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = _normalize_market(stock.market)
    source = _get_financial_source(db=db, market=market)
    quarters = _target_quarters(
        db=db,
        stock_id=stock_id,
        from_fiscal_year=from_fiscal_year,
        from_quarter=from_quarter,
        to_fiscal_year=to_fiscal_year,
        to_quarter=to_quarter,
        lookback_quarters=lookback_quarters,
    )

    session = new_session()
    results: list[dict] = []
    fetched_count = 0
    cached_count = 0
    skipped_existing_count = 0
    inserted_count = 0
    updated_count = 0
    error_count = 0

    for fiscal_year, quarter in quarters:
        existing = (
            db.query(FinancialMetricQuarterly.id)
            .filter(FinancialMetricQuarterly.source_id == source.id)
            .filter(FinancialMetricQuarterly.stock_id == stock_id)
            .filter(FinancialMetricQuarterly.fiscal_year == fiscal_year)
            .filter(FinancialMetricQuarterly.quarter == quarter)
            .first()
        )

        if skip_existing and existing is not None:
            skipped_existing_count += 1
            results.append(
                {
                    "period": f"{fiscal_year}Q{quarter}",
                    "status": "skipped_existing",
                    "raw_result_id": None,
                    "message": "Skipped because financial metric row already exists.",
                    "error_message": None,
                }
            )
            continue

        cache_url = _bundle_cache_url(market=market, fiscal_year=fiscal_year, quarter=quarter)

        try:
            raw_result = _get_cached_raw_result(db=db, source_id=source.id, url=cache_url)
            if raw_result is not None:
                cached_count += 1
                bundle = json.loads(raw_result.raw_text or "{}")
            else:
                income_text, income_status, income_content_type, income_url = _fetch_statement_html(
                    session=session,
                    statement="04",
                    market=market,
                    fiscal_year=fiscal_year,
                    quarter=quarter,
                )
                balance_text, balance_status, balance_content_type, balance_url = _fetch_statement_html(
                    session=session,
                    statement="05",
                    market=market,
                    fiscal_year=fiscal_year,
                    quarter=quarter,
                )
                fetched_count += 1
                bundle = {
                    "income": {"url": income_url, "raw_text": income_text},
                    "balance": {"url": balance_url, "raw_text": balance_text},
                }
                raw_result = _create_raw_result(
                    db=db,
                    source_id=source.id,
                    url=cache_url,
                    raw_text=json.dumps(bundle, ensure_ascii=False),
                    status_code=max(income_status, balance_status),
                    content_type=income_content_type or balance_content_type,
                )

            income_row = _row_map_from_html(
                raw_text=bundle.get("income", {}).get("raw_text") or "",
                stock_id=stock_id,
            )
            balance_row = _row_map_from_html(
                raw_text=bundle.get("balance", {}).get("raw_text") or "",
                stock_id=stock_id,
            )

            if income_row is None:
                db.commit()
                results.append(
                    {
                        "period": f"{fiscal_year}Q{quarter}",
                        "status": "no_data",
                        "raw_result_id": raw_result.id,
                        "message": "Stock row was not found in MOPS income statement page.",
                        "error_message": None,
                    }
                )
                continue

            payload = _financial_payload(
                source_id=source.id,
                raw_result_id=raw_result.id,
                fiscal_year=fiscal_year,
                quarter=quarter,
                stock_id=stock_id,
                stock=stock,
                market=market,
                income=income_row,
                balance=balance_row,
            )
            mutation = _upsert_financial_metric(db=db, payload=payload)
            db.commit()

            if mutation == "inserted":
                inserted_count += 1
            else:
                updated_count += 1

            results.append(
                {
                    "period": f"{fiscal_year}Q{quarter}",
                    "status": mutation,
                    "raw_result_id": raw_result.id,
                    "message": "MOPS financial metric row saved.",
                    "error_message": None,
                }
            )
        except Exception as exc:
            db.rollback()
            error_count += 1
            results.append(
                {
                    "period": f"{fiscal_year}Q{quarter}",
                    "status": "error",
                    "raw_result_id": None,
                    "message": "MOPS financial metrics history backfill failed.",
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
        "requested_period_count": len(quarters),
        "fetched_count": fetched_count,
        "cached_count": cached_count,
        "skipped_existing_count": skipped_existing_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "error_count": error_count,
        "results": results,
    }


__all__ = ["ensure_stock_financial_metrics_history"]
