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


TPEX_POST_CLOSE_INDEX_FIELDS = (
    ("櫃買指數", "櫃買指數"),
    ("紡織纖維", "紡織纖維"),
    ("電機機械", "電機機械"),
    ("化學工業", "化學"),
    ("鋼鐵工業", "鋼鐵"),
    ("電子工業", "電子"),
    ("建材營造", "建材營造"),
    ("航運業", "航運業"),
    ("觀光餐旅", "觀光餐旅"),
    ("生技醫療", "生技醫療"),
    ("半導體業", "半導體"),
    ("電腦週邊業", "電腦及週邊設備"),
    ("光電業", "光電"),
    ("通信網路業", "通信網路"),
    ("電子零件業", "電子零組件"),
    ("電子通路業", "電子通路"),
    ("資訊服務業", "資訊服務"),
    ("其他電子業", "其他電子"),
    ("文化創意業", "文化創意"),
    ("綠能環保", "綠能環保"),
    ("數位雲端", "數位雲端"),
    ("居家生活", "居家生活"),
    ("其他", "其他"),
)
TPEX_POST_CLOSE_INDEX_NAMES = tuple(
    display_name for _, display_name in TPEX_POST_CLOSE_INDEX_FIELDS
)
TPEX_POST_CLOSE_INDEX_FIELD_ALIASES = {
    "紡織纖維": ("紡織纖維", "紡纖纖維"),
}


def _normalized_tpex_field(value) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").strip()


def parse_tpex_post_close_index_list(
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

    table = next(
        (
            item
            for item in payload.get("tables") or []
            if isinstance(item, dict)
            and isinstance(item.get("fields"), list)
            and isinstance(item.get("data"), list)
            and "櫃買指數"
            in {_normalized_tpex_field(field) for field in item.get("fields") or []}
        ),
        None,
    )
    if table is None:
        return []

    fields = table.get("fields") or []
    rows = table.get("data") or []
    positions = {
        _normalized_tpex_field(field): index for index, field in enumerate(fields)
    }
    time_index = positions.get("時間")
    if time_index is None:
        return []

    reference_row = next(
        (
            row
            for row in rows
            if isinstance(row, list)
            and time_index < len(row)
            and str(row[time_index]).strip() == "09:00:00"
        ),
        None,
    )
    closing_row = next(
        (
            row
            for row in reversed(rows)
            if isinstance(row, list)
            and time_index < len(row)
            and str(row[time_index]).strip() == "99:99:99"
        ),
        None,
    )
    if reference_row is None or closing_row is None:
        return []

    items: list[dict] = []
    for provider_name, display_name in TPEX_POST_CLOSE_INDEX_FIELDS:
        provider_aliases = TPEX_POST_CLOSE_INDEX_FIELD_ALIASES.get(
            provider_name,
            (provider_name,),
        )
        value_index = next(
            (
                positions[normalized_alias]
                for alias in provider_aliases
                for normalized_alias in [_normalized_tpex_field(alias)]
                if normalized_alias in positions
            ),
            None,
        )
        if value_index is None or value_index >= len(closing_row):
            continue

        close = as_float(closing_row[value_index])
        if close is None:
            continue
        previous_close = (
            as_float(reference_row[value_index])
            if value_index < len(reference_row)
            else None
        )
        change = close - previous_close if previous_close is not None else None
        change_pct = (
            (change / previous_close) * 100
            if change is not None and previous_close not in (None, 0)
            else None
        )
        items.append(
            {
                "market": "TPEX",
                "name": display_name,
                "close": close,
                "change": change,
                "change_pct": change_pct,
                "trade_date": trade_date,
            }
        )

    return items


def parse_tpex50_index_list_item(payload) -> dict | None:
    rows = payload if isinstance(payload, list) else []
    values_by_date: dict[date, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        trade_date = parse_trade_date(row.get("Date"))
        close = as_float(row.get("TPEx50Index"))
        if trade_date is not None and close is not None:
            values_by_date[trade_date] = close

    ordered = sorted(values_by_date.items())
    if not ordered:
        return None

    trade_date, close = ordered[-1]
    previous_close = ordered[-2][1] if len(ordered) >= 2 else None
    change = close - previous_close if previous_close is not None else None
    change_pct = (
        (change / previous_close) * 100
        if change is not None and previous_close not in (None, 0)
        else None
    )
    return {
        "market": "TPEX",
        "name": "富櫃五十指數",
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "trade_date": trade_date,
    }


def parse_tpex200_index_list_item(payload) -> dict | None:
    rows = payload if isinstance(payload, list) else []
    candidates: list[tuple[date, dict]] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("指數") or "").strip() != "富櫃200指數":
            continue
        trade_date = parse_trade_date(row.get("資料日期"))
        if trade_date is not None:
            candidates.append((trade_date, row))

    if not candidates:
        return None

    trade_date, latest = max(candidates, key=lambda item: item[0])
    return {
        "market": "TPEX",
        "name": "富櫃200指數",
        "close": as_float(latest.get("收盤指數")),
        "change": signed_change(latest.get("漲跌"), latest.get("漲跌點數")),
        "change_pct": signed_change(
            latest.get("漲跌"), latest.get("漲跌百分比")
        ),
        "trade_date": trade_date,
    }


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
    "TPEX_POST_CLOSE_INDEX_FIELDS",
    "TPEX_POST_CLOSE_INDEX_NAMES",
    "as_float",
    "as_int",
    "count_with_limit",
    "list_value",
    "market_index_ohlc_item",
    "market_index_stat_item",
    "parse_tpex200_index_list_item",
    "parse_tpex50_index_list_item",
    "parse_tpex_market_highlight_rows",
    "parse_tpex_market_daily_rows",
    "parse_tpex_post_close_index_list",
    "parse_trade_date",
    "parse_twse_index_daily_ohlc_rows",
    "parse_twse_market_daily_history_rows",
    "regular_stock_code",
    "row_value",
    "signed_change",
]
