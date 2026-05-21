import re

from app.db.models import RawFetchResult
from app.parsers.twse_common import load_json_payload, normalize_text, parse_int, payload_trade_date


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

    raise ValueError("TPEx margin trading payload does not contain a data table.")


def _row_value(row: list, index: int):
    if index >= len(row):
        return None

    return row[index]


def _is_stock_like_id(stock_id: str | None) -> bool:
    return bool(stock_id and re.search(r"[0-9A-Za-z]", stock_id))


def parse_tpex_margin_trading_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payload = load_json_payload(raw_result.raw_text, "TPEx margin trading")
    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []

    if not isinstance(data, list):
        raise ValueError("TPEx margin trading data field should be a list.")

    trade_date = payload_trade_date(payload, raw_result)
    parsed_rows: list[dict] = []
    skipped_count = 0

    for row in data:
        if not isinstance(row, list):
            skipped_count += 1
            continue

        stock_id = normalize_text(_row_value(row, 0))

        if not _is_stock_like_id(stock_id):
            skipped_count += 1
            continue

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "trade_date": trade_date,
                "stock_id": stock_id.strip(),
                "stock_name": normalize_text(_row_value(row, 1)),
                "margin_previous_balance": parse_int(_row_value(row, 2)),
                "margin_buy": parse_int(_row_value(row, 3)),
                "margin_sell": parse_int(_row_value(row, 4)),
                "margin_cash_repayment": parse_int(_row_value(row, 5)),
                "margin_today_balance": parse_int(_row_value(row, 6)),
                "margin_next_limit": parse_int(_row_value(row, 9)),
                "short_previous_balance": parse_int(_row_value(row, 10)),
                "short_sale": parse_int(_row_value(row, 11)),
                "short_covering": parse_int(_row_value(row, 12)),
                "short_stock_repayment": parse_int(_row_value(row, 13)),
                "short_today_balance": parse_int(_row_value(row, 14)),
                "short_next_limit": parse_int(_row_value(row, 17)),
                "offset": parse_int(_row_value(row, 18)),
                "note": normalize_text(_row_value(row, 19)),
            }
        )

    return parsed_rows, skipped_count
