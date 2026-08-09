from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

from app.http_client import new_session
from app.market.providers.tw_etf_contracts import TaiwanEtfPcfRecord


UPAMC_PROVIDER = "upamc_etfs"
UPAMC_PCF_PAGE_URL = "https://www.ezmoney.com.tw/ETF/Transaction/PCF"
UPAMC_PCF_API_URL = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfUpamcProviderError(RuntimeError):
    pass


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized.casefold() in {"null", "none", "undefined", "-", "--"}:
        return None
    return normalized


def _decimal(value: object) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return Decimal(normalized.replace(",", "").replace("%", ""))
    except InvalidOperation as exc:
        raise TaiwanEtfUpamcProviderError(
            f"Invalid Uni-President ETF numeric value: {normalized}"
        ) from exc


def _integer(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed != parsed.to_integral_value():
        raise TaiwanEtfUpamcProviderError(
            f"Invalid Uni-President ETF integer value: {value}"
        )
    return int(parsed)


def _iso_date(value: object, *, field: str) -> date:
    normalized = _text(value)
    if normalized is None:
        raise TaiwanEtfUpamcProviderError(
            f"Uni-President ETF PCF omitted {field}."
        )
    microsoft_date = re.fullmatch(r"/Date\((?P<milliseconds>-?\d+)(?:[+-]\d{4})?\)/", normalized)
    try:
        if microsoft_date is not None:
            return datetime.fromtimestamp(
                int(microsoft_date.group("milliseconds")) / 1000,
                tz=ZoneInfo("UTC"),
            ).astimezone(TAIWAN_TZ).date()
        return datetime.fromisoformat(normalized).date()
    except ValueError as exc:
        raise TaiwanEtfUpamcProviderError(
            f"Invalid Uni-President ETF {field}: {normalized}"
        ) from exc


def _iso_datetime(value: object) -> datetime | None:
    normalized = _text(value)
    if normalized is None:
        return None
    microsoft_date = re.fullmatch(r"/Date\((?P<milliseconds>-?\d+)(?:[+-]\d{4})?\)/", normalized)
    try:
        if microsoft_date is not None:
            return datetime.fromtimestamp(
                int(microsoft_date.group("milliseconds")) / 1000,
                tz=ZoneInfo("UTC"),
            ).astimezone(TAIWAN_TZ)
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TaiwanEtfUpamcProviderError(
            f"Invalid Uni-President ETF source timestamp: {normalized}"
        ) from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=TAIWAN_TZ)


