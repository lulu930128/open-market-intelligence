from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup

from app.observability.provider_http import provider_http_failure

from ._http import DEFAULT_HEADERS, get, get_json, post


TWSE_PROVIDER = "twse_openapi"
TPEX_PROVIDER = "tpex_openapi"
MOPS_PROVIDER = "mops"
RESOURCE = "tw_corporate_events"

TWSE_EX_DIVIDEND_URL = (
    "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
)
TPEX_EX_DIVIDEND_URL = (
    "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"
)
TWSE_EX_DIVIDEND_HISTORY_URL = (
    "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
)
TPEX_EX_DIVIDEND_HISTORY_URL = (
    "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
)
MOPS_REDIRECT_URL = "https://mops.twse.com.tw/mops/api/redirectToOld"
MOPS_CONFERENCE_URL = "https://mops.twse.com.tw/mops/#/web/t100sb02_1"
MOPS_RESULT_REFERER = "https://mops.twse.com.tw/mops/"

_DATE_TOKEN = re.compile(r"(?<!\d)(\d{3}/\d{1,2}/\d{1,2}|\d{4}/\d{1,2}/\d{1,2}|\d{7}|\d{8})(?!\d)")
_FINANCIAL_TOPIC = re.compile(r"財務報告|財報|財務暨營運報告|營運成果|業績")
_FINANCIAL_PUBLICATION = re.compile(
    r"(?:公布|發布).{0,18}(?:財務報告|財報|財務暨營運報告|營運成果|業績)"
    r"|(?:財務報告|財報|財務暨營運報告|營運成果|業績).{0,18}(?:公布|發布)"
)


@dataclass(frozen=True)
class MopsConferenceWindowFailure:
    provider: str
    market: str
    window: str
    stage: str
    status: str
    exception_type: str
    attempt_count: int
    retryable: bool
    message: str
    http_status_code: int | None = None
    rate_limited: bool = False
    retry_after_seconds: int | None = None

    def summary(self) -> str:
        return (
            f"{self.provider.upper()}/{self.market}/{self.window}/{self.stage}："
            f"{self.exception_type}（{self.status}），"
            f"嘗試 {self.attempt_count} 次後仍失敗：{self.message}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "market": self.market,
            "window": self.window,
            "stage": self.stage,
            "status": self.status,
            "exception_type": self.exception_type,
            "attempt_count": self.attempt_count,
            "retryable": self.retryable,
            "message": self.message,
            "http_status_code": self.http_status_code,
            "rate_limited": self.rate_limited,
            "retry_after_seconds": self.retry_after_seconds,
        }


