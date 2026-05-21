import re

from app.db.models import RawFetchResult
from app.parsers.twse_common import load_json_payload, normalize_text, payload_trade_date


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

    raise ValueError("TPEx company profile payload does not contain a data table.")


def _row_value(row: list, index: int):
    if index >= len(row):
        return None

    return row[index]


def _is_stock_like_id(stock_id: str | None) -> bool:
    return bool(stock_id and re.match(r"^[0-9A-Za-z]+$", stock_id))


def parse_tpex_company_profile_raw(raw_result: RawFetchResult) -> tuple[list[dict], int]:
    payload = load_json_payload(raw_result.raw_text, "TPEx company profile")
    table = _extract_first_table(payload)
    data = table.get("data") or table.get("Data") or []

    if not isinstance(data, list):
        raise ValueError("TPEx company profile data field should be a list.")

    report_date = payload_trade_date(payload, raw_result)
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

        company_name = normalize_text(_row_value(row, 1))

        parsed_rows.append(
            {
                "source_id": raw_result.source_id,
                "raw_result_id": raw_result.id,
                "report_date": report_date,
                "stock_id": stock_id.strip(),
                "company_name": company_name,
                "short_name": company_name,
                "market": "TPEX",
                "industry": normalize_text(_row_value(row, 3)),
                "listed_date": None,
                "established_date": None,
                "paid_in_capital": None,
                "issued_shares": None,
                "private_placement_shares": None,
                "preferred_shares": None,
                "chairman": None,
                "general_manager": None,
                "spokesman": None,
                "spokesman_title": None,
                "phone": None,
                "address": None,
                "website": None,
                "email": None,
            }
        )

    return parsed_rows, skipped_count
