from __future__ import annotations

from datetime import date
import re

from bs4 import BeautifulSoup

from ._http import get as provider_get


JPX_LISTED_ISSUES_URL = (
    "https://www.jpx.co.jp/english/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_e.xls"
)
JPX_MARKET_HOLIDAYS_URL = (
    "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html"
)
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_jpx_market_holidays(html: str) -> dict[date, str]:
    soup = BeautifulSoup(html or "", "lxml")
    holidays: dict[date, str] = {}
    parsed_years: set[int] = set()
    for table in soup.select("table.overtable"):
        heading = table.find_previous(["h2", "h3"])
        year_match = re.search(r"\b(20\d{2})\b", heading.get_text(" ", strip=True) if heading else "")
        if not year_match:
            continue
        year = int(year_match.group(1))
        row_count = 0
        for row in table.select("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
            if len(cells) < 2:
                continue
            date_match = re.search(r"\b([A-Z][a-z]{2})\.?\s+(\d{1,2})\b", cells[0])
            if not date_match or date_match.group(1) not in _MONTHS:
                continue
            try:
                holiday_date = date(
                    year,
                    _MONTHS[date_match.group(1)],
                    int(date_match.group(2)),
                )
            except ValueError:
                continue
            holidays[holiday_date] = cells[1].strip() or "Market Holiday"
            row_count += 1
        if row_count >= 8:
            parsed_years.add(year)

    if not parsed_years:
        raise ValueError("JPX market-holiday page did not contain a complete calendar table.")
    return {
        holiday_date: name
        for holiday_date, name in holidays.items()
        if holiday_date.year in parsed_years
    }


def fetch_jpx_market_holidays(
    *,
    timeout_seconds: int,
) -> tuple[dict[date, str], str]:
    response = provider_get(
        JPX_MARKET_HOLIDAYS_URL,
        provider="jpx_calendar",
        resource="exchange_calendar",
        target="TSE",
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    return parse_jpx_market_holidays(response.text), response.url


def fetch_jpx_listed_issues_workbook(
    *,
    timeout_seconds: int,
) -> tuple[bytes, str]:
    response = provider_get(
        JPX_LISTED_ISSUES_URL,
        provider="jpx_listed_issues",
        resource="symbol_master",
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/vnd.ms-excel,application/octet-stream,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    return response.content, response.url
