from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime


def as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def as_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def list_value(values, index: int):
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def parse_trade_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for separator in ("/", "-"):
        if separator not in text:
            continue
        parts = text.split(separator)
        if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) <= 3:
            year = int(parts[0]) + 1911
            return date(year, int(parts[1]), int(parts[2]))
    normalized = text.replace("/", "").replace("-", "")
    if len(normalized) == 7 and normalized.isdigit():
        year = int(normalized[:3]) + 1911
        return date(year, int(normalized[3:5]), int(normalized[5:7]))
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def signed_change(sign_value, change_value) -> float | None:
    change = as_float(change_value)
    if change is None:
        return None
    sign = str(sign_value or "").strip()
    if sign in {"-", "－"}:
        return -abs(change)
    if sign in {"+", "＋"}:
        return abs(change)
    return change


def regular_stock_code(value) -> str | None:
    if value is None:
        return None
    code = str(value).strip()
    if len(code) == 4 and code.isdigit():
        return code
    return None


def count_with_limit(value) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    text = str(value).strip()
    base_text = text.split("(", 1)[0]
    limit_text = (
        text.split("(", 1)[1].split(")", 1)[0]
        if "(" in text and ")" in text
        else None
    )
    return as_int(base_text), as_int(limit_text)


def row_value(row, keys: Iterable[str], positions: Iterable[int]):
    if isinstance(row, dict):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None
    if isinstance(row, (list, tuple)):
        for position in positions:
            if position < len(row):
                value = row[position]
                if value not in (None, ""):
                    return value
    return None


def market_index_stat_item(
    *,
    trade_date: date | None,
    trade_volume: int | None,
    trade_value: int | None,
    transaction_count: int | None,
    close_value: float | None,
    price_change: float | None,
) -> dict | None:
    if trade_date is None:
        return None
    if trade_volume is None and trade_value is None and close_value is None:
        return None
    return {
        "trade_date": trade_date,
        "trade_volume": trade_volume,
        "trade_value": trade_value,
        "transaction_count": transaction_count,
        "close_value": close_value,
        "price_change": price_change,
    }


def parse_twse_market_daily_history_rows(payload) -> list[dict]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    results: list[dict] = []
    for row in rows:
        item = market_index_stat_item(
            trade_date=parse_trade_date(row_value(row, keys=("Date", "date", "日期"), positions=(0,))),
            trade_volume=as_int(row_value(row, keys=("TradeVolume", "trade_volume", "成交股數"), positions=(1,))),
            trade_value=as_int(row_value(row, keys=("TradeValue", "trade_value", "成交金額"), positions=(2,))),
            transaction_count=as_int(row_value(row, keys=("Transaction", "transaction_count", "成交筆數"), positions=(3,))),
            close_value=as_float(row_value(row, keys=("TAIEX", "close_value", "發行量加權股價指數"), positions=(4,))),
            price_change=as_float(row_value(row, keys=("Change", "price_change", "漲跌點數"), positions=(5,))),
        )
        if item is not None:
            results.append(item)
    return results


def parse_tpex_market_daily_rows(payload) -> list[dict]:
    rows = payload if isinstance(payload, list) else []
    results: list[dict] = []
    for row in rows:
        item = market_index_stat_item(
            trade_date=parse_trade_date(row_value(row, keys=("Date", "date"), positions=(0,))),
            trade_volume=as_int(row_value(row, keys=("TradeVolume", "Volume", "TransactionVolume"), positions=(1,))),
            trade_value=as_int(row_value(row, keys=("TradeAmount", "TradeValue", "TransactionAmount"), positions=(2,))),
            transaction_count=as_int(row_value(row, keys=("Transaction", "TransactionCount"), positions=(3,))),
            close_value=as_float(row_value(row, keys=("TPExIndex", "Index", "Close", "TPEX"), positions=(4,))),
            price_change=as_float(row_value(row, keys=("Change",), positions=(5,))),
        )
        if item is not None:
            results.append(item)
    return results


__all__ = [
    "as_float",
    "as_int",
    "count_with_limit",
    "list_value",
    "market_index_stat_item",
    "parse_tpex_market_daily_rows",
    "parse_trade_date",
    "parse_twse_market_daily_history_rows",
    "regular_stock_code",
    "row_value",
    "signed_change",
]