def _roc_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def parse_upamc_pcf_page(html: str, stock_id: str) -> tuple[str, str]:
    normalized_id = stock_id.strip().upper()
    soup = BeautifulSoup(html or "", "html.parser")
    matches: list[str] = []
    for node in soup.select('a[href*="fundCode="]'):
        label = _text(node.get_text(" ", strip=True))
        if label is None or not label.upper().startswith(normalized_id):
            continue
        fund_codes = parse_qs(urlparse(str(node.get("href") or "")).query).get(
            "fundCode", []
        )
        matches.extend(code for code in fund_codes if _text(code))
    unique_matches = tuple(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        raise TaiwanEtfUpamcProviderError(
            f"Uni-President ETF PCF page returned {len(unique_matches)} fund-code matches for stock_id={normalized_id}."
        )
    date_input = soup.select_one("#ED")
    default_date = _text(date_input.get("value") if date_input is not None else None)
    if default_date is None:
        raise TaiwanEtfUpamcProviderError(
            "Uni-President ETF PCF page omitted its default effective date."
        )
    return unique_matches[0], default_date


def parse_upamc_etf_pcf_payload(payload: object, stock_id: str) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    if not isinstance(payload, dict):
        raise TaiwanEtfUpamcProviderError(
            "Uni-President ETF PCF response was not an object."
        )
    fund = payload.get("fund")
    rows = payload.get("pcf")
    if not isinstance(fund, dict) or not isinstance(rows, list) or not rows:
        raise TaiwanEtfUpamcProviderError(
            "Uni-President ETF PCF response omitted fund or PCF rows."
        )
    payload_id = str(fund.get("sStockNo") or "").strip().upper()
    if payload_id != normalized_id:
        raise TaiwanEtfUpamcProviderError(
            f"Uni-President ETF PCF returned stock_id={payload_id or 'missing'} for requested stock_id={normalized_id}."
        )
    values: dict[str, object] = {}
    first_row: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            raise TaiwanEtfUpamcProviderError(
                "Uni-President ETF PCF contained a malformed row."
            )
        code = str(row.get("PCFCode") or "").strip().upper()
        if code:
            values[code] = row.get("Amount")
        if first_row is None:
            first_row = row
    assert first_row is not None
    required_codes = {"NAV", "OUT_UNIT", "P_UNIT", "FUND_BASEUNIT", "PRE_AMT"}
    missing_codes = sorted(code for code in required_codes if code not in values)
    if missing_codes:
        raise TaiwanEtfUpamcProviderError(
            "Uni-President ETF PCF omitted required codes: " + ", ".join(missing_codes)
        )
    return TaiwanEtfPcfRecord(
        stock_id=normalized_id,
        fund_id=_text(fund.get("sFundCode")),
        fund_name=_text(fund.get("sFundName")),
        full_name=_text(fund.get("sFundName")),
        name_en=None,
        reference_date=_iso_date(first_row.get("TranDate"), field="reference date"),
        effective_date=_iso_date(first_row.get("PostDate"), field="effective date"),
        total_net_assets=_decimal(values.get("NAV")),
        issued_units=_integer(values.get("OUT_UNIT")),
        unit_nav=_decimal(values.get("P_UNIT")),
        creation_unit=_integer(values.get("FUND_BASEUNIT")),
        estimated_creation_value=_decimal(values.get("PRE_AMT")),
        estimated_cash_component=None,
        unit_change=_integer(values.get("DIFF_UNIT")),
        actual_cash_component=None,
        redemption_method="cash",
        source_updated_at=_iso_datetime(first_row.get("EditDate")),
        components=(),
    )


def fetch_upamc_etf_pcf(
    stock_id: str,
    *,
    target_date: date | None = None,
    session_factory: Callable[[], requests.Session] = new_session,
) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    session = session_factory()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    try:
        page_response = session.request(
            "GET", UPAMC_PCF_PAGE_URL, timeout=20, headers=headers
        )
        page_response.raise_for_status()
        page_response.encoding = "utf-8"
        fund_code, default_date = parse_upamc_pcf_page(
            page_response.text, normalized_id
        )
        requested_date = _roc_date(target_date) if target_date else default_date
        response = session.request(
            "POST",
            UPAMC_PCF_API_URL,
            timeout=20,
            headers={
                **headers,
                "Accept": "application/json,text/javascript,*/*;q=0.01",
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": UPAMC_PCF_PAGE_URL,
            },
            json={
                "fundCode": fund_code,
                "date": requested_date,
                "specificDate": True,
            },
        )
        response.raise_for_status()
        record = parse_upamc_etf_pcf_payload(response.json(), normalized_id)
        if target_date is not None and record.effective_date != target_date:
            raise TaiwanEtfUpamcProviderError(
                f"Uni-President ETF PCF returned effective_date={record.effective_date.isoformat()} "
                f"for target_date={target_date.isoformat()}."
            )
        return record
    finally:
        session.close()


__all__ = [
    "UPAMC_PCF_API_URL",
    "UPAMC_PCF_PAGE_URL",
    "UPAMC_PROVIDER",
    "TaiwanEtfUpamcProviderError",
    "fetch_upamc_etf_pcf",
    "parse_upamc_etf_pcf_payload",
    "parse_upamc_pcf_page",
]
