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


def market_index_ohlc_item(
    *,
    trade_date: date | None,
    open_value: float | None,
    high_value: float | None,
    low_value: float | None,
    close_value: float | None,
) -> dict | None:
    if (
        trade_date is None
        or open_value is None
        or high_value is None
        or low_value is None
        or close_value is None
    ):
        return None
    if high_value < max(open_value, close_value):
        return None
    if low_value > min(open_value, close_value):
        return None
    return {
        "trade_date": trade_date,
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
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


def parse_twse_index_daily_ohlc_rows(payload) -> list[dict]:
    if not isinstance(payload, dict) or str(payload.get("stat") or "").upper() != "OK":
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    results: list[dict] = []
    for row in rows:
        item = market_index_ohlc_item(
            trade_date=parse_trade_date(
                row_value(row, keys=("Date", "date", "日期"), positions=(0,))
            ),
            open_value=as_float(
                row_value(row, keys=("Open", "open", "開盤指數"), positions=(1,))
            ),
            high_value=as_float(
                row_value(row, keys=("High", "high", "最高指數"), positions=(2,))
            ),
            low_value=as_float(
                row_value(row, keys=("Low", "low", "最低指數"), positions=(3,))
            ),
            close_value=as_float(
                row_value(row, keys=("Close", "close", "收盤指數"), positions=(4,))
            ),
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


def parse_tpex_market_highlight_rows(
    payload,
    *,
    expected_trade_date: date | None = None,
) -> list[dict]:
    if not isinstance(payload, dict) or str(payload.get("stat") or "").lower() != "ok":
        return []

    trade_date = parse_trade_date(payload.get("date"))
    if trade_date is None or (
        expected_trade_date is not None and trade_date != expected_trade_date
    ):
        return []

    tables = payload.get("tables")
    if not isinstance(tables, list):
        return []

    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        rows = table.get("data")
        if not isinstance(fields, list) or not isinstance(rows, list) or not rows:
            continue
        row = rows[0]
        if not isinstance(row, list):
            continue

        values_by_field = {
            str(field).strip(): list_value(row, index)
            for index, field in enumerate(fields)
        }
        trade_value_field = next(
            (
                field
                for field in values_by_field
                if field.startswith("本日總成交值")
            ),
            None,
        )
        trade_volume_field = next(
            (
                field
                for field in values_by_field
                if field.startswith("本日總成交股數")
            ),
            None,
        )
        close_field = next(
            (field for field in values_by_field if field.startswith("收市指數")),
            None,
        )
        change_field = next(
            (field for field in values_by_field if field.startswith("指數漲跌")),
            None,
        )

        trade_value = as_int(
            values_by_field.get(trade_value_field) if trade_value_field else None
        )
        trade_volume = as_int(
            values_by_field.get(trade_volume_field) if trade_volume_field else None
        )
        if trade_value is not None and trade_value_field and "佰萬元" in trade_value_field:
            trade_value *= 1_000_000
        if trade_volume is not None and trade_volume_field and (
            "張數" in trade_volume_field or "仟股" in trade_volume_field
        ):
            trade_volume *= 1_000

        item = market_index_stat_item(
            trade_date=trade_date,
            trade_volume=trade_volume,
            trade_value=trade_value,
            transaction_count=None,
            close_value=as_float(
                values_by_field.get(close_field) if close_field else None
            ),
            price_change=as_float(
                values_by_field.get(change_field) if change_field else None
            ),
        )
        return [item] if item is not None else []

    return []


__all__ = [
    "as_float",
    "as_int",
    "count_with_limit",
    "list_value",
    "market_index_ohlc_item",
    "market_index_stat_item",
    "parse_tpex_market_highlight_rows",
    "parse_tpex_market_daily_rows",
    "parse_trade_date",
    "parse_twse_index_daily_ohlc_rows",
    "parse_twse_market_daily_history_rows",
    "regular_stock_code",
    "row_value",
    "signed_change",
]
