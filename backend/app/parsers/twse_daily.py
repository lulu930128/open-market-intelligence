import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.db.models import RawFetchResult


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _first_value(row: dict, keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None

    cleaned = value.replace(",", "").strip()

    if cleaned in {"", "-", "--", "NaN", "null"}:
        return None

    match = re.search(r"-?\d+", cleaned)

    if match is None:
        return None

    return int(match.group())


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None

    cleaned = value.replace(",", "").strip()

    if cleaned in {"", "-", "--", "NaN", "null"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if match is None:
        return None

    return float(match.group())


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None

    cleaned = value.strip()

    # TWSE often uses ROC year, e.g. 115/05/08 or 115-05-08.
    separated_match = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})$", cleaned)
    if separated_match:
        year = int(separated_match.group(1))
        month = int(separated_match.group(2))
        day = int(separated_match.group(3))

        if year < 1911:
            year += 1911

        return date(year, month, day)

    # Compact format: Gregorian YYYYMMDD or ROC YYYMMDD.
    digits = re.sub(r"\D", "", cleaned)

    if len(digits) == 8:
        year = int(digits[:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        return date(year, month, day)

    if len(digits) == 7:
        year = int(digits[:3]) + 1911
        month = int(digits[3:5])
        day = int(digits[5:7])
        return date(year, month, day)

    return None


def _fallback_trade_date(raw_result: RawFetchResult) -> date:
    fetched_at = raw_result.fetched_at

    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=ZoneInfo("UTC"))

    return fetched_at.astimezone(TAIPEI_TZ).date()


def parse_twse_daily_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    if not raw_result.raw_text:
        raise ValueError("raw_text is empty.")

    payload = json.loads(raw_result.raw_text)

    if not isinstance(payload, list):
        raise ValueError("TWSE daily payload should be a JSON list.")

    fallback_date = _fallback_trade_date(raw_result)

    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in payload:
        if not isinstance(row, dict):
            skipped_count += 1
            continue

        stock_id = _first_value(row, ["Code", "code", "證券代號"])
        stock_name = _first_value(row, ["Name", "name", "證券名稱"])

        if not stock_id:
            skipped_count += 1
            continue

        row_date = _first_value(row, ["Date", "date", "TradeDate", "trade_date", "交易日期"])
        trade_date = _parse_date(row_date) or fallback_date

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "trade_volume": _parse_int(
                    _first_value(row, ["TradeVolume", "trade_volume", "成交股數"])
                ),
                "trade_value": _parse_int(
                    _first_value(row, ["TradeValue", "trade_value", "成交金額"])
                ),
                "open_price": _parse_float(
                    _first_value(row, ["OpeningPrice", "open_price", "開盤價"])
                ),
                "high_price": _parse_float(
                    _first_value(row, ["HighestPrice", "high_price", "最高價"])
                ),
                "low_price": _parse_float(
                    _first_value(row, ["LowestPrice", "low_price", "最低價"])
                ),
                "close_price": _parse_float(
                    _first_value(row, ["ClosingPrice", "close_price", "收盤價"])
                ),
                "price_change": _parse_float(
                    _first_value(row, ["Change", "price_change", "漲跌價差"])
                ),
                "transaction_count": _parse_int(
                    _first_value(row, ["Transaction", "transaction_count", "成交筆數"])
                ),
            }
        )

    return parsed_rows, skipped_count