class MopsConferenceStageError(RuntimeError):
    def __init__(self, message: str, *, stage: str, exception_type: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.exception_type = exception_type


@dataclass(frozen=True)
class MopsConferenceBatch:
    entries: list[dict[str, Any]]
    request_count: int
    errors: list[str]
    coverage_start: date
    coverage_end: date
    failures: list[MopsConferenceWindowFailure] = field(default_factory=list)
    successful_windows: list[str] = field(default_factory=list)
    recovered_windows: list[str] = field(default_factory=list)
    retry_count: int = 0


def _parse_market_date(value: Any) -> date | None:
    text = (
        str(value or "")
        .strip()
        .replace("年", "/")
        .replace("月", "/")
        .replace("日", "")
        .replace("-", "/")
    )
    try:
        if "/" in text:
            parts = [int(part) for part in text.split("/")]
            if len(parts) != 3:
                return None
            year, month, day = parts
            if year < 1911:
                year += 1911
            return date(year, month, day)
        if text.isdigit() and len(text) == 7:
            return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
        if text.isdigit() and len(text) == 8:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return None


def _parse_date_range(value: Any) -> tuple[date | None, date | None]:
    tokens = _DATE_TOKEN.findall(str(value or ""))
    parsed = [item for token in tokens if (item := _parse_market_date(token))]
    if not parsed:
        return None, None
    return parsed[0], parsed[-1]


def _decimal(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _event_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _ex_dividend_entry(
    *,
    provider: str,
    market: str,
    source_url: str,
    stock_id: Any,
    stock_name: Any,
    event_date: Any,
    event_label: Any,
    cash_dividend: Any,
    stock_dividend_ratio: Any,
    timing_status: str = "scheduled",
    source_name: str | None = None,
) -> dict[str, Any] | None:
    normalized_stock_id = str(stock_id or "").strip()
    normalized_date = _parse_market_date(event_date)
    if not normalized_stock_id or normalized_date is None:
        return None
    normalized_name = str(stock_name or "").strip() or None
    label = str(event_label or "").strip() or "除權息"
    cash_value = _decimal(cash_dividend)
    stock_ratio = _decimal(stock_dividend_ratio)
    return {
        "event_id": _event_id(provider, "ex_dividend", normalized_stock_id, normalized_date, label),
        "event_type": "ex_dividend",
        "timing_status": timing_status,
        "provider": provider,
        "market": market,
        "source_name": source_name
        or (
            "TWSE 上市股票除權除息預告表"
            if market == "TWSE"
            else "TPEx 上櫃股票除權除息預告表"
        ),
        "source_url": source_url,
        "stock_id": normalized_stock_id,
        "stock_name": normalized_name,
        "start_date": normalized_date,
        "end_date": normalized_date,
        "start_time": None,
        "title": label,
        "summary": None,
        "location": None,
        "cash_dividend": cash_value,
        "stock_dividend_ratio": stock_ratio,
        "financial_report_related": False,
        "related_event_id": None,
        "company_url": None,
        "video_url": None,
    }


def parse_twse_ex_dividends(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("TWSE ex-dividend API returned a non-list JSON payload.")
    entries: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        entry = _ex_dividend_entry(
            provider=TWSE_PROVIDER,
            market="TWSE",
            source_url=TWSE_EX_DIVIDEND_URL,
            stock_id=row.get("Code"),
            stock_name=row.get("Name"),
            event_date=row.get("Date"),
            event_label=row.get("Exdividend"),
            cash_dividend=row.get("CashDividend"),
            stock_dividend_ratio=row.get("StockDividendRatio"),
        )
        if entry is not None:
            entries.append(entry)
    if payload and not entries:
        raise ValueError("TWSE ex-dividend API returned no usable rows.")
    return entries


def parse_tpex_ex_dividends(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("TPEx ex-dividend API returned a non-list JSON payload.")
    entries: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        entry = _ex_dividend_entry(
            provider=TPEX_PROVIDER,
            market="TPEX",
            source_url=TPEX_EX_DIVIDEND_URL,
            stock_id=row.get("SecuritiesCompanyCode"),
            stock_name=row.get("CompanyName"),
            event_date=row.get("ExRrightsExDividendDate"),
            event_label=row.get("ExRrightsExDividend"),
            cash_dividend=row.get("CashDividend"),
            stock_dividend_ratio=row.get("StockDividendRatio"),
        )
        if entry is not None:
            entries.append(entry)
    if payload and not entries:
        raise ValueError("TPEx ex-dividend API returned no usable rows.")
    return entries


def _history_event_label(value: Any) -> str:
    label = str(value or "").strip()
    if not label:
        return "除權息"
    if label.startswith("除"):
        return label
    return f"除{label}"


def parse_twse_ex_dividend_history(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or str(payload.get("stat") or "").upper() != "OK":
        raise ValueError("TWSE historical ex-dividend API returned an invalid payload.")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("TWSE historical ex-dividend API returned no data array.")

    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        label = _history_event_label(row[6])
        entry = _ex_dividend_entry(
            provider=TWSE_PROVIDER,
            market="TWSE",
            source_url=TWSE_EX_DIVIDEND_HISTORY_URL,
            stock_id=row[1],
            stock_name=row[2],
            event_date=row[0],
            event_label=label,
            cash_dividend=row[5] if label == "除息" else None,
            stock_dividend_ratio=None,
            timing_status="actual",
            source_name="TWSE 除權除息計算結果表",
        )
        if entry is not None:
            entries.append(entry)
    if rows and not entries:
        raise ValueError("TWSE historical ex-dividend API returned no usable rows.")
    return entries


def parse_tpex_ex_dividend_history(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or str(payload.get("stat") or "").lower() != "ok":
        raise ValueError("TPEx historical ex-dividend API returned an invalid payload.")
    tables = payload.get("tables")
    rows = tables[0].get("data") if isinstance(tables, list) and tables else None
    if not isinstance(rows, list):
        raise ValueError("TPEx historical ex-dividend API returned no data array.")

    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 15:
            continue
        stock_ratio_per_thousand = _decimal(row[14])
        entry = _ex_dividend_entry(
            provider=TPEX_PROVIDER,
            market="TPEX",
            source_url=TPEX_EX_DIVIDEND_HISTORY_URL,
            stock_id=row[1],
            stock_name=row[2],
            event_date=row[0],
            event_label=_history_event_label(row[8]),
            cash_dividend=row[13],
            stock_dividend_ratio=(
                stock_ratio_per_thousand / 1000
                if stock_ratio_per_thousand is not None
                else None
            ),
            timing_status="actual",
            source_name="TPEx 除權除息計算結果表",
        )
        if entry is not None:
            entries.append(entry)
    if rows and not entries:
        raise ValueError("TPEx historical ex-dividend API returned no usable rows.")
    return entries


def _first_link(cell: Any) -> str | None:
    if cell is None:
        return None
    link = cell.find("a", href=True)
    if link is None:
        return None
    href = str(link.get("href") or "").strip()
    return href if href.startswith(("http://", "https://")) else None


def parse_mops_conferences(
    html: str,
    *,
    market: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "lxml")
    table = soup.select_one("table#myTable")
    if table is None:
        raise ValueError("MOPS investor-conference response did not contain #myTable.")

    entries: list[dict[str, Any]] = []
    for row in table.select("tr[data-type='body']"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 11:
            continue
        stock_id = cells[0].get_text(" ", strip=True)
        stock_name = cells[1].get_text(" ", strip=True) or None
        start_date, end_date = _parse_date_range(cells[2].get_text(" ", strip=True))
        if not stock_id or start_date is None or end_date is None:
            continue
        start_time = cells[3].get_text(" ", strip=True) or None
        location = cells[4].get_text(" ", strip=True) or None
        summary = cells[5].get_text(" ", strip=True) or None
        company_url = _first_link(cells[8]) if len(cells) > 8 else None
        video_url = _first_link(cells[9]) if len(cells) > 9 else None
        conference_id = _event_id(
            MOPS_PROVIDER,
            "investor_conference",
            stock_id,
            start_date,
            end_date,
            start_time,
            summary,
        )
        financial_related = bool(_FINANCIAL_TOPIC.search(summary or ""))
        entries.append(
            {
                "event_id": conference_id,
                "event_type": "investor_conference",
                "timing_status": "scheduled",
                "provider": MOPS_PROVIDER,
                "market": market,
                "source_name": "MOPS 法人說明會一覽表",
                "source_url": MOPS_CONFERENCE_URL,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "title": "法人說明會",
                "summary": summary,
                "location": location,
                "cash_dividend": None,
                "stock_dividend_ratio": None,
                "financial_report_related": financial_related,
                "related_event_id": None,
                "company_url": company_url,
                "video_url": video_url,
            }
        )
        if _FINANCIAL_PUBLICATION.search(summary or ""):
            entries.append(
                {
                    **entries[-1],
                    "event_id": _event_id(
                        MOPS_PROVIDER,
                        "financial_report",
                        stock_id,
                        start_date,
                        start_time,
                        summary,
                    ),
                    "event_type": "financial_report",
                    "title": "財務報告公布",
                    "related_event_id": conference_id,
                }
            )
    return entries


def fetch_twse_ex_dividends(*, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    payload = get_json(
        TWSE_EX_DIVIDEND_URL,
        provider=TWSE_PROVIDER,
        resource=RESOURCE,
        target="TWSE",
        timeout_seconds=timeout_seconds,
    )
    return parse_twse_ex_dividends(payload)


def fetch_tpex_ex_dividends(*, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    payload = get_json(
        TPEX_EX_DIVIDEND_URL,
        provider=TPEX_PROVIDER,
        resource=RESOURCE,
        target="TPEX",
        timeout_seconds=timeout_seconds,
    )
    return parse_tpex_ex_dividends(payload)


def fetch_twse_ex_dividend_history(
    *,
    date_from: date,
    date_to: date,
    timeout_seconds: int = 20,
) -> list[dict[str, Any]]:
    payload = get_json(
        TWSE_EX_DIVIDEND_HISTORY_URL,
        provider=TWSE_PROVIDER,
        resource=RESOURCE,
        target=f"TWSE:{date_from.isoformat()}:{date_to.isoformat()}",
        timeout_seconds=timeout_seconds,
        params={
            "startDate": date_from.strftime("%Y%m%d"),
            "endDate": date_to.strftime("%Y%m%d"),
            "response": "json",
        },
    )
    return parse_twse_ex_dividend_history(payload)


def fetch_tpex_ex_dividend_history(
    *,
    date_from: date,
    date_to: date,
    timeout_seconds: int = 20,
) -> list[dict[str, Any]]:
    response = post(
        TPEX_EX_DIVIDEND_HISTORY_URL,
        provider=TPEX_PROVIDER,
        resource=RESOURCE,
        target=f"TPEX:{date_from.isoformat()}:{date_to.isoformat()}",
        timeout_seconds=timeout_seconds,
        headers={
            **DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.tpex.org.tw/zh-tw/announce/market/ex/cal.html",
        },
        data={
            "startDate": date_from.strftime("%Y/%m/%d"),
            "endDate": date_to.strftime("%Y/%m/%d"),
            "response": "json",
        },
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_tpex_ex_dividend_history(response.json())


def _month_windows(as_of: date, count: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    year = as_of.year
    month = as_of.month
    for offset in range(max(1, count)):
        zero_based = month - 1 + offset
        windows.append((year + zero_based // 12, zero_based % 12 + 1))
    return windows


def _mops_window_label(year: int, month: int | None) -> str:
    return f"{year}-{month:02d}" if month is not None else str(year)


def _mops_failure_from_exception(
    exc: BaseException,
    *,
    market: str,
    year: int,
    month: int | None,
    attempt_count: int,
) -> MopsConferenceWindowFailure:
    failure = provider_http_failure(exc)
    if failure is not None:
        target_parts = failure.context.target.rsplit(":", 1)
        stage = target_parts[-1] if len(target_parts) == 2 else "request"
        status = failure.status
        exception_type = failure.exception_type or type(exc).__name__
        message = failure.error_message or str(exc).strip() or exception_type
        retryable = status in {"error", "timeout"} or (
            failure.http_status_code is not None
            and failure.http_status_code >= 500
        )
        return MopsConferenceWindowFailure(
            provider=MOPS_PROVIDER,
            market=market,
            window=_mops_window_label(year, month),
            stage=stage,
            status=status,
            exception_type=exception_type,
            attempt_count=attempt_count,
            retryable=retryable,
            message=message,
            http_status_code=failure.http_status_code,
            rate_limited=failure.rate_limited,
            retry_after_seconds=failure.retry_after_seconds,
        )

    stage = str(getattr(exc, "stage", "parse") or "parse")
    exception_type = str(
        getattr(exc, "exception_type", type(exc).__name__)
        or type(exc).__name__
    )
    return MopsConferenceWindowFailure(
        provider=MOPS_PROVIDER,
        market=market,
        window=_mops_window_label(year, month),
        stage=stage,
        status="invalid_response",
        exception_type=exception_type,
        attempt_count=attempt_count,
        retryable=False,
        message=str(exc).strip() or exception_type,
    )


def _fetch_mops_conference_window(
    *,
    market_kind: str,
    market: str,
    year: int,
    month: int | None,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    month_text = f"{month:02d}" if month is not None else ""
    target_window = f"{year}-{month_text}" if month_text else str(year)
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Referer": MOPS_RESULT_REFERER,
    }
    redirect_response = post(
        MOPS_REDIRECT_URL,
        provider=MOPS_PROVIDER,
        resource=RESOURCE,
        target=f"{market}:{target_window}:redirect",
        timeout_seconds=timeout_seconds,
        headers=headers,
        json={
            "apiName": "ajax_t100sb02_1",
            "parameters": {
                "TYPEK": market_kind,
                "year": str(year - 1911),
                "month": month_text,
                "co_id": "",
                "encodeURIComponent": 1,
                "step": 1,
                "firstin": 1,
                "off": 1,
            },
        },
    )
    redirect_response.raise_for_status()
    redirect_response.encoding = "utf-8"
    try:
        redirect_payload = redirect_response.json()
    except Exception as exc:
        raise MopsConferenceStageError(
            str(exc).strip() or "MOPS redirect response was not valid JSON.",
            stage="redirect_payload",
            exception_type=type(exc).__name__,
        ) from exc
    result_url = str(
        ((redirect_payload.get("result") or {}).get("url")) or ""
    ).strip()
    if redirect_payload.get("code") != 200 or not result_url.startswith("https://"):
        raise MopsConferenceStageError(
            "MOPS did not return a usable signed result URL.",
            stage="redirect_payload",
            exception_type="InvalidRedirectPayload",
        )

    result_response = get(
        result_url,
        provider=MOPS_PROVIDER,
        resource=RESOURCE,
        target=f"{market}:{target_window}:result",
        timeout_seconds=timeout_seconds,
        headers={
            "User-Agent": DEFAULT_HEADERS["User-Agent"],
            "Accept": "text/html,*/*",
            "Referer": MOPS_RESULT_REFERER,
        },
    )
    result_response.raise_for_status()
    result_response.encoding = "utf-8"
    try:
        return parse_mops_conferences(result_response.text, market=market)
    except Exception as exc:
        raise MopsConferenceStageError(
            str(exc).strip() or "MOPS result page could not be parsed.",
            stage="parse",
            exception_type=type(exc).__name__,
        ) from exc


def _fetch_mops_window_with_retries(
    *,
    market_kind: str,
    market: str,
    year: int,
    month: int | None,
    timeout_seconds: int,
    max_attempts: int,
) -> tuple[
    list[dict[str, Any]],
    int,
    MopsConferenceWindowFailure | None,
    int,
]:
    bounded_attempts = max(1, min(int(max_attempts), 3))
    for attempt in range(1, bounded_attempts + 1):
        try:
            entries = _fetch_mops_conference_window(
                market_kind=market_kind,
                market=market,
                year=year,
                month=month,
                timeout_seconds=timeout_seconds,
            )
            return entries, attempt * 2, None, attempt - 1
        except Exception as exc:
            failure = _mops_failure_from_exception(
                exc,
                market=market,
                year=year,
                month=month,
                attempt_count=attempt,
            )
            if failure.retryable and attempt < bounded_attempts:
                continue
            return [], attempt * 2, failure, attempt - 1

    raise AssertionError("Bounded MOPS retry loop exited unexpectedly.")


def fetch_mops_conferences(
    *,
    as_of: date,
    month_count: int = 2,
    timeout_seconds: int = 20,
    max_attempts: int = 2,
) -> MopsConferenceBatch:
    windows = _month_windows(as_of, month_count)
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    failures: list[MopsConferenceWindowFailure] = []
    successful_windows: list[str] = []
    recovered_windows: list[str] = []
    request_count = 0
    retry_count = 0
    for market_kind, market in (("sii", "TWSE"), ("otc", "TPEX")):
        for year, month in windows:
            fetched, requests_used, failure, retries_used = _fetch_mops_window_with_retries(
                market_kind=market_kind,
                market=market,
                year=year,
                month=month,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
            request_count += requests_used
            retry_count += retries_used
            window_key = f"{market}:{_mops_window_label(year, month)}"
            if failure is not None:
                failures.append(failure)
                errors.append(failure.summary())
                continue
            entries.extend(fetched)
            successful_windows.append(window_key)
            if retries_used:
                recovered_windows.append(window_key)

    deduped = {entry["event_id"]: entry for entry in entries}
    coverage_start = date(windows[0][0], windows[0][1], 1)
    last_year, last_month = windows[-1]
    coverage_end = date(last_year, last_month, monthrange(last_year, last_month)[1])
    return MopsConferenceBatch(
        entries=sorted(
            deduped.values(),
            key=lambda item: (
                item["start_date"],
                item.get("start_time") or "",
                item["stock_id"],
                item["event_type"],
            ),
        ),
        request_count=request_count,
        errors=errors,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        failures=failures,
        successful_windows=successful_windows,
        recovered_windows=recovered_windows,
        retry_count=retry_count,
    )


def fetch_mops_conference_history(
    *,
    year: int,
    as_of: date,
    timeout_seconds: int = 20,
    max_attempts: int = 2,
) -> MopsConferenceBatch:
    coverage_start = date(year, 1, 1)
    coverage_end = min(date(year, 12, 31), as_of - timedelta(days=1))
    if coverage_end < coverage_start:
        return MopsConferenceBatch(
            entries=[],
            request_count=0,
            errors=[],
            coverage_start=coverage_start,
            coverage_end=coverage_start,
        )

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    failures: list[MopsConferenceWindowFailure] = []
    successful_windows: list[str] = []
    recovered_windows: list[str] = []
    request_count = 0
    retry_count = 0
    for market_kind, market in (("sii", "TWSE"), ("otc", "TPEX")):
        fetched, requests_used, failure, retries_used = _fetch_mops_window_with_retries(
            market_kind=market_kind,
            market=market,
            year=year,
            month=None,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        request_count += requests_used
        retry_count += retries_used
        window_key = f"{market}:{year}"
        if failure is not None:
            failures.append(failure)
            errors.append(failure.summary())
            continue
        entries.extend(
            entry
            for entry in fetched
            if coverage_start <= entry["start_date"] <= coverage_end
        )
        successful_windows.append(window_key)
        if retries_used:
            recovered_windows.append(window_key)

    deduped = {entry["event_id"]: entry for entry in entries}
    return MopsConferenceBatch(
        entries=sorted(
            deduped.values(),
            key=lambda item: (
                item["start_date"],
                item.get("start_time") or "",
                item["stock_id"],
                item["event_type"],
            ),
        ),
        request_count=request_count,
        errors=errors,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        failures=failures,
        successful_windows=successful_windows,
        recovered_windows=recovered_windows,
        retry_count=retry_count,
    )


__all__ = [
    "MOPS_CONFERENCE_URL",
    "MOPS_PROVIDER",
    "MopsConferenceBatch",
    "MopsConferenceWindowFailure",
    "TPEX_EX_DIVIDEND_URL",
    "TPEX_EX_DIVIDEND_HISTORY_URL",
    "TPEX_PROVIDER",
    "TWSE_EX_DIVIDEND_URL",
    "TWSE_EX_DIVIDEND_HISTORY_URL",
    "TWSE_PROVIDER",
    "fetch_mops_conference_history",
    "fetch_mops_conferences",
    "fetch_tpex_ex_dividend_history",
    "fetch_tpex_ex_dividends",
    "fetch_twse_ex_dividend_history",
    "fetch_twse_ex_dividends",
    "parse_mops_conferences",
    "parse_tpex_ex_dividend_history",
    "parse_tpex_ex_dividends",
    "parse_twse_ex_dividend_history",
    "parse_twse_ex_dividends",
]
