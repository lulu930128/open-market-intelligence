from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from bs4 import BeautifulSoup

from app.market.providers._http import DEFAULT_HEADERS, get_json, post


TWSE_ETF_PROFILE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
MOPS_ETF_NAV_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t78sb35"


class TaiwanEtfProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaiwanEtfProfileRecord:
    stock_id: str
    report_date: date | None
    fund_short_name: str | None
    fund_name: str | None
    fund_name_en: str | None
    fund_type: str | None
    benchmark_name: str | None
    is_customized_index: bool | None
    investment_scope: str | None
    has_performance_benchmark: bool | None
    performance_benchmark_name: str | None
    has_foreign_components: bool | None
    tax_id: str | None
    established_date: date | None
    listed_date: date | None
    fund_manager: str | None
    issued_units: int | None
    custodian: str | None


@dataclass(frozen=True)
class TaiwanEtfNavRecord:
    stock_id: str
    nav_date: date
    issuer_name: str | None
    fund_name: str | None
    nav: Decimal | None
    previous_nav: Decimal | None
    nav_change: Decimal | None
    nav_change_pct: Decimal | None
    close_price: Decimal | None
    premium_discount_pct: Decimal | None
    benchmark_name: str | None = None
    benchmark_date: date | None = None
    benchmark_close: Decimal | None = None
    benchmark_previous_close: Decimal | None = None
    benchmark_change: Decimal | None = None
    benchmark_change_pct: Decimal | None = None


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized in {"-", "--", "不適用"}:
        return None
    return normalized


def _roc_date(value: object) -> date | None:
    normalized = _text(value)
    if normalized is None:
        return None
    digits = re.sub(r"\D", "", normalized)
    try:
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError as exc:
        raise TaiwanEtfProviderError(f"Invalid ETF date value: {normalized!r}") from exc
    raise TaiwanEtfProviderError(f"Unsupported ETF date value: {normalized!r}")


def _decimal(value: object) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    normalized = normalized.replace(",", "").replace("%", "")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise TaiwanEtfProviderError(f"Invalid ETF numeric value: {value!r}") from exc


def _integer(value: object) -> int | None:
    parsed = _decimal(value)
    return int(parsed) if parsed is not None else None


def _boolean(value: object) -> bool | None:
    normalized = _text(value)
    if normalized == "是":
        return True
    if normalized == "否":
        return False
    return None


def parse_twse_etf_profiles(payload: object) -> tuple[TaiwanEtfProfileRecord, ...]:
    if not isinstance(payload, list):
        raise TaiwanEtfProviderError("TWSE ETF profile payload must be a list.")

    records: list[TaiwanEtfProfileRecord] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        stock_id = _text(row.get("基金代號"))
        if stock_id is None:
            continue
        records.append(
            TaiwanEtfProfileRecord(
                stock_id=stock_id,
                report_date=_roc_date(row.get("出表日期")),
                fund_short_name=_text(row.get("基金簡稱")),
                fund_name=_text(row.get("基金中文名稱")),
                fund_name_en=_text(row.get("基金英文名稱")),
                fund_type=_text(row.get("基金類型")),
                benchmark_name=_text(row.get("標的指數/追蹤指數名稱")),
                is_customized_index=_boolean(
                    row.get("標的指數是否為客製化或需揭露相關資訊之指數")
                ),
                investment_scope=_text(row.get("股票及債券投資比例說明")),
                has_performance_benchmark=_boolean(row.get("是否設有績效指標")),
                performance_benchmark_name=_text(row.get("績效指標中文名稱"))
                or _text(row.get("績效指標英文名稱")),
                has_foreign_components=_boolean(row.get("是否包含國外成分股")),
                tax_id=_text(row.get("基金統一編號")),
                established_date=_roc_date(row.get("成立日期")),
                listed_date=_roc_date(row.get("上市日期")),
                fund_manager=_text(row.get("基金經理人")),
                issued_units=_integer(row.get("發行單位數/轉換數")),
                custodian=_text(row.get("保管機構")),
            )
        )

    if not records:
        raise TaiwanEtfProviderError("TWSE ETF profile payload contained no valid fund rows.")
    return tuple(records)


def fetch_twse_etf_profile(
    stock_id: str,
    *,
    fetch_json: Callable[..., Any] = get_json,
) -> TaiwanEtfProfileRecord:
    payload = fetch_json(
        TWSE_ETF_PROFILE_URL,
        provider="twse_openapi",
        resource="etf_profile",
        target=stock_id,
        timeout_seconds=20,
    )
    for record in parse_twse_etf_profiles(payload):
        if record.stock_id == stock_id:
            return record
    raise TaiwanEtfProviderError(f"TWSE ETF profile did not contain stock_id={stock_id}.")


def _row_values(row: Any) -> list[str]:
    return [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]


