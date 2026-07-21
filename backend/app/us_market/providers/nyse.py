from __future__ import annotations

from datetime import date
import re

from bs4 import BeautifulSoup

from ._http import get as provider_get


NYSE_MARKET_HOLIDAYS_URL = "https://www.nyse.com/trade/hours-calendars"
_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


def parse_nyse_market_holidays(html: str) -> dict[date, str]:
    soup = BeautifulSoup(html or "", "lxml")
    calendar_table = None
    for table in soup.find_all("table"):
        header_cells = [
            cell.get_text(" ", strip=True)
            for cell in table.select_one("tr").select("th,td")
        ] if table.select_one("tr") else []
        if header_cells and header_cells[0].lower() == "holiday":
            calendar_table = table
            break
    if calendar_table is None:
        raise ValueError("NYSE holiday page did not contain the holiday table.")

    rows = calendar_table.select("tr")
    headers = [cell.get_text(" ", strip=True) for cell in rows[0].select("th,td")]
    years: list[int | None] = []
    for value in headers[1:]:
        match = re.search(r"\b(20\d{2})\b", value)
        years.append(int(match.group(1)) if match else None)

    holidays: dict[date, str] = {}
    counts: dict[int, int] = {}
    for row in rows[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if len(cells) < 2:
            continue
        holiday_name = cells[0].strip()
        for index, cell_text in enumerate(cells[1:]):
            if index >= len(years) or years[index] is None:
                continue
            match = re.search(
                r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\b",
                cell_text,
            )
            if not match:
                continue
            year = years[index]
            assert year is not None
            try:
                holiday_date = date(year, _MONTHS[match.group(1)], int(match.group(2)))
            except ValueError:
                continue
            holidays[holiday_date] = holiday_name or "Market Holiday"
            counts[year] = counts.get(year, 0) + 1

    complete_years = {year for year, count in counts.items() if count >= 8}
    if not complete_years:
        raise ValueError("NYSE holiday page did not contain a complete calendar year.")
    return {
        holiday_date: name
        for holiday_date, name in holidays.items()
        if holiday_date.year in complete_years
    }


def fetch_nyse_market_holidays(
    *,
    timeout_seconds: int,
) -> tuple[dict[date, str], str]:
    response = provider_get(
        NYSE_MARKET_HOLIDAYS_URL,
        provider="nyse_calendar",
        resource="exchange_calendar",
        target="NYSE",
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    return parse_nyse_market_holidays(response.text), response.url


__all__ = [
    "NYSE_MARKET_HOLIDAYS_URL",
    "fetch_nyse_market_holidays",
    "parse_nyse_market_holidays",
]
