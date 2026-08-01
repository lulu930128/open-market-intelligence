from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.us_market.trading_calendar import previous_us_trading_day


US_MARKET_TIMEZONE = ZoneInfo("America/New_York")

_CLOSE_HINT_PATTERN = re.compile(
    r"(?:closing\s+price|close\s+price|market\s+close|regular[-\s]?session\s+close|"
    r"收盤價|收盘价|收盤|收盘)",
    re.IGNORECASE,
)
_ISO_DATE_PATTERN = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_CHINESE_FULL_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号](?!\d)"
)
_MONTH_DAY_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:月|/)\s*(\d{1,2})\s*(?:日|號|号)?(?!\d)"
)
_DAY_ONLY_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*(?:號|号)(?!\d)")
_PREVIOUS_SESSION_PATTERN = re.compile(
    r"(?:昨天|昨日|yesterday|前一(?:個)?交易日|上一(?:個)?交易日|"
    r"previous\s+trading\s+(?:day|session)|last\s+trading\s+(?:day|session))",
    re.IGNORECASE,
)


def _reference_trade_date(now: datetime | None) -> date:
    if now is None:
        return datetime.now(US_MARKET_TIMEZONE).date()
    if now.tzinfo is None:
        return now.replace(tzinfo=US_MARKET_TIMEZONE).date()
    return now.astimezone(US_MARKET_TIMEZONE).date()


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _latest_month_day(reference: date, month: int, day: int) -> date | None:
    for year in range(reference.year, reference.year - 9, -1):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate <= reference:
            return candidate
    return None


def _latest_day_of_month(reference: date, day: int) -> date | None:
    year = reference.year
    month = reference.month
    for _ in range(14):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate <= reference:
            return candidate
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return None


def parse_market_trade_date(value: Any) -> date | None:
    """Parse an explicit target-market trade date.

    The public contract uses an ISO calendar date in the exchange timezone.
    Invalid explicit values are rejected instead of silently falling back to
    the latest available row.
    """

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(US_MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(
            "market_data_params.trade_date must be an ISO date in YYYY-MM-DD format."
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "market_data_params.trade_date must be a valid ISO date in YYYY-MM-DD format."
        ) from exc


def requested_us_trade_date(
    question: str,
    *,
    explicit_value: Any = None,
    now: datetime | None = None,
) -> date | None:
    """Resolve a US exchange trade date from explicit input or a close query.

    Relative previous-day wording resolves in ``America/New_York`` and rolls
    weekends or known exchange holidays back to the latest trading session.
    Other natural-language inference remains limited to questions that
    explicitly ask for a close. Missing year/month values resolve to the most
    recent matching US calendar date, never a future occurrence.
    """

    explicit = parse_market_trade_date(explicit_value)
    if explicit is not None:
        return explicit

    text = str(question or "").strip()
    if not text:
        return None

    reference = _reference_trade_date(now)
    if _PREVIOUS_SESSION_PATTERN.search(text):
        return previous_us_trading_day(
            reference - timedelta(days=1),
            include_value=True,
        )

    if not _CLOSE_HINT_PATTERN.search(text):
        return None

    match = _ISO_DATE_PATTERN.search(text)
    if match:
        return _safe_date(*(int(value) for value in match.groups()))

    match = _CHINESE_FULL_DATE_PATTERN.search(text)
    if match:
        return _safe_date(*(int(value) for value in match.groups()))

    match = _MONTH_DAY_PATTERN.search(text)
    if match:
        month, day = (int(value) for value in match.groups())
        return _latest_month_day(reference, month, day)

    match = _DAY_ONLY_PATTERN.search(text)
    if not match:
        return None
    day = int(match.group(1))
    return _latest_day_of_month(reference, day)