def _benchmark_from_rows(rows: list[Any], start: int) -> tuple[object, ...] | None:
    for candidate in rows[start : start + 3]:
        values = _row_values(candidate)
        if len(values) < 6 or any(re.fullmatch(r"\d{4,6}[A-Z]?", value) for value in values):
            continue
        for date_index, value in enumerate(values):
            if not re.fullmatch(r"(?:\d{3}|\d{4})[/.-]\d{1,2}[/.-]\d{1,2}", value):
                continue
            if date_index < 1 or len(values) < date_index + 5:
                continue
            return (
                _text(values[date_index - 1]),
                _roc_date(value),
                _decimal(values[date_index + 1]),
                _decimal(values[date_index + 2]),
                _decimal(values[date_index + 3]),
                _decimal(values[date_index + 4]),
            )
    return None


def parse_mops_etf_nav_html(html: str) -> tuple[TaiwanEtfNavRecord, ...]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.hasBorder")
    if table is None:
        if "查無資料" in soup.get_text(" ", strip=True):
            return ()
        raise TaiwanEtfProviderError("MOPS ETF NAV table was not found.")

    rows = table.find_all("tr")
    records: list[TaiwanEtfNavRecord] = []
    current_issuer: str | None = None
    pending_code: str | None = None

    for index, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        values = _row_values(row)
        if not values:
            continue

        code_index = next(
            (idx for idx, value in enumerate(values) if re.fullmatch(r"\d{4,6}[A-Z]?", value)),
            None,
        )
        if code_index is not None:
            if code_index > 0:
                current_issuer = _text(values[code_index - 1]) or current_issuer
            pending_code = values[code_index]
            data = values[code_index + 1 :]
        elif pending_code is not None and not row.find("th"):
            data = values
        else:
            continue

        date_index = next(
            (
                idx
                for idx, value in enumerate(data)
                if re.fullmatch(r"(?:\d{3}|\d{4})[/.-]\d{1,2}[/.-]\d{1,2}", value)
            ),
            None,
        )
        if date_index is None or date_index < 1 or len(data) < date_index + 7:
            continue

        benchmark = _benchmark_from_rows(rows, index + 1)
        records.append(
            TaiwanEtfNavRecord(
                stock_id=pending_code,
                issuer_name=current_issuer,
                fund_name=_text(data[date_index - 1]),
                nav_date=_roc_date(data[date_index]),
                nav=_decimal(data[date_index + 1]),
                previous_nav=_decimal(data[date_index + 2]),
                nav_change=_decimal(data[date_index + 3]),
                nav_change_pct=_decimal(data[date_index + 4]),
                close_price=_decimal(data[date_index + 5]),
                premium_discount_pct=_decimal(data[date_index + 6]),
                benchmark_name=benchmark[0] if benchmark else None,
                benchmark_date=benchmark[1] if benchmark else None,
                benchmark_close=benchmark[2] if benchmark else None,
                benchmark_previous_close=benchmark[3] if benchmark else None,
                benchmark_change=benchmark[4] if benchmark else None,
                benchmark_change_pct=benchmark[5] if benchmark else None,
            )
        )
        pending_code = None

    if not records:
        text = soup.get_text(" ", strip=True)
        if "查無資料" in text or "無資料" in text:
            return ()
        raise TaiwanEtfProviderError("MOPS ETF NAV table contained no valid fund rows.")
    return tuple(records)


def _decode_html(content: bytes) -> str:
    for encoding in ("utf-8-sig", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TaiwanEtfProviderError("MOPS ETF NAV response encoding was not recognized.")


def fetch_mops_etf_nav_daily(
    target_date: date,
    *,
    request_post: Callable[..., Any] = post,
) -> tuple[TaiwanEtfNavRecord, ...]:
    if target_date.year <= 1911:
        raise ValueError("MOPS ETF NAV target date must use the Gregorian calendar.")
    response = request_post(
        MOPS_ETF_NAV_URL,
        provider="mops",
        resource="etf_daily_nav",
        target=target_date.isoformat(),
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://mopsov.twse.com.tw/mops/web/t78sb35",
        },
        data={
            "step": "1",
            "step00": "0",
            "firstin": "1",
            "off": "1",
            "TYPEK": "all",
            "year": str(target_date.year - 1911),
            "month": f"{target_date.month:02d}",
            "day": f"{target_date.day:02d}",
        },
    )
    response.raise_for_status()
    records = parse_mops_etf_nav_html(_decode_html(response.content))
    return tuple(record for record in records if record.nav_date == target_date)


def find_etf_nav_record(
    records: Iterable[TaiwanEtfNavRecord],
    stock_id: str,
) -> TaiwanEtfNavRecord:
    for record in records:
        if record.stock_id == stock_id:
            return record
    raise TaiwanEtfProviderError(f"MOPS ETF NAV did not contain stock_id={stock_id}.")
