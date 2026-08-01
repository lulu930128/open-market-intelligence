import json
import re

from app.db.models import RawFetchResult
from app.parsers.twse_common import (
    normalize_text,
    parse_date,
    parse_float,
    parse_int,
    payload_trade_date,
    repair_mojibake_text,
)


def _extract_first_table(payload: dict) -> dict:
    tables = payload.get("tables") or payload.get("Tables") or []

    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue

            if isinstance(table.get("data"), list):
                return table

    if isinstance(payload.get("data"), list):
        return payload

    raise ValueError("TPEx daily quotes payload does not contain a data table.")


def _row_value(row: list, index: int):
    if index >= len(row):
        return None

    return row[index]


def _is_security_like_id(stock_id: str | None) -> bool:
    return bool(stock_id and re.search(r"[0-9A-Za-z]", stock_id))


def _load_payload(raw_text: str | None) -> dict | list:
    if not raw_text:
        raise ValueError("raw_text is empty.")

    cleaned_text = repair_mojibake_text(raw_text).lstrip("\ufeff").strip()
    payload = json.loads(cleaned_text)
    if not isinstance(payload, (dict, list)):
        raise ValueError("TPEx daily quotes payload should be a JSON object or list.")
    return payload


def _parse_openapi_rows(
    payload: list,
    raw_result: RawFetchResult,
) -> tuple[list[dict], int]:
    fallback_date = payload_trade_date({}, raw_result)
    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in payload:
        if not isinstance(row, dict):
            skipped_count += 1
            continue

        stock_id = normalize_text(row.get("SecuritiesCompanyCode"))
        if not _is_security_like_id(stock_id):
            skipped_count += 1
            continue

        trade_date = parse_date(str(row.get("Date") or "")) or fallback_date
        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "trade_date": trade_date,
                "stock_id": stock_id.strip(),
                "stock_name": normalize_text(row.get("CompanyName")),
                "close_price": parse_float(row.get("Close")),
                "price_change": parse_float(row.get("Change")),
                "open_price": parse_float(row.get("Open")),
                "high_price": parse_float(row.get("High")),
                "low_price": parse_float(row.get("Low")),
                "trade_volume": parse_int(row.get("TradingShares")),
                "trade_value": parse_int(row.get("TransactionAmount")),
                "transaction_count": parse_int(row.get("TransactionNumber")),
            }
        )

    return parsed_rows, skipped_count


def parse_tpex_daily_quotes_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payload = _load_payload(raw_result.raw_text)
    if isinstance(payload, list):
        return _parse_openapi_rows(payload, raw_result)

    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []

    if not isinstance(data, list):
        raise ValueError("TPEx daily quotes data field should be a list.")

    trade_date = payload_trade_date(payload, raw_result)
    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in data:
        if not isinstance(row, list):
            skipped_count += 1
            continue

        stock_id = normalize_text(_row_value(row, 0))

        if not _is_security_like_id(stock_id):
            skipped_count += 1
            continue

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "trade_date": trade_date,
                "stock_id": stock_id.strip(),
                "stock_name": normalize_text(_row_value(row, 1)),
                "close_price": parse_float(_row_value(row, 2)),
                "price_change": parse_float(_row_value(row, 3)),
                "open_price": parse_float(_row_value(row, 4)),
                "high_price": parse_float(_row_value(row, 5)),
                "low_price": parse_float(_row_value(row, 6)),
                "trade_volume": parse_int(_row_value(row, 8)),
                "trade_value": parse_int(_row_value(row, 9)),
                "transaction_count": parse_int(_row_value(row, 10)),
            }
        )

    return parsed_rows, skipped_count
