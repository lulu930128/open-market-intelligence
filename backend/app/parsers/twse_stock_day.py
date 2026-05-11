import json
import re
from datetime import date


def _parse_roc_or_gregorian_date(value: str | None) -> date | None:
    if value is None:
        return None

    cleaned = value.strip()

    match = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})$", cleaned)
    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    if year < 1911:
        year += 1911

    return date(year, month, day)


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

    cleaned = value.replace(",", "").replace("X", "").strip()

    if cleaned in {"", "-", "--", "NaN", "null"}:
        return None

    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)

    if match is None:
        return None

    return float(match.group())


def validate_twse_stock_day_payload(raw_text: str) -> tuple[str, str, int]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return "error", f"TWSE stock day payload is not valid JSON: {exc}.", 0

    if not isinstance(payload, dict):
        return "error", "TWSE stock day payload should be a JSON object.", 0

    data = payload.get("data")

    if data is None:
        return "error", "TWSE stock day payload does not contain data field.", 0

    if not isinstance(data, list):
        return "error", "TWSE stock day data field should be a list.", 0

    if len(data) == 0:
        return "warning", "TWSE stock day query returned zero rows.", 0

    sample = data[0]

    if not isinstance(sample, list) or len(sample) < 9:
        return "error", "TWSE stock day row shape is invalid.", len(data)

    return "valid", "TWSE stock day payload is valid.", len(data)


def parse_twse_stock_day_raw(
    raw_text: str,
    stock_id: str,
    stock_name: str | None = None,
    source_id: int | None = None,
    raw_result_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict], int]:
    payload = json.loads(raw_text)

    data = payload.get("data", [])

    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in data:
        if not isinstance(row, list) or len(row) < 9:
            skipped_count += 1
            continue

        trade_date = _parse_roc_or_gregorian_date(str(row[0]))

        if trade_date is None:
            skipped_count += 1
            continue

        if start_date is not None and trade_date < start_date:
            continue

        if end_date is not None and trade_date > end_date:
            continue

        parsed_rows.append(
            {
                "source_id": source_id,
                "raw_result_id": raw_result_id,
                "trade_date": trade_date,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "trade_volume": _parse_int(str(row[1])),
                "trade_value": _parse_int(str(row[2])),
                "open_price": _parse_float(str(row[3])),
                "high_price": _parse_float(str(row[4])),
                "low_price": _parse_float(str(row[5])),
                "close_price": _parse_float(str(row[6])),
                "price_change": _parse_float(str(row[7])),
                "transaction_count": _parse_int(str(row[8])),
            }
        )

    return parsed_rows, skipped_count